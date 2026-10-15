"""
routes/pages.py - the HTML pages (templates are built in Part 5).

The pages are mostly empty frames: after a page loads, its JavaScript asks
the JSON API (routes/api.py) for the data. Only login, registration and
logout are handled here with normal HTML forms.
"""
from flask import Blueprint, abort, current_app, redirect, render_template, request, send_from_directory, url_for

from database import db
from services import auth
from services.auth import current_user, login_required
from services.calorie_calculator import SERVING_UNITS

pages_bp = Blueprint("pages", __name__)


@pages_bp.app_context_processor
def inject_user():
    """Make `current_user` available in every template (for the navbar)."""
    return {"current_user": auth.current_user()}


@pages_bp.get("/")
@login_required
def index():
    return render_template("index.html", meal_types=db.MEAL_TYPES, serving_units=SERVING_UNITS)


@pages_bp.get("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", meal_types=db.MEAL_TYPES)


@pages_bp.get("/history")
@login_required
def history():
    return render_template("history.html", meal_types=db.MEAL_TYPES)


@pages_bp.get("/foods")
@login_required
def foods():
    return render_template("foods.html", serving_units=SERVING_UNITS)


@pages_bp.get("/uploads/<name>")
@login_required
def uploaded_photo(name):
    """Send a meal photo, but only to the user who uploaded it.

    send_from_directory() refuses paths that try to leave the upload folder.
    """
    if not db.user_owns_image(current_user()["id"], f"uploads/{name}"):
        abort(404)                                   # same answer as "does not exist"
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], name)


@pages_bp.route("/register", methods=["GET", "POST"])
def register():
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        user_id, errors = auth.register_user(form.get("name"), form.get("email"), form.get("password"))
        if not errors:
            auth.log_in(db.get_user(user_id))
            return redirect(url_for("pages.index"))
        return render_template("register.html", errors=errors, form=form), 400
    return render_template("register.html", errors=[], form=form)


@pages_bp.route("/login", methods=["GET", "POST"])
def login():
    form = request.form if request.method == "POST" else {}
    if request.method == "POST":
        user = auth.check_login(form.get("email"), form.get("password"))
        if user:
            auth.log_in(user)
            return redirect(auth.safe_next(request.args.get("next")) or url_for("pages.index"))
        # Same message for "no such email" and "wrong password": reveals nothing to an attacker.
        return render_template("login.html", error="Wrong email or password", form=form), 401
    return render_template("login.html", error=None, form=form)


@pages_bp.post("/logout")
def logout():
    auth.log_out()
    return redirect(url_for("pages.login"))
