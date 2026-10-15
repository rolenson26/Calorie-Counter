"""
routes/api.py - the JSON API used by the JavaScript in the pages (HLD section 9).

Every answer has the same shape, so the JavaScript handles all of them alike:
    success: {"success": true, ...data...}
    failure: {"success": false, "error": "message for the user"}

Endpoints (all need login except /status)
    GET    /api/status              is the AI model ready?
    POST   /api/predict             photo -> top 3 foods
    POST   /api/calculate           food + portion -> nutrition (nothing saved)
    POST   /api/food-log            save a meal
    PUT    /api/food-log/<id>       change the meal type or portion of a saved meal
    DELETE /api/food-log/<id>       delete one of your meals
    GET    /api/history             meals in a date range
    GET    /api/dashboard           totals, charts and today's meals
    GET    /api/foods               list or search foods
    GET    /api/foods/recent        the foods you logged most recently (quick add)
    POST   /api/foods               add a custom food
    PUT    /api/user/goal           change the daily calorie goal

The routes stay short: they check input, call a service or database
function, and turn the result into JSON.
"""
import sqlite3
from dataclasses import asdict
from datetime import date, timedelta

from flask import Blueprint, current_app, jsonify, request, url_for

from database import db
from services import cleanup
from services.auth import current_user, login_required
from services.calorie_calculator import PortionError, calculate, daily_summary, validate_custom_food
from services.image_processor import ImageValidationError, process_upload

api_bp = Blueprint("api", __name__)

MAX_HISTORY_DAYS = 31
LEVEL_MESSAGES = {
    "high": "Looks like {name}. Check the portion, then calculate.",
    "medium": "Not completely sure. Please pick the right food from the suggestions.",
    "low": "Not sure what this is. Please search for the food, or add it if it is missing.",
    "not_food": "This doesn't look like food. Try another photo, or search for the food yourself.",
}


# =============================================================== helpers

class ApiError(Exception):
    """Raise anywhere in a route to answer {"success": false, "error": message}."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


@api_bp.errorhandler(ApiError)
def handle_api_error(error):
    return fail(error.message, error.status)


@api_bp.errorhandler(PortionError)
def handle_portion_error(error):
    return fail(str(error), 400)


@api_bp.errorhandler(ImageValidationError)
def handle_image_error(error):
    return fail(str(error), error.status)


def ok(status=200, **data):
    return jsonify(success=True, **data), status


def fail(message, status=400):
    return jsonify(success=False, error=message), status


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Send the data as a JSON object")
    return data


def to_int(value, field):
    if isinstance(value, bool):
        raise ApiError(f"{field} must be a whole number")
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise ApiError(f"{field} must be a whole number") from None


def to_date(value, field):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError(f"{field} must be a date like 2026-10-02") from None


def get_food_or_404(food_id):
    food = db.get_food(to_int(food_id, "food_id"))
    if food is None:
        raise ApiError("Food not found", 404)
    return food


def food_json(food):
    """The food fields the pages need (no internal columns such as ai_prompt)."""
    keys = ("id", "name", "category", "serving_unit", "serving_grams", "calories_per_100g",
            "protein_per_100g", "carbs_per_100g", "fat_per_100g", "fiber_per_100g", "is_custom", "source")
    return {key: food[key] for key in keys}


def image_url(path):
    """'uploads/3f9c....jpg' -> '/uploads/3f9c....jpg' (served only to the photo's owner)."""
    return url_for("pages.uploaded_photo", name=path.removeprefix("uploads/")) if path else None


def log_json(log):
    """One meal for the history and dashboard tables."""
    return {
        "id": log["id"],
        "food_id": log["food_id"],
        "food": log["food_name"],
        "meal_type": log["meal_type"],
        "quantity": log["quantity"],
        "serving_unit": log["serving_unit"],
        "serving_grams": log["serving_grams"],
        "grams": log["grams"],
        "calories": log["calories"],
        "protein": log["protein"],
        "carbs": log["carbs"],
        "fat": log["fat"],
        "fiber": log["fiber"],
        "image_url": image_url(log["image_path"]),
        "ai_guess": log["ai_guess"],
        "was_corrected": bool(log["was_corrected"]),
        "log_date": log["log_date"],
        "logged_at": log["logged_at"],
    }


def rounded(totals):
    return {key: round(value, 1) for key, value in totals.items()}


def classifier():
    """The loaded FoodClassifier, or None while it is still loading."""
    return current_app.extensions.get("food_classifier")


# =============================================================== model status

@api_bp.get("/status")
def status():
    return ok(model_ready=classifier() is not None,
              model_error=current_app.extensions.get("classifier_error"))


# =============================================================== predict

@api_bp.post("/predict")
@login_required
def predict():
    """Photo in, top 3 foods out. The prediction is stored so a meal can point to it."""
    model = classifier()
    if model is None:
        return fail("The AI model is still loading. Please try again in a few seconds.", 503)

    upload = request.files.get("image")
    if upload is None:
        raise ApiError("No image was uploaded (form field 'image')")
    image, image_path = process_upload(upload.stream, upload.filename, current_app.config)
    result = model.classify(image)
    cleanup.run(current_app._get_current_object())      # removes old unused photos, at most once an hour

    top_food_id = result.top3[0].food_id if result.is_food else None
    prediction_id = db.add_prediction(
        current_user()["id"], image_path, result.is_food, top_food_id,
        result.top3[0].confidence, result.level, [asdict(g) for g in result.top3],
    )

    suggestions = []
    for guess in result.top3:
        food = db.get_food(guess.food_id)
        if food:
            suggestions.append({"food_id": food["id"], "name": food["name"], "confidence": guess.confidence,
                                "serving_unit": food["serving_unit"], "serving_grams": food["serving_grams"]})

    return ok(
        prediction_id=prediction_id,
        image_url=image_url(image_path),
        is_food=result.is_food,
        food_probability=result.food_probability,
        confidence_level=result.level,
        top_predictions=suggestions,
        message=LEVEL_MESSAGES[result.level].format(name=result.top3[0].name),
    )


# =============================================================== calculate and log

@api_bp.post("/calculate")
@login_required
def calculate_nutrition():
    """Preview the nutrition of a portion. Nothing is saved."""
    data = json_body()
    food = get_food_or_404(data.get("food_id"))
    result = calculate(food, quantity=data.get("quantity"), grams=data.get("grams"))
    return ok(food={"id": food["id"], "name": food["name"], "serving_unit": food["serving_unit"],
                    "serving_grams": food["serving_grams"]}, **result)


@api_bp.post("/food-log")
@login_required
def add_food_log():
    """Save a meal. The nutrition is recalculated here; numbers from the browser are never trusted."""
    data = json_body()
    user = current_user()
    food = get_food_or_404(data.get("food_id"))

    meal_type = data.get("meal_type")
    if meal_type not in db.MEAL_TYPES:
        raise ApiError("meal_type must be one of: " + ", ".join(db.MEAL_TYPES))

    result = calculate(food, quantity=data.get("quantity"), grams=data.get("grams"))

    prediction_id, was_corrected = None, False
    if data.get("prediction_id") is not None:
        prediction = db.get_prediction(to_int(data["prediction_id"], "prediction_id"), user["id"])
        if prediction is None:
            raise ApiError("Prediction not found", 404)
        prediction_id = prediction["id"]
        was_corrected = prediction["predicted_food_id"] != food["id"]

    nutrients = {key: result[key] for key in ("calories", "protein", "carbs", "fat", "fiber")}
    log_id = db.add_food_log(user["id"], food["id"], meal_type, result["grams"], nutrients,
                             quantity=result["quantity"], prediction_id=prediction_id,
                             was_corrected=was_corrected)

    summary = daily_summary(db.get_daily_totals(user["id"], date.today()), user["daily_calorie_goal"])
    return ok(201, log_id=log_id, nutrition=result,
              today={key: summary[key] for key in ("consumed", "goal", "remaining")})


@api_bp.put("/food-log/<int:log_id>")
@login_required
def update_food_log(log_id):
    """Change the meal type and/or the portion of a saved meal.

    Send meal_type, and either quantity or grams (leave both out to keep the portion).
    The nutrition is recalculated from the food's current values; the food itself
    cannot be changed (delete the meal and add it again for that).
    """
    data = json_body()
    user = current_user()
    log = db.get_log(log_id, user["id"])
    if log is None:
        raise ApiError("Meal not found", 404)

    meal_type = data.get("meal_type", log["meal_type"])
    if meal_type not in db.MEAL_TYPES:
        raise ApiError("meal_type must be one of: " + ", ".join(db.MEAL_TYPES))

    if data.get("quantity") is None and data.get("grams") is None:
        raise ApiError("Send either quantity (servings) or grams")
    food = get_food_or_404(log["food_id"])
    result = calculate(food, quantity=data.get("quantity"), grams=data.get("grams"))

    nutrients = {key: result[key] for key in ("calories", "protein", "carbs", "fat", "fiber")}
    db.update_food_log(log_id, user["id"], meal_type, result["grams"], nutrients, quantity=result["quantity"])

    summary = daily_summary(db.get_daily_totals(user["id"], log["log_date"]), user["daily_calorie_goal"])
    return ok(log_id=log_id, nutrition=result, meal_type=meal_type,
              day={key: summary[key] for key in ("consumed", "goal", "remaining")})


@api_bp.delete("/food-log/<int:log_id>")
@login_required
def delete_food_log(log_id):
    if not db.delete_food_log(log_id, current_user()["id"]):
        raise ApiError("Meal not found", 404)        # also for other users' meals: reveals nothing
    return ok()


# =============================================================== history and dashboard

@api_bp.get("/history")
@login_required
def history():
    """Meals between ?from= and ?to= (default: the last 7 days)."""
    end = to_date(request.args["to"], "to") if request.args.get("to") else date.today()
    start = to_date(request.args["from"], "from") if request.args.get("from") else end - timedelta(days=6)
    if start > end:
        raise ApiError("'from' must be on or before 'to'")
    if (end - start).days >= MAX_HISTORY_DAYS:
        raise ApiError(f"Choose at most {MAX_HISTORY_DAYS} days")
    logs = db.get_logs(current_user()["id"], start, end)
    return ok(**{"from": start.isoformat(), "to": end.isoformat(), "logs": [log_json(log) for log in logs]})


@api_bp.get("/dashboard")
@login_required
def dashboard():
    """Everything the dashboard page shows for one day (default: today)."""
    user = current_user()
    day = to_date(request.args["date"], "date") if request.args.get("date") else date.today()
    totals = db.get_daily_totals(user["id"], day)
    summary = daily_summary(totals, user["daily_calorie_goal"])
    return ok(
        date=day.isoformat(),
        meals_count=totals["meals_count"],
        totals=rounded({key: totals[key] for key in ("protein", "carbs", "fat", "fiber")}),
        by_meal_type=rounded(db.get_calories_by_meal_type(user["id"], day)),
        last_7_days=[{"date": d["date"], "calories": round(d["calories"])}
                     for d in db.get_daily_calories(user["id"], day)],
        meals=[log_json(log) for log in db.get_logs(user["id"], day, day)],
        **summary,
    )


# =============================================================== foods and settings

@api_bp.get("/foods")
@login_required
def list_foods():
    """All foods, or the ones whose name contains ?q= (at most 20)."""
    query = request.args.get("q", "").strip()[:80]
    foods = db.search_foods(query) if query else db.get_all_foods()
    return ok(foods=[food_json(food) for food in foods])


@api_bp.get("/foods/recent")
@login_required
def recent_foods():
    """The foods you logged most recently (each once, newest first) for the quick-add buttons."""
    return ok(foods=[food_json(food) for food in db.get_recent_foods(current_user()["id"])])


@api_bp.post("/foods")
@login_required
def add_food():
    """Add a custom food. It becomes an AI label straight away (no retraining)."""
    food, errors = validate_custom_food(json_body())
    if errors:
        return jsonify(success=False, error=errors[0], errors=errors), 400
    try:
        food_id = db.add_custom_food(food, current_user()["id"])
    except sqlite3.IntegrityError:
        raise ApiError("A food with this name already exists", 409) from None
    saved = db.get_food(food_id)
    if classifier() is not None:
        classifier().add_food(saved)
    return ok(201, food=food_json(saved))


@api_bp.put("/user/goal")
@login_required
def update_goal():
    goal = to_int(json_body().get("daily_calorie_goal"), "daily_calorie_goal")
    if not 800 <= goal <= 5000:
        raise ApiError("The daily goal must be between 800 and 5000 kcal")
    db.update_calorie_goal(current_user()["id"], goal)
    return ok(daily_calorie_goal=goal)
