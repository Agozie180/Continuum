# Continuum

Continuum is an accountability memory system for autonomous agents: promises persist in Sibyl Memory, deadlines are enforced by deterministic policy, agents coordinate consequences, and breaches receive a verifiable Base Sepolia attestation.

## Demo

```bash
cd Continuum
copy .env.example .env
python continuum.py doctor
python continuum.py session1
# terminate process
python continuum.py session2 T-1042
python continuum.py session3 T-1042
python continuum.py check-deadlines
python continuum.py create-ticket T-NEW --customer-id C-NEW --vendor-id V-NEW --issue-summary "Issue" --promise-made "Resolve by Friday" --promised-date 2026-09-10T17:00:00+00:00
```

`doctor` is the required preflight. The default backend is the installed Sibyl Memory SDK with a durable SQLite store. Use `python continuum.py doctor --strict` in a judged/live environment; it refuses to run if the SDK is unavailable. Set `CONTINUUM_MEMORY_BACKEND=json` only for isolated tests. Configure the corresponding values in `.env`; no integration is silently claimed as live.

Session 2 is a fresh process. It recalls the private operational record, detects the expired promise, coordinates Support/Accountability/Reputation agents via the Virtuals ACP adapter, calculates a deterministic credit, and writes a safe hashed payload to Base. `BASE_PRIVATE_KEY` and `BASE_RPC_URL` are required: the app never fabricates a transaction hash. Without credentials the consequence is persisted once and the missing attestation is retried later without issuing a second credit.

`session3` proves idempotency: an already broken ticket with an attestation produces no second credit or transaction. Run `python continuum.py clear-memory` before the same session to demonstrate that memory-off cannot discover the prior commitment.

The Sibyl SDK stores ticket entities in `SIBYL_MEMORY_DB` (default `data/sibyl_memory.db`) and survives process restarts. The `sibyl` CLI can inspect that same store when configured with the matching `--db` path. Detailed customer data never enters the Base payload: only hashes, deadline, and breach time do.

Set `VIRTUALS_ACP_URL` and `VIRTUALS_API_KEY` to send the three-role workflow to a Virtuals-native ACP endpoint. Without them, output is labeled `local-development`; it is not presented as a live Virtuals run.

When `ANTHROPIC_API_KEY` is set, Claude Sonnet explains the recalled outcome after the policy engine has decided the breach and credit. Claude never decides whether a consequence or transaction occurs.

Reputation schemas live in `data/reputation.json`. Vendor reliability aggregates outcomes; agent reputation measures escalation accuracy and recovered credit. Future Virtuals agents can use these profiles for routing, pricing, or selecting reliable vendors.
