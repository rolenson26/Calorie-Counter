"""Tests for services/auth.py and the login/register/logout routes."""
import pytest

from database import db
from services.auth import check_login, register_user, safe_next


def test_password_is_stored_only_as_a_hash(app, user_id):
    with app.app_context():
        stored = db.get_user(user_id)["password_hash"]
    assert "secret-pass" not in stored
    assert stored.startswith(("scrypt:", "pbkdf2:"))


@pytest.mark.parametrize("name, email, password, message", [
    ("A", "a@example.com", "long-enough", "Name"),
    ("Asha", "not-an-email", "long-enough", "valid email"),
    ("Asha", "asha2@example.com", "short", "at least 8"),
])
def test_registration_checks_the_details(app, name, email, password, message):
    with app.app_context():
        user_id, errors = register_user(name, email, password)
    assert user_id is None
    assert any(message in error for error in errors)


def test_same_email_cannot_register_twice(app, user_id):
    with app.app_context():
        _, errors = register_user("Asha again", "  ASHA@example.com ", "another-pass")
    assert errors == ["An account with this email already exists"]


def test_check_login(app, user_id):
    with app.app_context():
        assert check_login("Asha@Example.com", "secret-pass")["id"] == user_id
        assert check_login("asha@example.com", "wrong-pass") is None
        assert check_login("nobody@example.com", "secret-pass") is None


@pytest.mark.parametrize("url, expected", [
    ("/dashboard", "/dashboard"),
    ("//evil.example.com", None),
    ("https://evil.example.com", None),
    ("/\\evil.example.com", None),
    (None, None),
])
def test_only_local_redirects_after_login(url, expected):
    assert safe_next(url) == expected


def test_pages_redirect_to_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login?next=/dashboard"


def test_register_form_logs_the_user_in(client):
    response = client.post("/register", data={"name": "Ravi", "email": "ravi@example.com",
                                              "password": "ravi-pass-1"})
    assert response.status_code == 302 and response.headers["Location"] == "/"
    with client.session_transaction() as session:
        assert session["user_id"]


def test_login_form_goes_to_the_requested_page(client, user_id):
    response = client.post("/login?next=/history", data={"email": "asha@example.com", "password": "secret-pass"})
    assert response.headers["Location"] == "/history"
    response = client.post("/login?next=//evil.example.com",
                           data={"email": "asha@example.com", "password": "secret-pass"})
    assert response.headers["Location"] == "/"


def test_logout_clears_the_session(auth_client):
    response = auth_client.post("/logout")
    assert response.status_code == 302
    assert auth_client.get("/api/dashboard").status_code == 401
