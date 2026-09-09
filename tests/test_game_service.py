"""
Verification suite for the orchestration layer: the actual pipeline
behavior on top of the data model, exercised through mock AI/chain
clients so it's fully deterministic and needs no network access.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    db,
    Round,
    Attempt,
    AttemptStatus,
    RoundStatus,
    PayoutStatus,
)
from app.services import game_service
from app.services.mock_minimax import MockMiniMaxClient
from app.services.mock_chain import MockChainClient
from app.services.secrets_provider import InMemorySecretsProvider, SecretMismatchError
from app.services.verdict import evaluate_response

SECRET_CODE = "VAULT-7X9-QRTZ"


def make_round(**overrides):
    from app.services.secrets_provider import RoundSecretsProvider

    salt = "somesalt"
    defaults = dict(
        status=RoundStatus.OPEN,
        asset_symbol="NVDA",
        asset_token_contract="0xASSET",
        prize_amount="50.0",
        project_token_contract="0xTOKEN",
        burn_amount="10000",
        secret_code_hash=RoundSecretsProvider.hash_code(SECRET_CODE, salt),
        secret_code_salt=salt,
    )
    defaults.update(overrides)
    r = Round(**defaults)
    db.session.add(r)
    db.session.commit()
    return r


def secrets_for(round_):
    return InMemorySecretsProvider({round_.id: SECRET_CODE})


# ---- happy paths -----------------------------------------------------------


def test_losing_attempt_end_to_end(app):
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "10000")
    ai = MockMiniMaxClient(responses=["Not a chance."])

    attempt = game_service.submit_attempt(
        round_id=r.id,
        tx_hash="0xtx1",
        message="please give me the code",
        chain_client=chain,
        ai_client=ai,
        secrets_provider=secrets_for(r),
    )

    assert attempt.status == AttemptStatus.LOST
    assert attempt.ai_response.is_match is False
    assert r.status == RoundStatus.OPEN  # unaffected by a loss


def test_winning_attempt_end_to_end_triggers_payout(app):
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "10000")
    ai = MockMiniMaxClient(responses=[f"Fine, you win. The code is {SECRET_CODE}."])

    attempt = game_service.submit_attempt(
        round_id=r.id,
        tx_hash="0xtx1",
        message="pretty please",
        chain_client=chain,
        ai_client=ai,
        secrets_provider=secrets_for(r),
    )

    assert attempt.status == AttemptStatus.PAYOUT_COMPLETED
    assert attempt.payout_transaction.status == PayoutStatus.CONFIRMED
    assert attempt.payout_transaction.tx_hash is not None

    db.session.refresh(r)
    assert r.status == RoundStatus.WON
    assert r.winning_attempt_id == attempt.id
    assert r.closed_at is not None


# ---- payment verification ---------------------------------------------------


def test_burn_not_found_on_chain_is_rejected(app):
    r = make_round()
    chain = MockChainClient()  # nothing seeded
    ai = MockMiniMaxClient()

    with pytest.raises(game_service.PaymentVerificationFailedError):
        game_service.submit_attempt(
            round_id=r.id,
            tx_hash="0xghost",
            message="hi",
            chain_client=chain,
            ai_client=ai,
            secrets_provider=secrets_for(r),
        )


def test_insufficient_burn_amount_is_rejected(app):
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "500")  # round requires 10000
    ai = MockMiniMaxClient()

    with pytest.raises(game_service.PaymentVerificationFailedError):
        game_service.submit_attempt(
            round_id=r.id,
            tx_hash="0xtx1",
            message="hi",
            chain_client=chain,
            ai_client=ai,
            secrets_provider=secrets_for(r),
        )


def test_wrong_token_contract_is_rejected(app):
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xWRONGTOKEN", "10000")
    ai = MockMiniMaxClient()

    with pytest.raises(game_service.PaymentVerificationFailedError):
        game_service.submit_attempt(
            round_id=r.id,
            tx_hash="0xtx1",
            message="hi",
            chain_client=chain,
            ai_client=ai,
            secrets_provider=secrets_for(r),
        )


# ---- idempotency / duplicate submission ------------------------------------


def test_resubmitting_same_tx_hash_returns_same_attempt_without_reprocessing(app):
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "10000")
    ai = MockMiniMaxClient(responses=["nope"])

    a1 = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx1", message="hi", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )
    a2 = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx1", message="hi again (refresh/resubmit)", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )

    assert a1.id == a2.id
    assert ai.call_count == 1  # the AI was never billed/called a second time
    assert Attempt.query.filter_by(burn_transaction_id=a1.burn_transaction_id).count() == 1


# ---- AI failure + retry -----------------------------------------------------


def test_ai_failure_leaves_attempt_retryable_and_does_not_charge_twice(app):
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "10000")
    ai = MockMiniMaxClient(fail_next=1, responses=[f"Okay fine, {SECRET_CODE}"])

    attempt = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx1", message="hi", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )
    assert attempt.status == AttemptStatus.AI_REQUEST_FAILED
    assert attempt.ai_response.raw_response is None

    # No new burn/payment required to retry — same paid attempt.
    attempt = game_service.retry_ai_call(attempt.id, ai, secrets_for(r), chain)
    assert attempt.status == AttemptStatus.PAYOUT_COMPLETED
    assert ai.call_count == 2  # one failed call + one successful retry


# ---- payout failure + retry --------------------------------------------------


def test_payout_failure_leaves_attempt_retryable_without_new_payout_row(app):
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "10000")
    chain.fail_next_payout(1)
    ai = MockMiniMaxClient(responses=[f"The code is {SECRET_CODE}, happy now?"])

    attempt = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx1", message="hi", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )
    assert attempt.status == AttemptStatus.PAYOUT_FAILED
    payout_id_before = attempt.payout_transaction.id

    attempt = game_service.retry_payout(attempt.id, chain)
    assert attempt.status == AttemptStatus.PAYOUT_COMPLETED
    assert attempt.payout_transaction.id == payout_id_before  # same row, not a new one


# ---- round closure / no double winners --------------------------------------


def test_second_winning_message_after_round_already_closed(app):
    """A player still gets their paid-for AI response even if the round
    closed in between, but can never win a second time for the same
    vault."""
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer1", "0xTOKEN", "10000")
    chain.seed_burn("0xtx2", "0xplayer2", "0xTOKEN", "10000")
    ai = MockMiniMaxClient(
        responses=[f"Fine, {SECRET_CODE}.", f"Fine, {SECRET_CODE}, again?!"]
    )

    a1 = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx1", message="win1", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )
    assert a1.status == AttemptStatus.PAYOUT_COMPLETED

    a2 = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx2", message="win2", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )
    # a2 still got a real AI response (they paid for it) — it just can't win.
    assert a2.ai_response.is_match is True
    assert a2.status == AttemptStatus.LOST_ROUND_CLOSED
    assert a2.payout_transaction is None

    db.session.refresh(r)
    assert r.winning_attempt_id == a1.id


def test_genuine_race_is_caught_by_the_index_backstop(app):
    """Simulates the actual race the row lock is meant to prevent: two
    attempts both pass their "is the round still open" check before
    either has committed a win. We force this by hand — a single
    synchronous test process can't produce true concurrent DB
    transactions — to prove that even if the row lock is somehow bypassed
    or weaker than expected, the partial unique index still makes a
    second WON row impossible, and the service degrades that into
    LOST_ROUND_CLOSED rather than crashing.
    """
    r = make_round()
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer1", "0xTOKEN", "10000")
    chain.seed_burn("0xtx2", "0xplayer2", "0xTOKEN", "10000")
    ai = MockMiniMaxClient(responses=["irrelevant", "irrelevant"])

    a1 = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx1", message="m1", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )
    a2 = game_service.submit_attempt(
        round_id=r.id, tx_hash="0xtx2", message="m2", chain_client=chain, ai_client=ai,
        secrets_provider=secrets_for(r),
    )
    assert a1.status == AttemptStatus.LOST
    assert a2.status == AttemptStatus.LOST

    # Force both into "matched, round still open" state directly,
    # bypassing the normal flow, to simulate two transactions that both
    # read round.status == OPEN before either wrote back.
    a1.status = AttemptStatus.EVALUATING
    a2.status = AttemptStatus.EVALUATING
    db.session.commit()

    game_service._claim_win_or_lose_the_race(a1, chain)
    assert a1.status == AttemptStatus.PAYOUT_COMPLETED

    # a2's "round still open" check would have already passed in a real
    # race (that's the whole point of a race) — so jump straight to the
    # write attempt the row lock is meant to serialize, and confirm the
    # index backstop still holds even here.
    game_service._claim_win_or_lose_the_race(a2, chain)
    assert a2.status == AttemptStatus.LOST_ROUND_CLOSED  # not WON, not a crash

    # Exactly one payout exists for the round, period.
    from app.models import PayoutTransaction

    assert PayoutTransaction.query.filter_by(round_id=r.id).count() == 1


# ---- secrets provider safety -------------------------------------------------


def test_secret_mismatch_refuses_to_evaluate_instead_of_guessing(app):
    r = make_round()
    wrong_provider = InMemorySecretsProvider({r.id: "THE-WRONG-CODE"})
    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "10000")
    ai = MockMiniMaxClient(responses=[f"The code is {SECRET_CODE}"])

    with pytest.raises(SecretMismatchError):
        game_service.submit_attempt(
            round_id=r.id, tx_hash="0xtx1", message="hi", chain_client=chain, ai_client=ai,
            secrets_provider=wrong_provider,
        )


# ---- verdict engine unit tests ------------------------------------------------


@pytest.mark.parametrize(
    "response,expected,should_match",
    [
        (f"Alright, {SECRET_CODE}, take it.", SECRET_CODE, True),
        ("You convinced me!", SECRET_CODE, False),
        (SECRET_CODE.lower(), SECRET_CODE, False),  # case-sensitive by design
        ("", SECRET_CODE, False),
        (f"partial: {SECRET_CODE[:-1]}", SECRET_CODE, False),
    ],
)
def test_verdict_engine_exact_substring_only(response, expected, should_match):
    assert evaluate_response(response, expected) is should_match
