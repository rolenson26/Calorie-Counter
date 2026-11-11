"""Tests for database/db.py, run against a fresh temporary database each time."""
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from flask import Flask

from database import db
from database.nutrition_data import FOODS

# One chicken biryani plate (250 g), already calculated.
BIRYANI = {"calories": 260.0, "protein": 18.0, "carbs": 34.0, "fat": 6.0, "fiber": 2.8}


@pytest.fixture
def app(tmp_path):
    """A tiny Flask app that uses a brand-new database file for one test."""
    app = Flask(__name__)
    app.config["DATABASE"] = tmp_path / "test.db"
    db.init_app(app)
    with app.app_context():
        yield app


@pytest.fixture
def user_id(app):
    return db.create_user("Asha", "asha@example.com", "not-a-real-hash")


def food_id(name):
    return next(food["id"] for food in db.get_all_foods() if food["name"] == name)


def test_starter_foods_are_loaded_once(app):
    assert len(db.get_all_foods()) == len(FOODS)
    # Running the setup again must not add the foods a second time.
    assert db.init_db(db.get_db()) == 0
    assert len(db.get_all_foods()) == len(FOODS)


def test_new_starter_foods_reach_an_existing_database(app):
    """A database made before a food was added to nutrition_data.py gets it on the next start,
    and foods already there (including a user's edits) are not touched."""
    conn = db.get_db()
    conn.execute("DELETE FROM foods WHERE name IN ('Ooti', 'Eromba', 'Singju')")
    conn.execute("UPDATE foods SET serving_grams = 123 WHERE name = 'Idli'")
    conn.commit()
    assert db.init_db(conn) == 3
    assert len(db.get_all_foods()) == len(FOODS)
    assert {"Ooti", "Eromba", "Singju"} <= {food["name"] for food in db.get_all_foods()}
    assert db.get_food(food_id("Idli"))["serving_grams"] == 123


def test_manipuri_foods_are_recipe_estimates():
    manipuri = {food["name"]: food for food in FOODS if food["category"] == "Manipuri"}
    assert set(manipuri) == {"Ooti", "Eromba", "Singju"}
    for food in manipuri.values():
        assert "recipe estimate" in food["source"]
        assert 40 <= food["calories"] <= 150, food["name"]     # light everyday dishes, not fried


def test_search_ignores_case(app):
    results = db.search_foods("PANEER")
    assert len(results) == 4
    assert all("paneer" in food["name"].lower() for food in results)


def test_duplicate_email_is_rejected_ignoring_case(user_id):
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user("Asha 2", "ASHA@example.com", "x")


def test_duplicate_custom_food_name_is_rejected(user_id):
    food = {"name": "dal", "category": "Dal & Legumes", "serving_unit": "katori",
            "serving_grams": 150, "calories": 100, "protein": 5, "carbs": 12, "fat": 3, "fiber": 2}
    with pytest.raises(sqlite3.IntegrityError):
        db.add_custom_food(food, user_id)


def test_daily_totals_and_meal_types(user_id):
    today = datetime(2026, 10, 2, 13, 0)
    biryani, samosa = food_id("Chicken Biryani"), food_id("Samosa")
    db.add_food_log(user_id, biryani, "lunch", 250, BIRYANI, quantity=1, eaten_at=today)
    snack = {"calories": 310.0, "protein": 5.1, "carbs": 33.2, "fat": 17.5, "fiber": 1.8}
    db.add_food_log(user_id, samosa, "snack", 100, snack, quantity=1, eaten_at=today)
    db.add_food_log(user_id, biryani, "dinner", 250, BIRYANI, eaten_at=today - timedelta(days=1))

    totals = db.get_daily_totals(user_id, date(2026, 10, 2))
    assert totals["meals_count"] == 2
    assert totals["calories"] == pytest.approx(570.0)
    assert totals["protein"] == pytest.approx(23.1)

    by_meal = db.get_calories_by_meal_type(user_id, "2026-10-02")
    assert by_meal == {"breakfast": 0, "lunch": 260.0, "dinner": 0, "snack": 310.0}


def test_last_seven_days_include_empty_days(user_id):
    db.add_food_log(user_id, food_id("Idli"), "breakfast", 80, BIRYANI,
                    eaten_at=datetime(2026, 9, 30, 8, 0))
    days = db.get_daily_calories(user_id, date(2026, 10, 2))
    assert [d["date"] for d in days] == [f"2026-09-{n}" for n in range(26, 31)] + ["2026-10-01", "2026-10-02"]
    assert [d["calories"] for d in days] == [0, 0, 0, 0, 260.0, 0, 0]


def test_several_foods_are_saved_together(user_id):
    eaten = datetime(2026, 10, 2, 20, 0)
    entries = [
        {"food_id": food_id("Chicken Biryani"), "grams": 250, "quantity": 1, "nutrients": BIRYANI, "was_corrected": False},
        {"food_id": food_id("Dal"), "grams": 150, "quantity": None, "nutrients": BIRYANI, "was_corrected": True},
    ]
    ids = db.add_food_logs(user_id, "dinner", entries, eaten_at=eaten)
    logs = db.get_logs(user_id, "2026-10-02", "2026-10-02")
    assert sorted(log["id"] for log in logs) == sorted(ids)
    assert {log["logged_at"] for log in logs} == {"2026-10-02 20:00:00"}      # one meal, one time


def test_one_bad_row_saves_none_of_the_foods(user_id):
    good = {"food_id": food_id("Idli"), "grams": 80, "quantity": 2, "nutrients": BIRYANI, "was_corrected": False}
    bad = {**good, "grams": 5000}                                            # breaks the CHECK (grams <= 3000)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_food_logs(user_id, "lunch", [good, bad])
    assert db.get_daily_totals(user_id, date.today())["meals_count"] == 0


def test_user_can_only_delete_own_meal(user_id):
    other = db.create_user("Ravi", "ravi@example.com", "x")
    log_id = db.add_food_log(user_id, food_id("Dal"), "lunch", 150, BIRYANI)
    assert db.delete_food_log(log_id, other) is False
    assert db.delete_food_log(log_id, user_id) is True


def test_prediction_is_private_to_its_user(user_id):
    other = db.create_user("Ravi", "ravi@example.com", "x")
    pid = db.add_prediction(user_id, "uploads/a.jpg", True, food_id("Idli"), 0.81, "high",
                            [{"food_id": 1, "name": "Idli", "confidence": 0.81}])
    assert db.get_prediction(pid, user_id)["confidence_level"] == "high"
    assert db.get_prediction(pid, other) is None


def test_history_shows_ai_guess(user_id):
    idli, dosa = food_id("Idli"), food_id("Plain Dosa")
    pid = db.add_prediction(user_id, "uploads/a.jpg", True, dosa, 0.45, "medium", [])
    db.add_food_log(user_id, idli, "breakfast", 80, BIRYANI, prediction_id=pid,
                    was_corrected=True, eaten_at=datetime(2026, 10, 2, 8, 0))
    [log] = db.get_logs(user_id, "2026-10-01", "2026-10-02")
    assert log["food_name"] == "Idli"
    assert log["ai_guess"] == "Plain Dosa"
    assert log["image_path"] == "uploads/a.jpg"


def test_ai_accuracy_counts_only_photo_meals(user_id):
    idli = food_id("Idli")
    pid = db.add_prediction(user_id, "uploads/a.jpg", True, idli, 0.9, "high", [])
    db.add_food_log(user_id, idli, "breakfast", 80, BIRYANI, prediction_id=pid)
    db.add_food_log(user_id, idli, "breakfast", 80, BIRYANI, prediction_id=pid, was_corrected=True)
    db.add_food_log(user_id, idli, "dinner", 80, BIRYANI)          # manual entry, not counted
    assert db.get_ai_accuracy(user_id) == {"total": 2, "correct": 1, "accuracy": 0.5}


def test_database_refuses_invalid_rows(user_id):
    with pytest.raises(sqlite3.IntegrityError):          # unknown food: foreign key
        db.add_food_log(user_id, 99999, "lunch", 100, BIRYANI)
    with pytest.raises(sqlite3.IntegrityError):          # meal type not allowed: CHECK
        db.add_food_log(user_id, food_id("Dal"), "brunch", 100, BIRYANI)
    with pytest.raises(sqlite3.IntegrityError):          # more than 3000 g: CHECK
        db.add_food_log(user_id, food_id("Dal"), "lunch", 5000, BIRYANI)
