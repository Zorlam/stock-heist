import os
from decimal import Decimal, InvalidOperation

import requests

from app.services.mock_chain import ChainRequestError

class SolanaBurnVerifier:
"""
Verifies SPL token burns using finalized Solana transaction data.

```
This verifier does not submit payouts and does not replace the existing
mock chain client. It can be integrated into the runtime separately
after its behavior has been tested.
"""

TOKEN_PROGRAMS = {"spl-token", "spl-token-2022"}
BURN_INSTRUCTION_TYPES = {"burn", "burnChecked"}

def __init__(
    self,
    rpc_url=None,
    token_mint=None,
    timeout=15,
):
    self.rpc_url = rpc_url or os.environ.get("SOLANA_RPC_URL")
    self.token_mint = token_mint or os.environ.get(
        "PROJECT_TOKEN_MINT"
    )
    self.timeout = timeout

    if not self.rpc_url:
        raise ValueError("SOLANA_RPC_URL is not configured")

    if not self.token_mint:
        raise ValueError("PROJECT_TOKEN_MINT is not configured")

def _rpc_call(self, method, params):
    """Send a JSON-RPC request to the configured Solana endpoint."""

    try:
        response = requests.post(
            self.rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()

    except (requests.RequestException, ValueError) as exc:
        raise ChainRequestError(
            f"Solana RPC request failed: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ChainRequestError(
            "Solana RPC returned an invalid response"
        )

    if payload.get("error"):
        raise ChainRequestError(
            f"Solana RPC error: {payload['error']}"
        )

    if "result" not in payload:
        raise ChainRequestError(
            "Solana RPC response has no result"
        )

    return payload["result"]

@staticmethod
def _account_keys(transaction):
    """Return transaction account keys as a list of public keys."""

    message = transaction.get("transaction", {}).get("message", {})
    keys = message.get("accountKeys", [])

    return [
        key.get("pubkey") if isinstance(key, dict) else key
        for key in keys
    ]

@staticmethod
def _token_balances_by_account(transaction):
    """
    Map token-account indexes to their pre-transaction token balances.

    This allows us to identify the mint for an ordinary SPL Burn
    instruction, which may not include the mint in its parsed info.
    """

    meta = transaction.get("meta") or {}
    balances = {}

    for entry in meta.get("preTokenBalances") or []:
        account_index = entry.get("accountIndex")
        mint = entry.get("mint")
        token_amount = entry.get("uiTokenAmount") or {}

        if account_index is None or not mint:
            continue

        try:
            decimals = int(token_amount["decimals"])
        except (KeyError, TypeError, ValueError):
            continue

        balances[account_index] = {
            "mint": mint,
            "decimals": decimals,
        }

    return balances

@staticmethod
def _instructions(transaction):
    """Yield parsed top-level and inner transaction instructions."""

    meta = transaction.get("meta") or {}
    message = transaction.get("transaction", {}).get(
        "message", {}
    )

    for instruction in message.get("instructions") or []:
        yield instruction

    for group in meta.get("innerInstructions") or []:
        for instruction in group.get("instructions") or []:
            yield instruction

def get_burn(self, tx_hash):
    """
    Verify a finalized transaction and return its actual burn details.

    Returns:
        A dictionary containing wallet_address, token_contract,
        amount, and block_number when a qualifying burn is found.

        None when the transaction is unavailable, failed, or contains
        no qualifying burn of the configured project token.

    Raises:
        ChainRequestError when the RPC request fails.
    """

    if not isinstance(tx_hash, str) or not tx_hash.strip():
        return None

    tx_hash = tx_hash.strip()

    transaction = self._rpc_call(
        "getTransaction",
        [
            tx_hash,
            {
                "encoding": "jsonParsed",
                "commitment": "finalized",
                "maxSupportedTransactionVersion": 0,
            },
        ],
    )

    # A missing result is not proof of a successful transaction.
    if transaction is None:
        return None

    meta = transaction.get("meta")

    # Fail closed if the transaction failed or lacks execution metadata.
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return None

    slot = transaction.get("slot")
    if not isinstance(slot, int):
        return None

    account_keys = self._account_keys(transaction)
    signer_addresses = set()

    message = transaction.get("transaction", {}).get(
        "message", {}
    )

    for key in message.get("accountKeys") or []:
        if isinstance(key, dict) and key.get("signer") is True:
            signer_addresses.add(key.get("pubkey"))

    token_balances = self._token_balances_by_account(transaction)

    # Aggregate matching burns only when they have the same mint
    # and the same transaction-signing authority.
    matching_burns = {}

    for instruction in self._instructions(transaction):
        if not isinstance(instruction, dict):
            continue

        if instruction.get("program") not in self.TOKEN_PROGRAMS:
            continue

        parsed = instruction.get("parsed")
        if not isinstance(parsed, dict):
            continue

        if parsed.get("type") not in self.BURN_INSTRUCTION_TYPES:
            continue

        info = parsed.get("info")
        if not isinstance(info, dict):
            continue

        token_account = info.get("account")
        authority = info.get("authority")
        raw_amount = info.get("amount")

        # Require a known token account and an authority that signed
        # the transaction. This intentionally excludes unsupported
        # multisig/delegate cases until explicitly implemented.
        if (
            not isinstance(token_account, str)
            or not isinstance(authority, str)
            or authority not in signer_addresses
        ):
            continue

        try:
            raw_amount = int(raw_amount)
        except (TypeError, ValueError):
            continue

        if raw_amount <= 0:
            continue

        # BurnChecked provides the mint and decimals directly.
        mint = info.get("mint")
        decimals = info.get("decimals")

        # Ordinary Burn does not necessarily include the mint.
        # Derive it from the token account's pre-transaction balance.
        if mint is None or decimals is None:
            try:
                account_index = account_keys.index(token_account)
            except ValueError:
                continue

            balance_info = token_balances.get(account_index)
            if balance_info is None:
                continue

            mint = balance_info["mint"]
            decimals = balance_info["decimals"]

        try:
            decimals = int(decimals)
        except (TypeError, ValueError):
            continue

        if decimals < 0 or decimals > 18:
            continue

        # Never accept a burn of a different token.
        if mint != self.token_mint:
            continue

        key = (authority, mint, decimals)

        matching_burns[key] = (
            matching_burns.get(key, 0) + raw_amount
        )

    # If qualifying burns were authorized by different wallets or
    # have inconsistent decimals, don't guess which one should count.
    if not matching_burns:
        return None

    if len(matching_burns) != 1:
        return None

    (wallet_address, mint, decimals), raw_total = (
        next(iter(matching_burns.items()))
    )

    try:
        human_amount = Decimal(raw_total) / (
            Decimal(10) ** decimals
        )
    except (InvalidOperation, OverflowError):
        return None

    return {
        "wallet_address": wallet_address,
        "token_contract": mint,
        "amount": format(human_amount, "f"),
        "block_number": slot,
    }
```
