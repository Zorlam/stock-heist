"""
App factory. Wires up the data layer, the runtime (chain/AI/secrets
dependencies), CORS, and the API blueprint.
"""

import os

from flask import Flask
from flask_cors import CORS

import app.config  # noqa: F401 — imported for its side effect: loads .env
from app.models import db
from app.runtime import init_runtime


def create_app(database_url: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url or os.environ.get(
        "DATABASE_URL", "postgresql://localhost/stock_heist"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Dev-only admin routes (see app/api/routes.py) default to enabled
    # since there's no real deployment yet. MUST be set to False — via
    # ENABLE_DEV_ADMIN_ROUTES=false in the environment, or by editing
    # this default — before this app is ever exposed outside local dev.
    app.config["ENABLE_DEV_ADMIN_ROUTES"] = os.environ.get(
        "ENABLE_DEV_ADMIN_ROUTES", "true"
    ).lower() not in ("false", "0", "no")

    db.init_app(app)
    init_runtime(app)

    # Permissive CORS for local dev, where the 3D frontend runs on a
    # different origin/port than this API. CORS_ALLOWED_ORIGINS lets you
    # lock this down (comma-separated list) once there's a real frontend
    # origin to restrict to — "*" is fine for local development only.
    allowed_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "*")
    origins = "*" if allowed_origins == "*" else allowed_origins.split(",")
    CORS(app, resources={r"/api/*": {"origins": origins}})

    from app.api.routes import api as api_blueprint

    app.register_blueprint(api_blueprint)

    return app
