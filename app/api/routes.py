"""
The HTTP surface for the 3D frontend.

Player-facing routes (what the real client uses):
    GET  /api/rounds/active        -> current open round's vault info
    GET  /api/rounds/<id>          -> any round's info (for showing a past/won round)
    POST /api/attempts             -> submit a burn + message, get the attempt back
    GET  /api/attempts/<id>        -> poll an attempt's current status

Dev-only admin routes (see the warning block below — NOT for the real
client, exist purely to let frontend development happen without a real
wallet, real chain, or real AI calls):
    POST /api/admin/rounds
    POST /api/admin/burns/seed
    POST /api/admin/ai/queue-response

Every route here is a thin wrapper: parse the request, call into
game_service or the models directly for reads, serialize the result.
No game logic lives in this file — see game_service.py for that.
"""

import os

from flask import Blueprint, current_app, jsonify, request

from app.api.serializers import attempt_public, round_public
from app.models import Attempt, Round, RoundStatus, db
from app.runtime import get_runtime
from app.services import game_service
from app.services.mock_minimax import MockMiniMaxClient
from app.services.secrets_provider import RoundSecretsProvider

api = Blueprint("api", __name__, url_prefix="/api")


# =============================================================================
# Player-facing routes
# =============================================================================


@api.get("/rounds/active")
def get_active_round():
    round_ = (
        Round.query.filter_by(status=RoundStatus.OPEN)
        .order_by(Round.opened_at.desc())
        .first()
    )
    if round_ is None:
        return jsonify({"error": "no active round"}), 404
    return jsonify(round_public(round_))


@api.get("/rounds/<round_id>")
def get_round(round_id):
    round_ = db.session.get(Round, round_id)
    if round_ is None:
        return jsonify({"error": "round not found"}), 404
    return jsonify(round_public(round_))


@api.post("/attempts")
def create_attempt():
    """Submit a claimed burn + message. Synchronous for now: this call
    blocks until the AI has responded and, if it's a win, until the
    (mock) payout has settled — matching how game_service.submit_attempt
    itself works today (see its module docstring for why the round lock
    is scoped narrowly rather than held across this). If/when a
    background worker exists, this becomes "202 Accepted, poll
    GET /api/attempts/<id>" instead of blocking — worth knowing now if
    the frontend is choosing between a blocking-fetch UI and a
    poll-from-the-start UI, since the latter survives that change for
    free and the former doesn't.
    """
    data = request.get_json(silent=True) or {}
    round_id = data.get("round_id")
    tx_hash = data.get("tx_hash")
    message = data.get("message")

    if not round_id or not tx_hash or not message:
        return jsonify({"error": "round_id, tx_hash, and message are all required"}), 400
    if not isinstance(message, str) or len(message) > 2000:
        return jsonify({"error": "message must be a string of 2000 characters or fewer"}), 400

    runtime = get_runtime()
    try:
        attempt = game_service.submit_attempt(
            round_id=round_id,
            tx_hash=tx_hash,
            message=message,
            chain_client=runtime.chain_client,
            ai_client=runtime.ai_client,
            secrets_provider=runtime.secrets_provider,
        )
    except game_service.PaymentVerificationFailedError as exc:
        return jsonify({"error": str(exc)}), 402
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception:
        current_app.logger.exception("submit_attempt failed")
        return jsonify({"error": "internal error processing attempt"}), 500

    return jsonify(attempt_public(attempt)), 201


@api.get("/attempts/<attempt_id>")
def get_attempt(attempt_id):
    attempt = db.session.get(Attempt, attempt_id)
    if attempt is None:
        return jsonify({"error": "attempt not found"}), 404
    return jsonify(attempt_public(attempt))


# =============================================================================
# Dev-only admin routes
#
# THESE ARE NOT PART OF THE REAL PRODUCT SURFACE. They exist so a
# frontend developer can create a round, simulate a burn, and script a
# specific broker reply, entirely without a real wallet, real chain
# access, or spending real MiniMax API calls — i.e. so the 3D client can
# be built and tested end-to-end before the still-open blockchain
# questions are resolved and before every UI iteration needs a live AI
# call.
#
# They must be disabled or removed entirely before any real deployment.
# Gated behind ENABLE_DEV_ADMIN_ROUTES (default True right now, because
# there's no production deployment yet) — flip this to False, or delete
# this whole section, before that changes. There is no authentication on
# these routes; anyone who can reach them can create rounds and fabricate
# wins. Do not expose this app to the public internet with this flag on.
# =============================================================================


def _dev_routes_guard():
    if not current_app.config.get("ENABLE_DEV_ADMIN_ROUTES", True):
        return jsonify({"error": "not found"}), 404
    return None


@api.post("/admin/rounds")
def admin_create_round():
    guard = _dev_routes_guard()
    if guard:
        return guard

    data = request.get_json(silent=True) or {}
    required = [
        "asset_symbol",
        "asset_token_contract",
        "prize_amount",
        "project_token_contract",
        "burn_amount",
        "secret_code",
    ]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"missing required fields: {missing}"}), 400

    salt = os.urandom(16).hex()
    round_ = Round(
        status=RoundStatus.OPEN,
        asset_symbol=data["asset_symbol"],
        asset_token_contract=data["asset_token_contract"],
        prize_amount=data["prize_amount"],
        project_token_contract=data["project_token_contract"],
        burn_amount=data["burn_amount"],
        secret_code_hash=RoundSecretsProvider.hash_code(data["secret_code"], salt),
        secret_code_salt=salt,
    )
    db.session.add(round_)
    db.session.commit()

    get_runtime().secrets_provider.add_code(round_.id, data["secret_code"])

    return jsonify(round_public(round_)), 201


@api.post("/admin/burns/seed")
def admin_seed_burn():
    """Simulate a burn transaction existing on-chain, for the mock chain
    client. Stands in for a real wallet actually broadcasting a burn."""
    guard = _dev_routes_guard()
    if guard:
        return guard

    data = request.get_json(silent=True) or {}
    required = ["tx_hash", "wallet_address", "token_contract", "amount"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"missing required fields: {missing}"}), 400

    get_runtime().chain_client.seed_burn(
        tx_hash=data["tx_hash"],
        wallet_address=data["wallet_address"],
        token_contract=data["token_contract"],
        amount=data["amount"],
    )
    return jsonify({"ok": True}), 201


@api.post("/admin/ai/queue-response")
def admin_queue_ai_response():
    """Script the next broker reply, so the frontend can be driven
    through a win or a loss deliberately (e.g. for demoing the vault-
    opening animation) without needing a real AI call. Only works when
    the app is configured with the mock AI client (AI_CLIENT=mock, the
    default) — there is no equivalent for the real client, by design."""
    guard = _dev_routes_guard()
    if guard:
        return guard

    runtime = get_runtime()
    if not isinstance(runtime.ai_client, MockMiniMaxClient):
        return (
            jsonify({"error": "AI client is not the mock — this endpoint only works with AI_CLIENT=mock"}),
            400,
        )

    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if not text:
        return jsonify({"error": "text is required"}), 400

    runtime.ai_client.queue_response(text)
    return jsonify({"ok": True}), 201
