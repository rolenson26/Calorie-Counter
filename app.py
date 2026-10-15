"""
app.py - builds and starts the AI Food Calorie Counter.

Run it (from the project folder, with the virtual environment active):
    python app.py                     -> http://127.0.0.1:5000 on this laptop
    python app.py --host 0.0.0.0      -> also reachable from a phone on the same Wi-Fi

What happens at start-up
    1. Settings are read from config.py.
    2. The database is created and filled with the starter foods if needed.
    3. Old photos that were never saved to a meal are deleted (services/cleanup.py).
    4. The page routes and the /api routes are registered.
    5. The CLIP model starts loading in a background thread, so the website
       opens immediately. Until it is ready, /api/predict answers 503
       "model is still loading" and /api/status says model_ready: false.
"""
import argparse
import logging
import threading

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from config import Config
from database import db
from routes.api import api_bp
from routes.pages import pages_bp
from services import cleanup


def create_app(config_overrides=None, classifier=None):
    """Application factory: build a configured Flask app.

    config_overrides - settings to change (tests use a temporary database)
    classifier       - a ready classifier to use instead of loading CLIP (tests pass a fake one)
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)
    app.logger.setLevel(logging.INFO)              # show "AI model ready" in the terminal

    db.init_app(app)
    cleanup.run(app, force=True)                   # delete old photos that were never saved to a meal
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    register_error_handlers(app)

    app.extensions["food_classifier"] = classifier
    app.extensions["classifier_error"] = None
    if classifier is None and app.config.get("LOAD_MODEL", True):
        start_loading_classifier(app)
    return app


def start_loading_classifier(app):
    """Load CLIP in a background thread and hand it to the app when ready."""

    def load():
        try:
            from services.food_classifier import FoodClassifier   # slow import, so done here

            model = FoodClassifier(
                app.config["MODEL_NAME"], app.config["MODEL_CACHE_DIR"],
                app.config["HIGH_CONFIDENCE"], app.config["LOW_CONFIDENCE"],
                app.config["FOOD_GATE_THRESHOLD"],
            )
            with app.app_context():
                model.set_foods(db.get_all_foods())
            app.extensions["food_classifier"] = model
            app.logger.info("AI model ready (%d foods)", len(model.foods))
        except Exception:
            app.logger.exception("Could not load the AI model")
            app.extensions["classifier_error"] = "The AI model could not be loaded. See the server log."

    threading.Thread(target=load, name="load-clip", daemon=True).start()


def register_error_handlers(app):
    """Turn every error into a clean answer: JSON for /api/..., a simple page otherwise.

    Stack traces go to the server log only, never to the browser.
    """
    messages = {
        404: "Page not found",
        405: "This action is not allowed here",
        413: f"The image is larger than {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB",
        500: "Something went wrong on the server. Please try again.",
    }

    def respond(code, message):
        if request.path.startswith("/api/"):
            return jsonify(success=False, error=message), code
        return render_template("error.html", code=code, message=message), code

    @app.errorhandler(HTTPException)
    def http_error(error):
        return respond(error.code, messages.get(error.code, error.description))

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.exception("Unexpected error on %s", request.path)
        return respond(500, messages[500])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the AI Food Calorie Counter.")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow phones on the same Wi-Fi")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port, debug=False)
