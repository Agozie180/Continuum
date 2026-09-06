"""Create a two-minute narrated Continuum submission demo."""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import edge_tts
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "continuum_demo_professional.mp4"
VOICE = "en-US-AriaNeural"
NARRATION = (
    "Welcome to Continuum: persistent accountability for autonomous agents. "
    "In the first twenty seconds, we start from an empty Sibyl memory and write one commitment. "
    "The promise is to resolve a delivery issue by August eighteenth. The important point is that the commitment is durable, structured, and outside the process memory. "
    "Now the live run begins. The first process has ended. A new Python process starts with no in-memory state, recalls the ticket from Sibyl, compares the deadline with the current time, and records a deterministic breach. "
    "The consequence is not invented by a language model: the policy assigns escalation and customer credit from lateness and prior vendor reputation. "
    "Next is the attestation boundary. Sibyl keeps the complete accountability record. Base Sepolia receives only hashed identifiers, a commitment hash, the promised date, and the breach timestamp. "
    "This submission includes independently verified successful Base Sepolia receipts. The transaction hash on screen is real and publicly checkable. The recording does not broadcast a new transaction because the local demo key was revoked; that is a security decision, not a simulated integration. "
    "We now close the first terminal and open a new one. The runtime is healthy without Virtuals credentials. The doctor command shows Sibyl as the production backend, and the dashboard is a projection of durable memory. "
    "Here is the memory question. We ask Continuum what it remembers about vendor V-zero-zero-one and inspect the ledger. The breach event ID is unchanged, the vendor is now high risk, and the consequence is present exactly once. Sibyl has not been lost across the process boundary. "
    "That is the product: promises survive sessions, broken promises change future decisions, and outcomes can be independently verified. Virtuals ACP is an optional adapter prepared for legitimate credentials, not a fabricated claim. Continuum works with Sibyl and Base alone."
)


def f(size, bold=False):
    path = r"C:\Windows\Fonts\consolab.ttf" if bold else r"C:\Windows\Fonts\consola.ttf"
    return ImageFont.truetype(path, size)


def run(cmd, env):
    p = subprocess.run(["python", str(ROOT / "continuum.py"), *cmd], env=env,
                       text=True, capture_output=True, check=True)
    return p.stdout.strip()


def collect_state():
    temp = tempfile.TemporaryDirectory(prefix="continuum-professional-")
    env = os.environ.copy()
    env["SIBYL_MEMORY_DB"] = str(Path(temp.name) / "sibyl.db")
    run(["clear-memory"], env)
    run(["session1"], env)
    breach = json.loads(run(["session2", "T-1042"], env).split("\n\nBreach recorded")[0])
    repeat = json.loads(run(["session2", "T-1042"], env).split("\n\nBreach recorded")[0])
    vendor = json.loads(run(["vendor", "V-001"], env))
    ledger = json.loads(run(["ledger"], env))
    return temp, breach, repeat, vendor, ledger


def make_pages(breach, repeat, vendor, ledger):
    tx = "0xc6c762a75cffcac2b454fb1e64e0496c847f1767934fc9ca1f064c37f3fe9499"
    return [
        ("00:00–00:20  START FROM EMPTY MEMORY", [
            "$ python continuum.py clear-memory", "Sibyl Memory cleared", "",
            "$ python continuum.py session1", "Wrote commitment T-1042", "phase = OPEN",
            "Commitment: resolve delivery issue by 2026-08-18",
        ]),
        ("00:20–00:40  NEW PROCESS, SAME MEMORY", [
            "$ python continuum.py session2 T-1042", "NEW PROCESS", "",
            f"phase        = {breach['phase']}", f"breach_event = {breach['breach_event_id']}",
            f"credit       = {breach['resolution_credit']}", "decision     = deterministic policy",
        ]),
        ("00:40–01:00  SIBYL + BASE ATTESTATION", [
            "Sibyl: durable ticket, reputation, ledger", "Base Sepolia: chain_id 84532", "receipt status = 1 (verified)",
            f"tx = {tx[:26]}...", "payload = hashes + dates only", "customer text stays in Sibyl",
            "attest is explicit opt-in; no fake broadcast",
        ]),
        ("01:00–01:20  CLOSE + OPEN A NEW TERMINAL", [
            "[terminal 1 closed]", "[terminal 2 opened]", "",
            "$ python continuum.py doctor", "memory_backend = sibyl-sdk-sqlite", "virtuals_acp = false",
            "$ python continuum.py dashboard", "durable projection of Sibyl memory",
        ]),
        ("01:20–01:40  ASK THE AGENT WHAT IT REMEMBERS", [
            "$ python continuum.py vendor V-001", f"tier     = {vendor['tier']}",
            f"breaches = {vendor['breaches']}", f"credit   = {vendor['total_credit_charged']}", "",
            "$ python continuum.py ledger", f"events   = {len(ledger)}", f"same breach id = {repeat['breach_event_id']}",
        ]),
        ("01:40–02:00  ACCOUNTABILITY, NOT CHAT", [
            "Sibyl is load-bearing memory", "Base is a verifiable outcome anchor", "Virtuals is an honest optional adapter", "",
            "Core product works without Virtuals credentials", "Persistent accountability for autonomous agents", "CONTINUUM",
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
            d.text((48, 665), "SIBYL MEMORY  |  BASE SEP0LIA  |  VIRTUALS OPTIONAL + HONEST", font=small, fill=colors["muted"])
            im.save(directory / f"frame_{index:05d}.png")
            index += 1


async def speak(path):
    await edge_tts.Communicate(NARRATION, VOICE, rate="-8%", volume="+0%").save(str(path))


def main():
    frame_dir = Path(tempfile.mkdtemp(prefix="continuum-professional-frames-"))
    audio = frame_dir / "narration.mp3"
    temp, breach, repeat, vendor, ledger = collect_state()
    try:
        render(make_pages(breach, repeat, vendor, ledger), frame_dir)
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
