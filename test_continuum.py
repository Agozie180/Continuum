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


class Coordinator:
    def __init__(self):
        self.calls = 0

    def coordinate(self, ticket):
        self.calls += 1
        return f"virt-{self.calls}"


class Attestor:
    def __init__(self):
        self.calls = 0

    def submit(self, ticket, store):
        self.calls += 1
        return f"0xhash-{self.calls}", "2026-01-01T00:00:00+00:00"


def runtime(store, coord, att, clock):
    return AccountabilityRuntime(store, coord, att, clock)


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
        result = runtime(store, Coordinator(), Attestor(), at(2020, 1, 3)).process("T")
        self.assertEqual(result["phase"], "CLOSED")
        self.assertEqual(result["status"], "broken")
        self.assertTrue(result["breach_event_id"])
        self.assertEqual(result["virtuals_event_id"], "virt-1")
        self.assertEqual(result["attestation_tx_hash"], "0xhash-1")

    def test_future_deadline_has_no_consequence(self):
        store = InMemoryStore()
        self._open(store, date="2099-01-01T00:00:00+00:00")
        result = runtime(store, Coordinator(), Attestor(), at(2026, 1, 1)).process("T")
        self.assertEqual(result["phase"], "OPEN")
        self.assertEqual(result["status"], "pending")

    def test_idempotent_rerun_makes_no_duplicate_calls(self):
        store = InMemoryStore()
        self._open(store)
        coord, att = Coordinator(), Attestor()
        runtime(store, coord, att, at(2020, 1, 3)).process("T")
        # A second, later run (a fresh process would look identical) must be a no-op.
        again = runtime(store, coord, att, at(2020, 1, 9)).process("T")
        self.assertEqual(coord.calls, 1)
        self.assertEqual(att.calls, 1)
        self.assertEqual(again["escalation_count"], 1)
        self.assertEqual(again["resolution_credit"], store.get("T")["resolution_credit"])

    def test_crash_after_breach_still_coordinates_on_recovery(self):
        # Regression test for the root defect: a breach is durably persisted but
        # Virtuals never ran. A recovery run MUST coordinate before attesting.
        # The old code nested coordination inside the breach branch and skipped it.
        store = InMemoryStore()
        self._open(store)

        class Boom(Coordinator):
            def coordinate(self, ticket):
                raise RuntimeError("virtuals down")

        with self.assertRaises(RuntimeError):
            runtime(store, Boom(), Attestor(), at(2020, 1, 3)).process("T")

        crashed = store.get("T")
        self.assertEqual(crashed["phase"], "BREACHED")
        self.assertIsNone(crashed["virtuals_event_id"])
        self.assertIsNone(crashed["attestation_tx_hash"])

        coord, att = Coordinator(), Attestor()
        recovered = runtime(store, coord, att, at(2020, 1, 3)).process("T")
        self.assertEqual(coord.calls, 1)  # coordination WAS reached on recovery
        self.assertEqual(recovered["virtuals_event_id"], "virt-1")
        self.assertEqual(recovered["attestation_tx_hash"], "0xhash-1")
        self.assertEqual(recovered["phase"], "CLOSED")

    def test_crash_before_attestation_resumes_without_recoordinating(self):
        store = InMemoryStore()
        self._open(store)

        class Boom(Attestor):
            def submit(self, ticket, store):
                raise RuntimeError("base down")

        coord = Coordinator()
        with self.assertRaises(RuntimeError):
            runtime(store, coord, Boom(), at(2020, 1, 3)).process("T")
        self.assertEqual(store.get("T")["phase"], "COORDINATED")
        self.assertEqual(coord.calls, 1)

        att = Attestor()
        recovered = runtime(store, coord, att, at(2020, 1, 3)).process("T")
        self.assertEqual(coord.calls, 1)  # NOT re-coordinated
        self.assertEqual(att.calls, 1)
        self.assertEqual(recovered["phase"], "CLOSED")


class ReputationTests(unittest.TestCase):
    def test_reputation_is_derived_and_fed_forward(self):
        store = InMemoryStore()
        # A vendor breaches two prior commitments.
        for tid in ("A", "B"):
            store.put(new_ticket(tid, "C", "V-BAD", "i", "p", "2020-01-01T00:00:00+00:00"))
            runtime(store, Coordinator(), Attestor(), at(2020, 1, 5)).process(tid)
        rep = store.vendor_reputation("V-BAD")
        self.assertEqual(rep["breaches"], 2)
        self.assertEqual(rep["tier"], "high-risk")

        # Same lateness, two vendors: the repeat offender is escalated harder.
        store.put(new_ticket("C1", "C", "V-BAD", "i", "p", "2020-01-01T00:00:00+00:00"))
        store.put(new_ticket("D1", "C", "V-GOOD", "i", "p", "2020-01-01T00:00:00+00:00"))
        bad = runtime(store, Coordinator(), Attestor(), at(2020, 1, 3)).process("C1")
        good = runtime(store, Coordinator(), Attestor(), at(2020, 1, 3)).process("D1")
        self.assertGreater(bad["resolution_credit"], good["resolution_credit"])
        self.assertGreater(bad["escalation_level"], good["escalation_level"])
        self.assertEqual(bad["vendor_tier_at_breach"], "high-risk")
        self.assertEqual(good["vendor_tier_at_breach"], "trusted")

    def test_no_cross_contamination_between_vendors(self):
        store = InMemoryStore()
        store.put(new_ticket("T-A", "C-500", "V-AAA", "i", "p", "2020-01-01T00:00:00+00:00"))
        store.put(new_ticket("T-B", "C-500", "V-BBB", "i", "p", "2099-01-01T00:00:00+00:00"))
        runtime(store, Coordinator(), Attestor(), at(2026, 1, 1)).process("T-A")
        runtime(store, Coordinator(), Attestor(), at(2026, 1, 1)).process("T-B")
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
        runtime(store, Coordinator(), Attestor(), at(2020, 1, 3)).process("T")
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
