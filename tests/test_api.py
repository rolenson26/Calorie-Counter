"""Tests for every /api endpoint, using the fake classifier from conftest.py."""
import json
from datetime import date, timedelta

import pytest

from app import create_app
from database import db
from database.nutrition_data import FOODS


def upload(client, image, filename="lunch.jpg"):
    return client.post("/api/predict", data={"image": (image, filename)},
                       content_type="multipart/form-data")


# =============================================================== login and status

@pytest.mark.parametrize("method, path", [
    ("get", "/api/dashboard"), ("get", "/api/history"), ("get", "/api/foods"),
    ("post", "/api/predict"), ("post", "/api/calculate"),
    ("post", "/api/food-log"), ("post", "/api/food-log/batch"),
    ("delete", "/api/food-log/1"), ("put", "/api/food-log/1"), ("get", "/api/foods/recent"), ("post", "/api/foods"), ("put", "/api/user/goal"),
])
def test_every_api_needs_login(client, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.get_json() == {"success": False, "error": "Please log in first"}


def test_status_reports_model_ready(client):
    assert client.get("/api/status").get_json()["model_ready"] is True


def test_predict_says_503_while_model_loads(tmp_path, photo):
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "t.db", "LOAD_MODEL": False})
    client = app.test_client()
    with app.app_context():
        user_id = db.create_user("A", "a@example.com", "x")
    with client.session_transaction() as session:
        session["user_id"] = user_id
    assert client.get("/api/status").get_json()["model_ready"] is False
    response = upload(client, photo())
    assert response.status_code == 503
    assert "still loading" in response.get_json()["error"]


# =============================================================== predict

def test_predict_high_confidence(auth_client, fake_classifier, photo, app, user_id):
    fake_classifier.answer([("Idli", 0.81), ("Medu Vada", 0.10), ("Upma", 0.05)])
    response = upload(auth_client, photo())
    data = response.get_json()

    assert response.status_code == 200
    assert data["confidence_level"] == "high"
    assert data["message"] == "Looks like Idli. Check the portion, then calculate."
    assert data["image_url"].startswith("/uploads/")
    assert [p["name"] for p in data["top_predictions"]] == ["Idli", "Medu Vada", "Upma"]
    assert data["top_predictions"][0]["serving_unit"] == "piece"
    assert data["top_predictions"][0]["serving_grams"] == 40

    with app.app_context():
        prediction = db.get_prediction(data["prediction_id"], user_id)
    assert prediction["confidence_level"] == "high"
    assert (app.config["UPLOAD_FOLDER"] / data["image_url"].rsplit("/", 1)[1]).is_file()


def test_predict_offers_more_than_3_foods_for_a_plate(auth_client, fake_classifier, photo, app, user_id):
    guesses = [("Aloo Matar", 0.12), ("Veg Khichdi", 0.12), ("Chana Dal", 0.07),
               ("Baingan Bharta", 0.07), ("Dal", 0.07), ("Uttapam", 0.06)]
    fake_classifier.answer(guesses)
    data = upload(auth_client, photo()).get_json()
    assert [p["name"] for p in data["top_predictions"]] == [name for name, _ in guesses]
    assert data["confidence_level"] == "low"                 # the level still comes from the top food
    with app.app_context():
        stored = json.loads(db.get_prediction(data["prediction_id"], user_id)["top3_json"])
    assert [g["name"] for g in stored] == ["Aloo Matar", "Veg Khichdi", "Chana Dal"]   # the record keeps the top 3


def test_photo_is_shown_only_to_its_owner(auth_client, fake_classifier, photo, app):
    fake_classifier.answer([("Idli", 0.81), ("Medu Vada", 0.10), ("Upma", 0.05)])
    url = upload(auth_client, photo()).get_json()["image_url"]

    owner = auth_client.get(url)
    assert owner.status_code == 200 and owner.mimetype == "image/jpeg"
    owner.close()

    with app.app_context():
        other = db.create_user("Ravi", "ravi@example.com", "x")
    other_client = app.test_client()
    with other_client.session_transaction() as session:
        session["user_id"] = other
    assert other_client.get(url).status_code == 404               # someone else's photo
    assert app.test_client().get(url).status_code == 302          # not logged in -> login page
    assert auth_client.get("/uploads/..%2F..%2Fapp.py").status_code == 404


@pytest.mark.parametrize("guesses, level, phrase", [
    ([("Plain Dosa", 0.45), ("Masala Dosa", 0.40), ("Uttapam", 0.05)], "medium", "pick the right food"),
    ([("Dal", 0.20), ("Sambar", 0.15), ("Rajma", 0.10)], "low", "search for the food"),
])
def test_predict_medium_and_low_ask_the_user(auth_client, fake_classifier, photo, guesses, level, phrase):
    fake_classifier.answer(guesses)
    data = upload(auth_client, photo()).get_json()
    assert data["confidence_level"] == level
    assert phrase in data["message"]


def test_predict_not_food(auth_client, fake_classifier, photo, app, user_id):
    fake_classifier.answer([("Dal", 0.14), ("Curd", 0.14), ("Chole", 0.11)], is_food=False)
    data = upload(auth_client, photo()).get_json()
    assert data["is_food"] is False
    assert data["confidence_level"] == "not_food"
    with app.app_context():
        assert db.get_prediction(data["prediction_id"], user_id)["predicted_food_id"] is None


def test_predict_without_a_file(auth_client):
    response = auth_client.post("/api/predict", data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert "No image" in response.get_json()["error"]


def test_predict_rejects_wrong_type(auth_client, photo):
    response = upload(auth_client, photo(fmt="GIF", mode="P", color=1), "anim.gif")
    assert response.status_code == 415


def test_predict_rejects_a_fake_image(auth_client):
    import io
    response = upload(auth_client, io.BytesIO(b"not really a photo"), "photo.jpg")
    assert response.status_code == 400
    assert response.get_json()["error"] == "The file is not a valid image"


def test_predict_rejects_files_over_the_limit(auth_client, app, photo):
    app.config["MAX_CONTENT_LENGTH"] = 300              # bytes; any real photo is bigger
    response = upload(auth_client, photo(size=(400, 400)), "big.jpg")
    assert response.status_code == 413
    assert response.get_json()["success"] is False


def test_model_crash_gives_a_clean_500(auth_client, fake_classifier, photo):
    fake_classifier.result = None                       # the fake raises RuntimeError
    response = upload(auth_client, photo())
    assert response.status_code == 500
    body = response.get_json()
    assert body == {"success": False, "error": "Something went wrong on the server. Please try again."}


# =============================================================== calculate

def test_calculate_one_plate_of_biryani(auth_client, food_id):
    response = auth_client.post("/api/calculate", json={"food_id": food_id("Chicken Biryani"), "quantity": 1})
    data = response.get_json()
    assert response.status_code == 200
    assert (data["grams"], data["calories"], data["protein"], data["carbs"], data["fat"], data["fiber"]) == \
        (250, 260, 18.0, 34.0, 6.0, 2.8)
    assert data["food"]["name"] == "Chicken Biryani"


def test_calculate_with_grams(auth_client, food_id):
    data = auth_client.post("/api/calculate", json={"food_id": food_id("Idli"), "grams": 100}).get_json()
    assert data["calories"] == 138                      # 137.5 kcal per 100 g


@pytest.mark.parametrize("body, status, phrase", [
    ({"quantity": 1}, 400, "food_id"),
    ({"food_id": 99999, "quantity": 1}, 404, "Food not found"),
    ({"food_id": "abc", "quantity": 1}, 400, "whole number"),
    ({"food_id": 1}, 400, "either quantity"),
    ({"food_id": 1, "quantity": 0}, 400, "between"),
    ({"food_id": 1, "quantity": "two"}, 400, "must be a number"),
])
def test_calculate_errors(auth_client, body, status, phrase):
    response = auth_client.post("/api/calculate", json=body)
    assert response.status_code == status
    assert phrase in response.get_json()["error"]


def test_calculate_needs_json(auth_client):
    response = auth_client.post("/api/calculate", data="food_id=1")
    assert response.status_code == 400
    assert "JSON" in response.get_json()["error"]


# =============================================================== food log

def test_save_meal_from_a_photo(auth_client, fake_classifier, photo, food_id, app, user_id):
    fake_classifier.answer([("Chicken Biryani", 0.92), ("Mutton Biryani", 0.05), ("Veg Pulao", 0.01)])
    prediction_id = upload(auth_client, photo()).get_json()["prediction_id"]

    response = auth_client.post("/api/food-log", json={
        "food_id": food_id("Chicken Biryani"), "quantity": 1, "meal_type": "lunch", "prediction_id": prediction_id,
    })
    data = response.get_json()
    assert response.status_code == 201
    assert data["today"] == {"consumed": 260, "goal": 2000, "remaining": 1740}

    with app.app_context():
        [log] = db.get_logs(user_id, date.today(), date.today())
    assert log["was_corrected"] == 0
    assert log["calories"] == 260


def test_correcting_the_ai_is_recorded(auth_client, fake_classifier, photo, food_id, app, user_id):
    fake_classifier.answer([("Plain Dosa", 0.45), ("Masala Dosa", 0.40), ("Uttapam", 0.05)])
    prediction_id = upload(auth_client, photo()).get_json()["prediction_id"]
    auth_client.post("/api/food-log", json={
        "food_id": food_id("Masala Dosa"), "quantity": 1, "meal_type": "breakfast", "prediction_id": prediction_id,
    })
    with app.app_context():
        [log] = db.get_logs(user_id, date.today(), date.today())
        assert log["was_corrected"] == 1
        assert log["ai_guess"] == "Plain Dosa"
        assert db.get_ai_accuracy(user_id)["accuracy"] == 0.0


def test_thali_one_photo_many_items(auth_client, fake_classifier, photo, food_id):
    fake_classifier.answer([("Steamed Rice", 0.7), ("Dal", 0.2), ("Roti / Chapati", 0.05)])
    prediction_id = upload(auth_client, photo()).get_json()["prediction_id"]
    for name, quantity in (("Steamed Rice", 1), ("Dal", 1), ("Roti / Chapati", 2)):
        response = auth_client.post("/api/food-log", json={
            "food_id": food_id(name), "quantity": quantity, "meal_type": "dinner", "prediction_id": prediction_id,
        })
        assert response.status_code == 201
    dashboard = auth_client.get("/api/dashboard").get_json()
    assert dashboard["meals_count"] == 3
    assert dashboard["consumed"] == 176 + 93 + 162          # rice 175.8, dal 92.9, 2 rotis 161.8


def test_save_a_whole_plate_in_one_step(auth_client, fake_classifier, photo, food_id, app, user_id):
    fake_classifier.answer([("Steamed Rice", 0.4), ("Dal", 0.3), ("Roti / Chapati", 0.2)])
    prediction_id = upload(auth_client, photo()).get_json()["prediction_id"]
    response = auth_client.post("/api/food-log/batch", json={
        "meal_type": "dinner", "prediction_id": prediction_id,
        "items": [{"food_id": food_id("Steamed Rice"), "quantity": 1},
                  {"food_id": food_id("Dal"), "quantity": 1},
                  {"food_id": food_id("Roti / Chapati"), "quantity": 2}],
    })
    data = response.get_json()
    assert response.status_code == 201
    assert len(data["log_ids"]) == 3
    assert [item["food"]["name"] for item in data["items"]] == ["Steamed Rice", "Dal", "Roti / Chapati"]
    assert [item["calories"] for item in data["items"]] == [176, 93, 162]
    assert data["totals"]["calories"] == 431
    assert data["today"] == {"consumed": 431, "goal": 2000, "remaining": 1569}

    with app.app_context():
        logs = db.get_logs(user_id, date.today(), date.today())
    assert {log["meal_type"] for log in logs} == {"dinner"}
    assert {log["prediction_id"] for log in logs} == {prediction_id}
    # was_corrected keeps its meaning: "not the AI's top guess" (the AI's top guess was rice).
    assert {log["food_name"]: log["was_corrected"] for log in logs} == \
        {"Steamed Rice": 0, "Dal": 1, "Roti / Chapati": 1}
    # ... but all three were in the AI's top 3, so History does not call them "corrected".
    assert {log["food_name"]: log["in_ai_top3"] for log in logs} == \
        {"Steamed Rice": 1, "Dal": 1, "Roti / Chapati": 1}
    history = auth_client.get("/api/history").get_json()["logs"]
    assert all(log["in_ai_top3"] for log in history)


def test_a_food_outside_the_top_3_is_not_counted_as_suggested(auth_client, fake_classifier, photo, food_id, app,
                                                              user_id):
    fake_classifier.answer([("Steamed Rice", 0.4), ("Dal", 0.3), ("Roti / Chapati", 0.2)])
    prediction_id = upload(auth_client, photo()).get_json()["prediction_id"]
    auth_client.post("/api/food-log/batch", json={"meal_type": "lunch", "prediction_id": prediction_id,
                                                  "items": [{"food_id": food_id("Curd"), "quantity": 1}]})
    [log] = auth_client.get("/api/history").get_json()["logs"]
    assert log["was_corrected"] and not log["in_ai_top3"]


def test_plate_without_photo_mixes_grams_and_servings(auth_client, food_id):
    response = auth_client.post("/api/food-log/batch", json={"meal_type": "snack", "items": [
        {"food_id": food_id("Idli"), "grams": 100}, {"food_id": food_id("Banana"), "quantity": 1}]})
    data = response.get_json()
    assert response.status_code == 201
    assert [item["calories"] for item in data["items"]] == [138, 105]
    assert data["items"][0]["quantity"] is None


def test_one_bad_food_on_the_plate_saves_nothing(auth_client, food_id, app, user_id):
    response = auth_client.post("/api/food-log/batch", json={"meal_type": "lunch", "items": [
        {"food_id": food_id("Steamed Rice"), "quantity": 1}, {"food_id": food_id("Dal"), "quantity": 0}]})
    assert response.status_code == 400
    assert response.get_json()["error"].startswith("Dal: quantity must be between")
    with app.app_context():
        assert db.get_logs(user_id, date.today(), date.today()) == []


@pytest.mark.parametrize("change, status, phrase", [
    ({"items": None}, 400, "at least one food"),
    ({"items": []}, 400, "at least one food"),
    ({"items": "rice"}, 400, "at least one food"),
    ({"items": [1]}, 400, "Item 1 must be an object"),
    ({"items": [{"food_id": 1, "quantity": 1}] * 11}, 400, "at most 10"),
    ({"items": [{"food_id": 99999, "quantity": 1}]}, 404, "Food not found"),
    ({"items": [{"food_id": 1}]}, 400, "either quantity"),
    ({"meal_type": "brunch"}, 400, "meal_type"),
    ({"prediction_id": 99999}, 404, "Prediction not found"),
])
def test_plate_errors(auth_client, change, status, phrase):
    body = {"meal_type": "lunch", "items": [{"food_id": 1, "quantity": 1}], **change}
    response = auth_client.post("/api/food-log/batch", json=body)
    assert response.status_code == status
    assert phrase in response.get_json()["error"]


def test_manual_meal_without_photo(auth_client, food_id):
    response = auth_client.post("/api/food-log", json={"food_id": food_id("Banana"), "quantity": 1,
                                                       "meal_type": "snack"})
    assert response.status_code == 201
    assert response.get_json()["nutrition"]["calories"] == 105      # 89 kcal x 118 g / 100


def test_someone_elses_prediction_is_refused(auth_client, app, food_id):
    with app.app_context():
        other = db.create_user("Ravi", "ravi@example.com", "x")
        foreign = db.add_prediction(other, "uploads/x.jpg", True, food_id("Idli"), 0.9, "high", [])
    response = auth_client.post("/api/food-log", json={
        "food_id": food_id("Idli"), "quantity": 1, "meal_type": "lunch", "prediction_id": foreign,
    })
    assert response.status_code == 404


@pytest.mark.parametrize("change, phrase", [
    ({"meal_type": "brunch"}, "meal_type"),
    ({"quantity": 20}, "3000"),                         # 20 plates x 250 g
    ({"quantity": None, "grams": 5000}, "between"),
])
def test_food_log_errors(auth_client, food_id, change, phrase):
    body = {"food_id": food_id("Chicken Biryani"), "quantity": 1, "meal_type": "lunch", **change}
    response = auth_client.post("/api/food-log", json=body)
    assert response.status_code == 400
    assert phrase in response.get_json()["error"]


def test_delete_only_your_own_meal(auth_client, client, app, food_id):
    log_id = auth_client.post("/api/food-log", json={"food_id": food_id("Idli"), "quantity": 2,
                                                     "meal_type": "breakfast"}).get_json()["log_id"]
    with app.app_context():
        other = db.create_user("Ravi", "ravi@example.com", "x")
    other_client = app.test_client()
    with other_client.session_transaction() as session:
        session["user_id"] = other
    assert other_client.delete(f"/api/food-log/{log_id}").status_code == 404
    assert auth_client.delete(f"/api/food-log/{log_id}").status_code == 200
    assert auth_client.delete(f"/api/food-log/{log_id}").status_code == 404


# =============================================================== history and dashboard

def test_history_defaults_to_last_7_days(auth_client, food_id):
    auth_client.post("/api/food-log", json={"food_id": food_id("Poha"), "quantity": 1, "meal_type": "breakfast"})
    data = auth_client.get("/api/history").get_json()
    assert data["to"] == date.today().isoformat()
    assert data["from"] == (date.today() - timedelta(days=6)).isoformat()
    assert [log["food"] for log in data["logs"]] == ["Poha"]
    assert data["logs"][0]["image_url"] is None                      # typed in, no photo


@pytest.mark.parametrize("query, phrase", [
    ("?from=yesterday", "must be a date"),
    ("?from=2026-10-05&to=2026-10-01", "on or before"),
    ("?from=2026-01-01&to=2026-03-01", "at most 31 days"),
])
def test_history_errors(auth_client, query, phrase):
    response = auth_client.get("/api/history" + query)
    assert response.status_code == 400
    assert phrase in response.get_json()["error"]


def test_dashboard_numbers(auth_client, food_id):
    auth_client.post("/api/food-log", json={"food_id": food_id("Idli"), "quantity": 2, "meal_type": "breakfast"})
    auth_client.post("/api/food-log", json={"food_id": food_id("Samosa"), "quantity": 1, "meal_type": "snack"})
    data = auth_client.get("/api/dashboard").get_json()

    assert data["consumed"] == 110 + 310
    assert data["remaining"] == 2000 - 420
    assert data["meals_count"] == 2
    assert data["by_meal_type"] == {"breakfast": 110, "lunch": 0, "dinner": 0, "snack": 310}
    assert len(data["last_7_days"]) == 7 and data["last_7_days"][-1]["calories"] == 420
    assert sum(data["energy_split_percent"].values()) in (99, 100, 101)
    assert {meal["food"] for meal in data["meals"]} == {"Idli", "Samosa"}


def test_dashboard_bad_date(auth_client):
    assert auth_client.get("/api/dashboard?date=02-10-2026").status_code == 400


# =============================================================== foods and goal

def test_list_and_search_foods(auth_client):
    assert len(auth_client.get("/api/foods").get_json()["foods"]) == len(FOODS)
    names = [f["name"] for f in auth_client.get("/api/foods?q=PANEER").get_json()["foods"]]
    assert names == ["Kadai Paneer", "Matar Paneer", "Palak Paneer", "Paneer Butter Masala"]
    assert "ai_prompt" not in auth_client.get("/api/foods?q=idli").get_json()["foods"][0]


NEW_FOOD = {"name": "Pav Bhaji", "category": "Snack", "serving_unit": "plate", "serving_grams": 250,
            "calories": 150, "protein": 4, "carbs": 20, "fat": 6, "fiber": 3}


def test_add_custom_food_becomes_an_ai_label(auth_client, fake_classifier):
    response = auth_client.post("/api/foods", json=NEW_FOOD)
    assert response.status_code == 201
    assert response.get_json()["food"]["is_custom"] == 1
    assert fake_classifier.added == ["Pav Bhaji"]
    assert auth_client.get("/api/foods?q=pav").get_json()["foods"][0]["name"] == "Pav Bhaji"


def test_custom_food_errors(auth_client):
    assert auth_client.post("/api/foods", json={**NEW_FOOD, "name": "IDLI"}).status_code == 409
    response = auth_client.post("/api/foods", json={**NEW_FOOD, "calories": 2000, "serving_unit": "bucket"})
    assert response.status_code == 400
    assert len(response.get_json()["errors"]) == 2


def test_change_daily_goal(auth_client):
    assert auth_client.put("/api/user/goal", json={"daily_calorie_goal": 1800}).status_code == 200
    assert auth_client.get("/api/dashboard").get_json()["goal"] == 1800
    assert auth_client.put("/api/user/goal", json={"daily_calorie_goal": 500}).status_code == 400


# =============================================================== errors

def test_unknown_api_path_and_wrong_method_answer_json(auth_client):
    missing = auth_client.get("/api/nothing-here")
    assert missing.status_code == 404 and missing.get_json()["success"] is False
    wrong = auth_client.get("/api/predict")
    assert wrong.status_code == 405 and wrong.get_json()["success"] is False


# =============================================================== edit a saved meal

def save_meal(auth_client, food_id, name="Chicken Biryani", quantity=1, meal_type="lunch"):
    response = auth_client.post("/api/food-log", json={
        "food_id": food_id(name), "quantity": quantity, "meal_type": meal_type})
    return response.get_json()["log_id"]


def test_edit_meal_portion_and_type(auth_client, food_id, app, user_id):
    log_id = save_meal(auth_client, food_id)              # 1 plate = 250 g = 260 kcal
    response = auth_client.put(f"/api/food-log/{log_id}", json={"meal_type": "dinner", "quantity": 2})
    data = response.get_json()
    assert response.status_code == 200
    assert data["nutrition"]["calories"] == 520            # recalculated on the server
    assert data["day"] == {"consumed": 520, "goal": 2000, "remaining": 1480}

    with app.app_context():
        [log] = db.get_logs(user_id, date.today(), date.today())
    assert (log["meal_type"], log["quantity"], log["grams"], log["calories"]) == ("dinner", 2, 500, 520)


def test_edit_meal_with_grams_clears_quantity(auth_client, food_id, app, user_id):
    log_id = save_meal(auth_client, food_id)
    assert auth_client.put(f"/api/food-log/{log_id}", json={"grams": 100}).status_code == 200
    with app.app_context():
        [log] = db.get_logs(user_id, date.today(), date.today())
    assert (log["quantity"], log["grams"], log["calories"]) == (None, 100, 104)
    assert log["meal_type"] == "lunch"                      # meal_type was left out, so it is kept


@pytest.mark.parametrize("body, text", [
    ({}, "quantity"),
    ({"quantity": 0}, "quantity must be between"),
    ({"quantity": 1, "grams": 100}, "not both"),
    ({"quantity": 1, "meal_type": "brunch"}, "meal_type"),
])
def test_edit_meal_errors(auth_client, food_id, body, text):
    log_id = save_meal(auth_client, food_id)
    response = auth_client.put(f"/api/food-log/{log_id}", json=body)
    assert response.status_code == 400
    assert text in response.get_json()["error"]


def test_edit_meal_not_found_or_not_yours(auth_client, client, app, food_id):
    assert auth_client.put("/api/food-log/999", json={"quantity": 1}).status_code == 404
    log_id = save_meal(auth_client, food_id)
    with app.app_context():
        other = db.create_user("Ravi", "ravi@example.com", "x")
    with client.session_transaction() as session:
        session["user_id"] = other
    assert client.put(f"/api/food-log/{log_id}", json={"quantity": 3}).status_code == 404


def test_history_rows_carry_the_serving_size(auth_client, food_id):
    save_meal(auth_client, food_id)
    [log] = auth_client.get("/api/history").get_json()["logs"]
    assert log["serving_grams"] == 250


# =============================================================== recent foods (quick add)

def test_recent_foods_newest_first_each_once(auth_client, food_id):
    assert auth_client.get("/api/foods/recent").get_json()["foods"] == []
    save_meal(auth_client, food_id, "Idli")
    save_meal(auth_client, food_id, "Banana", meal_type="snack")
    save_meal(auth_client, food_id, "Idli", meal_type="dinner")
    foods = auth_client.get("/api/foods/recent").get_json()["foods"]
    assert [f["name"] for f in foods] == ["Idli", "Banana"]
    assert "ai_prompt" not in foods[0]                      # same safe fields as /api/foods


def test_recent_foods_are_private(auth_client, client, app, food_id):
    save_meal(auth_client, food_id, "Idli")
    with app.app_context():
        other = db.create_user("Ravi", "ravi@example.com", "x")
    with client.session_transaction() as session:
        session["user_id"] = other
    assert client.get("/api/foods/recent").get_json()["foods"] == []
