# Continuum

Continuum is a **memory-powered accountability runtime** for autonomous agents. When a
vendor makes a commitment ("we'll resolve this by Friday"), Continuum records it as
durable, structured memory in **Sibyl**, then drives a *resumable* workflow off that
memory: detect the breach, decide a consequence, and anchor a tamper-evident attestation
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
deterministic policy detects a breach and prices the consequence, and Base Sepolia records
a privacy-safe proof of what happened. The next session inherits the prior history, so
repeat failures cost more. This is accountability infrastructure, not a support chatbot.

## Memory architecture

All state lives in Sibyl, across three of its tiers. Everything is in
[`continuum.py`](continuum.py); the memory layer is the `SibylMemory` class.

| Tier | Sibyl primitive | What Continuum stores | Where |
| --- | --- | --- | --- |
| WARM | `set_entity("ticket", …)` | Per-commitment operational state **and the saga cursor** (`phase`) | `SibylMemory.put/get/all` |
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
  └─ deadline not passed ────┤  breach is durably recorded here; the on-chain
     stays OPEN              │  attestation is a separate, opt-in step
     (no consequence)        
```

Each arrow is guarded **only by durable state** (`phase` plus the presence of a result
like `attestation_tx_hash`), and it persists to Sibyl before and after any external side
effect. `process()` drives the ticket to a fixpoint, so a run resumes from wherever the
previous one stopped:

- Breach **detection** is pure memory work and always runs (`OPEN → BREACHED`).
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

The recorded judge demo is [`output/continuum_demo.mp4`](output/continuum_demo.mp4).
Regenerate it with `python tools/record_demo.py`; it executes the real CLI against a
temporary Sibyl database and does not broadcast a transaction.

```powershell
python continuum.py clear-memory        # start from empty Sibyl memory
python continuum.py session1            # writes T-1042 to Sibyl (phase=OPEN), then exits
# --- process fully terminates; nothing is held in RAM ---
python continuum.py session2 T-1042     # a NEW process recalls T-1042 and records the breach
python continuum.py attest  T-1042      # deliberate on-chain step: real Base Sepolia tx
```

Session 2 shares no memory with session 1 except Sibyl. It recalls the ticket, sees the
promised date is in the past, transitions `OPEN → BREACHED`, records the consequence, and
**stops** — it does not broadcast. `attest` is the explicit step that anchors the breach
on-chain (`BREACHED → ATTESTED → CLOSED`); if a crash interrupts it, the next `attest`
resumes on the same transaction nonce. Every command is idempotent.

Inspect the accumulated memory:

```powershell
python continuum.py vendor V-001        # derived vendor reputation
python continuum.py ledger              # the append-only evaluated/acted/forward journal
python continuum.py dashboard           # read-only at-a-glance view of all of the above
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

Base must be Base Sepolia (`chain_id=84532`); Continuum writes only hashes, the promised
date, and the breach timestamp to the transaction calldata. Customer identifiers and issue
text never leave Sibyl.

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
commitment hash, promised date, and breach timestamp; customer IDs and issue text stay in
Sibyl.

## Why this can be a product

Continuum is aimed first at agent operators, marketplaces, and vendor platforms where a
missed promise has a measurable cost. Their current options are reminders, tickets, or
bespoke workflow code; none carries institutional reliability forward across independent
agent sessions with a verifiable outcome record. A pilot can start with one commitment
type, one deterministic credit policy, and Base attestations enabled only for material
breaches. The product metric is simple: fewer repeated breaches and faster, auditable
recovery.

## Submission checklist

- `python -m pytest -q` passes all tests.
- `python tools/judge_demo.py` proves fresh-process Sibyl recall and idempotency.
- Base Sepolia evidence and explorer links are in `evidence/base-sepolia.json`.
- Virtuals is explicitly unverified and off the core path; no fabricated execution is used.
- Local credentials are blank and `.env` is ignored by Git.
- Read [`SECURITY.md`](SECURITY.md) before any public deployment; previously exposed local credentials must be rotated.

## Prior Work

Continuum was built for the Sibyl Labs Hackathon. No prior project or submission is being
reused.

## License

MIT. See [LICENSE](LICENSE).
