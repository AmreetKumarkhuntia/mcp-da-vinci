"""Generate panel/icon.ico — run once; the .ico is committed.

    python.exe scripts/make_icon.py

Drawn rather than shipped as a binary blob so it can be tweaked without a
graphics editor. Kept deliberately bold: it has to read at 16 px in a taskbar.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BG = (27, 27, 27, 255)
TEAL = (78, 201, 176, 255)
MAGENTA = (197, 134, 192, 255)

SIZES = (256, 128, 64, 48, 32, 16)
BASE = 256


def render(size: int) -> Image.Image:
    scale = size / BASE
    image = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle([6, 6, BASE - 6, BASE - 6], radius=48, fill=BG)

    # Waveform bars — the library's signature shape.
    heights = (54, 96, 142, 178, 142, 96, 54)
    bar_w, gap = 20, 10
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (BASE - total) / 2
    middle = BASE / 2 + 6
    for height in heights:
        draw.rounded_rectangle(
            [x, middle - height / 2, x + bar_w, middle + height / 2],
            radius=8,
            fill=TEAL,
        )
        x += bar_w + gap

    # Play triangle, so it reads as "media" and not "audio meter".
    draw.polygon([(104, 34), (104, 86), (152, 60)], fill=MAGENTA)

    return image.resize((size, size), Image.LANCZOS) if scale != 1 else image


def main() -> int:
    target = Path(__file__).resolve().parent.parent / "panel" / "icon.ico"
    frames = [render(size) for size in SIZES]
    frames[0].save(target, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"wrote {target}  ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
