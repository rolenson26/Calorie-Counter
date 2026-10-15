"""
services/cleanup.py - deletes photos that were scanned but never saved to a meal.

Every /api/predict call saves a photo and a `predictions` row. If the user then
leaves without logging the meal, that photo is useless and (being a private
food photo) should not stay on disk forever. A prediction is "unused" when
    * no saved meal (food_logs row) points to it, and
    * it is older than UNUSED_PHOTO_MAX_AGE_HOURS (so a photo still being
      worked on is never removed).

It runs once when the app starts, and then at most once per
CLEANUP_INTERVAL_SECONDS when a new photo is scanned. A failure here is logged
and never stops the app or the request.
"""
import time
from pathlib import Path

from database import db


def delete_unused_photos(upload_folder, max_age_hours):
    """Delete unused predictions and their photo files. Returns how many were removed.

    Needs an active Flask app context (it uses the request/app database).
    """
    unused = db.get_unused_predictions(max_age_hours)
    if not unused:
        return 0
    for row in unused:
        # Only the file name is used, so a damaged database row can never point outside the folder.
        photo = Path(upload_folder) / Path(row["image_path"]).name
        try:
            photo.unlink(missing_ok=True)
        except OSError:
            pass                                   # locked or already gone: the row is removed anyway
    db.delete_predictions([row["id"] for row in unused])
    return len(unused)


def run(app, force=False):
    """Run the cleanup if it is due (or force=True). Never raises."""
    now = time.monotonic()
    last = app.extensions.get("last_cleanup")
    interval = app.config["CLEANUP_INTERVAL_SECONDS"]
    if not force and last is not None and now - last < interval:
        return 0
    app.extensions["last_cleanup"] = now
    try:
        with app.app_context():
            removed = delete_unused_photos(app.config["UPLOAD_FOLDER"], app.config["UNUSED_PHOTO_MAX_AGE_HOURS"])
        if removed:
            app.logger.info("Removed %d unused photo(s)", removed)
        return removed
    except Exception:
        app.logger.exception("Photo cleanup failed")
        return 0
