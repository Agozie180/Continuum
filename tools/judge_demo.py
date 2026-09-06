"""Submission demo: prove Sibyl recall and idempotent breach handling."""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with tempfile.TemporaryDirectory(prefix="continuum-judge-") as dbdir:
    env = os.environ.copy()
    env["SIBYL_MEMORY_DB"] = os.path.join(dbdir, "sibyl.db")
    def run(*args):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "continuum.py"), *args], env=env, text=True, capture_output=True)
        print(f"$ python continuum.py {' '.join(args)}\n{p.stdout.strip()}\n")
        if p.returncode: raise SystemExit(p.returncode)
        return p.stdout
    run("clear-memory")
    run("session1")
    first = json.loads(run("session2", "T-1042").split("\n\nBreach recorded")[0])
    second = json.loads(run("session2", "T-1042").split("\n\nBreach recorded")[0])
    assert first["phase"] == "BREACHED" and second["phase"] == "BREACHED"
    assert first["breach_event_id"] == second["breach_event_id"]
    run("vendor", "V-001")
    ledger = json.loads(run("ledger"))
    assert len(ledger) == 1, f"expected one breach event, got {len(ledger)}"
    print("PASS: second process recalled Sibyl state; repeat processing created no duplicate breach.")
    print("For the real Base step, run: python continuum.py attest T-1042")
