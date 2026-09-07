#!/usr/bin/env python3
"""Generate the Tauri desktop icon set for hesabdari_balkh.

Creates the standard Tauri v2 desktop icon files under icons/ from a
1024x1024 source image drawn programmatically (no external artwork):

  icons/icon.png  icons/32x32.png  icons/128x128.png
  icons/128x128@2x.png  icons/icon.ico

Design: dark navy rounded square with a golden double-entry balance mark
(two columns on a baseline) that keeps its shape at 32px.

Requires: Pillow (pip install pillow). Re-run to regenerate:
    python3 frontend/src-tauri/icons/generate_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
SIZE = 1024
NAVY = (15, 52, 88, 255)          # #0F3458
NAVY_DARK = (10, 38, 66, 255)     # gradient bottom
GOLD = (232, 179, 59, 255)        # #E8B33B
WHITE = (245, 247, 250, 255)


def make_background(size: int, radius: int) -> Image.Image:
    """Navy vertical gradient clipped to a rounded rectangle."""
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = base.load()
    for y in range(size):
        t = y / size
        color = (
            int(NAVY[0] + (NAVY_DARK[0] - NAVY[0]) * t),
            int(NAVY[1] + (NAVY_DARK[1] - NAVY[1]) * t),
            int(NAVY[2] + (NAVY_DARK[2] - NAVY[2]) * t),
            255,
        )
        for x in range(size):
            px[x, y] = color
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    background = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    background.paste(base, (0, 0), mask)
    return background


def draw_icon() -> Image.Image:
    img = make_background(SIZE, radius=int(SIZE * 0.22))
    d = ImageDraw.Draw(img)

    cx = SIZE // 2
    # --- double-entry balance mark ---
    # horizontal beam
    beam_y = int(SIZE * 0.44)
    beam_w = int(SIZE * 0.045)
    d.line((int(SIZE * 0.28), beam_y, int(SIZE * 0.72), beam_y), fill=GOLD, width=beam_w)
    # central post below the beam
    post_top = beam_y + beam_w
    d.line((cx, post_top, cx, int(SIZE * 0.62)), fill=GOLD, width=beam_w)
    # pivot finial above the beam
    fin = int(SIZE * 0.08)
    d.polygon(
        [(cx - fin, post_top - beam_w // 2 - 2), (cx + fin, post_top - beam_w // 2 - 2), (cx, int(SIZE * 0.30))],
        fill=GOLD,
    )
    # pan strings
    d.line((int(SIZE * 0.28), beam_y, int(SIZE * 0.28), int(SIZE * 0.50)), fill=GOLD, width=max(6, beam_w // 4))
    d.line((int(SIZE * 0.72), beam_y, int(SIZE * 0.72), int(SIZE * 0.50)), fill=GOLD, width=max(6, beam_w // 4))
    # pans (debit lower-left, credit upper-right => two equal cups at rest)
    pan_r = int(SIZE * 0.085)
    d.ellipse(
        (int(SIZE * 0.28) - pan_r, int(SIZE * 0.50), int(SIZE * 0.28) + pan_r, int(SIZE * 0.50) + 2 * pan_r),
        outline=GOLD, width=int(SIZE * 0.028),
    )
    d.ellipse(
        (int(SIZE * 0.72) - pan_r, int(SIZE * 0.50), int(SIZE * 0.72) + pan_r, int(SIZE * 0.50) + 2 * pan_r),
        outline=WHITE, width=int(SIZE * 0.028),
    )
    # baseline (the ledger line both columns rest on)
    d.line((int(SIZE * 0.22), int(SIZE * 0.72), int(SIZE * 0.78), int(SIZE * 0.72)), fill=WHITE, width=max(8, beam_w // 3))
    return img


def main() -> None:
    source = draw_icon()
    source.save(OUT / "icon.png", format="PNG")
    sizes = {"32x32.png": 32, "128x128.png": 128, "128x128@2x.png": 256}
    for name, size in sizes.items():
        source.resize((size, size), Image.LANCZOS).save(OUT / name, format="PNG")
    source.resize((256, 256), Image.LANCZOS).save(
        OUT / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    for name in ("icon.png", "32x32.png", "128x128.png", "128x128@2x.png", "icon.ico"):
        print(f"generated {OUT / name} ({ (OUT / name).stat().st_size } bytes)")


if __name__ == "__main__":
    main()
