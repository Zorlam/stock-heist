"""
Minimal app factory — data layer only.

This is intentionally bare: no blueprints, no routes yet. Its only job
right now is to prove the models wire up cleanly into a real Flask app and
to give the test suite / a future `flask db` (Alembic) setup something to
import. Blockchain, MiniMax, and route layers get added in later steps.
"""

import os

from dotenv import load_dotenv
from flask import Flask

from app.models import db

load_dotenv()  # picks up .env in the project root, if present; no-op otherwise


def create_app(database_url: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url or os.environ.get(
        "DATABASE_URL", "postgresql://localhost/stock_heist"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    return app
