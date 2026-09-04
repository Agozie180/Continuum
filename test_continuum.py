import json, tempfile, unittest
from pathlib import Path
from continuum import SibylMemory, credit_for

class ContinuumTests(unittest.TestCase):
    def test_credit_policy(self):
        self.assertEqual(credit_for(1),5); self.assertEqual(credit_for(3),10); self.assertEqual(credit_for(4),20)
    def test_persistence_across_instances(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'memory.json'; m=SibylMemory(p)
            t={'ticket_id':'T','customer_id':'C','vendor_id':'V','issue_summary':'x','promise_made':'y','promised_date':'2099-01-01T00:00:00+00:00','status':'pending','escalation_count':0,'resolution_credit':0,'attestation_tx_hash':None,'attestation_timestamp':None,'last_action':'promise recorded'}
            m.put(t); self.assertEqual(SibylMemory(p).get('T')['status'],'pending')

    def test_schema_rejects_incomplete_ticket(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): SibylMemory(Path(d)/'memory.json').put({'ticket_id':'T'})

    def test_broken_ticket_cannot_be_reset_to_pending(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'memory.json'; m=SibylMemory(p)
            t={'ticket_id':'T','customer_id':'C','vendor_id':'V','issue_summary':'x','promise_made':'y','promised_date':'2020-01-01T00:00:00+00:00','status':'broken','escalation_count':1,'resolution_credit':20,'attestation_tx_hash':None,'attestation_timestamp':None,'last_action':'breach'}
            m.put(t); t['status']='pending'
            with self.assertRaises(ValueError): m.put(t)
    def test_reputation_fixture_schema(self):
        data=json.loads((Path(__file__).parent/'data'/'reputation.json').read_text()); self.assertIn('vendor_reliability_profile',data); self.assertIn('agent_reputation',data)

if __name__=='__main__': unittest.main()
