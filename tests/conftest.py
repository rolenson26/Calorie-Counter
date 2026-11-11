"""
Shared test fixtures: a test app with a temporary database and a FAKE AI model.

The fake classifier returns whatever answer a test sets, so the API tests run
in seconds, need no 1.2 GB download, and can check every confidence level.
"""
import io

import pytest
from PIL import Image

from app import create_app
from database import db
from services.auth import register_user
from services.food_classifier import ClassificationResult, Guess, confidence_level


class FakeClassifier:
    """Stands in for CLIP. Call answer() first, then classify() returns that answer."""

    def __init__(self):
        self.app = None
        self.result = None
        self.added = []

    def answer(self, guesses, is_food=True):
        """guesses: [("Idli", 0.81), ("Medu Vada", 0.10), ("Upma", 0.05)]
        The first 3 are the top 3; all of them are the suggestions (give more than 3 for a plate)."""
        with self.app.app_context():
            ids = {food["name"]: food["id"] for food in db.get_all_foods()}
        ranked = [Guess(ids[name], name, confidence) for name, confidence in guesses]
        self.result = ClassificationResult(
            is_food=is_food,
            food_probability=0.97 if is_food else 0.08,
            level=confidence_level(is_food, ranked[0].confidence),
            top3=ranked[:3],
            seconds=0.01,
            suggestions=ranked,
        )

    def classify(self, image):
        if self.result is None:
            raise RuntimeError("the test did not call answer() first")
        return self.result

    def add_food(self, food):
        self.added.append(food["name"])


class FakePortionEstimator:
    """Stands in for CLIPSeg: every food is 'measured' as 2 servings. Remembers what it was asked."""

    def __init__(self):
        self.calls = []

    def estimate(self, image, foods):
        self.calls.append((image.size, [food["name"] for food in foods]))
        return {
            "method": "plate", "message": "Measured against a standard 27 cm plate.",
            "plate_share": 0.5, "bowl_share": 0.05, "food_share_of_plate": 0.4, "overlay": None,
            "items": [{"food_id": food["id"], "name": food["name"], "estimated": True,
                       "grams": 2 * food["serving_grams"], "servings": 2.0, "area_cm2": 100,
                       "colour": "#e6194b", "note": None} for food in foods],
        }


@pytest.fixture
def fake_classifier():
    return FakeClassifier()


@pytest.fixture
def fake_estimator():
    return FakePortionEstimator()


@pytest.fixture
def app(tmp_path, fake_classifier, fake_estimator):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": tmp_path / "test.db",
            "UPLOAD_FOLDER": tmp_path / "uploads",
        },
        classifier=fake_classifier,
        portion_estimator=fake_estimator,
    )
    fake_classifier.app = app
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user_id(app):
    with app.app_context():
        new_id, errors = register_user("Asha", "asha@example.com", "secret-pass")
    assert errors == []
    return new_id


@pytest.fixture
def auth_client(client, user_id):
    """A test client that is already logged in as Asha."""
    with client.session_transaction() as session:
        session["user_id"] = user_id
    return client


@pytest.fixture
def food_id(app):
    """food_id("Idli") -> the id of that food in the test database."""
    def lookup(name):
        with app.app_context():
            return next(food["id"] for food in db.get_all_foods() if food["name"] == name)
    return lookup


@pytest.fixture
def photo():
    """photo() -> an in-memory JPEG, ready to upload."""
    def make(size=(64, 64), fmt="JPEG", mode="RGB", color=(220, 180, 60)):
        buffer = io.BytesIO()
        Image.new(mode, size, color).save(buffer, fmt)
        buffer.seek(0)
        return buffer
    return make
