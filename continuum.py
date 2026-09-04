"""Continuum accountability runtime with Sibyl-only production memory."""
from __future__ import annotations
import argparse, hashlib, json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'; SIBYL_DB=Path(os.getenv('SIBYL_MEMORY_DB',str(DATA/'sibyl_memory.db'))).resolve(); SIBYL_TENANT=os.getenv('SIBYL_TENANT_ID','00000000-0000-0000-0000-000000000001')
REQUIRED={'ticket_id','customer_id','vendor_id','issue_summary','promise_made','promised_date','status','escalation_count','resolution_credit','attestation_tx_hash','attestation_timestamp','last_action','breach_event_id','attestation_intent','virtuals_event_id'}
def now(): return datetime.now(timezone.utc)
def iso(v): return v.astimezone(timezone.utc).isoformat()
def digest(v): return hashlib.sha256(v.encode()).hexdigest()
def validate(t):
 missing=REQUIRED-set(t)
 if missing: raise ValueError('Ticket missing required fields: '+', '.join(sorted(missing)))
 if t['status'] not in {'pending','broken','resolved'}: raise ValueError('invalid ticket status')
 try: d=datetime.fromisoformat(t['promised_date'].replace('Z','+00:00'))
 except ValueError as e: raise ValueError('promised_date must be ISO-8601') from e
 if d.tzinfo is None: raise ValueError('promised_date must include a timezone')
 return t
class TicketStore(Protocol):
 def get(self,k): ...
 def put(self,t): ...
 def all(self): ...
 def clear(self): ...
class SibylMemory:
 backend_name='sibyl-sdk-sqlite'
 def __init__(self,db=SIBYL_DB):
  try:
   from sibyl_memory_client import MemoryClient
   self.client=MemoryClient.local(str(db),tenant_id=SIBYL_TENANT)
  except ImportError as e: raise RuntimeError('Install sibyl-memory-client before running Continuum') from e
 def get(self,k):
  from sibyl_memory_client.exceptions import NotFoundError
  try: return validate(self.client.get_entity('ticket',k)['body'])
  except NotFoundError: return None
 def put(self,t):
  validate(t); old=self.get(t['ticket_id'])
  if old and old['status']=='broken' and t['status']=='pending': raise ValueError('broken tickets cannot return to pending')
  self.client.set_entity('ticket',t['ticket_id'],t,status=t['status'])
 def all(self): return [validate(x['body']) for x in self.client.list_entities('ticket',limit=10000)]
 def clear(self):
  for x in self.client.list_entities('ticket',limit=10000): self.client.delete_entity('ticket',x['name'])
class MemoryTestStore:
 backend_name='test-memory'
 def __init__(self): self.rows={}
 def get(self,k): return self.rows.get(k)
 def put(self,t): validate(t); self.rows[t['ticket_id']]=json.loads(json.dumps(t))
 def all(self): return list(self.rows.values())
 def clear(self): self.rows.clear()
def credit_for(days): return 0 if days<=0 else 5 if days==1 else 10 if days<=3 else 20
class VirtualsCoordinator:
 def coordinate(self,t):
  url,key=os.getenv('VIRTUALS_ACP_URL'),os.getenv('VIRTUALS_API_KEY')
  if not url or not key: raise RuntimeError('Virtuals ACP credentials are required; no local substitute exists')
  import requests
  r=requests.post(url,json={'workflow':'continuum-accountability-v1','idempotency_key':t['breach_event_id'],'ticket':{'ticket_id_hash':digest(t['ticket_id']),'vendor_id_hash':digest(t['vendor_id']),'credit':t['resolution_credit']}},headers={'Authorization':'Bearer '+key},timeout=30); r.raise_for_status(); out=r.json(); event=out.get('event_id') if isinstance(out,dict) else None
  if not isinstance(event,str) or not event: raise RuntimeError('Virtuals response lacks event_id')
  return event
class BaseAttestation:
 def payload(self,t): return {'vendor_id_hash':digest(t['vendor_id']),'ticket_id_hash':digest(t['ticket_id']),'commitment_hash':digest(t['promise_made']),'promised_date':t['promised_date'],'breached_at':t['breach_event_id']}
 def submit(self,t,store):
  if not os.getenv('BASE_PRIVATE_KEY') or not os.getenv('BASE_RPC_URL'): raise RuntimeError('Base credentials missing')
  from web3 import Web3
  w3=Web3(Web3.HTTPProvider(os.environ['BASE_RPC_URL']))
  if w3.eth.chain_id!=84532: raise RuntimeError('Base Sepolia (84532) is required')
  acct=w3.eth.account.from_key(os.environ['BASE_PRIVATE_KEY']); p=self.payload(t); intent=t.get('attestation_intent'); nonce=intent['nonce'] if intent else w3.eth.get_transaction_count(acct.address,'pending')
  tx={'from':acct.address,'to':acct.address,'value':0,'data':w3.to_hex(text=json.dumps(p,separators=(',',':'))),'nonce':nonce,'chainId':84532,'gas':100000,'maxFeePerGas':w3.to_wei(1,'gwei'),'maxPriorityFeePerGas':w3.to_wei(1,'gwei')}; signed=acct.sign_transaction(tx); h=w3.to_hex(signed.hash)
  if not intent: t['attestation_intent']={'tx_hash':h,'nonce':nonce,'payload_hash':digest(json.dumps(p,sort_keys=True))}; store.put(t)
  w3.eth.send_raw_transaction(signed.raw_transaction); w3.eth.wait_for_transaction_receipt(h); return h,iso(now())
def process_ticket(t,store,coordinator=None,attestor=None,clock=now):
 validate(t)
 if t['status']=='resolved' or (t['status']=='broken' and t.get('attestation_tx_hash')): return t
 if t['status']=='pending':
  d=datetime.fromisoformat(t['promised_date'].replace('Z','+00:00')); late=(clock()-d).total_seconds()/86400
  if late<=0: return t
  t.update(status='broken',escalation_count=t['escalation_count']+1,resolution_credit=credit_for(max(1,int(late))),breach_event_id=iso(clock()),last_action='deadline breach detected'); store.put(t)
  if t['status']=='broken' and not t.get('virtuals_event_id'):
   t['virtuals_event_id']=(coordinator or VirtualsCoordinator()).coordinate(t); store.put(t)
 if t['status']=='broken' and not t.get('attestation_tx_hash'):
  h,ts=(attestor or BaseAttestation()).submit(t,store); t.update(attestation_tx_hash=h,attestation_timestamp=ts,last_action='Base attestation confirmed'); store.put(t)
 return t
def new_ticket(i,c,v,issue,promise,date): return {'ticket_id':i,'customer_id':c,'vendor_id':v,'issue_summary':issue,'promise_made':promise,'promised_date':date,'status':'pending','escalation_count':0,'resolution_credit':0,'attestation_tx_hash':None,'attestation_timestamp':None,'last_action':'promise recorded','breach_event_id':None,'attestation_intent':None,'virtuals_event_id':None}
def main():
 p=argparse.ArgumentParser(); p.add_argument('command',choices=['session1','session2','session3','check-deadlines','clear-memory','create-ticket','doctor']); p.add_argument('ticket_id',nargs='?',default='T-1042'); p.add_argument('--customer-id',default='C-001'); p.add_argument('--vendor-id',default='V-001'); p.add_argument('--issue-summary',default='Support issue'); p.add_argument('--promise-made',default='Resolve the issue'); p.add_argument('--promised-date'); a=p.parse_args(); m=SibylMemory()
 if a.command=='doctor': print(json.dumps({'memory_backend':m.backend_name,'sibyl_db':str(SIBYL_DB),'base_configured':bool(os.getenv('BASE_PRIVATE_KEY') and os.getenv('BASE_RPC_URL')),'virtuals_configured':bool(os.getenv('VIRTUALS_API_KEY') and os.getenv('VIRTUALS_ACP_URL'))},indent=2)); return
 if a.command=='clear-memory': m.clear(); print('Sibyl Memory cleared.'); return
 if a.command=='session1': m.put(new_ticket('T-1042','C-001','V-001','Package has not arrived.','Resolve delivery issue','2026-08-18T17:00:00+00:00')); return
 if a.command=='create-ticket':
  if not a.promised_date: p.error('create-ticket requires --promised-date')
  m.put(new_ticket(a.ticket_id,a.customer_id,a.vendor_id,a.issue_summary,a.promise_made,a.promised_date)); return
 if a.command in {'session2','session3'}:
  t=m.get(a.ticket_id)
  if not t: print('No Sibyl memory found for',a.ticket_id); return
  print(json.dumps(process_ticket(t,m),indent=2)); return
 for t in m.all():
  if t['status']=='pending': process_ticket(t,m)
if __name__=='__main__': main()
