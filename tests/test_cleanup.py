"""Tests for services/cleanup.py: unused photos are deleted, photos of saved meals are kept."""
from datetime import date

import pytest

from app import create_app
from database import db
from services import cleanup
from tests.test_api import upload

GUESSES = [("Idli", 0.81), ("Medu Vada", 0.10), ("Upma", 0.05)]


def age_prediction(app, prediction_id, hours):
    """Pretend a prediction was made `hours` ago."""
    with app.app_context():
        conn = db.get_db()
        conn.execute("UPDATE predictions SET created_at = datetime('now', 'localtime', ?) WHERE id = ?",
                     (f"-{hours} hours", prediction_id))
        conn.commit()


def photo_files(app):
    return list(app.config["UPLOAD_FOLDER"].glob("*.jpg"))


@pytest.fixture
def scanned(auth_client, fake_classifier, photo):
    """scanned(n) uploads n photos and returns their prediction ids."""
    fake_classifier.answer(GUESSES)
    return lambda n=1: [upload(auth_client, photo()).get_json()["prediction_id"] for _ in range(n)]


def test_old_unused_photo_is_deleted(app, scanned):
    [prediction_id] = scanned()
    age_prediction(app, prediction_id, 30)
    assert len(photo_files(app)) == 1
    assert cleanup.run(app, force=True) == 1
    assert photo_files(app) == []
    with app.app_context():
        assert db.get_db().execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_recent_unused_photo_is_kept(app, scanned):
    scanned()
    assert cleanup.run(app, force=True) == 0
    assert len(photo_files(app)) == 1


def test_photo_of_a_saved_meal_is_kept_however_old(app, auth_client, scanned, food_id):
    [prediction_id] = scanned()
    auth_client.post("/api/food-log", json={"food_id": food_id("Idli"), "quantity": 2,
                                            "meal_type": "breakfast", "prediction_id": prediction_id})
    age_prediction(app, prediction_id, 500)
    assert cleanup.run(app, force=True) == 0
    assert len(photo_files(app)) == 1


def test_only_the_unused_photo_goes(app, auth_client, scanned, food_id, user_id):
    kept, dropped = scanned(2)
    auth_client.post("/api/food-log", json={"food_id": food_id("Idli"), "quantity": 1,
                                            "meal_type": "lunch", "prediction_id": kept})
    for prediction_id in (kept, dropped):
        age_prediction(app, prediction_id, 48)
    assert cleanup.run(app, force=True) == 1
    assert len(photo_files(app)) == 1
    with app.app_context():
        [log] = db.get_logs(user_id, date.today(), date.today())
        assert log["image_path"]                            # the saved meal still has its photo


def test_cleanup_is_throttled_but_runs_when_a_photo_is_scanned(tmp_path, fake_classifier, photo):
    settings = {"TESTING": True, "DATABASE": tmp_path / "t.db", "UPLOAD_FOLDER": tmp_path / "up"}
    app = create_app(settings, classifier=fake_classifier)
    fake_classifier.app = app
    assert app.extensions["last_cleanup"] is not None       # ran once while building the app
    assert cleanup.run(app) == 0                            # too soon: skipped

    with app.app_context():
        user = db.create_user("A", "a@example.com", "x")
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = user
    fake_classifier.answer(GUESSES)
    old = upload(client, photo()).get_json()["prediction_id"]
    age_prediction(app, old, 30)

    app.extensions["last_cleanup"] = None                   # pretend the last run was long ago
    upload(client, photo())                                 # scanning a new photo triggers the cleanup
    assert len(list((tmp_path / "up").glob("*.jpg"))) == 1  # the old one is gone, the new one stays


def test_a_bad_database_row_cannot_delete_outside_the_folder(app, scanned, tmp_path):
    [prediction_id] = scanned()
    outside = tmp_path / "precious.txt"
    outside.write_text("keep me")
    with app.app_context():
        conn = db.get_db()
        conn.execute("UPDATE predictions SET image_path = ? WHERE id = ?", ("../precious.txt", prediction_id))
        conn.commit()
    age_prediction(app, prediction_id, 30)
    cleanup.run(app, force=True)
    assert outside.exists()
