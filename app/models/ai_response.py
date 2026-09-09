from sqlalchemy.sql import func

from .base import db, GUID, new_uuid


class AIResponse(db.Model):
    """The MiniMax call and result for a single attempt. One-to-one with
    Attempt (an attempt gets exactly one message to the AI, per the game
    rules — there is no retry-with-a-different-message path; a failed AI
    *request* can be retried, but that retry reuses this same row rather
    than creating a new one, since it's still "the one message" being
    delivered).

    `prompt_sent` stores the exact prompt (system + user message) that was
    actually sent, not just the player's raw message — useful for
    debugging prompt-injection incidents and for reproducing a dispute
    ("what did the AI actually see"). Be mindful this means the broker
    system prompt itself is recoverable by anyone with DB read access;
    restrict access accordingly, same as the secret code.
    """

    __tablename__ = "ai_responses"

    id = db.Column(GUID(), primary_key=True, default=new_uuid)

    attempt_id = db.Column(GUID(), db.ForeignKey("attempts.id"), nullable=False, unique=True)

    model_used = db.Column(db.String(64), nullable=False, default="minimax")
    prompt_sent = db.Column(db.Text, nullable=True)
    raw_response = db.Column(db.Text, nullable=True)

    # Result of the deterministic verdict check (raw_response contains the
    # secret code or not). Nullable because it's unset until evaluation
    # runs; distinguishing "not yet evaluated" (NULL) from "evaluated,
    # no match" (False) matters for the worker picking up pending work.
    is_match = db.Column(db.Boolean, nullable=True)

    requested_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), nullable=True)
    evaluated_at = db.Column(db.DateTime(timezone=True), nullable=True)

    attempt = db.relationship("Attempt", back_populates="ai_response")

    def __repr__(self):
        return f"<AIResponse for attempt {self.attempt_id} match={self.is_match}>"
