"""Render `continuum.py dashboard` to a PNG (dark terminal look).

Standalone helper for producing a shareable screenshot of the live memory
view. Pure read-only: it imports the dashboard renderer and paints its text;
it never advances the saga or broadcasts. Not part of the runtime.

    python tools/shoot_dashboard.py [output.png]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import continuum as c  # noqa: E402

# Dark theme tuned to read like the hackathon site.
BG = (13, 17, 23)
FG = (201, 209, 217)
DIM = (110, 118, 129)
PAD = 28
LINE_SPACING = 6


def _mono_font(size=22):
    for name in ("consola.ttf", "CascadiaCode.ttf", "DejaVuSansMono.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(text: str, out_path: Path) -> Path:
    font = _mono_font(22)
    lines = text.split("\n")

    # Measure using the widest line so the frame never clips.
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    char_w = tmp.textlength("M", font=font)
    ascent, descent = font.getmetrics()
    row_h = ascent + descent + LINE_SPACING
    width = int(max(tmp.textlength(ln, font=font) for ln in lines) + PAD * 2)
    height = int(row_h * len(lines) + PAD * 2)

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    y = PAD
    for ln in lines:
        # The trailing caption line is drawn dimmed.
        color = DIM if ln.startswith("read-only view") else FG
        draw.text((PAD, y), ln, font=font, fill=color)
        y += row_h

    img.save(out_path)
    return out_path


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "continuum-dashboard.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = c.render_dashboard(c.SibylMemory())
    saved = render(text, out)
    print(f"Wrote {saved}  ({saved.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
