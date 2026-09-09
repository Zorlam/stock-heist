"""
Verification suite for the data layer.

These tests exist to prove the DB-level guarantees actually hold — i.e.
that violating them raises IntegrityError from the database itself, not
just "the application code happens not to do that today." Each test name
maps directly to one of the requirements in the brief.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    db,
    Player,
    Round,
    BurnTransaction,
    Attempt,
    AIResponse,
    PayoutTransaction,
    AttemptStatusHistory,
    RoundStatus,
    BurnTxStatus,
    AttemptStatus,
    PayoutStatus,
)


# ---- helpers -----------------------------------------------------------


def make_round(**overrides):
    defaults = dict(
        status=RoundStatus.OPEN,
        asset_symbol="NVDA",
        asset_token_contract="0xASSET",
        prize_amount="50.0",
        project_token_contract="0xTOKEN",
        burn_amount="10000",
        secret_code_hash="hash_abc",
        secret_code_salt="salt_abc",
    )
    defaults.update(overrides)
    r = Round(**defaults)
    db.session.add(r)
    db.session.commit()
    return r


def make_player(wallet_address="0xplayer1"):
    p = Player(wallet_address=wallet_address)
    db.session.add(p)
    db.session.commit()
    return p


def make_burn(round_, tx_hash, wallet_address="0xplayer1", amount="10000"):
    b = BurnTransaction(
        tx_hash=tx_hash,
        wallet_address=wallet_address,
        round_id=round_.id,
        token_contract=round_.project_token_contract,
        amount=amount,
        status=BurnTxStatus.CONFIRMED,
    )
    db.session.add(b)
    db.session.commit()
    return b


def make_attempt(round_, player, burn, message="please", status=AttemptStatus.PAYMENT_CONFIRMED):
    a = Attempt(
        round_id=round_.id,
        player_id=player.id,
        burn_transaction_id=burn.id,
        message=message,
        status=status,
    )
    db.session.add(a)
    db.session.commit()
    return a


# ---- happy path ----------------------------------------------------------


def test_full_happy_path_insert(app):
    """Round -> Player -> Burn -> Attempt -> AIResponse -> Payout, all linked."""
    r = make_round()
    p = make_player()
    b = make_burn(r, "0xtxhash1")
    a = make_attempt(r, p, b)

    resp = AIResponse(
        attempt_id=a.id,
        model_used="minimax",
        prompt_sent="system+user prompt",
        raw_response="Nice try, but no.",
        is_match=False,
    )
    db.session.add(resp)
    a.status = AttemptStatus.LOST
    db.session.add(
        AttemptStatusHistory(
            attempt_id=a.id,
            from_status=AttemptStatus.PAYMENT_CONFIRMED,
            to_status=AttemptStatus.LOST,
            note="verdict engine: no code match",
        )
    )
    db.session.commit()

    assert a.ai_response.is_match is False
    assert a.status_history[0].to_status == AttemptStatus.LOST

    # Now simulate a winning attempt with a payout.
    b2 = make_burn(r, "0xtxhash2")
    a2 = make_attempt(r, p, b2)
    a2.status = AttemptStatus.WON
    db.session.commit()

    payout = PayoutTransaction(
        round_id=r.id,
        attempt_id=a2.id,
        wallet_address=p.wallet_address,
        asset_token_contract=r.asset_token_contract,
        amount=r.prize_amount,
        status=PayoutStatus.PENDING,
    )
    db.session.add(payout)
    from datetime import datetime, timezone

    r.status = RoundStatus.WON
    r.closed_at = datetime.now(timezone.utc)
    r.winning_attempt_id = a2.id
    db.session.commit()

    assert r.winning_attempt_id == a2.id
    assert a2.payout_transaction.amount == r.prize_amount


# ---- 1 burn = 1 attempt, no reuse ----------------------------------------


def test_burn_tx_hash_must_be_unique(app):
    r = make_round()
    make_burn(r, "0xdup")
    with pytest.raises(IntegrityError):
        make_burn(r, "0xdup")


def test_burn_transaction_cannot_back_two_attempts(app):
    """The core '1 burn = 1 attempt' guarantee."""
    r = make_round()
    p = make_player()
    b = make_burn(r, "0xonceonly")
    make_attempt(r, p, b)

    db.session.rollback()  # clear failed-session state before second try
    second = Attempt(
        round_id=r.id,
        player_id=p.id,
        burn_transaction_id=b.id,  # same burn again
        message="let me try with this burn too",
        status=AttemptStatus.PAYMENT_CONFIRMED,
    )
    db.session.add(second)
    with pytest.raises(IntegrityError):
        db.session.commit()


# ---- idempotent processing / duplicate request handling -------------------


def test_resubmitting_same_tx_hash_is_rejected_not_double_processed(app):
    """Simulates a page-refresh double-submit: the second attempt to
    record the same on-chain tx must fail cleanly so the caller can treat
    it as 'already processed' rather than creating new state."""
    r = make_round()
    make_burn(r, "0xrefresh")
    db.session.rollback()
    with pytest.raises(IntegrityError):
        make_burn(r, "0xrefresh")


# ---- one winner per round, even under a race -------------------------------


def test_only_one_winning_attempt_allowed_per_round(app):
    r = make_round()
    p = make_player()

    b1 = make_burn(r, "0xrace1")
    a1 = make_attempt(r, p, b1)
    a1.status = AttemptStatus.WON
    db.session.commit()

    b2 = make_burn(r, "0xrace2")
    a2 = make_attempt(r, p, b2)  # created before round closure, as the edge case describes
    a2.status = AttemptStatus.WON  # a second "win" tries to land
    with pytest.raises(IntegrityError):
        db.session.commit()

    # The correct application-level handling of that IntegrityError is to
    # roll back and instead set a2.status = LOST_ROUND_CLOSED.
    db.session.rollback()
    a2.status = AttemptStatus.LOST_ROUND_CLOSED
    db.session.commit()
    assert a2.status == AttemptStatus.LOST_ROUND_CLOSED


def test_two_different_rounds_can_each_have_their_own_winner(app):
    """Sanity check that the partial unique index is scoped per-round, not global."""
    r1 = make_round()
    r2 = make_round()
    p = make_player()

    b1 = make_burn(r1, "0xr1")
    a1 = make_attempt(r1, p, b1)
    a1.status = AttemptStatus.WON

    b2 = make_burn(r2, "0xr2")
    a2 = make_attempt(r2, p, b2)
    a2.status = AttemptStatus.WON

    db.session.commit()  # should NOT raise — different rounds
    assert a1.status == AttemptStatus.WON
    assert a2.status == AttemptStatus.WON


# ---- payout guarantees -----------------------------------------------------


def test_payout_round_id_must_be_unique(app):
    """A round can never have two payout rows."""
    r = make_round()
    p = make_player()
    b1 = make_burn(r, "0xpay1")
    a1 = make_attempt(r, p, b1, status=AttemptStatus.WON)

    b2 = make_burn(r, "0xpay2")
    a2 = make_attempt(r, p, b2, status=AttemptStatus.PAYMENT_CONFIRMED)

    db.session.add(
        PayoutTransaction(
            round_id=r.id,
            attempt_id=a1.id,
            wallet_address=p.wallet_address,
            asset_token_contract=r.asset_token_contract,
            amount=r.prize_amount,
        )
    )
    db.session.commit()

    db.session.add(
        PayoutTransaction(
            round_id=r.id,  # same round again
            attempt_id=a2.id,
            wallet_address=p.wallet_address,
            asset_token_contract=r.asset_token_contract,
            amount=r.prize_amount,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()


def test_payout_attempt_id_must_be_unique(app):
    """A single attempt can never be paid out twice."""
    r = make_round()
    p = make_player()
    b1 = make_burn(r, "0xpayattempt1")
    a1 = make_attempt(r, p, b1, status=AttemptStatus.WON)

    db.session.add(
        PayoutTransaction(
            round_id=r.id,
            attempt_id=a1.id,
            wallet_address=p.wallet_address,
            asset_token_contract=r.asset_token_contract,
            amount=r.prize_amount,
        )
    )
    db.session.commit()

    db.session.rollback()
    db.session.add(
        PayoutTransaction(
            round_id=make_round().id,  # different round, but same attempt
            attempt_id=a1.id,
            wallet_address=p.wallet_address,
            asset_token_contract=r.asset_token_contract,
            amount=r.prize_amount,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()


# ---- data sanity / CHECK constraints ---------------------------------------


def test_round_prize_amount_must_be_positive(app):
    with pytest.raises(IntegrityError):
        make_round(prize_amount="0")


def test_burn_amount_must_be_positive(app):
    r = make_round()
    with pytest.raises(IntegrityError):
        make_burn(r, "0xzero", amount="0")


def test_wallet_address_uniqueness_on_player(app):
    make_player("0xsame")
    db.session.rollback()
    with pytest.raises(IntegrityError):
        make_player("0xsame")


# ---- pending/processing/completed/failed attempt states -------------------


def test_attempt_status_transitions_and_history_audit_trail(app):
    r = make_round()
    p = make_player()
    b = make_burn(r, "0xhistory")
    a = make_attempt(r, p, b, status=AttemptStatus.PENDING_PAYMENT)

    transitions = [
        (None, AttemptStatus.PENDING_PAYMENT),
        (AttemptStatus.PENDING_PAYMENT, AttemptStatus.PAYMENT_CONFIRMED),
        (AttemptStatus.PAYMENT_CONFIRMED, AttemptStatus.AI_REQUEST_IN_PROGRESS),
        (AttemptStatus.AI_REQUEST_IN_PROGRESS, AttemptStatus.AI_REQUEST_FAILED),
        (AttemptStatus.AI_REQUEST_FAILED, AttemptStatus.AI_REQUEST_IN_PROGRESS),
        (AttemptStatus.AI_REQUEST_IN_PROGRESS, AttemptStatus.EVALUATING),
        (AttemptStatus.EVALUATING, AttemptStatus.WON),
        (AttemptStatus.WON, AttemptStatus.PAYOUT_PENDING),
        (AttemptStatus.PAYOUT_PENDING, AttemptStatus.PAYOUT_FAILED),
        (AttemptStatus.PAYOUT_FAILED, AttemptStatus.PAYOUT_PENDING),
        (AttemptStatus.PAYOUT_PENDING, AttemptStatus.PAYOUT_COMPLETED),
    ]
    for from_status, to_status in transitions:
        a.status = to_status
        db.session.add(AttemptStatusHistory(attempt_id=a.id, from_status=from_status, to_status=to_status))
    db.session.commit()

    assert len(a.status_history) == len(transitions)
    assert a.status_history[-1].to_status == AttemptStatus.PAYOUT_COMPLETED
    assert a.status == AttemptStatus.PAYOUT_COMPLETED


# ---- round closure ----------------------------------------------------------


def test_round_closed_at_consistency_check(app):
    """A round marked non-OPEN without closed_at set should be rejected;
    OPEN rounds must not have closed_at set. Guards against silently
    inconsistent round state."""
    r = make_round()
    r.status = RoundStatus.WON  # no closed_at set
    with pytest.raises(IntegrityError):
        db.session.commit()


def test_round_closure_recorded_correctly(app):
    r = make_round()
    from datetime import datetime, timezone

    r.status = RoundStatus.WON
    r.closed_at = datetime.now(timezone.utc)
    db.session.commit()
    assert r.status == RoundStatus.WON
    assert r.closed_at is not None
