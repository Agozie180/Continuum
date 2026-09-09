# Continuum

Continuum is a **memory-powered accountability runtime** for autonomous agents. When a
vendor makes a commitment ("we'll resolve this by Friday"), Continuum records it as
durable, structured memory in **Sibyl**, then drives a *resumable* workflow off that
memory: detect the breach, **issue a deterministic remedy** (a customer credit memo and a
vendor penalty, priced by policy — not by an LLM), and anchor a tamper-evident attestation
on **Base Sepolia**.

The point of the project is the memory. Continuum accumulates institutional knowledge
about how reliable each vendor is and feeds it forward into future decisions, so the
*same* lateness costs a repeat offender more than a first-timer. Delete Sibyl and there
is no state, no recall, and no consequence — memory is the product, not a cache.

The runtime is fully functional with **Sibyl + Base alone**. Virtuals ACP is not on the
core path; a clean, unwired integration seam (`VirtualsCoordinator`) is kept for when ACP
credentials exist, and it is a real client — never a fake.

### The 30-second pitch

Autonomous agents can make promises but usually cannot remember, enforce, or prove them.
Continuum turns each promise into a durable accountability object: Sibyl remembers it,
deterministic policy detects a breach, prices the consequence, and **issues a remedy**, and
Base Sepolia records a privacy-safe proof of what happened. The next session inherits the
prior history, so repeat failures cost more. This is accountability infrastructure, not a
support chatbot.

## Memory architecture

All state lives in Sibyl, across three of its tiers. Everything is in
[`continuum.py`](continuum.py); the memory layer is the `SibylMemory` class.

| Tier | Sibyl primitive | What Continuum stores | Where |
| --- | --- | --- | --- |
| WARM | `set_entity("ticket", …)` | Per-commitment operational state, the issued **remedy**, **and the saga cursor** (`phase`) | `SibylMemory.put/get/all` |
| WARM | `set_entity("vendor", …)` | Institutional vendor reputation, **derived** from ticket history | `SibylMemory.refresh_reputation` |
| HOT | `set_state("agent_reputation", …)` | Compounding agent-level counters | `SibylMemory.refresh_reputation` |
| COLD | `write_event(evaluated, acted, forward)` | Append-only consequence ledger | `SibylMemory.append_ledger` |

The journal uses Sibyl's purpose-built accountability triple: **`evaluated`** (what memory
said), **`acted`** (the consequence taken), **`forward`** (the institutional update). One
row is appended per state transition, so the ledger is a faithful, immutable audit trail.

Reputation is **derived** from durable ticket history, never blindly incremented
(`derive_vendor_reputation`, `derive_agent_reputation`). That makes it idempotent by
construction — reprocessing a breach cannot double-count it — and it is then materialized
as a queryable `vendor/<id>` entity and the `agent_reputation` state document.

## The workflow is a resumable saga

`AccountabilityRuntime` advances a ticket through explicit phases:

```
OPEN ──deadline passed──► BREACHED ──explicit attest──► ATTESTED ──► CLOSED
  │                          │
  └─ deadline not passed ────┤  breach + remedy are durably recorded here; the
     stays OPEN              │  on-chain attestation is a separate, opt-in step
     (no consequence)        
```

Each arrow is guarded **only by durable state** (`phase` plus the presence of a result
like `attestation_tx_hash`), and it persists to Sibyl before and after any external side
effect. `process()` drives the ticket to a fixpoint, so a run resumes from wherever the
previous one stopped:

- Breach **detection and remedy issuance** are pure memory work and always run
  (`OPEN → BREACHED`). The remedy — a customer credit memo and a vendor penalty, priced by
  the deterministic policy — is *issued* (recorded as owed) here; **settlement** (moving
  funds) is deliberately left off the core path. Its id is a pure function of the ticket
  and breach event, so reprocessing can never issue it twice.
- On-chain **attestation** is the one irreversible side effect, so it fires **only under
  an explicit opt-in** (`allow_attestation` / the `attest` command). Without it the saga
  rests safely at `BREACHED`; routine processing and the deadline sweep never spend
  on-chain by accident.
- A crash after breach detection but before attestation resumes **at attestation** and
  re-uses the same durable breach — it is never lost or re-counted.
- Re-running a `CLOSED` ticket fires no arrow and makes no external calls.

Idempotency is enforced at the source: the Base transaction intent (nonce + payload hash)
is persisted *before* broadcast, so a crash-retry re-sends the identical transaction on
the same nonce instead of double-spending.

## Reproduce

```powershell
python -m pip install -r requirements.txt
sibyl init
sibyl setup
sibyl health
sibyl status
Copy-Item .env.example .env
python continuum.py doctor
```

`doctor` prints the memory backend, the resolved Sibyl DB path and tenant, the ticket
count, whether Base credentials are configured, and that attestation is an explicit
opt-in.

Production execution requires **Sibyl** and **Base Sepolia** credentials. There is **no**
JSON or local-development substitute for either. Configure `SIBYL_MEMORY_DB`,
`SIBYL_TENANT_ID`, `BASE_PRIVATE_KEY`, and `BASE_RPC_URL` in `.env`; never commit `.env`.

## Fresh-session demo (memory is load-bearing)

For a judge-safe run that uses a temporary Sibyl database and leaves repository data
untouched:

```powershell
python tools/judge_demo.py
```

Generate a recorded walkthrough with `python tools/record_demo.py`; it executes the real
CLI against a temporary Sibyl database, does not broadcast a transaction, and writes
`output/continuum_demo.mp4` locally (the video is generated on demand, not committed to
the repository).

```powershell
python continuum.py clear-memory        # start from empty Sibyl memory
python continuum.py session1            # writes T-1042 to Sibyl (phase=OPEN), then exits
# --- process fully terminates; nothing is held in RAM ---
python continuum.py session2 T-1042     # a NEW process recalls T-1042, breaches, issues a remedy
python continuum.py attest  T-1042      # deliberate on-chain step: real Base Sepolia tx
```

Session 2 shares no memory with session 1 except Sibyl. It recalls the ticket, sees the
promised date is in the past, transitions `OPEN → BREACHED`, records the consequence and a
deterministic **remedy**, and **stops** — it does not broadcast. `attest` is the explicit
step that anchors the breach on-chain (`BREACHED → ATTESTED → CLOSED`); if a crash
interrupts it, the next `attest` resumes on the same transaction nonce. Every command is
idempotent.

**Memory feeds forward — the same lateness costs a repeat offender more.** Give the same
vendor a second identical commitment and the history Sibyl carries changes the decision:

```powershell
python continuum.py create-ticket T-1043 --vendor-id V-001 --promised-date 2026-08-18T17:00:00+00:00
python continuum.py session2 T-1043     # same lateness, but V-001 is now HIGH-RISK
```

The first breach (V-001 *trusted*) issues a $20 credit at escalation level 3; the second,
for identical lateness, issues **$40 at level 5** — because Sibyl remembers the first
breach and the policy prices repeat offenders higher. Delete Sibyl and the second breach
would look exactly like the first. (`python tools/judge_demo.py` runs this whole sequence
against a throwaway database and asserts the escalation.)

Inspect the accumulated memory:

```powershell
python continuum.py vendor V-001        # derived vendor reputation
python continuum.py ledger              # the append-only evaluated/acted/forward journal
python continuum.py dashboard           # read-only at-a-glance view of all of the above
python continuum.py verify-evidence     # re-check the persisted Base receipts on-chain
```

`dashboard` is a pure projection of durable Sibyl memory — agent reputation, every
commitment with its saga phase, derived vendor reputation, and the ledger tail. It never
advances the saga and never broadcasts, so it is safe to run at any point. (Render it to a
PNG with `python tools/shoot_dashboard.py`, which needs `Pillow`.)

`InMemoryStore` in `continuum.py` exists **only** for the unit tests
(`python -m unittest test_continuum.py`); it is never used in production.

The demo deliberately stops before broadcasting. To show the real Base step, configure a
funded Base Sepolia key in a private `.env`, then run `python continuum.py attest T-1042`.
Never commit that key. The local `.env` shipped with this repository contains no secrets.

## Partner boundaries

Base must be Base Sepolia (`chain_id=84532`); Continuum writes only hashes (of the vendor
id, ticket id, commitment, and the issued remedy), the promised date, and the breach
timestamp to the transaction calldata. Customer identifiers and issue text never leave
Sibyl. The `remedy_hash` lets anyone prove *what was owed* against the on-chain record
without exposing the amount.

Virtuals ACP is an **optional, off-path** integration. `VirtualsCoordinator` is a real
client kept as a clean seam; it is not wired into the runtime and is never faked. To
enable it later, restore a `virtuals_event_id` field, add a non-blocking `BREACHED` branch
that records the event id, and supply `VIRTUALS_ACP_URL` / `VIRTUALS_API_KEY`.

There is no Virtuals-native execution claim in this submission. ACP access was unavailable,
so Virtuals partner credit should be treated as zero. The core product remains complete
without it.

## Base evidence

The persisted transaction hashes in [`evidence/base-sepolia.json`](evidence/base-sepolia.json)
were independently checked on Base Sepolia (`chain_id=84532`) and returned successful
receipts. The explorer links are public. Calldata contains only hashed identifiers,
commitment hash, remedy hash, promised date, and breach timestamp; customer IDs and issue
text stay in Sibyl.

Re-verify them yourself against a live RPC — this reads chain state and broadcasts nothing:

```powershell
python continuum.py verify-evidence     # confirms status==1, chain 84532, and privacy-safe calldata
```

For each transaction it fetches the receipt, checks the status and chain id, decodes the
calldata, and asserts every key is in the privacy-safe allow-list (no customer id, no issue
text). It needs only `BASE_RPC_URL`; no private key is used.

## Why this can be a product

Continuum is aimed first at agent operators, marketplaces, and vendor platforms where a
missed promise has a measurable cost. Their current options are reminders, tickets, or
bespoke workflow code; none carries institutional reliability forward across independent
agent sessions with a verifiable outcome record. A pilot can start with one commitment
type, one deterministic credit policy, and Base attestations enabled only for material
breaches. The product metric is simple: fewer repeated breaches and faster, auditable
recovery.

### Market & cost model (illustrative)

The numbers below are an **illustrative** unit model to show the shape of the economics,
not measured results or a forecast.

- **Who pays and why now.** Marketplaces and agent operators are the buyers: as more vendor
  interactions are handled by autonomous agents, "the agent said it would and then forgot"
  becomes a recurring, unpriced liability. Continuum is the system of record that prices it.
- **Where the value is.** A missed promise already has a cost — a credit, a churned
  customer, an SLA penalty. Continuum's job is to *reduce repeat* breaches by carrying
  reliability forward, and to make each outcome auditable.
- **Illustrative unit math.** A platform tracking **10,000 commitments/month** at a **4%**
  breach rate issues ≈ **400 remedies/month**; at an average **$18** credit that is
  ≈ **$7,200/month** in priced, logged accountability flowing through one deterministic
  policy. Anchoring only material breaches on Base Sepolia keeps per-event cost negligible
  (calldata is a few hashes). The pitch to the buyer is that surfacing and pricing repeat
  offenders shifts that breach rate down over time.
- **Pricing.** A per-tracked-commitment fee (fractions of a cent) or a percentage of
  credits administered — either way the cost is small next to the mispriced-liability it
  replaces.

## Submission checklist

- `python -m unittest test_continuum.py` passes all tests (18: policy, saga, reputation, remedy, Base recovery).
- `python tools/judge_demo.py` proves fresh-process Sibyl recall, idempotency, and memory-driven escalation.
- Base Sepolia evidence and explorer links are in `evidence/base-sepolia.json`; `python continuum.py verify-evidence` re-checks them on-chain.
- Virtuals is explicitly unverified and off the core path; no fabricated execution is used.
- Local credentials are blank and `.env` is ignored by Git.
- Read [`SECURITY.md`](SECURITY.md) before any public deployment; previously exposed local credentials must be rotated.

## Prior Work

Continuum was built for the Sibyl Labs Hackathon. No prior project or submission is being
reused.

## License

MIT. See [LICENSE](LICENSE).
