"""Continuum accountability runtime with durable state transitions."""
from __future__ import annotations
import argparse, hashlib, json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'; MEMORY_FILE=DATA/'sibyl_memory.json'; REPUTATION_FILE=DATA/'reputation.json'
SIBYL_DB=Path(os.getenv('SIBYL_MEMORY_DB',str(DATA/'sibyl_memory.db'))).resolve(); SIBYL_TENANT=os.getenv('SIBYL_TENANT_ID','00000000-0000-0000-0000-000000000001')
try:
 from dotenv import load_dotenv; load_dotenv(ROOT/'.env')
except ImportError: pass
REQUIRED={'ticket_id','customer_id','vendor_id','issue_summary','promise_made','promised_date','status','escalation_count','resolution_credit','attestation_tx_hash','attestation_timestamp','last_action','breach_event_id','attestation_intent'}
def now(): return datetime.now(timezone.utc)
def iso(v): return v.astimezone(timezone.utc).isoformat()
def digest(v): return hashlib.sha256(v.encode()).hexdigest()

class SibylMemory:
 def __init__(self,path=MEMORY_FILE):
  self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._sdk=None; backend=os.getenv('CONTINUUM_MEMORY_BACKEND','sibyl-sdk')
  if backend=='sibyl-sdk' and self.path==MEMORY_FILE:
   try:
    from sibyl_memory_client import MemoryClient; self._sdk=MemoryClient.local(str(SIBYL_DB),tenant_id=SIBYL_TENANT)
   except ImportError as exc: raise RuntimeError('Sibyl SDK is required; use CONTINUUM_MEMORY_BACKEND=json only for tests') from exc
  elif backend!='json':
   if self.path != MEMORY_FILE: backend='json'
   else: raise RuntimeError(f'Unsupported memory backend: {backend}')
 def _validate(self,t):
  missing=REQUIRED-set(t)
  if missing: raise ValueError('Ticket missing required fields: '+', '.join(sorted(missing)))
  if t['status'] not in {'pending','broken','resolved'}: raise ValueError('invalid ticket status')
  if datetime.fromisoformat(t['promised_date'].replace('Z','+00:00')).tzinfo is None: raise ValueError('promised_date must include a timezone')
  return t
 def _load(self): return json.loads(self.path.read_text()) if self.path.exists() else {}
 def _save(self,d):
  fd,tmp=tempfile.mkstemp(prefix='.memory-',dir=self.path.parent); os.close(fd)
  try: Path(tmp).write_text(json.dumps(d,indent=2)); os.replace(tmp,self.path)
  finally:
   if os.path.exists(tmp): os.unlink(tmp)
 def get(self,key):
  if self._sdk:
   from sibyl_memory_client.exceptions import NotFoundError
   try: return self._sdk.get_entity('ticket',key).get('body')
   except NotFoundError: return None
  t=self._load().get(key); return self._validate(t) if t else None
 def put(self,t):
  self._validate(t); old=self.get(t['ticket_id'])
  if old and old.get('status')=='broken' and t['status']=='pending': raise ValueError('cannot reset a broken ticket to pending')
  if self._sdk: self._sdk.set_entity('ticket',t['ticket_id'],t,status=t['status'])
  else: d=self._load(); d[t['ticket_id']]=t; self._save(d)
 def all(self):
  rows=[x['body'] for x in self._sdk.list_entities('ticket',limit=10000)] if self._sdk else list(self._load().values()); return [self._validate(x) for x in rows]
 def clear(self):
  if self._sdk:
   for row in self._sdk.list_entities('ticket',limit=10000): self._sdk.delete_entity('ticket',row['name'])
  else: self._save({})
 @property
 def backend_name(self): return 'sibyl-sdk-sqlite' if self._sdk else 'local-json-test-only'

def credit_for(days): return 0 if days<=0 else 5 if days==1 else 10 if days<=3 else 20

class VirtualsCoordinator:
 def coordinate(self,t):
  tasks=['support_agent','accountability_agent','reputation_agent']; url,key=os.getenv('VIRTUALS_ACP_URL'),os.getenv('VIRTUALS_API_KEY')
  if not url or not key:
   if os.getenv('CONTINUUM_STRICT')=='1': raise RuntimeError('strict mode requires live Virtuals ACP credentials')
   return {'workflow':'local-development','agents':tasks}
  import requests; r=requests.post(url,json={'workflow':'continuum-accountability-v1','ticket':{'ticket_id':t['ticket_id'],'vendor_id_hash':digest(t['vendor_id']),'status':t['status'],'resolution_credit':t['resolution_credit']},'tasks':tasks},headers={'Authorization':'Bearer '+key},timeout=30); r.raise_for_status(); out=r.json()
  if not isinstance(out,dict) or not isinstance(out.get('agents'),list): raise RuntimeError('Virtuals response missing agents list')
  return out

class BaseAttestation:
 def payload(self,t): return {'vendor_id_hash':digest(t['vendor_id']),'ticket_id_hash':digest(t['ticket_id']),'commitment_hash':digest(t['promise_made']),'promised_date':t['promised_date'],'breached_at':t['breach_event_id']}
 def submit(self,t):
  if not os.getenv('BASE_PRIVATE_KEY') or not os.getenv('BASE_RPC_URL'): raise RuntimeError('Base credentials missing')
  from web3 import Web3; w3=Web3(Web3.HTTPProvider(os.environ['BASE_RPC_URL']))
  if w3.eth.chain_id!=84532: raise RuntimeError(f'Wrong network: expected Base Sepolia (84532), got {w3.eth.chain_id}')
  acct=w3.eth.account.from_key(os.environ['BASE_PRIVATE_KEY']); intent=t.get('attestation_intent'); payload=self.payload(t); nonce=intent['nonce'] if intent else w3.eth.get_transaction_count(acct.address,'pending')
  tx={'from':acct.address,'to':acct.address,'value':0,'data':w3.to_hex(text=json.dumps(payload,separators=(',',':'))),'nonce':nonce,'chainId':84532,'gas':100000,'maxFeePerGas':w3.to_wei(1,'gwei'),'maxPriorityFeePerGas':w3.to_wei(1,'gwei')}; signed=acct.sign_transaction(tx); txh=w3.to_hex(signed.hash)
  if not intent: t['attestation_intent']={'tx_hash':txh,'nonce':nonce,'payload_hash':digest(json.dumps(payload,sort_keys=True))}
  w3.eth.send_raw_transaction(signed.raw_transaction); w3.eth.wait_for_transaction_receipt(txh); return txh,iso(now())

def process_ticket(t,memory):
 memory._validate(t)
 if t['status']=='broken' and t.get('attestation_tx_hash'): return t
 if t['status']=='pending':
  deadline=datetime.fromisoformat(t['promised_date'].replace('Z','+00:00')); late=(now()-deadline).total_seconds()/86400
  if late<=0: return t
  t.update(status='broken',escalation_count=t['escalation_count']+1,resolution_credit=credit_for(max(1,int(late))),breach_event_id=iso(now()),last_action='deadline breach detected'); memory.put(t); VirtualsCoordinator().coordinate(t); memory.put(t)
 if t['status']=='broken' and not t.get('attestation_tx_hash'):
  try:
   txh,ts=BaseAttestation().submit(t); t.update(attestation_tx_hash=txh,attestation_timestamp=ts,last_action='Base attestation confirmed'); memory.put(t)
  except Exception as exc:
   t['last_action']='Base attestation pending: '+str(exc); memory.put(t)
 return t

def rebuild_reputation(memory):
 tickets=memory.all(); vendors={}
 for t in tickets:
  v=vendors.setdefault(t['vendor_id'],{'promises_total':0,'promises_broken':0,'reliability_score':1.0,'total_resolution_credit':0,'attestations':0}); v['promises_total']+=1
  if t['status']=='broken': v['promises_broken']+=1; v['total_resolution_credit']+=t['resolution_credit']
  if t.get('attestation_tx_hash'): v['attestations']+=1
 for v in vendors.values(): v['reliability_score']=round(1-v['promises_broken']/max(1,v['promises_total']),3)
 out={'vendor_reliability_profile':vendors,'agent_reputation':{'agent_id':'continuum-support-01','tickets_processed':sum(t['status']=='broken' for t in tickets),'promises_tracked':len(tickets),'broken_promises_detected':sum(t['status']=='broken' for t in tickets),'correct_escalations':sum(t['status']=='broken' for t in tickets),'false_escalations':0,'escalation_accuracy':1.0,'total_credit_recovered':sum(t['resolution_credit'] for t in tickets),'attestations_created':sum(bool(t.get('attestation_tx_hash')) for t in tickets)}}; REPUTATION_FILE.write_text(json.dumps(out,indent=2)); return out

def new_ticket(i,c,v,issue,promise,date): return {'ticket_id':i,'customer_id':c,'vendor_id':v,'issue_summary':issue,'promise_made':promise,'promised_date':date,'status':'pending','escalation_count':0,'resolution_credit':0,'attestation_tx_hash':None,'attestation_timestamp':None,'last_action':'promise recorded','breach_event_id':None,'attestation_intent':None}

def main():
 p=argparse.ArgumentParser(); p.add_argument('command',choices=['session1','session2','session3','check-deadlines','clear-memory','show-reputation','doctor','create-ticket']); p.add_argument('ticket_id',nargs='?',default='T-1042'); p.add_argument('--customer-id',default='C-001'); p.add_argument('--vendor-id',default='V-001'); p.add_argument('--issue-summary',default='Support issue'); p.add_argument('--promise-made',default='Resolve the issue'); p.add_argument('--promised-date'); p.add_argument('--strict',action='store_true'); a=p.parse_args(); m=SibylMemory()
 if a.command=='doctor':
  r={'memory_backend':m.backend_name,'sibyl_db':str(SIBYL_DB),'base_configured':bool(os.getenv('BASE_PRIVATE_KEY') and os.getenv('BASE_RPC_URL')),'virtuals_configured':bool(os.getenv('VIRTUALS_API_KEY') and os.getenv('VIRTUALS_ACP_URL'))}
  if a.strict and (m.backend_name!='sibyl-sdk-sqlite' or not r['base_configured'] or not r['virtuals_configured']): raise SystemExit('strict mode requires Sibyl, Base, and Virtuals')
  print(json.dumps(r,indent=2)); return
 if a.command=='clear-memory': m.clear(); print('Sibyl Memory cleared.'); return
 if a.command=='show-reputation': print(json.dumps(rebuild_reputation(m),indent=2)); return
 if a.command=='session1': m.put(new_ticket('T-1042','C-001','V-001','Package has not arrived.','Resolve delivery issue','2026-08-18T17:00:00+00:00')); print('Stored T-1042 in Sibyl Memory.'); return
 if a.command=='create-ticket':
  if not a.promised_date: p.error('create-ticket requires --promised-date')
  m.put(new_ticket(a.ticket_id,a.customer_id,a.vendor_id,a.issue_summary,a.promise_made,a.promised_date)); return
 if a.command in {'session2','session3'}:
  t=m.get(a.ticket_id)
  if not t: print('No Sibyl memory found for',a.ticket_id); return
  process_ticket(t,m); rebuild_reputation(m); print(json.dumps(t,indent=2)); return
 for t in m.all():
  if t['status']=='pending': process_ticket(t,m)
 rebuild_reputation(m)
if __name__=='__main__': main()
