"""
Turns the Picsart-generated source artwork into the exact PWA icon sizes
(manifest icons, apple-touch-icon, favicon). Crops in from the edges first
to discard any rounded-corner/halo artifact baked into the source image,
then resizes to each required size.

    python scripts/make_icons.py
"""

import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(os.path.dirname(HERE), "static", "icons")
SRC = os.path.join(ICONS_DIR, "source2.png")

SIZES = {
    "icon-192.png": 192,
    "icon-512.png": 512,
    "apple-touch-icon.png": 180,
    "favicon-32.png": 32,
}

CROP_FRACTION = 0.88  # keep the center 88% to cut off any corner artifact


def main():
    img = Image.open(SRC).convert("RGB")
    w, h = img.size
    side = min(w, h)
    crop_side = int(side * CROP_FRACTION)
    left = (w - crop_side) // 2
    top = (h - crop_side) // 2
    img = img.crop((left, top, left + crop_side, top + crop_side))

    for name, size in SIZES.items():
        out = img.resize((size, size), Image.LANCZOS)
        out.save(os.path.join(ICONS_DIR, name))
        print(f"wrote {name} ({size}x{size})")


if __name__ == "__main__":
    main()
