"""Flask web application factory for ApplyPilot dashboard."""

import os
import sys
from pathlib import Path

from flask import Flask


def _get_template_folder() -> str:
    """Resolve template path — works in both dev and PyInstaller builds."""
    if getattr(sys, 'frozen', False):
        return str(Path(sys._MEIPASS) / 'applypilot' / 'web' / 'templates')
    return str(Path(__file__).parent / 'templates')


def create_app() -> Flask:
    from applypilot.config import ensure_dirs, load_env
    from applypilot.database import init_db

    load_env()
    ensure_dirs()
    init_db()

    app = Flask(__name__, template_folder=_get_template_folder())
    app.config['EXPLAIN_TEMPLATE_LOADING'] = True

    from applypilot.web.routes import bp
    app.register_blueprint(bp)

    return app
