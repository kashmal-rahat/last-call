"""Image processing and preparation for Freshness Inspector."""

import hashlib
import io
from typing import NamedTuple

from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 40_000_000


class ImageError(ValueError):
    """Raised when an image cannot be opened, decoded, or read."""
    pass


class PreparedImage(NamedTuple):
    full: Image.Image
    jpeg: bytes
    width: int
    height: int
    sha256: str


def prepare_image(raw: bytes) -> PreparedImage:
    """Decodes, validates, normalizes, and prepares shelf photo for inspection.

    1. Decompression bomb guard: Image.MAX_IMAGE_PIXELS = 40M.
    2. Any open or decode failure raises ImageError('not a readable image').
    3. Handles EXIF orientation via ImageOps.exif_transpose and converts to RGB.
    4. full: kept in memory, downscaled only if long side > 4096 px.
    5. jpeg: downscaled so long side <= 1600 px (LANCZOS; never upscaled), quality 85, no EXIF.
    """
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise ImageError("not a readable image") from exc

    # Handle EXIF orientation
    transposed = ImageOps.exif_transpose(img)
    if transposed is not None:
        img = transposed

    img = img.convert("RGB")

    # full: downscale only if long side > 4096 px
    max_dim = max(img.width, img.height)
    if max_dim > 4096:
        scale = 4096.0 / max_dim
        full_w = int(round(img.width * scale))
        full_h = int(round(img.height * scale))
        full = img.resize((full_w, full_h), Image.Resampling.LANCZOS)
    else:
        full = img

    # jpeg: downscaled so long side <= 1600 px (never upscale)
    full_max = max(full.width, full.height)
    if full_max > 1600:
        scale_preview = 1600.0 / full_max
        preview_w = int(round(full.width * scale_preview))
        preview_h = int(round(full.height * scale_preview))
        preview = full.resize((preview_w, preview_h), Image.Resampling.LANCZOS)
    else:
        preview = full

    width, height = preview.width, preview.height
    buf = io.BytesIO()
    preview.save(buf, format="JPEG", quality=85)
    jpeg_bytes = buf.getvalue()
    sha256_hex = hashlib.sha256(jpeg_bytes).hexdigest()

    return PreparedImage(
        full=full,
        jpeg=jpeg_bytes,
        width=width,
        height=height,
        sha256=sha256_hex,
    )


def crop_group(full: Image.Image, box_2d: list[int]) -> bytes:
    """Crops a detected group with margins for pass-2 zoom inspection.

    1. Converts 0–1000 scale box to pixels of full image and adds 10% margin.
    2. Grows crop to 256 px around center if short side < 256 px (clamped).
    3. Downscales long side to <= 1600 px if needed, saves as JPEG quality 90 (no EXIF).
    """
    ymin_norm, xmin_norm, ymax_norm, xmax_norm = box_2d
    img_w, img_h = full.width, full.height

    ymin_px = (ymin_norm / 1000.0) * img_h
    xmin_px = (xmin_norm / 1000.0) * img_w
    ymax_px = (ymax_norm / 1000.0) * img_h
    xmax_px = (xmax_norm / 1000.0) * img_w

    box_h = ymax_px - ymin_px
    box_w = xmax_px - xmin_px

    margin_y = 0.10 * box_h
    margin_x = 0.10 * box_w

    c_ymin = max(0.0, ymin_px - margin_y)
    c_xmin = max(0.0, xmin_px - margin_x)
    c_ymax = min(float(img_h), ymax_px + margin_y)
    c_xmax = min(float(img_w), xmax_px + margin_x)

    crop_w = c_xmax - c_xmin
    crop_h = c_ymax - c_ymin

    # Grow short side to 256 px around center if needed
    if crop_w < 256 and img_w >= 256:
        center_x = (c_xmin + c_xmax) / 2.0
        c_xmin = center_x - 128.0
        c_xmax = center_x + 128.0
        if c_xmin < 0.0:
            c_xmax = min(float(img_w), c_xmax - c_xmin)
            c_xmin = 0.0
        elif c_xmax > float(img_w):
            c_xmin = max(0.0, c_xmin - (c_xmax - float(img_w)))
            c_xmax = float(img_w)
    elif crop_w < 256:
        c_xmin = 0.0
        c_xmax = float(img_w)

    if crop_h < 256 and img_h >= 256:
        center_y = (c_ymin + c_ymax) / 2.0
        c_ymin = center_y - 128.0
        c_ymax = center_y + 128.0
        if c_ymin < 0.0:
            c_ymax = min(float(img_h), c_ymax - c_ymin)
            c_ymin = 0.0
        elif c_ymax > float(img_h):
            c_ymin = max(0.0, c_ymin - (c_ymax - float(img_h)))
            c_ymax = float(img_h)
    elif crop_h < 256:
        c_ymin = 0.0
        c_ymax = float(img_h)

    # Convert to integer pixel coordinates clamped to image dimensions
    i_ymin = max(0, min(img_h - 1, int(round(c_ymin))))
    i_xmin = max(0, min(img_w - 1, int(round(c_xmin))))
    i_ymax = max(i_ymin + 1, min(img_h, int(round(c_ymax))))
    i_xmax = max(i_xmin + 1, min(img_w, int(round(c_xmax))))

    cropped = full.crop((i_xmin, i_ymin, i_xmax, i_ymax))

    # Downscale long side if > 1600 px
    crop_max = max(cropped.width, cropped.height)
    if crop_max > 1600:
        scale = 1600.0 / crop_max
        new_w = int(round(cropped.width * scale))
        new_h = int(round(cropped.height * scale))
        cropped = cropped.resize((new_w, new_h), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
