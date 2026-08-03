"""Render the Tertius T mark to every icon format the launchers need.

Geometry is copied from the <svg class="logo"> in templates/index.html so the
launcher icon and the in-app logo cannot drift apart:

    rect  0, 9  100x9   full
    rect 12,29   76x9   opacity 0.42
    rect 42, 9   16x91  full

Run once with any Python that has Pillow; the outputs are committed, so Pillow
never becomes a Tertius dependency.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

# The copper from the favicon in index.html.
COPPER = (200, 121, 78, 255)
FADED = (200, 121, 78, 107)  # 0.42 alpha, the middle bar

# x, y, w, h, fill - in the SVG's 100x100 viewBox.
RECTS = (
    (0, 9, 100, 9, COPPER),
    (12, 29, 76, 9, FADED),
    (42, 9, 16, 91, COPPER),
)

# The mark is drawn edge to edge in the viewBox; icons want a little breathing
# room. One ratio for every size on purpose - varying it made 32px render
# visibly bolder than 48px, which looks like two different logos in a row.
PADDING_RATIO = 0.06

# Below this the bars are thinner than a pixel and the mark turns into a pale
# smudge, so small sizes drop the faded middle bar and snap to whole pixels.
# Checked by rendering a contact sheet at 16/24/32/48/64/128/256 and looking.
SMALL_SIZE = 24


def render(size: int) -> Image.Image:
    """The mark at `size` px, supersampled 4x so the edges stay clean."""
    small = size <= SMALL_SIZE
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    inset = canvas * PADDING_RATIO
    span = canvas - 2 * inset
    unit = span / 100.0

    for x, y, w, h, fill in RECTS:
        # The faded bar is detail that only muddies the stem junction once it is
        # a pixel tall. The full-strength bars carry the mark on their own.
        if small and fill is FADED:
            continue
        left, top = inset + x * unit, inset + y * unit
        right, bottom = inset + (x + w) * unit, inset + (y + h) * unit
        if small:
            # Snap to the final pixel grid so the downscale lands on hard edges
            # instead of averaging every bar down to half opacity.
            left, top = round(left / scale) * scale, round(top / scale) * scale
            right = max(round(right / scale) * scale, left + scale)
            bottom = max(round(bottom / scale) * scale, top + scale)
        draw.rectangle([left, top, right, bottom], fill=fill)
    return image.resize((size, size), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" \
width="100" height="100" role="img" aria-label="Tertius">
  <rect x="0"  y="9"  width="100" height="9"  fill="#C8794E"/>
  <rect x="12" y="29" width="76"  height="9"  fill="#C8794E" opacity="0.42"/>
  <rect x="42" y="9"  width="16"  height="91" fill="#C8794E"/>
</svg>
"""


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "tertius.svg").write_text(SVG, encoding="utf-8")

    # Linux .desktop wants a PNG; 512 is the largest hicolor size that matters.
    render(512).save(out_dir / "tertius-512.png")
    render(256).save(out_dir / "tertius-256.png")

    # Windows .ico for the shortcut and the folder icon. Pillow generates each
    # size from the source image, but rendering them individually is sharper at
    # 16 and 32 where a downscale would smear the 9px bars.
    icon_sizes = [16, 24, 32, 48, 64, 128, 256]
    render(256).save(
        out_dir / "tertius.ico",
        sizes=[(s, s) for s in icon_sizes],
        append_images=[render(s) for s in icon_sizes],
    )

    # macOS .icns. Pillow writes the container on any platform - verified on
    # Windows - but it has never been looked at on a Mac.
    render(1024).save(out_dir / "tertius.icns")

    for path in sorted(out_dir.iterdir()):
        print(f"  {path.name:22} {path.stat().st_size:>8,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
