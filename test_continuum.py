import json, tempfile, unittest
from pathlib import Path
from continuum import SibylMemory, credit_for

class ContinuumTests(unittest.TestCase):
    def test_credit_policy(self):
        self.assertEqual(credit_for(1),5); self.assertEqual(credit_for(3),10); self.assertEqual(credit_for(4),20)
    def test_persistence_across_instances(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'memory.json'; m=SibylMemory(p); m.put({'ticket_id':'T','status':'pending'}); self.assertEqual(SibylMemory(p).get('T')['status'],'pending')
    def test_reputation_fixture_schema(self):
        data=json.loads((Path(__file__).parent/'data'/'reputation.json').read_text()); self.assertIn('vendor_reliability_profile',data); self.assertIn('agent_reputation',data)

if __name__=='__main__': unittest.main()
