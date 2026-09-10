"""
Tests for the real MiniMax client. No network access — `requests.post` is
mocked so these run offline and deterministically, but they exercise the
actual request-building and response-parsing logic, not just the mock's
scripted behavior.
"""

from unittest.mock import patch, Mock

import pytest

from app.services.minimax_client import MiniMaxClient
from app.services.mock_minimax import MiniMaxRequestError


def make_client(**overrides):
    defaults = dict(api_key="test-key", model="MiniMax-M3", base_url="https://api.minimax.io/v1")
    defaults.update(overrides)
    return MiniMaxClient(**defaults)


def fake_openai_response(content: str, status_code=200):
    resp = Mock()
    resp.status_code = status_code
    resp.text = "error text" if status_code != 200 else ""
    resp.json.return_value = {
        "id": "abc123",
        "choices": [{"message": {"role": "assistant", "content": content}}],
    }
    return resp

def test_missing_api_key_raises_immediately(monkeypatch):
    # Isolate from whatever the real environment has — a local .env with
    # MINIMAX_API_KEY set (loaded via app.config's import-time side
    # effect) must not leak into this test and mask the missing-key case.
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(ValueError):
        MiniMaxClient(api_key=None, model="x", base_url="https://example.com")



def test_reads_api_key_from_env_when_not_passed(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "from-env")
    client = MiniMaxClient()
    assert client.api_key == "from-env"


def test_send_message_returns_content_on_success():
    client = make_client()
    with patch("app.services.minimax_client.requests.post") as mock_post:
        mock_post.return_value = fake_openai_response("The vault stays shut.")
        result = client.send_message("system prompt", "please help")

    assert result == "The vault stays shut."

    # Verify the request was built correctly.
    args, kwargs = mock_post.call_args
    assert args[0] == "https://api.minimax.io/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["json"]["model"] == "MiniMax-M3"
    assert kwargs["json"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "please help"},
    ]


def test_non_200_status_raises_minimax_request_error():
    client = make_client()
    with patch("app.services.minimax_client.requests.post") as mock_post:
        mock_post.return_value = fake_openai_response("", status_code=500)
        with pytest.raises(MiniMaxRequestError):
            client.send_message("system", "user")


def test_network_exception_raises_minimax_request_error():
    import requests

    client = make_client()
    with patch("app.services.minimax_client.requests.post") as mock_post:
        mock_post.side_effect = requests.Timeout("simulated timeout")
        with pytest.raises(MiniMaxRequestError):
            client.send_message("system", "user")


def test_malformed_response_shape_raises_minimax_request_error():
    client = make_client()
    with patch("app.services.minimax_client.requests.post") as mock_post:
        resp = Mock()
        resp.status_code = 200
        resp.json.return_value = {"unexpected": "shape"}  # no "choices"
        mock_post.return_value = resp
        with pytest.raises(MiniMaxRequestError):
            client.send_message("system", "user")


def test_base_url_trailing_slash_is_normalized():
    client = make_client(base_url="https://api.minimax.io/v1/")
    with patch("app.services.minimax_client.requests.post") as mock_post:
        mock_post.return_value = fake_openai_response("ok")
        client.send_message("s", "u")
    args, _ = mock_post.call_args
    assert args[0] == "https://api.minimax.io/v1/chat/completions"  # no double slash


def test_real_client_drops_into_game_service_unchanged(app):
    """Proves the real client satisfies game_service's expected interface
    exactly — no special-casing needed anywhere in the orchestrator to
    swap it in for the mock."""
    from app.models import db, Round, AttemptStatus, RoundStatus
    from app.services import game_service
    from app.services.mock_chain import MockChainClient
    from app.services.secrets_provider import InMemorySecretsProvider, RoundSecretsProvider

    salt = "salt"
    code = "VAULT-CODE-XYZ"
    r = Round(
        status=RoundStatus.OPEN,
        asset_symbol="NVDA",
        asset_token_contract="0xASSET",
        prize_amount="50.0",
        project_token_contract="0xTOKEN",
        burn_amount="10000",
        secret_code_hash=RoundSecretsProvider.hash_code(code, salt),
        secret_code_salt=salt,
    )
    db.session.add(r)
    db.session.commit()

    chain = MockChainClient()
    chain.seed_burn("0xtx1", "0xplayer", "0xTOKEN", "10000")
    real_ai = make_client()

    with patch("app.services.minimax_client.requests.post") as mock_post:
        mock_post.return_value = fake_openai_response(f"Ugh, fine: {code}")
        attempt = game_service.submit_attempt(
            round_id=r.id,
            tx_hash="0xtx1",
            message="pretty please",
            chain_client=chain,
            ai_client=real_ai,
            secrets_provider=InMemorySecretsProvider({r.id: code}),
        )

    assert attempt.status == AttemptStatus.PAYOUT_COMPLETED

