from sqlalchemy.sql import func

from .base import db, GUID, new_uuid, pg_enum
from .enums import RoundStatus


class Round(db.Model):
    """A single vault instance. Exactly one round should be OPEN at a time
    in v1 (enforced at the application/service layer, not the DB — see
    note below) — this table itself supports multiple concurrent rounds
    if that constraint is relaxed later, since nothing here assumes
    singleton-ness.

    NOTE on "only one OPEN round at a time": a partial unique index would
    normally be the clean way to enforce this in Postgres, e.g.
        CREATE UNIQUE INDEX one_open_round ON rounds ((true)) WHERE status = 'open';
    We deliberately do NOT add that here. Ambiguity #4 in the architecture
    doc (can multiple rounds run concurrently, e.g. different vaults at
    once?) hasn't been resolved yet — add that index once it is, if the
    answer is "no, always exactly one."
    """

    __tablename__ = "rounds"

    id = db.Column(GUID(), primary_key=True, default=new_uuid)

    status = db.Column(
        pg_enum(RoundStatus, "round_status"),
        nullable=False,
        default=RoundStatus.OPEN,
        index=True,
    )

    # --- vault contents (the prize) ---
    asset_symbol = db.Column(db.String(32), nullable=False)  # e.g. "NVDA"
    asset_token_contract = db.Column(db.String(255), nullable=False)  # tokenized-stock contract address
    prize_amount = db.Column(db.Numeric(38, 18), nullable=False)  # amount of asset held in vault

    # --- cost to attempt (the project token economics) ---
    project_token_contract = db.Column(db.String(255), nullable=False)
    burn_amount = db.Column(db.Numeric(38, 18), nullable=False)  # tokens required per attempt

    # --- secret ---
    # Store a salted hash, not the plaintext code. The verdict engine
    # hashes the AI's response text (or substrings of it) with the same
    # salt and compares — this means even a full DB read doesn't hand
    # over the secret outright. `secret_code_plaintext` is intentionally
    # NOT a column; if you need it for admin/debug tooling, keep it in a
    # separate, tightly-access-controlled config store, not this table.
    secret_code_hash = db.Column(db.String(255), nullable=False)
    secret_code_salt = db.Column(db.String(64), nullable=False)

    opened_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Convenience pointer to the winning attempt, set atomically (same DB
    # transaction) as the attempt's status flip to WON and this round's
    # status flip to WON. This is a *query convenience*, not the source of
    # truth for "is there a winner" — that guarantee comes from the
    # partial unique index on attempts (round_id) WHERE status = 'won',
    # defined in attempt.py. Two independent mechanisms agreeing is the
    # point: this FK could theoretically be wrong due to an application
    # bug, but the partial index can never be violated regardless of
    # application-layer bugs.
    winning_attempt_id = db.Column(
        GUID(),
        db.ForeignKey("attempts.id", use_alter=True, name="fk_round_winning_attempt"),
        nullable=True,
        unique=True,
    )

    attempts = db.relationship(
        "Attempt",
        back_populates="round",
        foreign_keys="Attempt.round_id",
    )
    winning_attempt = db.relationship(
        "Attempt",
        foreign_keys=[winning_attempt_id],
        post_update=True,
    )

    __table_args__ = (
        db.CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR (status != 'open' AND closed_at IS NOT NULL)",
            name="ck_round_closed_at_consistency",
        ),
        db.CheckConstraint("prize_amount > 0", name="ck_round_prize_amount_positive"),
        db.CheckConstraint("burn_amount > 0", name="ck_round_burn_amount_positive"),
    )

    def __repr__(self):
        return f"<Round {self.id} {self.status} {self.asset_symbol}>"
