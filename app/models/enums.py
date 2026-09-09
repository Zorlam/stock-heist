"""
State machines for Stock Heist.

Every enum here is stored as a plain string column (native_enum=False on the
SQLAlchemy Enum type — see base.py) rather than a native Postgres ENUM type.
This is a deliberate tradeoff: native Postgres enums are marginally more
storage-efficient, but altering them later (adding a new status value) is a
migration headache. A CHECK constraint on a VARCHAR gets us the same
correctness guarantee and is trivial to extend.
"""

import enum


class RoundStatus(str, enum.Enum):
    """Lifecycle of a single vault/round."""

    OPEN = "open"          # accepting attempts
    WON = "won"             # a winning attempt has been recorded; no new attempts
    CANCELLED = "cancelled"  # closed without a winner (ops decision, e.g. relaunch)


class BurnTxStatus(str, enum.Enum):
    """Lifecycle of an on-chain burn/payment transaction, independent of
    whatever attempt it may end up backing."""

    PENDING = "pending"      # seen/submitted, not yet confirmed on-chain
    CONFIRMED = "confirmed"  # confirmed with required confirmations
    FAILED = "failed"        # reverted, dropped, or never confirmed within timeout


class AttemptStatus(str, enum.Enum):
    """Lifecycle of a single attempt (= one confirmed burn = one message).

    Linear happy path:
        PENDING_PAYMENT -> PAYMENT_CONFIRMED -> AI_REQUEST_IN_PROGRESS
        -> EVALUATING -> (WON -> PAYOUT_PENDING -> PAYOUT_COMPLETED)
                       -> (LOST)

    Failure/retry branches:
        AI_REQUEST_IN_PROGRESS -> AI_REQUEST_FAILED  (retryable, no re-payment)
        WON -> PAYOUT_PENDING -> PAYOUT_FAILED        (retryable, no re-evaluation)

    Race branch:
        EVALUATING -> LOST_ROUND_CLOSED   (would have won, but another
                                            attempt's payout already closed
                                            the round first)
    """

    PENDING_PAYMENT = "pending_payment"
    PAYMENT_CONFIRMED = "payment_confirmed"
    AI_REQUEST_IN_PROGRESS = "ai_request_in_progress"
    AI_REQUEST_FAILED = "ai_request_failed"
    EVALUATING = "evaluating"
    LOST = "lost"
    LOST_ROUND_CLOSED = "lost_round_closed"
    WON = "won"
    PAYOUT_PENDING = "payout_pending"
    PAYOUT_FAILED = "payout_failed"
    PAYOUT_COMPLETED = "payout_completed"


# Statuses that represent a "finished, no further processing" state.
# Useful for queries like "give me all attempts still needing work".
ATTEMPT_TERMINAL_STATUSES = {
    AttemptStatus.LOST,
    AttemptStatus.LOST_ROUND_CLOSED,
    AttemptStatus.PAYOUT_COMPLETED,
}

# Statuses eligible for a background worker to pick up and retry/advance.
ATTEMPT_ACTIONABLE_STATUSES = {
    AttemptStatus.PAYMENT_CONFIRMED,
    AttemptStatus.AI_REQUEST_FAILED,
    AttemptStatus.EVALUATING,
    AttemptStatus.WON,
    AttemptStatus.PAYOUT_FAILED,
}


class PayoutStatus(str, enum.Enum):
    """Lifecycle of the on-chain prize transfer."""

    PENDING = "pending"      # row created, tx not yet submitted
    SUBMITTED = "submitted"  # tx broadcast, awaiting confirmation
    CONFIRMED = "confirmed"  # confirmed on-chain
    FAILED = "failed"        # submission or confirmation failed; retryable
