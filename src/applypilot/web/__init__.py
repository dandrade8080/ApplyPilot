"""Flask web application factory for ApplyPilot dashboard."""

from flask import Flask


def create_app() -> Flask:
    from applypilot.config import ensure_dirs, load_env
    from applypilot.database import init_db

    load_env()
    ensure_dirs()
    init_db()

    app = Flask(__name__)

    from applypilot.web.routes import bp
    app.register_blueprint(bp)

    return app
