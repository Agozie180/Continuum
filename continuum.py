"""Continuum: accountability memory demo for autonomous agents."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MEMORY_FILE = DATA / "sibyl_memory.json"
REPUTATION_FILE = DATA / "reputation.json"
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
except ImportError:
    pass

def now(): return datetime.now(timezone.utc)
def iso(dt): return dt.astimezone(timezone.utc).isoformat()

class SibylMemory:
    """Durable store. Uses Sibyl CLI when SIBYL_MEMORY_COMMAND is configured."""
    def __init__(self, path=MEMORY_FILE):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
    def _load(self):
        if not self.path.exists(): return {}
        return json.loads(self.path.read_text())
    def _save(self, data): self.path.write_text(json.dumps(data, indent=2))
    def put(self, ticket):
        if os.getenv('SIBYL_MEMORY_COMMAND'):
            subprocess.run([os.environ['SIBYL_MEMORY_COMMAND'],'put',ticket['ticket_id'],json.dumps(ticket)],check=True)
            return
        data=self._load(); data[ticket['ticket_id']]=ticket; self._save(data)
    def get(self, ticket_id):
        if os.getenv('SIBYL_MEMORY_COMMAND'):
            result=subprocess.run([os.environ['SIBYL_MEMORY_COMMAND'],'get',ticket_id],check=True,capture_output=True,text=True)
            return json.loads(result.stdout) if result.stdout.strip() else None
        return self._load().get(ticket_id)
    def all(self):
        if os.getenv('SIBYL_MEMORY_COMMAND'):
            result=subprocess.run([os.environ['SIBYL_MEMORY_COMMAND'],'list','--json'],check=True,capture_output=True,text=True)
            return json.loads(result.stdout)
        return list(self._load().values())
    def clear(self): self._save({})

def credit_for(days_late):
    if days_late <= 0: return 0
    if days_late == 1: return 5
    if days_late <= 3: return 10
    return 20

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

class BaseAttestation:
    def record_attestation(self, vendor_id, ticket_id, summary, promised_date):
        payload={'vendor_id_hash':digest(vendor_id), 'ticket_id_hash':digest(ticket_id),
                 'commitment_hash':digest(summary), 'promised_date':promised_date,
                 'breached_at':iso(now())}
        if not os.getenv('BASE_PRIVATE_KEY') or not os.getenv('BASE_RPC_URL'):
            raise RuntimeError('Base credentials missing; no attestation was created.')
        from web3 import Web3
        w3=Web3(Web3.HTTPProvider(os.environ['BASE_RPC_URL']))
        acct=w3.eth.account.from_key(os.environ['BASE_PRIVATE_KEY'])
        tx={'from':acct.address,'to':acct.address,'value':0,'data':w3.to_hex(text=json.dumps(payload,separators=(',',':'))),'nonce':w3.eth.get_transaction_count(acct.address),'chainId':84532,'gas':100000,'maxFeePerGas':w3.to_wei(1,'gwei'),'maxPriorityFeePerGas':w3.to_wei(1,'gwei')}
        signed=acct.sign_transaction(tx); txh=w3.eth.send_raw_transaction(signed.raw_transaction); w3.eth.wait_for_transaction_receipt(txh)
        return w3.to_hex(txh), iso(now()), payload

class VirtualsCoordinator:
    def coordinate(self, ticket):
        steps=['support_agent: verified customer context','accountability_agent: breach policy approved','reputation_agent: outcome queued']
        if os.getenv('VIRTUALS_ACP_URL'):
            import requests
            response=requests.post(os.environ['VIRTUALS_ACP_URL'],json={'workflow':'continuum-accountability-v1','ticket':ticket,'tasks':steps},headers={'Authorization':'Bearer '+os.getenv('VIRTUALS_API_KEY','')},timeout=30)
            response.raise_for_status()
            return response.json()
        return {'workflow':'local-development','agents':steps,'ticket_id':ticket['ticket_id']}

class ClaudeResponder:
    def respond(self, ticket):
        api_key=os.getenv('ANTHROPIC_API_KEY') or os.getenv('ANTHROPIC_AUTH_TOKEN')
        if api_key:
            try:
                import anthropic
                client=anthropic.Anthropic(api_key=api_key, base_url=os.getenv('ANTHROPIC_BASE_URL') or None)
                msg=client.messages.create(model=os.getenv('ANTHROPIC_MODEL','claude-3-5-sonnet-latest'),max_tokens=120,temperature=0,messages=[{'role':'user','content':f"Explain this accountability outcome briefly: ticket {ticket['ticket_id']}, promise '{ticket['promise_made']}', deadline {ticket['promised_date']}, status {ticket['status']}, credit ${ticket['resolution_credit']}."}])
                return msg.content[0].text
            except Exception as exc: return f'Claude unavailable ({exc}); policy response used.'
        return f"The prior promise '{ticket['promise_made']}' was due {ticket['promised_date']} and is now {ticket['status']}."

def process_ticket(ticket, memory, proactive=False):
    if ticket['status']=='broken' and ticket.get('attestation_tx_hash'):
        print('Already processed. No duplicate consequence required.')
        return ticket
    if ticket['status']=='broken':
        print('Consequence already applied. Retrying missing Base attestation only.')
        try:
            txh,ts,_=BaseAttestation().record_attestation(ticket['vendor_id'],ticket['ticket_id'],ticket['promise_made'],ticket['promised_date'])
            ticket['attestation_tx_hash']=txh; ticket['attestation_timestamp']=ts; memory.put(ticket)
            print('BASE ATTESTATION SUBMITTED\nTransaction confirmed\nTX:',txh)
        except Exception as exc: print('BASE ATTESTATION PENDING:',exc)
        return ticket
    deadline=datetime.fromisoformat(ticket['promised_date'].replace('Z','+00:00'))
    late=(now()-deadline).total_seconds()/86400
    if late <= 0:
        print('Commitment is still valid. No consequence triggered.')
        return ticket
    days=max(1,int(late)); ticket['status']='broken'; ticket['escalation_count'] += 1; ticket['resolution_credit']=credit_for(days); ticket['last_action']='deadline breach detected and escalated'
    print('\nCOMMITMENT BROKEN\nDeadline passed.\n Escalating\n Calculating credit: $%s\n' % ticket['resolution_credit'])
    flow=VirtualsCoordinator().coordinate(ticket); print('VIRTUALS COORDINATION'); print(' -> '.join(flow['agents']))
    memory.put(ticket); update_reputation(ticket)
    try:
        txh,ts,payload=BaseAttestation().record_attestation(ticket['vendor_id'],ticket['ticket_id'],ticket['promise_made'],ticket['promised_date'])
        ticket['attestation_tx_hash']=txh; ticket['attestation_timestamp']=ts; ticket['last_action']='Base attestation confirmed'; memory.put(ticket)
        print('BASE ATTESTATION SUBMITTED\nTransaction confirmed\nTX:',txh)
    except Exception as exc:
        print('BASE ATTESTATION PENDING:',exc)
    return ticket

def update_reputation(ticket):
    data=json.loads(REPUTATION_FILE.read_text()) if REPUTATION_FILE.exists() else {'vendor_reliability_profile':{},'agent_reputation':{'agent_id':'continuum-support-01','tickets_processed':0,'promises_tracked':0,'broken_promises_detected':0,'correct_escalations':0,'false_escalations':0,'escalation_accuracy':1.0,'total_credit_recovered':0,'attestations_created':0}}
    v=data['vendor_reliability_profile'].setdefault(ticket['vendor_id'],{'promises_total':0,'promises_broken':0,'reliability_score':1.0,'average_delay_days':0,'total_resolution_credit':0,'attestations':0})
    v['promises_total']=max(1,v['promises_total']); v['promises_broken']+=1; v['reliability_score']=round(1-v['promises_broken']/v['promises_total'],3); v['total_resolution_credit']+=ticket['resolution_credit']; v['attestations']+=1
    a=data['agent_reputation']; a['broken_promises_detected']+=1; a['correct_escalations']+=1; a['total_credit_recovered']+=ticket['resolution_credit']; a['attestations_created']+=1; a['escalation_accuracy']=round(a['correct_escalations']/max(1,a['correct_escalations']+a['false_escalations']),3)
    REPUTATION_FILE.write_text(json.dumps(data,indent=2))

def session1(memory):
    ticket={'ticket_id':'T-1042','customer_id':'C-001','vendor_id':'V-001','issue_summary':'Package has not arrived.','promise_made':'Resolve delivery issue','promised_date':'2026-08-18T17:00:00+00:00','status':'pending','escalation_count':0,'resolution_credit':0,'attestation_tx_hash':None,'attestation_timestamp':None,'last_action':'promise recorded'}
    memory.put(ticket); print('Ticket: T-1042\nCustomer: C-001\nVendor: V-001\n\nIssue: Package has not arrived.\nAgent promise: "I will have this resolved by August 18."\n\nStored in Sibyl Memory.')

def session2(memory, ticket_id):
    t=memory.get(ticket_id)
    if not t: print('No Sibyl memory found for',ticket_id); return
    print('SIBYL RECALL\nTicket:',t['ticket_id'],'\nPromise:',t['promise_made'],'\nDeadline:',t['promised_date'],'\nStatus:',t['status'])
    process_ticket(t,memory)
    print('\nCLAUDE RESPONSE\n'+ClaudeResponder().respond(t))

def check_deadlines(memory):
    pending=[t for t in memory.all() if t['status']=='pending']; print(f'Checking {len(pending)} pending commitment(s)...')
    for t in pending: process_ticket(t,memory,proactive=True)
    if not pending: print('No pending commitments.')

def main():
    p=argparse.ArgumentParser(description='Continuum accountability memory'); p.add_argument('command',choices=['session1','session2','session3','check-deadlines','clear-memory','show-reputation','doctor']); p.add_argument('ticket_id',nargs='?',default='T-1042'); a=p.parse_args(); m=SibylMemory()
    if a.command=='session1': session1(m)
    elif a.command in ('session2','session3'): session2(m,a.ticket_id)
    elif a.command=='check-deadlines': check_deadlines(m)
    elif a.command=='clear-memory': m.clear(); print('Sibyl Memory cleared. Memory-off run cannot recall commitments.')
    elif a.command=='doctor':
        print(json.dumps({'memory_backend':'sibyl-cli' if os.getenv('SIBYL_MEMORY_COMMAND') else 'local-json','sibyl_command':os.getenv('SIBYL_MEMORY_COMMAND'),'claude_configured':bool(os.getenv('ANTHROPIC_API_KEY') or os.getenv('ANTHROPIC_AUTH_TOKEN')),'base_configured':bool(os.getenv('BASE_PRIVATE_KEY') and os.getenv('BASE_RPC_URL')),'virtuals_configured':bool(os.getenv('VIRTUALS_ACP_URL'))},indent=2))
    else: print(json.dumps(json.loads(REPUTATION_FILE.read_text()) if REPUTATION_FILE.exists() else {},indent=2))
if __name__=='__main__': main()
