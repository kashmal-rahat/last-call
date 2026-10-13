"""Tests for image preparation and crop functions (Step 4)."""

import io

import pytest
from PIL import Image

from lastcall_api.inspector.images import crop_group, prepare_image


def _create_test_image(width: int, height: int, color="red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_prepare_image_basic():
    raw = _create_test_image(800, 600)
    prep = prepare_image(raw)
    assert prep.full.size == (800, 600)
    assert prep.width == 800
    assert prep.height == 600
    assert len(prep.sha256) == 64
    assert len(prep.jpeg) > 0


def test_prepare_image_downscales_jpeg_keeps_full():
    # 4000x3000 image: jpeg downscaled to <= 1600 long side, full stays 4000x3000
    raw = _create_test_image(4000, 3000)
    prep = prepare_image(raw)
    assert prep.full.size == (4000, 3000)
    assert max(prep.width, prep.height) == 1600
    assert prep.width == 1600
    assert prep.height == 1200


def test_prepare_image_invalid_bytes_raises_value_error():
    with pytest.raises(ValueError, match="not a readable image"):
        prepare_image(b"not an image at all")

    with pytest.raises(ValueError, match="not a readable image"):
        prepare_image(b"\xff\xd8\xff\xe0" + b"\x00" * 20)  # truncated JPEG header


def test_prepare_image_exif_transposition():
    # Create image with EXIF orientation tag 6 (rotate 90 CW)
    img = Image.new("RGB", (200, 100), color="blue")
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation = 6 (Rotate 270 CW to correct, so 100x200)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    raw = buf.getvalue()

    prep = prepare_image(raw)
    assert prep.full.size == (100, 200)
    assert (prep.width, prep.height) == (100, 200)


def test_prepare_image_removes_exif_gps():
    # Create image with GPS exif in IFD
    img = Image.new("RGB", (100, 100), color="green")
    exif = img.getexif()
    gps_ifd = exif.get_ifd(0x8825)
    gps_ifd[1] = "N"
    gps_ifd[2] = 31.5
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    raw = buf.getvalue()

    prep = prepare_image(raw)
    res_img = Image.open(io.BytesIO(prep.jpeg))
    res_exif = res_img.getexif()
    assert 0x8825 not in res_exif


def test_crop_group_margin_and_clamping():
    full = Image.new("RGB", (1000, 1000), color="yellow")
    # Box at corner: [0, 0, 500, 500] (0-1000 scale)
    # Box in px: ymin=0, xmin=0, ymax=500, xmax=500
    # 10% margin = 50px each side -> ymin=0, xmin=0, ymax=550, xmax=550
    crop_bytes = crop_group(full, [0, 0, 500, 500])
    crop_img = Image.open(io.BytesIO(crop_bytes))
    assert crop_img.size == (550, 550)


def test_crop_group_tiny_box_grows_to_256():
    full = Image.new("RGB", (1000, 1000), color="yellow")
    # Tiny box in center: [490, 490, 510, 510] -> 20x20 px
    crop_bytes = crop_group(full, [490, 490, 510, 510])
    crop_img = Image.open(io.BytesIO(crop_bytes))
    assert crop_img.width >= 256
    assert crop_img.height >= 256
