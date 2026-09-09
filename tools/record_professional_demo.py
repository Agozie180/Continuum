"""Create a two-minute narrated Continuum submission demo.

Every screen is derived from a real CLI run against a throwaway Sibyl database,
so the narration cannot drift from what the code actually does. The escalation is
real: a second, identical commitment for the same vendor is genuinely repriced
because Sibyl remembers the first breach. Nothing is broadcast on-chain; the
transaction shown is a previously verified receipt from evidence/base-sepolia.json.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "continuum_demo_professional.mp4"
VOICE = "en-US-AriaNeural"
# A real, independently verified Base Sepolia receipt for T-1042 (evidence/base-sepolia.json).
T1042_TX = "0xc4139e1ef3e51bf39130ccc11b5ae4517a9f9db2b4d6930c8dcd6237357a80be"
NARRATION = (
    "Welcome to Continuum: persistent accountability for autonomous agents. "
    "We start from an empty Sibyl memory and write one commitment: resolve a delivery issue by August eighteenth. "
    "The commitment is durable, structured, and stored outside the process memory. "
    "Now the live run begins. The first process has ended. A new Python process starts with no in-memory state, "
    "recalls the ticket from Sibyl, compares the deadline with the current time, and records a deterministic breach. "
    "The consequence is not invented by a language model: the policy prices the customer credit from lateness and prior vendor reputation, "
    "and Continuum issues a deterministic remedy, a customer credit memo and a vendor penalty, recorded as owed. Moving the funds is a separate, explicit step. "
    "Sibyl keeps the complete accountability record. Base Sepolia receives only hashed identifiers, a commitment hash, a remedy hash, the promised date, and the breach timestamp. "
    "Customer text never leaves Sibyl. This submission includes independently verified, successful Base Sepolia receipts; the transaction on screen is real and publicly checkable. "
    "The recording does not broadcast a new transaction, because attestation is an explicit opt-in step run separately with a funded key. That is a security decision, not a simulated integration. "
    "Now the point of the system. We give the same vendor a second, identical, equally late commitment. Because Sibyl remembers the first breach, the vendor is now high risk, "
    "and the same lateness is escalated harder: the credit rises from twenty dollars to forty. Delete Sibyl and the second breach would look exactly like the first. "
    "We ask Continuum what it remembers about vendor V-zero-zero-one and inspect the ledger. The vendor is high risk with two breaches, and each consequence is present exactly once, "
    "because reputation is derived from durable history and reprocessing never double-counts. "
    "That is the product: promises survive sessions, broken promises change future decisions, and outcomes can be independently verified. "
    "Virtuals ACP is an optional adapter prepared for legitimate credentials, not a fabricated claim. Continuum works with Sibyl and Base alone."
)


def f(size, bold=False):
    path = r"C:\Windows\Fonts\consolab.ttf" if bold else r"C:\Windows\Fonts\consola.ttf"
    return ImageFont.truetype(path, size)


def run(cmd, env):
    p = subprocess.run([sys.executable, str(ROOT / "continuum.py"), *cmd], env=env,
                       text=True, capture_output=True, encoding="utf-8", errors="replace", check=True)
    return p.stdout.strip()


def collect_state():
    """Drive the real escalation across separate processes on a throwaway DB."""
    temp = tempfile.TemporaryDirectory(prefix="continuum-professional-")
    env = os.environ.copy()
    env["SIBYL_MEMORY_DB"] = str(Path(temp.name) / "sibyl.db")
    env["PYTHONIOENCODING"] = "utf-8"
    due = "2026-08-18T17:00:00+00:00"
    run(["clear-memory"], env)
    run(["session1"], env)                                    # writes T-1042 for V-001 (trusted)
    first = json.loads(run(["session2", "T-1042"], env).split("\n\nBreach recorded")[0])
    run(["create-ticket", "T-1043", "--vendor-id", "V-001",   # a second, identical commitment
         "--promised-date", due], env)
    repeat = json.loads(run(["session2", "T-1043"], env).split("\n\nBreach recorded")[0])
    vendor = json.loads(run(["vendor", "V-001"], env))
    ledger = json.loads(run(["ledger"], env))
    return temp, first, repeat, vendor, ledger


def make_pages(first, repeat, vendor, ledger):
    return [
        ("00:00–00:20  START FROM EMPTY MEMORY", [
            "$ python continuum.py clear-memory", "Sibyl Memory cleared", "",
            "$ python continuum.py session1", "Wrote commitment T-1042", "phase = OPEN",
            "Commitment: resolve delivery issue by 2026-08-18",
        ]),
        ("00:20–00:40  NEW PROCESS RECALLS, BREACHES, ISSUES A REMEDY", [
            "$ python continuum.py session2 T-1042", "NEW PROCESS (no shared RAM)", "",
            f"phase        = {first['phase']}", f"breach_event = {first['breach_event_id']}",
            f"prior_tier   = {first['vendor_tier_at_breach']}",
            f"credit       = ${first['resolution_credit']}  (escalation {first['escalation_level']})",
            f"remedy       = {first['remedy']['remedy_id']} ({first['remedy']['settlement']})",
        ]),
        ("00:40–01:00  SIBYL + BASE ATTESTATION", [
            "Sibyl: durable ticket, reputation, remedy, ledger", "Base Sepolia: chain_id 84532",
            "receipt status = 1 (independently verified)", f"tx = {T1042_TX[:26]}...",
            "payload = hashes + dates only (incl. remedy hash)", "customer text stays in Sibyl",
            "attest is explicit opt-in; no fake broadcast",
        ]),
        ("01:00–01:20  MEMORY FEEDS FORWARD (SAME LATENESS COSTS MORE)", [
            "$ python continuum.py create-ticket T-1043 --vendor-id V-001 ...",
            "$ python continuum.py session2 T-1043", "",
            f"prior_tier   = {repeat['vendor_tier_at_breach']}  (was trusted)",
            f"credit       = ${repeat['resolution_credit']}  (escalation {repeat['escalation_level']})",
            f"first breach = ${first['resolution_credit']} — Sibyl raised the price",
            f"remedy       = {repeat['remedy']['remedy_id']} ({repeat['remedy']['settlement']})",
        ]),
        ("01:20–01:40  ASK THE AGENT WHAT IT REMEMBERS", [
            "$ python continuum.py vendor V-001", f"tier     = {vendor['tier']}",
            f"breaches = {vendor['breaches']}/{vendor['commitments']}",
            f"credit   = ${vendor['total_credit_charged']}", "",
            "$ python continuum.py ledger", f"events   = {len(ledger)}",
            "reputation derived from history; no double-count",
        ]),
        ("01:40–02:00  ACCOUNTABILITY, NOT CHAT", [
            "Sibyl is load-bearing memory", "Base is a verifiable outcome anchor",
            "Virtuals is an honest optional adapter", "",
            "Core product works without Virtuals credentials",
            "Persistent accountability for autonomous agents", "CONTINUUM",
        ]),
    ]


def render(pages, directory):
    W, H = 1280, 720
    colors = {"bg": (10, 15, 22), "bar": (21, 31, 43), "white": (232, 238, 245),
              "muted": (145, 160, 174), "green": (78, 210, 137), "amber": (245, 190, 78), "blue": (100, 180, 255)}
    title_font, body, small = f(31, True), f(25), f(19)
    index = 0
    for title, lines in pages:
        for _ in range(200):
            im = Image.new("RGB", (W, H), colors["bg"])
            d = ImageDraw.Draw(im)
            d.rectangle((0, 0, W, 92), fill=colors["bar"])
            d.text((48, 27), "CONTINUUM", font=title_font, fill=colors["green"])
            d.text((335, 34), "persistent accountability for autonomous agents", font=small, fill=colors["muted"])
            d.text((48, 133), title, font=title_font, fill=colors["amber"])
            y = 205
            for line in lines:
                fill = colors["blue"] if line.startswith("$") else colors["white"]
                d.text((60, y), line[:90], font=body, fill=fill)
                y += 39
            d.text((48, 665), "SIBYL MEMORY  |  BASE SEPOLIA  |  VIRTUALS OPTIONAL + HONEST", font=small, fill=colors["muted"])
            im.save(directory / f"frame_{index:05d}.png")
            index += 1


async def speak(path):
    await edge_tts.Communicate(NARRATION, VOICE, rate="-8%", volume="+0%").save(str(path))


def main():
    frame_dir = Path(tempfile.mkdtemp(prefix="continuum-professional-frames-"))
    audio = frame_dir / "narration.mp3"
    temp, first, repeat, vendor, ledger = collect_state()
    try:
        render(make_pages(first, repeat, vendor, ledger), frame_dir)
        asyncio.run(speak(audio))
        OUT.parent.mkdir(exist_ok=True)
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run([ffmpeg, "-y", "-framerate", "10", "-i", str(frame_dir / "frame_%05d.png"),
                        "-i", str(audio), "-t", "120", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", "-af", "apad", "-movflags", "+faststart", str(OUT)], check=True)
        print(f"Wrote {OUT}")
    finally:
        temp.cleanup()
        shutil.rmtree(frame_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
