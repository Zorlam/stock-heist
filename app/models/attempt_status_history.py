from sqlalchemy.sql import func

from .base import db, GUID, new_uuid, pg_enum
from .enums import AttemptStatus


class AttemptStatusHistory(db.Model):
    """Append-only audit trail of every status transition an attempt goes
    through. This is what lets you answer "what exactly happened to this
    attempt, and when" for support/dispute/debugging purposes, without
    relying on `attempts.updated_at` (which only tells you *when it last
    changed*, not the path it took to get there).

    Write a row here in the same DB transaction as every status change on
    `attempts.status`. `from_status` is nullable to represent the initial
    row creation (no prior status).
    """

    __tablename__ = "attempt_status_history"

    id = db.Column(GUID(), primary_key=True, default=new_uuid)

    attempt_id = db.Column(GUID(), db.ForeignKey("attempts.id"), nullable=False, index=True)

    from_status = db.Column(pg_enum(AttemptStatus, "attempt_status_history_from"), nullable=True)
    to_status = db.Column(pg_enum(AttemptStatus, "attempt_status_history_to"), nullable=False)

    note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    attempt = db.relationship("Attempt", back_populates="status_history")

    def __repr__(self):
        return f"<AttemptStatusHistory {self.attempt_id}: {self.from_status} -> {self.to_status}>"
