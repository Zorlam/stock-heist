from unittest.mock import Mock, patch

import pytest

from app.services.solana_chain import SolanaBurnVerifier
from app.services.mock_chain import ChainRequestError


RPC_URL = "https://example-solana-rpc.invalid"
PROJECT_MINT = "TestProjectTokenMint"
WALLET = "TestPlayerWallet"
TOKEN_ACCOUNT = "TestTokenAccount"
TX_SIGNATURE = "TestTransactionSignature"


@pytest.fixture
def verifier():
    return SolanaBurnVerifier(
        rpc_url=RPC_URL,
        token_mint=PROJECT_MINT,
    )


def make_transaction(
    *,
    mint=PROJECT_MINT,
    authority=WALLET,
    signer=True,
    amount="2500000",
    decimals=6,
    error=None,
):
    """Build a representative parsed Solana RPC response."""

    return {
        "slot": 12345,
        "transaction": {
            "signatures": [TX_SIGNATURE],
            "message": {
                "accountKeys": [
                    {
                        "pubkey": WALLET,
                        "signer": signer,
                        "writable": True,
                    },
                    {
                        "pubkey": TOKEN_ACCOUNT,
                        "signer": False,
                        "writable": True,
                    },
                ],
                "instructions": [
                    {
                        "program": "spl-token",
                        "parsed": {
                            "type": "burnChecked",
                            "info": {
                                "account": TOKEN_ACCOUNT,
                                "mint": mint,
                                "authority": authority,
                                "amount": amount,
                                "decimals": decimals,
                            },
                        },
                    }
                ],
            },
        },
        "meta": {
            "err": error,
            "preTokenBalances": [],
            "innerInstructions": [],
        },
    }


def mock_rpc(transaction):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": transaction,
    }
    return response


def test_valid_burn_returns_verified_details(verifier):
    transaction = make_transaction()

    with patch(
        "app.services.solana_chain.requests.post",
        return_value=mock_rpc(transaction),
    ) as post:
        result = verifier.get_burn(TX_SIGNATURE)

    assert result == {
        "wallet_address": WALLET,
        "token_contract": PROJECT_MINT,
        "amount": "2.5",
        "block_number": 12345,
    }

    # Ensure the verifier requests finalized transaction data.
    params = post.call_args.kwargs["json"]["params"]
    assert params[0] == TX_SIGNATURE
    assert params[1]["commitment"] == "finalized"
    assert params[1]["encoding"] == "jsonParsed"


def test_failed_transaction_is_rejected(verifier):
    transaction = make_transaction(
        error={"InstructionError": [0, "Custom"]},
    )

    with patch(
        "app.services.solana_chain.requests.post",
        return_value=mock_rpc(transaction),
    ):
        assert verifier.get_burn(TX_SIGNATURE) is None


def test_wrong_token_mint_is_rejected(verifier):
    transaction = make_transaction(mint="DifferentTokenMint")

    with patch(
        "app.services.solana_chain.requests.post",
        return_value=mock_rpc(transaction),
    ):
        assert verifier.get_burn(TX_SIGNATURE) is None


def test_unsigned_burn_authority_is_rejected(verifier):
    transaction = make_transaction(signer=False)

    with patch(
        "app.services.solana_chain.requests.post",
        return_value=mock_rpc(transaction),
    ):
        assert verifier.get_burn(TX_SIGNATURE) is None


def test_missing_transaction_is_rejected(verifier):
    with patch(
        "app.services.solana_chain.requests.post",
        return_value=mock_rpc(None),
    ):
        assert verifier.get_burn(TX_SIGNATURE) is None


def test_rpc_error_raises_chain_request_error(verifier):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "Invalid params"},
    }

    with patch(
        "app.services.solana_chain.requests.post",
        return_value=response,
    ):
        with pytest.raises(ChainRequestError):
            verifier.get_burn(TX_SIGNATURE)


def test_zero_amount_burn_is_rejected(verifier):
    transaction = make_transaction(amount="0")

    with patch(
        "app.services.solana_chain.requests.post",
        return_value=mock_rpc(transaction),
    ):
        assert verifier.get_burn(TX_SIGNATURE) is None