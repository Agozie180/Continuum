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

BG = (13, 17, 23)  # dark ground, tuned to read like the hackathon site
PAD = 28
LINE_SPACING = 6


def _mono_font(size=22):
    for name in ("consola.ttf", "CascadiaCode.ttf", "DejaVuSansMono.ttf", "cour.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(rows, out_path: Path) -> Path:
    """Paint the structured dashboard rows (segment lists) to a PNG.

    Each row is a list of ``(text, palette_key)`` segments; segments are drawn
    left-to-right on a fixed-width grid so color never shifts the layout.
    """
    font = _mono_font(22)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    char_w = tmp.textlength("M", font=font)  # monospace: every glyph same width
    ascent, descent = font.getmetrics()
    row_h = ascent + descent + LINE_SPACING

    cols = max(sum(len(t) for t, _ in row) for row in rows)
    width = int(char_w * cols + PAD * 2)
    height = int(row_h * len(rows) + PAD * 2)

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    y = PAD
    for row in rows:
        x = PAD
        for text, key in row:
            draw.text((x, y), text, font=font, fill=c.PALETTE.get(key, c.PALETTE["fg"]))
            x += char_w * len(text)
        y += row_h

    img.save(out_path)
    return out_path


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "continuum-dashboard.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = c._dashboard_rows(c.SibylMemory())
    saved = render(rows, out)
    print(f"Wrote {saved}  ({saved.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
