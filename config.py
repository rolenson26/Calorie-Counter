"""
config.py - every setting of the app in one place.

Flask copies these values into app.config when the app starts, and the other
modules read them from there. To change a limit (for example the upload size
or the AI confidence thresholds) you only edit this file.
"""
import os
import secrets
from pathlib import Path

# The folder that contains this file is the project root.
BASE_DIR = Path(__file__).resolve().parent


class Config:
    # ---------------------------------------------------------------- security
    # SECRET_KEY signs the login cookie so users cannot forge it.
    # Set the SECRET_KEY environment variable to keep users logged in across
    # restarts; otherwise a new random key is made each time the app starts.
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SESSION_COOKIE_HTTPONLY = True       # JavaScript cannot read the login cookie
    SESSION_COOKIE_SAMESITE = "Lax"      # cookie is not sent on cross-site form posts (basic CSRF protection)

    # ---------------------------------------------------------------- database
    DATABASE = BASE_DIR / "instance" / "food_calorie.db"

    # ---------------------------------------------------------------- uploads
    # Not inside static/: Flask would serve those files to anyone. Photos are
    # sent only to their owner by the /uploads/<name> route in routes/pages.py.
    UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024      # 8 MB; Flask answers 413 for anything larger
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
    MAX_IMAGE_PIXELS = 40_000_000             # 40 megapixels; stops "decompression bomb" images
    STORED_IMAGE_MAX_SIDE = 1024              # saved photos are shrunk to this many pixels on the longest side
    UNUSED_PHOTO_MAX_AGE_HOURS = 24           # a photo that was never saved to a meal is deleted after this long
    CLEANUP_INTERVAL_SECONDS = 3600           # how often the cleanup may run while the app is running

    # ---------------------------------------------------------------- AI model
    MODEL_NAME = "openai/clip-vit-base-patch32"
    MODEL_CACHE_DIR = BASE_DIR / "models"     # weights are downloaded here once (about 600 MB)
    FOOD_GATE_THRESHOLD = 0.50                # below this, the photo "doesn't look like food"
    HIGH_CONFIDENCE = 0.60                    # top food at or above this is pre-selected
    LOW_CONFIDENCE = 0.30                     # top food below this: ask the user to search
    # Suggestions shown after a scan: always the top 3, plus any other food scoring at least
    # SUGGESTION_MIN_CONFIDENCE, up to MAX_SUGGESTIONS. On a plate with several dishes the
    # scores spread out (e.g. 12 %, 12 %, 7 %, 7 %, 7 %...), so more of the dishes get offered.
    SUGGESTION_MIN_CONFIDENCE = 0.04
    MAX_SUGGESTIONS = 8
    # Few-shot example photos (Manipuri dishes): their CLIP vectors, made with
    #   python -m services.food_classifier --build-references data/reference_photos
    # A photo whose 5 most similar examples of a food average above the threshold gets
    # weight x (similarity - threshold) added to that food's score. Chosen with
    # scripts/calibrate_references.py: held-out Manipuri photos 35 % -> 85 % top-1, while
    # 941 public photos of other Indian foods stayed at 77 % top-1.
    REFERENCE_FILE = BASE_DIR / "data" / "reference_embeddings.pt"
    REFERENCE_TOP_K = 5
    REFERENCE_THRESHOLD = 0.80
    REFERENCE_WEIGHT = 200.0

    # ---------------------------------------------------------------- nutrition
    DEFAULT_CALORIE_GOAL = 2000               # kcal per day; each user can change their own goal
