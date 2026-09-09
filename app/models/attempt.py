from sqlalchemy.sql import func

from .base import db, GUID, new_uuid, pg_enum
from .enums import AttemptStatus


class Attempt(db.Model):
    """One message = one confirmed burn. The central entity of the game.

    Two constraints do the heaviest lifting in this whole schema:

    1. `burn_transaction_id` is UNIQUE -> a given burn can back at most one
       attempt. Combined with the UNIQUE tx_hash on BurnTransaction, this
       is the full "1 burn = 1 attempt, no reuse" guarantee, enforced by
       Postgres itself rather than application logic.

    2. The partial unique index `ix_one_winner_per_round` (see
       __table_args__) -> at most one attempt per round can ever be in
       status='won'. This is what makes "multiple winners for one vault"
       structurally impossible, even under concurrent writers, without
       relying on row locks being taken correctly everywhere. (You should
       still take a row lock on the round during the win-check —
       SELECT ... FOR UPDATE — because you want the *first* legitimate
       winner to succeed and the second to fail gracefully with a clear
       LOST_ROUND_CLOSED, not just fail loudly with an IntegrityError. But
       the index is the backstop if that discipline slips anywhere.)
    """

    __tablename__ = "attempts"

    id = db.Column(GUID(), primary_key=True, default=new_uuid)

    round_id = db.Column(GUID(), db.ForeignKey("rounds.id"), nullable=False, index=True)
    player_id = db.Column(GUID(), db.ForeignKey("players.id"), nullable=False, index=True)

    # One-to-one, and the anchor of the "1 burn = 1 attempt" guarantee.
    burn_transaction_id = db.Column(
        GUID(), db.ForeignKey("burn_transactions.id"), nullable=False, unique=True
    )

    message = db.Column(db.Text, nullable=False)

    status = db.Column(
        pg_enum(AttemptStatus, "attempt_status"),
        nullable=False,
        default=AttemptStatus.PENDING_PAYMENT,
        index=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    round = db.relationship("Round", back_populates="attempts", foreign_keys=[round_id])
    player = db.relationship("Player", back_populates="attempts")
    burn_transaction = db.relationship("BurnTransaction", back_populates="attempt")
    ai_response = db.relationship("AIResponse", back_populates="attempt", uselist=False)
    payout_transaction = db.relationship("PayoutTransaction", back_populates="attempt", uselist=False)
    status_history = db.relationship(
        "AttemptStatusHistory",
        back_populates="attempt",
        order_by="AttemptStatusHistory.created_at",
    )

    __table_args__ = (
        # THE core "no double winners" guarantee. Note the WHERE clause
        # references the raw stored string value ('won'), matching
        # AttemptStatus.WON.value — see pg_enum() in base.py for why this
        # is a VARCHAR under the hood rather than a native enum type.
        db.Index(
            "ix_one_winner_per_round",
            "round_id",
            unique=True,
            postgresql_where=db.text("status = 'won'"),
            sqlite_where=db.text("status = 'won'"),
        ),
        db.Index("ix_attempts_round_status", "round_id", "status"),
        db.Index("ix_attempts_player_created", "player_id", "created_at"),
    )

    def __repr__(self):
        return f"<Attempt {self.id} {self.status}>"
