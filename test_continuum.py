import unittest
from datetime import datetime, timezone

from continuum import (
    AccountabilityRuntime,
    InMemoryStore,
    base_credit,
    consequence,
    new_ticket,
    resolve_ticket,
)


def at(year, month, day):
    """A fixed-clock factory (the runtime takes a zero-arg clock callable)."""
    return lambda: datetime(year, month, day, tzinfo=timezone.utc)


class Attestor:
    """A Base attestor double: no chain, no broadcast, just a counted call."""

    def __init__(self):
        self.calls = 0

    def submit(self, ticket, store):
        self.calls += 1
        return f"0xhash-{self.calls}", "2026-01-01T00:00:00+00:00"


def runtime(store, att, clock, allow_attestation=True):
    """Build a runtime. Tests opt into attestation by default (the double is
    safe); the gate test below exercises the broadcast-safe path explicitly."""
    return AccountabilityRuntime(store, attestor=att, clock=clock, allow_attestation=allow_attestation)


class PolicyTests(unittest.TestCase):
    def test_credit_scales_with_lateness(self):
        self.assertEqual(base_credit(0), 0)
        self.assertEqual(base_credit(1), 5)
        self.assertEqual(base_credit(3), 10)
        self.assertEqual(base_credit(9), 20)

    def test_repeat_offender_costs_more_for_same_lateness(self):
        first_time = consequence(2, "trusted")
        repeat = consequence(2, "high-risk")
        self.assertGreater(repeat["resolution_credit"], first_time["resolution_credit"])
        self.assertGreater(repeat["escalation_level"], first_time["escalation_level"])


class WorkflowTests(unittest.TestCase):
    def _open(self, store, tid="T", vendor="V", date="2020-01-01T00:00:00+00:00"):
        store.put(new_ticket(tid, "C", vendor, "issue", "promise", date))

    def test_fresh_recall_drives_full_cycle(self):
        store = InMemoryStore()
        self._open(store)
        result = runtime(store, Attestor(), at(2020, 1, 3)).process("T")
        self.assertEqual(result["phase"], "CLOSED")
        self.assertEqual(result["status"], "broken")
        self.assertTrue(result["breach_event_id"])
        self.assertEqual(result["attestation_tx_hash"], "0xhash-1")

    def test_future_deadline_has_no_consequence(self):
        store = InMemoryStore()
        self._open(store, date="2099-01-01T00:00:00+00:00")
        result = runtime(store, Attestor(), at(2026, 1, 1)).process("T")
        self.assertEqual(result["phase"], "OPEN")
        self.assertEqual(result["status"], "pending")

    def test_attestation_requires_explicit_opt_in(self):
        # The core-path safety property: routine processing detects and records
        # the breach but must NEVER broadcast on-chain without an explicit opt-in.
        store = InMemoryStore()
        self._open(store)
        att = Attestor()

        breached = runtime(store, att, at(2020, 1, 3), allow_attestation=False).process("T")
        self.assertEqual(breached["phase"], "BREACHED")
        self.assertEqual(att.calls, 0)  # no broadcast attempted
        self.assertIsNone(store.get("T")["attestation_tx_hash"])

        # Opting in completes the cycle, reusing the same durable breach.
        closed = runtime(store, att, at(2020, 1, 3), allow_attestation=True).process("T")
        self.assertEqual(att.calls, 1)
        self.assertEqual(closed["phase"], "CLOSED")
        self.assertTrue(closed["attestation_tx_hash"])
        self.assertEqual(closed["escalation_count"], 1)  # breach not re-counted

    def test_idempotent_rerun_makes_no_duplicate_calls(self):
        store = InMemoryStore()
        self._open(store)
        att = Attestor()
        runtime(store, att, at(2020, 1, 3)).process("T")
        # A second, later run (a fresh process would look identical) must be a no-op.
        again = runtime(store, att, at(2020, 1, 9)).process("T")
        self.assertEqual(att.calls, 1)
        self.assertEqual(again["escalation_count"], 1)
        self.assertEqual(again["resolution_credit"], store.get("T")["resolution_credit"])

    def test_crash_after_breach_resumes_at_attestation(self):
        # Regression test for the resumable saga: a breach is durably persisted,
        # but attestation crashes. A recovery run MUST reach attestation exactly
        # once and close the cycle - the breach is never lost or re-counted.
        store = InMemoryStore()
        self._open(store)

        class Boom(Attestor):
            def submit(self, ticket, store):
                raise RuntimeError("base down")

        with self.assertRaises(RuntimeError):
            runtime(store, Boom(), at(2020, 1, 3), allow_attestation=True).process("T")

        crashed = store.get("T")
        self.assertEqual(crashed["phase"], "BREACHED")
        self.assertEqual(crashed["escalation_count"], 1)
        self.assertIsNone(crashed["attestation_tx_hash"])

        att = Attestor()
        recovered = runtime(store, att, at(2020, 1, 3), allow_attestation=True).process("T")
        self.assertEqual(att.calls, 1)  # attestation WAS reached on recovery
        self.assertEqual(recovered["escalation_count"], 1)  # breach not re-counted
        self.assertTrue(recovered["attestation_tx_hash"])
        self.assertEqual(recovered["phase"], "CLOSED")


class ReputationTests(unittest.TestCase):
    def test_reputation_is_derived_and_fed_forward(self):
        store = InMemoryStore()
        # A vendor breaches two prior commitments.
        for tid in ("A", "B"):
            store.put(new_ticket(tid, "C", "V-BAD", "i", "p", "2020-01-01T00:00:00+00:00"))
            runtime(store, Attestor(), at(2020, 1, 5)).process(tid)
        rep = store.vendor_reputation("V-BAD")
        self.assertEqual(rep["breaches"], 2)
        self.assertEqual(rep["tier"], "high-risk")

        # Same lateness, two vendors: the repeat offender is escalated harder.
        store.put(new_ticket("C1", "C", "V-BAD", "i", "p", "2020-01-01T00:00:00+00:00"))
        store.put(new_ticket("D1", "C", "V-GOOD", "i", "p", "2020-01-01T00:00:00+00:00"))
        bad = runtime(store, Attestor(), at(2020, 1, 3)).process("C1")
        good = runtime(store, Attestor(), at(2020, 1, 3)).process("D1")
        self.assertGreater(bad["resolution_credit"], good["resolution_credit"])
        self.assertGreater(bad["escalation_level"], good["escalation_level"])
        self.assertEqual(bad["vendor_tier_at_breach"], "high-risk")
        self.assertEqual(good["vendor_tier_at_breach"], "trusted")

    def test_no_cross_contamination_between_vendors(self):
        store = InMemoryStore()
        store.put(new_ticket("T-A", "C-500", "V-AAA", "i", "p", "2020-01-01T00:00:00+00:00"))
        store.put(new_ticket("T-B", "C-500", "V-BBB", "i", "p", "2099-01-01T00:00:00+00:00"))
        runtime(store, Attestor(), at(2026, 1, 1)).process("T-A")
        runtime(store, Attestor(), at(2026, 1, 1)).process("T-B")
        self.assertEqual(store.get("T-A")["status"], "broken")
        self.assertEqual(store.get("T-B")["status"], "pending")
        self.assertEqual(store.vendor_reputation("V-BBB")["breaches"], 0)


class SchemaAndResolutionTests(unittest.TestCase):
    def test_put_rejects_incomplete_ticket(self):
        with self.assertRaises(ValueError):
            InMemoryStore().put({"ticket_id": "T"})

    def test_broken_ticket_cannot_regress_to_pending(self):
        store = InMemoryStore()
        store.put(new_ticket("T", "C", "V", "i", "p", "2020-01-01T00:00:00+00:00"))
        runtime(store, Attestor(), at(2020, 1, 3)).process("T")
        stale = new_ticket("T", "C", "V", "i", "p", "2020-01-01T00:00:00+00:00")
        with self.assertRaises(ValueError):
            store.put(stale)

    def test_resolved_before_deadline_counts_on_time(self):
        store = InMemoryStore()
        store.put(new_ticket("T", "C", "V", "i", "p", "2099-01-01T00:00:00+00:00"))
        resolve_ticket(store, "T", clock=at(2026, 1, 1))
        rep = store.vendor_reputation("V")
        self.assertEqual(rep["breaches"], 0)
        self.assertEqual(rep["on_time_resolutions"], 1)


if __name__ == "__main__":
    unittest.main()
