# Continuum

Continuum is a **memory-powered accountability runtime** for autonomous agents. When a
vendor makes a commitment ("we'll resolve this by Friday"), Continuum records it as
durable, structured memory in **Sibyl**, then drives a *resumable* workflow off that
memory: detect the breach, decide a consequence, coordinate it through **Virtuals ACP**,
and anchor a tamper-evident attestation on **Base Sepolia**.

The point of the project is the memory. Continuum accumulates institutional knowledge
about how reliable each vendor is and feeds it forward into future decisions, so the
*same* lateness costs a repeat offender more than a first-timer. Delete Sibyl and there
is no state, no recall, and no consequence — memory is the product, not a cache.

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
OPEN ──deadline passed──► BREACHED ──► COORDINATED ──► ATTESTED ──► CLOSED
  │
  └─ deadline not passed ─► stays OPEN (no consequence)
```

Each arrow is guarded **only by durable state** (`phase` plus the presence of a result
like `virtuals_event_id` or `attestation_tx_hash`), and it persists to Sibyl before and
after any external side effect. `process()` drives the ticket to a fixpoint, so a run
resumes from wherever the previous one stopped:

- A crash after breach detection but before coordination resumes **at coordination** — it
  is not skipped (this is the root defect the rebuild fixes).
- A crash after coordination but before attestation resumes **at attestation**, and does
  **not** re-coordinate.
- Re-running a `CLOSED` ticket fires no arrow and makes no partner calls.

Idempotency is enforced at the source: Virtuals receives `breach_event_id` as its
idempotency key, and the Base transaction intent (nonce + payload hash) is persisted
*before* broadcast, so a retry re-sends the identical transaction on the same nonce.

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
count, and whether the Base/Virtuals credentials are configured.

Production execution requires Sibyl, Base Sepolia credentials, and a real Virtuals ACP
endpoint. There is **no** JSON or local-development substitute. Configure
`SIBYL_MEMORY_DB`, `SIBYL_TENANT_ID`, `BASE_PRIVATE_KEY`, `BASE_RPC_URL`,
`VIRTUALS_ACP_URL`, and `VIRTUALS_API_KEY` in `.env`; never commit `.env`.

## Fresh-session demo (memory is load-bearing)

```powershell
python continuum.py clear-memory        # start from empty Sibyl memory
python continuum.py session1            # writes T-1042 to Sibyl (phase=OPEN), then exits
# --- process fully terminates; nothing is held in RAM ---
python continuum.py session2 T-1042     # a NEW process recalls T-1042 and acts on it
```

Session 2 shares no memory with session 1 except Sibyl. It recalls the ticket, sees the
promised date is in the past, transitions `OPEN → BREACHED`, and records the consequence.
With Virtuals/Base credentials configured it continues to `COORDINATED → ATTESTED →
CLOSED`; without them it reports the pending step and the persisted breach, and the next
run resumes from there. Running `session2` again is idempotent.

Inspect the accumulated memory:

```powershell
python continuum.py vendor V-001        # derived vendor reputation
python continuum.py ledger              # the append-only evaluated/acted/forward journal
```

`InMemoryStore` in `continuum.py` exists **only** for the unit tests
(`python -m unittest test_continuum.py`); it is never used in production.

## Partner boundaries

Virtuals must return a durable `event_id` for the breach workflow. Base must be Base
Sepolia (`chain_id=84532`); Continuum writes only hashes, the promised date, and the
breach timestamp to the transaction calldata. Customer identifiers and issue text never
leave Sibyl.

## Prior Work

Continuum was built for the Sibyl Labs Hackathon. No prior project or submission is being
reused.

## License

MIT. See [LICENSE](LICENSE).
