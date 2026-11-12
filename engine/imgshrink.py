"""Shrink big photos before they are sent to a browser.

News photos arrive straight from the publisher at whatever size they published
(a 1920x1080 crop is ~300 KB; some are over a megabyte) and are shown in a card
about 400 px wide. `shrink()` re-encodes anything wider than MAX_WIDTH as WebP so
the phone downloads a fraction of the bytes. It is used by the image proxy, which
caches the result on disk, so the work is done once per photo.

It never makes things worse: GIF/SVG/anything it cannot decode, anything already
small, and any result that is not smaller than the original comes back untouched.
"""
import io

MAX_WIDTH = 640
WEBP_QUALITY = 80
# Refuse to decode absurd dimensions (decompression bombs): 40 megapixels is
# far above any real news photo and still safe to hold in memory once.
MAX_PIXELS = 40_000_000
# Only these are re-encoded. Animated GIFs and vector images must stay as they are.
SHRINKABLE = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


def shrink(data: bytes, content_type: str, max_width: int = MAX_WIDTH):
    """Return (bytes, content_type): a smaller WebP when that helps, else the input unchanged."""
    if (content_type or "").lower() not in SHRINKABLE:
        return data, content_type
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            if width * height > MAX_PIXELS:
                return data, content_type
            if getattr(im, "is_animated", False):
                return data, content_type
            if width <= max_width and len(data) < 60_000:
                return data, content_type           # already small enough; do not recompress
            im.load()
            if width > max_width:
                new_h = max(1, round(height * max_width / width))
                im = im.resize((max_width, new_h), Image.LANCZOS)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "PA") else "RGB")
            out = io.BytesIO()
            im.save(out, format="WEBP", quality=WEBP_QUALITY, method=4)
        result = out.getvalue()
        if len(result) >= len(data):
            return data, content_type
        return result, "image/webp"
    except Exception:                               # noqa: BLE001 - any decode/encode problem: serve the original
        return data, content_type
