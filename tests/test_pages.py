"""Tests that every page renders, and that forms and error pages behave."""
import pytest

from database import db


@pytest.mark.parametrize("path, marker", [
    ("/", 'id="step-capture"'),
    ("/dashboard", 'id="week-chart"'),
    ("/history", 'id="history-rows"'),
    ("/foods", 'id="add-food-form"'),
])
def test_logged_in_pages_render(auth_client, path, marker):
    response = auth_client.get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert marker in html
    assert "not medical or dietary advice" in html          # disclaimer on every page
    assert "Asha" in html                                   # navbar shows who is logged in


def test_scan_page_has_camera_and_upload_inputs(auth_client):
    html = auth_client.get("/").get_data(as_text=True)
    assert 'capture="environment"' in html
    assert 'accept="image/jpeg,image/png,image/webp"' in html
    for meal in ("breakfast", "lunch", "dinner", "snack"):
        assert f'value="{meal}"' in html


def test_foods_page_lists_serving_units(auth_client):
    html = auth_client.get("/foods").get_data(as_text=True)
    assert '<option value="katori">katori</option>' in html


@pytest.mark.parametrize("path", ["/login", "/register"])
def test_auth_pages_render_for_visitors(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert 'method="post"' in response.get_data(as_text=True)


def test_login_form_keeps_the_next_page(client):
    html = client.get("/login?next=/history").get_data(as_text=True)
    assert 'action="/login?next=/history"' in html or 'action="/login?next=%2Fhistory"' in html


def test_wrong_password_shows_a_message(client, user_id):
    response = client.post("/login", data={"email": "asha@example.com", "password": "nope-nope"})
    html = response.get_data(as_text=True)
    assert response.status_code == 401
    assert "Wrong email or password" in html
    assert 'value="asha@example.com"' in html               # the email is kept, the password is not


def test_registration_errors_are_listed(client):
    response = client.post("/register", data={"name": "A", "email": "bad", "password": "123"})
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert "Name must be 2 to 60 characters" in html
    assert "Enter a valid email address" in html
    assert "Password must be at least 8 characters" in html


def test_user_text_is_escaped(client, app):
    client.post("/register", data={"name": "<script>alert(1)</script>", "email": "x@example.com",
                                   "password": "long-enough"})
    html = client.get("/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_missing_page_shows_the_error_page(auth_client):
    response = auth_client.get("/no-such-page")
    html = response.get_data(as_text=True)
    assert response.status_code == 404
    assert "Page not found" in html and "Back to home" in html


def test_static_files_are_served(client):
    for path in ("/static/css/style.css", "/static/js/main.js", "/static/vendor/bootstrap.min.css",
                 "/static/vendor/chart.umd.min.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        response.close()


def test_home_page_example_card_uses_the_sample_photo(auth_client):
    """The home page shows a real AI result for static/img/example-thali.jpg, so the photo must exist and load."""
    import io

    from PIL import Image

    html = auth_client.get("/").get_data(as_text=True)
    assert "/static/img/example-thali.jpg" in html
    assert "Low confidence" in html                         # the honest result of the real run (see the comment in index.html)

    response = auth_client.get("/static/img/example-thali.jpg")
    assert response.status_code == 200
    image = Image.open(io.BytesIO(response.data))
    response.close()
    assert image.format == "JPEG"
    assert image.size == (784, 410)                         # the width/height written in the <img> tag


def test_navbar_marks_the_current_page(auth_client):
    html = auth_client.get("/history").get_data(as_text=True)
    assert 'aria-current="page"' in html
    assert html.index('aria-current="page"') < html.index(">History</a>")
