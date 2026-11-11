"""
database/db.py - the only file that talks to SQLite.

How it connects to the rest of the project
    * app.py calls init_app(app) once at startup. On the first run this
      creates the tables and loads the 73 starter foods automatically.
    * Routes call the query functions below (create_user, get_food,
      add_food_log, get_daily_totals, ...). No other file writes SQL.
    * get_db() gives each web request one connection, kept in flask.g, and
      close_db() closes it when the request ends.

Safety
    Every query uses "?" placeholders. SQLite inserts the values itself, so
    text typed by a user can never change the SQL command (no SQL injection).

Run `python -m database.db` from the project folder to build the database
and print a summary without starting the web app.
"""
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app, g

from database.nutrition_data import FOODS

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")


# =============================================================== setup

def connect(db_path):
    """Open a connection with the settings this app relies on."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row              # rows can be read like dicts: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")    # SQLite switches foreign keys off by default
    return conn


def init_db(conn):
    """Create any missing tables and add any starter food that is not in the table yet.

    On the first run that is every food. Later, only foods added to nutrition_data.py
    since then (for example the Manipuri dishes) are inserted; existing rows, and any
    edits to them, are left alone. Foods are matched by name, ignoring case.
    Returns the number of foods inserted (0 when nothing was missing).
    """
    conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
    existing = {row[0].lower() for row in conn.execute("SELECT name FROM foods")}
    missing = [food for food in FOODS if food["name"].lower() not in existing]
    if not missing:
        return 0
    conn.executemany(
        """INSERT INTO foods (name, category, serving_unit, serving_grams,
                              calories_per_100g, protein_per_100g, carbs_per_100g,
                              fat_per_100g, fiber_per_100g, ai_prompt, source)
           VALUES (:name, :category, :serving_unit, :serving_grams,
                   :calories, :protein, :carbs, :fat, :fiber, :ai_prompt, :source)""",
        missing,
    )
    conn.commit()
    return len(missing)


def get_db():
    """Return the current request's connection, opening it on first use."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exception=None):
    """Close the current request's connection. Flask calls this after every request."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    """Attach the database to a Flask app and make sure the tables exist."""
    app.teardown_appcontext(close_db)
    conn = connect(app.config["DATABASE"])
    try:
        init_db(conn)
    finally:
        conn.close()


def _one(row):
    """sqlite3.Row -> plain dict (or None), so results can go straight into JSON."""
    return dict(row) if row else None


def _all(rows):
    return [dict(row) for row in rows]


def _iso(day):
    """Accept a date object or a 'YYYY-MM-DD' string and return the string."""
    return day.isoformat() if isinstance(day, date) else str(day)


# =============================================================== users

def create_user(name, email, password_hash, daily_calorie_goal=2000):
    """Insert a user and return the new id.

    Raises sqlite3.IntegrityError if the email is already registered.
    """
    db = get_db()
    cursor = db.execute(
        "INSERT INTO users (name, email, password_hash, daily_calorie_goal) VALUES (?, ?, ?, ?)",
        (name, email, password_hash, daily_calorie_goal),
    )
    db.commit()
    return cursor.lastrowid


def get_user(user_id):
    return _one(get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_email(email):
    return _one(get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())


def update_calorie_goal(user_id, goal):
    db = get_db()
    db.execute("UPDATE users SET daily_calorie_goal = ? WHERE id = ?", (goal, user_id))
    db.commit()


# =============================================================== foods

def get_all_foods():
    """Every food, A to Z. The classifier uses this list as its labels."""
    return _all(get_db().execute("SELECT * FROM foods ORDER BY name"))


def get_food(food_id):
    return _one(get_db().execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone())


def search_foods(text, limit=20):
    """Foods whose name contains `text`, ignoring upper/lower case."""
    rows = get_db().execute(
        "SELECT * FROM foods WHERE instr(lower(name), lower(?)) > 0 ORDER BY name LIMIT ?",
        (text, limit),
    )
    return _all(rows)


def add_custom_food(food, user_id):
    """Save a food typed in by a user and return its new id.

    `food` is a dict with name, category, serving_unit, serving_grams and the
    per-100 g values calories, protein, carbs, fat, fiber (already validated).
    Raises sqlite3.IntegrityError if a food with that name already exists.
    """
    db = get_db()
    cursor = db.execute(
        """INSERT INTO foods (name, category, serving_unit, serving_grams,
                              calories_per_100g, protein_per_100g, carbs_per_100g,
                              fat_per_100g, fiber_per_100g, ai_prompt,
                              is_custom, created_by, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 'User')""",
        (
            food["name"], food["category"], food["serving_unit"], food["serving_grams"],
            food["calories"], food["protein"], food["carbs"], food["fat"], food["fiber"],
            f"a photo of {food['name'].lower()}, a dish of food",
            user_id,
        ),
    )
    db.commit()
    return cursor.lastrowid


# =============================================================== predictions

def add_prediction(user_id, image_path, is_food, predicted_food_id, confidence,
                   confidence_level, top3):
    """Store what the AI said about one photo and return the new id.

    top3 is a list like [{"food_id": 7, "name": "Idli", "confidence": 0.81}, ...].
    """
    db = get_db()
    cursor = db.execute(
        """INSERT INTO predictions (user_id, image_path, is_food, predicted_food_id,
                                    confidence, confidence_level, top3_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, image_path, int(is_food), predicted_food_id, confidence,
         confidence_level, json.dumps(top3)),
    )
    db.commit()
    return cursor.lastrowid


def get_prediction(prediction_id, user_id):
    """Return the prediction only if it belongs to this user, otherwise None."""
    row = get_db().execute(
        "SELECT * FROM predictions WHERE id = ? AND user_id = ?", (prediction_id, user_id)
    ).fetchone()
    return _one(row)


def user_owns_image(user_id, image_path):
    """True if this user uploaded the photo saved at image_path (e.g. 'uploads/3f9c....jpg')."""
    row = get_db().execute(
        "SELECT 1 FROM predictions WHERE user_id = ? AND image_path = ? LIMIT 1", (user_id, image_path)
    ).fetchone()
    return row is not None


def get_unused_predictions(max_age_hours):
    """Predictions older than max_age_hours that no saved meal points to.

    These are photos the user scanned but never logged. Returns a list of
    {"id", "image_path"} so the caller can delete the files too.
    """
    rows = get_db().execute(
        """SELECT p.id, p.image_path FROM predictions AS p
           WHERE p.created_at < datetime('now', 'localtime', ?)
             AND NOT EXISTS (SELECT 1 FROM food_logs AS l WHERE l.prediction_id = p.id)""",
        (f"-{int(max_age_hours)} hours",),
    )
    return _all(rows)


def delete_predictions(prediction_ids):
    """Delete these prediction rows (the caller removes the photo files)."""
    db = get_db()
    db.executemany("DELETE FROM predictions WHERE id = ?", [(i,) for i in prediction_ids])
    db.commit()


# =============================================================== food logs

def add_food_log(user_id, food_id, meal_type, grams, nutrients, quantity=None,
                 prediction_id=None, was_corrected=False, eaten_at=None):
    """Save one eaten food and return the new id.

    nutrients is a dict with calories, protein, carbs, fat and fiber, already
    calculated for `grams`. eaten_at defaults to now (laptop's local time).
    """
    db = get_db()
    log_id = _insert_log(db, user_id, food_id, meal_type, grams, nutrients, quantity,
                         prediction_id, was_corrected, eaten_at or datetime.now())
    db.commit()
    return log_id


def add_food_logs(user_id, meal_type, entries, prediction_id=None, eaten_at=None):
    """Save several foods eaten together (for example the items of one thali) and return their ids.

    entries is a list of dicts with food_id, grams, quantity, nutrients and was_corrected.
    Everything is saved in one transaction: either every row is stored or none is.
    """
    eaten_at = eaten_at or datetime.now()
    db = get_db()
    try:
        ids = [
            _insert_log(db, user_id, entry["food_id"], meal_type, entry["grams"], entry["nutrients"],
                        entry["quantity"], prediction_id, entry["was_corrected"], eaten_at)
            for entry in entries
        ]
    except Exception:
        db.rollback()
        raise
    db.commit()
    return ids


def _insert_log(db, user_id, food_id, meal_type, grams, nutrients, quantity,
                prediction_id, was_corrected, eaten_at):
    """INSERT one food_logs row without committing (the caller commits)."""
    cursor = db.execute(
        """INSERT INTO food_logs (user_id, food_id, prediction_id, meal_type, quantity, grams,
                                  calories, protein, carbs, fat, fiber, was_corrected,
                                  log_date, logged_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id, food_id, prediction_id, meal_type, quantity, grams,
            nutrients["calories"], nutrients["protein"], nutrients["carbs"],
            nutrients["fat"], nutrients["fiber"], int(was_corrected),
            eaten_at.date().isoformat(), eaten_at.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return cursor.lastrowid


def get_log(log_id, user_id):
    """One saved meal, only if it belongs to this user."""
    return _one(get_db().execute(
        "SELECT * FROM food_logs WHERE id = ? AND user_id = ?", (log_id, user_id)).fetchone())


def update_food_log(log_id, user_id, meal_type, grams, nutrients, quantity=None):
    """Change the meal type and portion of a saved meal. Returns True if a row was changed.

    The date and time stay as they were, so the meal keeps its place in the history.
    """
    db = get_db()
    cursor = db.execute(
        """UPDATE food_logs SET meal_type = ?, quantity = ?, grams = ?, calories = ?,
                  protein = ?, carbs = ?, fat = ?, fiber = ?
           WHERE id = ? AND user_id = ?""",
        (meal_type, quantity, grams, nutrients["calories"], nutrients["protein"],
         nutrients["carbs"], nutrients["fat"], nutrients["fiber"], log_id, user_id),
    )
    db.commit()
    return cursor.rowcount == 1


def get_recent_foods(user_id, limit=8):
    """The foods this user logged most recently (each food once), newest first.

    Newest is decided by the log id, which always grows, so two meals saved in the same second still sort correctly.
    """
    rows = get_db().execute(
        """SELECT f.* FROM foods AS f
           JOIN (SELECT food_id, MAX(id) AS last_eaten FROM food_logs
                 WHERE user_id = ? GROUP BY food_id) AS r ON r.food_id = f.id
           ORDER BY r.last_eaten DESC, f.name LIMIT ?""",
        (user_id, limit),
    )
    return _all(rows)


def delete_food_log(log_id, user_id):
    """Delete a meal if it belongs to this user. Returns True if a row was deleted."""
    db = get_db()
    cursor = db.execute("DELETE FROM food_logs WHERE id = ? AND user_id = ?", (log_id, user_id))
    db.commit()
    return cursor.rowcount == 1


def get_logs(user_id, start_day, end_day):
    """Meals between two dates (both included), newest first.

    Each row also carries the food name, the photo path and the AI's guess,
    so the history page can show whether the user corrected the AI.
    """
    rows = get_db().execute(
        """SELECT l.*, f.name AS food_name, f.serving_unit, f.serving_grams,
                  p.image_path, p.confidence AS ai_confidence, guess.name AS ai_guess
           FROM food_logs AS l
           JOIN foods AS f            ON f.id = l.food_id
           LEFT JOIN predictions AS p ON p.id = l.prediction_id
           LEFT JOIN foods AS guess   ON guess.id = p.predicted_food_id
           WHERE l.user_id = ? AND l.log_date BETWEEN ? AND ?
           ORDER BY l.logged_at DESC, l.id DESC""",
        (user_id, _iso(start_day), _iso(end_day)),
    )
    return _all(rows)


def get_daily_totals(user_id, day):
    """Total calories and nutrients eaten on one day, plus the number of meals."""
    row = get_db().execute(
        """SELECT COUNT(*)                   AS meals_count,
                  COALESCE(SUM(calories), 0) AS calories,
                  COALESCE(SUM(protein), 0)  AS protein,
                  COALESCE(SUM(carbs), 0)    AS carbs,
                  COALESCE(SUM(fat), 0)      AS fat,
                  COALESCE(SUM(fiber), 0)    AS fiber
           FROM food_logs WHERE user_id = ? AND log_date = ?""",
        (user_id, _iso(day)),
    ).fetchone()
    return dict(row)


def get_calories_by_meal_type(user_id, day):
    """Calories per meal type on one day, e.g. {"breakfast": 320, "lunch": 690, ...}."""
    totals = {meal: 0 for meal in MEAL_TYPES}
    rows = get_db().execute(
        """SELECT meal_type, SUM(calories) AS calories FROM food_logs
           WHERE user_id = ? AND log_date = ? GROUP BY meal_type""",
        (user_id, _iso(day)),
    )
    for row in rows:
        totals[row["meal_type"]] = row["calories"]
    return totals


def get_daily_calories(user_id, end_day, days=7):
    """Calories for each of the `days` days ending on end_day, oldest first.

    Days without any meals are included with 0, so the chart has no gaps.
    """
    if isinstance(end_day, str):
        end_day = date.fromisoformat(end_day)
    start_day = end_day - timedelta(days=days - 1)
    rows = get_db().execute(
        """SELECT log_date, SUM(calories) AS calories FROM food_logs
           WHERE user_id = ? AND log_date BETWEEN ? AND ? GROUP BY log_date""",
        (user_id, start_day.isoformat(), end_day.isoformat()),
    )
    by_date = {row["log_date"]: row["calories"] for row in rows}
    result = []
    for offset in range(days):
        day = (start_day + timedelta(days=offset)).isoformat()
        result.append({"date": day, "calories": by_date.get(day, 0)})
    return result


def get_ai_accuracy(user_id=None):
    """How often users kept the AI's top guess, counting only meals logged from a photo.

    Used in the Testing chapter: accuracy = meals where the AI was right / all photo meals.
    """
    sql = """SELECT COUNT(*) AS total, COALESCE(SUM(was_corrected = 0), 0) AS correct
             FROM food_logs WHERE prediction_id IS NOT NULL"""
    params = ()
    if user_id is not None:
        sql += " AND user_id = ?"
        params = (user_id,)
    row = get_db().execute(sql, params).fetchone()
    total, correct = row["total"], row["correct"]
    return {"total": total, "correct": correct, "accuracy": correct / total if total else None}


# =============================================================== command line

if __name__ == "__main__":
    from config import Config

    connection = connect(Config.DATABASE)
    added = init_db(connection)
    count = connection.execute("SELECT COUNT(*) FROM foods").fetchone()[0]
    print(f"Database file : {Config.DATABASE}")
    print(f"Foods added   : {added} (0 means the database already existed)")
    print(f"Foods in table: {count}")
    for category, n in connection.execute(
        "SELECT category, COUNT(*) FROM foods GROUP BY category ORDER BY category"
    ):
        print(f"   {category:<16} {n}")
    connection.close()
