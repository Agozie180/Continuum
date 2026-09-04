# Continuum

Continuum is a deadline-accountability runtime. It stores structured commitments in Sibyl Memory, evaluates deadlines with deterministic policy, and records downstream partner results against the same ticket.

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

Production execution requires Sibyl, Base Sepolia credentials, and a real Virtuals ACP endpoint. There is no production JSON or local-development substitute. Configure `SIBYL_MEMORY_DB`, `SIBYL_TENANT_ID`, `BASE_PRIVATE_KEY`, `BASE_RPC_URL`, `VIRTUALS_ACP_URL`, and `VIRTUALS_API_KEY` in `.env`; never commit `.env`.

## Fresh-session demo

Run `python continuum.py session1`, terminate the process, then run `python continuum.py session2 T-1042` in a new process. Session 2 must retrieve the ticket from Sibyl and apply the deterministic expired-deadline transition. A repeated run is idempotent because the persisted ticket contains the breach event, Virtuals event, attestation intent, and confirmed transaction hash.

`MemoryTestStore` exists only for unit tests. Removing Sibyl from production removes the ticket store and therefore removes recall, deadline evaluation, and consequence processing.

## Partner boundaries

Virtuals must return a durable `event_id` for the breach workflow. Base must be Base Sepolia (`chain_id=84532`); Continuum writes only hashes, the deadline, and breach timestamp to the transaction calldata. Customer identifiers and issue text remain in Sibyl.

## Prior Work

Continuum was built for the Sibyl Labs Hackathon. No prior project or submission is being reused.

## License

MIT. See [LICENSE](LICENSE).
