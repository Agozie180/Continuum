"""Submission demo: prove Sibyl recall, idempotency, and memory-driven escalation.

Runs the real CLI against a throwaway Sibyl database (repository data untouched),
across separate processes, and asserts the three claims that matter:

  1. a NEW process recalls the breach from Sibyl alone (no shared RAM);
  2. reprocessing the same breach is idempotent (no duplicate consequence);
  3. institutional memory feeds FORWARD - a repeat offender is escalated harder
     and charged more for the *same* lateness, and the remedy is priced to match.

Broadcasts nothing on-chain; the real Base step is called out at the end.
"""
import json, os, subprocess, sys, tempfile

# The dashboard we echo at the end emits box/block glyphs; make sure our OWN stdout
# can encode them on a default Windows code page (mirrors continuum.py's guard).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUE = "2026-08-18T17:00:00+00:00"  # both commitments share one deadline, so only history differs

with tempfile.TemporaryDirectory(prefix="continuum-judge-") as dbdir:
    env = os.environ.copy()
    env["SIBYL_MEMORY_DB"] = os.path.join(dbdir, "sibyl.db")
    env["PYTHONIOENCODING"] = "utf-8"  # the dashboard prints block/box glyphs

    def run(*args):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "continuum.py"), *args],
                           env=env, text=True, capture_output=True,
                           encoding="utf-8", errors="replace")
        print(f"$ python continuum.py {' '.join(args)}\n{p.stdout.strip()}\n")
        if p.returncode:
            print(p.stderr, file=sys.stderr)
            raise SystemExit(p.returncode)
        return p.stdout

    def breach(*args):
        return json.loads(run(*args).split("\n\nBreach recorded")[0])

    run("clear-memory")

    # -- claim 1 + 2: fresh-process recall, then idempotent reprocessing ----
    run("session1")                              # writes T-1042 (phase=OPEN), then exits
    first = breach("session2", "T-1042")         # a NEW process recalls it and records the breach
    second = breach("session2", "T-1042")        # reprocessing must change nothing
    assert first["phase"] == "BREACHED" and second["phase"] == "BREACHED"
    assert first["breach_event_id"] == second["breach_event_id"], "breach event id must be stable"
    assert first["remedy"]["remedy_id"] == second["remedy"]["remedy_id"], "remedy must not reissue"

    # -- claim 3: memory feeds forward - the SAME lateness costs the repeat --
    #    offender more, because Sibyl remembers the first breach.
    run("create-ticket", "T-1043", "--vendor-id", "V-001",
        "--issue-summary", "Second late delivery", "--promise-made", "Resolve delivery issue",
        "--promised-date", DUE)
    repeat = breach("session2", "T-1043")

    assert repeat["vendor_tier_at_breach"] == "high-risk", \
        f"vendor should be high-risk on the 2nd breach, got {repeat['vendor_tier_at_breach']}"
    assert first["vendor_tier_at_breach"] == "trusted", \
        f"vendor should be trusted on the 1st breach, got {first['vendor_tier_at_breach']}"
    assert repeat["resolution_credit"] > first["resolution_credit"], \
        f"repeat credit {repeat['resolution_credit']} should exceed first {first['resolution_credit']}"
    assert repeat["escalation_level"] > first["escalation_level"], \
        f"repeat escalation {repeat['escalation_level']} should exceed first {first['escalation_level']}"
    assert repeat["remedy"]["customer_credit"] == repeat["resolution_credit"], "remedy must match the decision"

    run("vendor", "V-001")
    ledger = json.loads(run("ledger"))
    breaches = [e for e in ledger if e.get("extra", {}).get("kind") == "breach"]
    assert len(breaches) == 2, f"expected two breach events (one per commitment), got {len(breaches)}"

    run("dashboard")

    print("PASS: fresh process recalled Sibyl state; reprocessing was idempotent;")
    print(f"      the SAME lateness escalated ${first['resolution_credit']} (trusted) -> "
          f"${repeat['resolution_credit']} (high-risk) because memory fed forward.")
    print("For the real Base step, run: python continuum.py attest T-1042")
