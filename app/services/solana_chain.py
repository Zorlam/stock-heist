import os
from decimal import Decimal

import requests

from app.services.mock_chain import ChainRequestError


class SolanaBurnVerifier:
    """Verify SPL token burns using finalized Solana transaction data."""

    TOKEN_PROGRAMS = {"spl-token", "spl-token-2022"}
    BURN_TYPES = {"burn", "burnChecked"}

    def __init__(self, rpc_url=None, token_mint=None, timeout=15):
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
        """Send a JSON-RPC request to Solana."""

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
            raise ChainRequestError("Invalid Solana RPC response")

        if payload.get("error"):
            raise ChainRequestError(
                f"Solana RPC error: {payload['error']}"
            )

        if "result" not in payload:
            raise ChainRequestError("Solana RPC response has no result")

        return payload["result"]

    def get_burn(self, tx_hash):
        """
        Return verified burn details, or None if no qualifying burn exists.

        Returned fields match the existing game_service.py interface.
        """

        if not isinstance(tx_hash, str) or not tx_hash.strip():
            return None

        transaction = self._rpc_call(
            "getTransaction",
            [
                tx_hash.strip(),
                {
                    "encoding": "jsonParsed",
                    "commitment": "finalized",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )

        if transaction is None:
            return None

        meta = transaction.get("meta")

        if not isinstance(meta, dict) or meta.get("err") is not None:
            return None

        slot = transaction.get("slot")
        if not isinstance(slot, int):
            return None

        message = transaction.get("transaction", {}).get(
            "message", {}
        )
        account_keys = message.get("accountKeys", [])

        # Identify accounts that signed the transaction.
        signers = set()

        for key in account_keys:
            if isinstance(key, dict) and key.get("signer") is True:
                signers.add(key.get("pubkey"))

        # Associate token accounts with their pre-transaction mint.
        pre_balances = {}

        for balance in meta.get("preTokenBalances") or []:
            index = balance.get("accountIndex")
            mint = balance.get("mint")
            token_amount = balance.get("uiTokenAmount") or {}

            try:
                decimals = int(token_amount["decimals"])
            except (KeyError, TypeError, ValueError):
                continue

            if index is not None and mint:
                pre_balances[index] = (mint, decimals)

        instructions = list(message.get("instructions") or [])

        for group in meta.get("innerInstructions") or []:
            instructions.extend(group.get("instructions") or [])

        burns = {}

        for instruction in instructions:
            if not isinstance(instruction, dict):
                continue

            if instruction.get("program") not in self.TOKEN_PROGRAMS:
                continue

            parsed = instruction.get("parsed")

            if not isinstance(parsed, dict):
                continue

            if parsed.get("type") not in self.BURN_TYPES:
                continue

            info = parsed.get("info")

            if not isinstance(info, dict):
                continue

            token_account = info.get("account")
            authority = info.get("authority")

            if not isinstance(token_account, str):
                continue

            if not isinstance(authority, str) or authority not in signers:
                continue

            try:
                raw_amount = int(info["amount"])
            except (KeyError, TypeError, ValueError):
                continue

            if raw_amount <= 0:
                continue

            mint = info.get("mint")
            decimals = info.get("decimals")

            # Ordinary Burn may omit the mint and decimals.
            if mint is None or decimals is None:
                account_index = next(
                    (
                        index
                        for index, key in enumerate(account_keys)
                        if (
                            key.get("pubkey") == token_account
                            if isinstance(key, dict)
                            else key == token_account
                        )
                    ),
                    None,
                )

                if account_index is None:
                    continue

                balance_info = pre_balances.get(account_index)

                if balance_info is None:
                    continue

                mint, decimals = balance_info

            try:
                decimals = int(decimals)
            except (TypeError, ValueError):
                continue

            if not 0 <= decimals <= 18:
                continue

            if mint != self.token_mint:
                continue

            key = (authority, mint, decimals)
            burns[key] = burns.get(key, 0) + raw_amount

        # Avoid ambiguous transactions involving multiple burn authorities.
        if len(burns) != 1:
            return None

        (wallet, mint, decimals), raw_total = next(iter(burns.items()))

        amount = Decimal(raw_total) / (Decimal(10) ** decimals)

        return {
            "wallet_address": wallet,
            "token_contract": mint,
            "amount": format(amount, "f"),
            "block_number": slot,
        }