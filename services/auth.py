"""
services/auth.py - registration, login and the login_required check.

Passwords are never stored. Werkzeug's generate_password_hash() turns a
password into a salted hash (for example "scrypt:32768:8:1$..."), and
check_password_hash() tells whether a typed password matches that hash.
Even someone who copies the database cannot read the passwords.

How it connects
    * routes/pages.py calls register_user(), check_login(), log_in(), log_out().
    * Every protected page and API route is wrapped in @login_required.
    * Flask keeps only the user's id in the signed session cookie.
"""
import re
import sqlite3
from functools import wraps

from flask import current_app, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import db

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def register_user(name, email, password):
    """Check the details and create an account. Returns (user_id, errors)."""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    password = password or ""

    errors = []
    if not 2 <= len(name) <= 60:
        errors.append("Name must be 2 to 60 characters")
    if len(email) > 120 or not EMAIL_PATTERN.match(email):
        errors.append("Enter a valid email address")
    if not 8 <= len(password) <= 200:
        errors.append("Password must be at least 8 characters")
    if errors:
        return None, errors

    try:
        user_id = db.create_user(
            name, email, generate_password_hash(password), current_app.config["DEFAULT_CALORIE_GOAL"]
        )
    except sqlite3.IntegrityError:                 # the email is UNIQUE in the users table
        return None, ["An account with this email already exists"]
    return user_id, []


def check_login(email, password):
    """Return the user if the email and password match, otherwise None."""
    user = db.get_user_by_email((email or "").strip().lower())
    if user and check_password_hash(user["password_hash"], password or ""):
        return user
    return None


def log_in(user):
    session.clear()                                # drop anything from before the login
    session["user_id"] = user["id"]


def log_out():
    session.clear()


def current_user():
    """The logged-in user as a dict, or None. Looked up once per request."""
    if "user" not in g:
        user_id = session.get("user_id")
        g.user = db.get_user(user_id) if user_id else None
    return g.user


def safe_next(url):
    """Only allow redirects to our own pages after login (blocks //evil.com tricks)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return None


def login_required(view):
    """Decorator: let the request through only for a logged-in user.

    API routes answer 401 with JSON; pages redirect to the login page.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify(success=False, error="Please log in first"), 401
            return redirect(url_for("pages.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped
