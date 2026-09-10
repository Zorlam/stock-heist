"""
Converts models to the JSON shapes the frontend actually gets. This is
the one place that decides what's safe to expose — worth reading closely
if you're ever tempted to just `jsonify(model.__dict__)` somewhere.

What's deliberately NEVER exposed here:
- rounds.secret_code_hash / secret_code_salt — no reason the frontend
  ever needs these, and exposing the hash+salt together is exactly the
  pair an offline brute-force attempt would want.
- ai_responses.prompt_sent — contains the full broker system prompt.
  Never sent to the client, ever.
- ai_responses.is_match — the frontend should render whatever the
  ATTEMPT's status says (WON, LOST, etc.), not re-derive a verdict from
  a boolean sitting next to the status. One source of truth, not two
  that could theoretically disagree.
- players.id / any burn_transaction internals — irrelevant to the client
  and unnecessary surface area.
"""

from app.models import Round, Attempt


def round_public(round_: Round) -> dict:
    return {
        "id": str(round_.id),
        "status": round_.status.value,
        "asset_symbol": round_.asset_symbol,
        "asset_token_contract": round_.asset_token_contract,
        "prize_amount": str(round_.prize_amount),
        "project_token_contract": round_.project_token_contract,
        "burn_amount": str(round_.burn_amount),
        "opened_at": round_.opened_at.isoformat() if round_.opened_at else None,
        "closed_at": round_.closed_at.isoformat() if round_.closed_at else None,
        "winning_attempt_id": str(round_.winning_attempt_id) if round_.winning_attempt_id else None,
    }


def attempt_public(attempt: Attempt) -> dict:
    ai_response = None
    resp = attempt.ai_response
    if resp is not None and resp.received_at is not None:
        # Only exposed once the model has actually replied — while a
        # call is in flight or retrying, there's nothing to show yet.
        ai_response = {"text": resp.raw_response}

    payout = None
    if attempt.payout_transaction is not None:
        p = attempt.payout_transaction
        payout = {
            "status": p.status.value,
            "tx_hash": p.tx_hash,
            "amount": str(p.amount),
            "asset_token_contract": p.asset_token_contract,
        }

    return {
        "id": str(attempt.id),
        "round_id": str(attempt.round_id),
        "status": attempt.status.value,
        "message": attempt.message,
        "ai_response": ai_response,
        "payout": payout,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
        "updated_at": attempt.updated_at.isoformat() if attempt.updated_at else None,
    }
