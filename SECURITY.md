# Security Notes

Continuum must never ship credentials. `.env` is ignored by Git and the checked-in
`.env.example` contains blank values only.

The development workspace previously contained local API and Base key values. They have
been removed from the working `.env`; those values must be treated as compromised and
revoked/rotated at their providers before any public submission or deployment.

Use a dedicated, low-balance Base Sepolia account for demos. The attestor validates the
chain ID and stores only privacy-safe hashes plus timing data in transaction calldata.
