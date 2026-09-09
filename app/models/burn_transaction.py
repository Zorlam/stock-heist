from sqlalchemy.sql import func

from .base import db, GUID, new_uuid, pg_enum
from .enums import BurnTxStatus


class BurnTransaction(db.Model):
    """A single on-chain burn/payment, tracked independently of whatever
    attempt it ends up backing.

    `tx_hash` is THE idempotency key for the whole "1 burn = 1 attempt"
    guarantee: it's globally unique, so the same on-chain transaction can
    never be recorded twice, no matter how many times the client retries
    or resubmits after a page refresh. The service layer should always
    attempt an insert-or-fetch-existing on tx_hash before doing anything
    else with an incoming payment claim.

    This table is intentionally separate from `attempts` (rather than
    folding these columns into the attempts table) because the burn can
    be observed/confirmed before we know anything else about the attempt
    it belongs to, and because it keeps "did the money move" fully
    decoupled from "what happened with the game logic."
    """

    __tablename__ = "burn_transactions"

    id = db.Column(GUID(), primary_key=True, default=new_uuid)

    tx_hash = db.Column(db.String(255), nullable=False, unique=True, index=True)

    wallet_address = db.Column(db.String(255), nullable=False, index=True)
    round_id = db.Column(GUID(), db.ForeignKey("rounds.id"), nullable=False, index=True)

    token_contract = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(38, 18), nullable=False)

    status = db.Column(
        pg_enum(BurnTxStatus, "burn_tx_status"),
        nullable=False,
        default=BurnTxStatus.PENDING,
        index=True,
    )

    block_number = db.Column(db.BigInteger, nullable=True)

    submitted_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    round = db.relationship("Round")
    attempt = db.relationship("Attempt", back_populates="burn_transaction", uselist=False)

    __table_args__ = (
        db.CheckConstraint("amount > 0", name="ck_burn_amount_positive"),
        db.Index("ix_burn_transactions_round_status", "round_id", "status"),
    )

    def __repr__(self):
        return f"<BurnTransaction {self.tx_hash} {self.status}>"
