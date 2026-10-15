"""Tests for services/image_processor.py. Every test image is created in memory."""
import io
import re

import pytest
from PIL import ExifTags, Image

from services.image_processor import ImageValidationError, process_upload


@pytest.fixture
def settings(tmp_path):
    return {
        "ALLOWED_EXTENSIONS": {"jpg", "jpeg", "png", "webp"},
        "MAX_IMAGE_PIXELS": 40_000_000,
        "STORED_IMAGE_MAX_SIDE": 1024,
        "UPLOAD_FOLDER": tmp_path / "uploads",
    }


def image_bytes(size=(200, 100), mode="RGB", color=(200, 120, 40), fmt="JPEG", exif=None):
    buffer = io.BytesIO()
    image = Image.new(mode, size, color)
    if exif is not None:
        image.save(buffer, fmt, exif=exif)
    else:
        image.save(buffer, fmt)
    buffer.seek(0)
    return buffer


def phone_exif():
    """EXIF like a phone writes: 'rotate 90 degrees' plus a GPS position and camera make."""
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6
    exif[ExifTags.Base.Make] = "PhoneMaker"
    exif.get_ifd(ExifTags.IFD.GPSInfo)[ExifTags.GPS.GPSLatitude] = (28.0, 36.0, 50.0)
    return exif


def test_phone_photo_is_rotated_and_metadata_removed(settings):
    upload = image_bytes(size=(200, 100), exif=phone_exif())
    assert Image.open(upload).getexif().get_ifd(ExifTags.IFD.GPSInfo)      # GPS really is there
    upload.seek(0)

    image, path = process_upload(upload, "IMG_2041.JPG", settings)

    assert image.size == (100, 200)                       # stood upright using the EXIF tag
    assert re.fullmatch(r"uploads/[0-9a-f]{32}\.jpg", path)
    saved = Image.open(settings["UPLOAD_FOLDER"] / path.split("/")[1])
    assert saved.format == "JPEG"
    assert len(saved.getexif()) == 0                      # no GPS, no camera make, nothing


def test_large_photo_is_shrunk(settings):
    image, path = process_upload(image_bytes(size=(3000, 2000)), "big.jpg", settings)
    assert image.size == (1024, 683)
    assert Image.open(settings["UPLOAD_FOLDER"] / path.split("/")[1]).size == (1024, 683)


def test_transparent_png_gets_a_white_background(settings):
    image, _ = process_upload(image_bytes(mode="RGBA", color=(0, 0, 0, 0), fmt="PNG"), "a.png", settings)
    assert image.mode == "RGB"
    assert image.getpixel((5, 5)) == (255, 255, 255)


def test_users_filename_is_never_used(settings):
    _, path = process_upload(image_bytes(), "../../app.py.jpg", settings)
    assert ".." not in path and "app" not in path
    assert len(list(settings["UPLOAD_FOLDER"].iterdir())) == 1


def test_renamed_text_file_is_rejected(settings):
    fake = io.BytesIO(b"MZ this is really a program, not a photo")
    with pytest.raises(ImageValidationError, match="not a valid image") as error:
        process_upload(fake, "holiday.jpg", settings)
    assert error.value.status == 400


def test_wrong_extension_is_rejected_with_415(settings):
    with pytest.raises(ImageValidationError) as error:
        process_upload(image_bytes(fmt="GIF", mode="P", color=1), "anim.gif", settings)
    assert error.value.status == 415


def test_gif_renamed_to_png_is_rejected(settings):
    with pytest.raises(ImageValidationError, match="not a JPG, PNG or WEBP"):
        process_upload(image_bytes(fmt="GIF", mode="P", color=1), "anim.png", settings)


def test_corrupt_jpeg_is_rejected(settings):
    data = image_bytes(size=(400, 400)).getvalue()
    with pytest.raises(ImageValidationError, match="not a valid image"):
        process_upload(io.BytesIO(data[: len(data) // 3]), "cut.jpg", settings)


def test_too_many_pixels_is_rejected(settings):
    settings["MAX_IMAGE_PIXELS"] = 10_000
    with pytest.raises(ImageValidationError, match="too many pixels"):
        process_upload(image_bytes(size=(200, 100)), "a.jpg", settings)


def test_missing_filename_is_rejected(settings):
    with pytest.raises(ImageValidationError, match="No file"):
        process_upload(image_bytes(), "", settings)


def test_nothing_is_saved_when_validation_fails(settings):
    with pytest.raises(ImageValidationError):
        process_upload(io.BytesIO(b"not an image"), "x.jpg", settings)
    assert not settings["UPLOAD_FOLDER"].exists()
