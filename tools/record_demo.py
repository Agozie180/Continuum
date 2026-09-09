"""Render a judge-ready Continuum demo video from real CLI executions."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "continuum_demo.mp4"


def font(size, bold=False):
    candidates = [
        r"C:\Windows\Fonts\CascadiaMono.ttf",
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\consolab.ttf",
    ]
    path = candidates[2 if bold else 1]
    return ImageFont.truetype(path, size)


def run_demo():
    with tempfile.TemporaryDirectory(prefix="continuum-video-") as dbdir:
        env = os.environ.copy()
        env["SIBYL_MEMORY_DB"] = str(Path(dbdir) / "sibyl.db")
        env["PYTHONIOENCODING"] = "utf-8"
        due = "2026-08-18T17:00:00+00:00"
        commands = [
            ("01  WRITE COMMITMENT TO SIBYL", [["clear-memory"], ["session1"]]),
            ("02  NEW PROCESS: RECALL, BREACH, REMEDY", [["session2", "T-1042"]]),
            ("03  MEMORY FEEDS FORWARD (SAME LATENESS COSTS MORE)",
             [["create-ticket", "T-1043", "--vendor-id", "V-001", "--promised-date", due],
              ["session2", "T-1043"]]),
            ("04  SIBYL DERIVES REPUTATION + LEDGER", [["vendor", "V-001"]]),
            ("05  HONEST PARTNER BOUNDARY", None),
        ]
        pages = []
        first_credit = {}
        for title, args in commands:
            if args is None:
                output = [
                    "Core product: HEALTHY without Virtuals credentials",
                    "Virtuals ACP: optional adapter, not verified live",
                    "Base Sepolia: explicit opt-in attestation step",
                    "Receipts are independently checkable:",
                    "  python continuum.py verify-evidence",
                    "",
                    "Next step (only with a funded key):",
                    "  python continuum.py attest T-1042",
                ]
            else:
                output = []
                last_stdout = ""  # only the final command in a step emits the JSON we parse
                for command in args:
                    p = subprocess.run([sys.executable, str(ROOT / "continuum.py"), *command], env=env,
                                       capture_output=True, text=True, encoding="utf-8", check=True)
                    last_stdout = p.stdout
                    output.extend(p.stdout.strip().splitlines())
                if title.startswith("02"):
                    payload = json.loads(last_stdout.split("\n\nBreach recorded")[0])
                    first_credit["v"] = payload["resolution_credit"]
                    output = [f"phase          = {payload['phase']}",
                              f"breach_event   = {payload['breach_event_id']}",
                              f"prior_tier     = {payload['vendor_tier_at_breach']}",
                              f"credit         = ${payload['resolution_credit']}  (escalation {payload['escalation_level']})",
                              f"remedy         = {payload['remedy']['remedy_id']} ({payload['remedy']['settlement']})",
                              "attestation     = explicit opt-in (not broadcast)"]
                elif title.startswith("03"):
                    payload = json.loads(last_stdout.split("\n\nBreach recorded")[0])
                    output = [f"same lateness, second commitment for V-001",
                              f"prior_tier     = {payload['vendor_tier_at_breach']}  (was trusted)",
                              f"credit         = ${payload['resolution_credit']}  (escalation {payload['escalation_level']})",
                              f"first breach was ${first_credit.get('v', '?')} - memory raised the price",
                              f"remedy         = {payload['remedy']['remedy_id']} ({payload['remedy']['settlement']})"]
                elif title.startswith("04"):
                    payload = json.loads(last_stdout)
                    output = [f"vendor         = {payload['vendor_id']}",
                              f"tier           = {payload['tier']}",
                              f"breaches       = {payload['breaches']}/{payload['commitments']}",
                              f"credit charged = ${payload['total_credit_charged']}"]
            pages.append((title, output))
        return pages


def render(pages, frame_dir):
    W, H = 1280, 720
    bg = (12, 17, 24)
    white = (231, 238, 245)
    muted = (145, 160, 174)
    green = (78, 210, 137)
    amber = (245, 190, 78)
    mono = font(25)
    small = font(20)
    heading = font(32, bold=True)
    n = 0
    for title, lines in pages:
        for hold in range(42):
            im = Image.new("RGB", (W, H), bg)
            d = ImageDraw.Draw(im)
            d.rectangle((0, 0, W, 94), fill=(21, 31, 43))
            d.text((54, 28), "CONTINUUM", font=heading, fill=green)
            d.text((310, 35), "persistent accountability for autonomous agents", font=small, fill=muted)
            d.text((54, 140), title, font=heading, fill=amber)
            d.text((54, 198), "$ python continuum.py", font=mono, fill=muted)
            y = 250
            for line in lines[:14]:
                d.text((54, y), line[:86], font=mono, fill=white if line else muted)
                y += 34
            d.text((54, 665), "Sibyl memory is the product | Base is verifiable | Virtuals is honestly optional", font=small, fill=muted)
            im.save(frame_dir / f"frame_{n:05d}.png")
            n += 1


def main():
    frame_dir = Path(tempfile.mkdtemp(prefix="continuum-frames-"))
    try:
        render(run_demo(), frame_dir)
        OUT.parent.mkdir(exist_ok=True)
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run([ffmpeg, "-y", "-framerate", "12", "-i", str(frame_dir / "frame_%05d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(OUT)], check=True)
        print(f"Wrote {OUT}")
    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
