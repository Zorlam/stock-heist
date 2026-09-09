"""
Stock Heist data model.

Usage from your Flask app factory:

    from app.models import db

    def create_app():
        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://..."
        db.init_app(app)
        return app

Importing this package registers all models on `db.metadata`, so
`db.create_all()` (or, in production, Alembic migrations generated against
this metadata) picks up every table below.
"""

from .base import db, GUID, new_uuid, pg_enum
from .enums import (
    RoundStatus,
    BurnTxStatus,
    AttemptStatus,
    PayoutStatus,
    ATTEMPT_TERMINAL_STATUSES,
    ATTEMPT_ACTIONABLE_STATUSES,
)
from .player import Player
from .round import Round
from .burn_transaction import BurnTransaction
from .attempt import Attempt
from .ai_response import AIResponse
from .payout_transaction import PayoutTransaction
from .attempt_status_history import AttemptStatusHistory

__all__ = [
    "db",
    "GUID",
    "new_uuid",
    "pg_enum",
    "RoundStatus",
    "BurnTxStatus",
    "AttemptStatus",
    "PayoutStatus",
    "ATTEMPT_TERMINAL_STATUSES",
    "ATTEMPT_ACTIONABLE_STATUSES",
    "Player",
    "Round",
    "BurnTransaction",
    "Attempt",
    "AIResponse",
    "PayoutTransaction",
    "AttemptStatusHistory",
]
