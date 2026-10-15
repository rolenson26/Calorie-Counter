"""
services/image_processor.py - checks an uploaded photo and saves a clean copy.

Steps (Module 2 of the HLD)
    1. The extension must be jpg, jpeg, png or webp.
    2. The size limit (8 MB) is enforced earlier by Flask's MAX_CONTENT_LENGTH.
    3. Pillow must really open it as JPEG, PNG or WEBP, with at most 40 megapixels.
       A renamed .exe or a corrupt file fails here.
    4. Fix the rotation that phones store in the EXIF "Orientation" tag.
    5. Convert to RGB, the 3 colour channels the AI model expects.
    6. Shrink so the longest side is at most 1024 px.
    7. Save as a NEW JPEG with a random name. Re-encoding drops all EXIF
       metadata, including GPS location.

Input : the uploaded file (or a path), its original filename and app.config
Output: (RGB image for the AI, a path such as "uploads/3f9c...jpg" that is stored
         in the database and served to its owner by the /uploads/<name> route)

The user's own filename is never used to save the file, so names like
"../../app.py" cannot overwrite anything.
"""
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# What Pillow says the file really is. MPO is a JPEG variant that some phone
# cameras save with a normal .jpg name; only its first picture is used.
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}


class ImageValidationError(ValueError):
    """The upload is not an acceptable image. `status` is the HTTP code for the API."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def has_allowed_extension(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


def to_rgb(image):
    """Convert any image mode to RGB. Transparent areas become white, not black."""
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")


def load_image(file, filename, allowed_extensions, max_pixels):
    """Steps 1 and 3-5: check the upload and return a correctly rotated RGB image."""
    if not filename:
        raise ImageValidationError("No file was selected")
    if not has_allowed_extension(filename, allowed_extensions):
        raise ImageValidationError("Only JPG, PNG and WEBP images are allowed", status=415)

    try:
        image = Image.open(file)               # reads only the header so far
        if image.format not in ALLOWED_FORMATS:
            raise ImageValidationError("The file is not a JPG, PNG or WEBP image", status=415)
        if image.width * image.height > max_pixels:
            raise ImageValidationError("The image has too many pixels")
        image.load()                           # decode all pixels; a corrupt file fails here
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ImageValidationError("The file is not a valid image") from exc

    image = ImageOps.exif_transpose(image)     # stand the photo upright
    return to_rgb(image)


def save_image(image, upload_folder):
    """Step 7: save a new JPEG with a random name and return that name."""
    image.info.clear()                         # make sure no metadata is carried over
    filename = f"{uuid.uuid4().hex}.jpg"
    folder = Path(upload_folder)
    folder.mkdir(parents=True, exist_ok=True)
    image.save(folder / filename, "JPEG", quality=85)
    return filename


def process_upload(file, filename, settings):
    """Run every step. `settings` is app.config (or any dict with the same keys).

    Returns (rgb_image, relative_path), where relative_path is "uploads/<random name>.jpg".
    """
    image = load_image(
        file, filename, settings["ALLOWED_EXTENSIONS"], settings["MAX_IMAGE_PIXELS"]
    )
    max_side = settings["STORED_IMAGE_MAX_SIDE"]
    image.thumbnail((max_side, max_side))      # step 6: keeps the shape, never enlarges
    saved_name = save_image(image, settings["UPLOAD_FOLDER"])
    return image, f"uploads/{saved_name}"
