from sqlalchemy.sql import func

from .base import db, GUID, new_uuid


class Player(db.Model):
    """A wallet that has interacted with the game.

    Deliberately thin — this is not a user-accounts system, just an
    identity anchor for a wallet address so attempts/history can be
    queried per-player. No auth/session data lives here.
    """

    __tablename__ = "players"

    id = db.Column(GUID(), primary_key=True, default=new_uuid)

    # Store addresses lower-cased/normalized at the application layer before
    # insert — this column assumes normalized input and relies on it for
    # the uniqueness guarantee (mixed-case duplicates would otherwise slip
    # through as "different" wallets).
    wallet_address = db.Column(db.String(255), nullable=False, unique=True, index=True)

    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)

    attempts = db.relationship("Attempt", back_populates="player")

    def __repr__(self):
        return f"<Player {self.wallet_address}>"
