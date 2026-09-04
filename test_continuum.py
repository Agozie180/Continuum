import unittest
from datetime import datetime, timezone
from continuum import MemoryTestStore, credit_for, new_ticket, process_ticket

class FakeCoordinator:
    def coordinate(self, ticket): return "virtuals-event-1"

class FakeAttestor:
    def submit(self, ticket, store): return "0xreal-test-double", "2026-01-01T00:00:00+00:00"

class ContinuumTests(unittest.TestCase):
    def test_credit_policy(self):
        self.assertEqual(credit_for(1), 5); self.assertEqual(credit_for(3), 10); self.assertEqual(credit_for(4), 20)
    def test_fresh_store_recall_and_behavior(self):
        store = MemoryTestStore(); ticket = new_ticket("T", "C", "V", "x", "y", "2020-01-01T00:00:00+00:00")
        store.put(ticket); recalled = store.get("T")
        result = process_ticket(recalled, store, FakeCoordinator(), FakeAttestor(), lambda: datetime(2020, 1, 3, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "broken"); self.assertEqual(result["resolution_credit"], 10)
        self.assertEqual(store.get("T")["virtuals_event_id"], "virtuals-event-1")
    def test_future_deadline_has_no_consequence(self):
        store = MemoryTestStore(); ticket = new_ticket("T", "C", "V", "x", "y", "2099-01-01T00:00:00+00:00"); store.put(ticket)
        result = process_ticket(ticket, store, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(result["status"], "pending")
    def test_idempotent_broken_ticket(self):
        store = MemoryTestStore(); ticket = new_ticket("T", "C", "V", "x", "y", "2020-01-01T00:00:00+00:00"); ticket.update(status="broken", attestation_tx_hash="0x1", escalation_count=1); store.put(ticket)
        result = process_ticket(store.get("T"), store, FakeCoordinator(), FakeAttestor()); self.assertEqual(result["attestation_tx_hash"], "0x1"); self.assertEqual(result["escalation_count"], 1)
    def test_schema_rejects_incomplete_ticket(self):
        with self.assertRaises(ValueError): MemoryTestStore().put({"ticket_id": "T"})

if __name__ == "__main__": unittest.main()
