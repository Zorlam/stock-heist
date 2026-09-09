from sqlalchemy.sql import func

from .base import db, GUID, new_uuid, pg_enum
from .enums import PayoutStatus


class PayoutTransaction(db.Model):
    """The on-chain prize transfer for a winning attempt.

    Both `round_id` and `attempt_id` are UNIQUE, which is deliberately
    redundant with the partial unique index on attempts — this is the
    payout-side backstop against a duplicate payout ever being recorded,
    independent of whatever guaranteed there was only one winning attempt
    in the first place. A round can have at most one payout row; an
    attempt can have at most one payout row.

    `tx_hash` is nullable (unset until the transaction is actually
    submitted) but unique when present, so a retried submission that
    reuses the same broadcast can't accidentally create a second payout
    record for the same on-chain event.
    """

    __tablename__ = "payout_transactions"

    id = db.Column(GUID(), primary_key=True, default=new_uuid)

    round_id = db.Column(GUID(), db.ForeignKey("rounds.id"), nullable=False, unique=True)
    attempt_id = db.Column(GUID(), db.ForeignKey("attempts.id"), nullable=False, unique=True)

    wallet_address = db.Column(db.String(255), nullable=False)
    asset_token_contract = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(38, 18), nullable=False)

    tx_hash = db.Column(db.String(255), nullable=True, unique=True)

    status = db.Column(
        pg_enum(PayoutStatus, "payout_status"),
        nullable=False,
        default=PayoutStatus.PENDING,
        index=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    round = db.relationship("Round")
    attempt = db.relationship("Attempt", back_populates="payout_transaction")

    __table_args__ = (db.CheckConstraint("amount > 0", name="ck_payout_amount_positive"),)

    def __repr__(self):
        return f"<PayoutTransaction round={self.round_id} {self.status}>"
