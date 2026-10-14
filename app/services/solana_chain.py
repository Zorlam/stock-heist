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
        self.token_mint = token_mint or os.environ.get("PROJECT_TOKEN_MINT")
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

        if payload.get("error") is not None:
            raise ChainRequestError(
                f"Solana RPC returned an error: {payload['error']}"
            )

        return payload.get("result")

    @staticmethod
    def _account_keys(transaction):
        """Extract account public keys from a parsed transaction."""

        tx_data = transaction.get("transaction") or {}
        message = tx_data.get("message") or {}
        keys = []

        for entry in message.get("accountKeys") or []:
            if isinstance(entry, dict):
                keys.append(entry.get("pubkey"))
            else:
                keys.append(entry)

        return keys

    @staticmethod
    def _token_balances(transaction):
        """Map token account indexes to owner and mint metadata."""

        meta = transaction.get("meta") or {}
        balances = {}

        for entry in meta.get("preTokenBalances") or []:
            account_index = entry.get("accountIndex")
            mint = entry.get("mint")
            owner = entry.get("owner")
            token_amount = entry.get("uiTokenAmount") or {}

            if (
                not isinstance(account_index, int)
                or isinstance(account_index, bool)
                or not isinstance(mint, str)
                or not mint
                or not isinstance(owner, str)
                or not owner
            ):
                continue

            try:
                decimals = int(token_amount["decimals"])
            except (KeyError, TypeError, ValueError):
                continue

            if not 0 <= decimals <= 18:
                continue

            balances[account_index] = {
                "mint": mint,
                "owner": owner,
                "decimals": decimals,
            }

        return balances

    @staticmethod
    def _instructions(transaction):
        """Yield top-level and inner instructions."""

        tx_data = transaction.get("transaction") or {}
        message = tx_data.get("message") or {}
        meta = transaction.get("meta") or {}

        yield from message.get("instructions") or []

        for group in meta.get("innerInstructions") or []:
            if isinstance(group, dict):
                yield from group.get("instructions") or []

    def get_burn(self, tx_hash):
        """Return verified burn details, or None if verification fails."""

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

        if not isinstance(transaction, dict):
            return None

        meta = transaction.get("meta")

        if not isinstance(meta, dict) or meta.get("err") is not None:
            return None

        slot = transaction.get("slot")

        if (
            not isinstance(slot, int)
            or isinstance(slot, bool)
            or slot < 0
        ):
            return None

        tx_data = transaction.get("transaction") or {}
        signatures = tx_data.get("signatures", [])

        if not isinstance(signatures, list) or tx_hash not in signatures:
            return None

        message = tx_data.get("message") or {}
        account_entries = message.get("accountKeys") or []
        account_keys = self._account_keys(transaction)

        signers = {
            entry["pubkey"]
            for entry in account_entries
            if isinstance(entry, dict)
            and entry.get("signer") is True
            and isinstance(entry.get("pubkey"), str)
        }

        if not signers:
            return None

        token_balances = self._token_balances(transaction)
        matching_burns = {}

        for instruction in self._instructions(transaction):
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

            if (
                not isinstance(token_account, str)
                or not isinstance(authority, str)
            ):
                continue

            try:
                account_index = account_keys.index(token_account)
            except ValueError:
                continue

            account_info = token_balances.get(account_index)

            instruction_mint = info.get("mint")
            instruction_decimals = info.get("decimals")

            if account_info is not None:
                owner = account_info["owner"]
                actual_mint = account_info["mint"]
                actual_decimals = account_info["decimals"]

                if authority != owner or owner not in signers:
                    continue

                if actual_mint != self.token_mint:
                    continue

                if (
                    instruction_mint is not None
                    and instruction_mint != actual_mint
                ):
                    continue

                if instruction_decimals is not None:
                    try:
                        if int(instruction_decimals) != actual_decimals:
                            continue
                    except (TypeError, ValueError):
                        continue

            else:
                # Fall back to parsed instruction metadata.
                if authority not in signers:
                    continue

                if instruction_mint != self.token_mint:
                    continue

                if instruction_decimals is None:
                    continue

                try:
                    actual_decimals = int(instruction_decimals)
                except (TypeError, ValueError):
                    continue

                if not 0 <= actual_decimals <= 18:
                    continue

                actual_mint = instruction_mint
                owner = authority
            try:
                raw_amount = int(info["amount"])
            except (KeyError, TypeError, ValueError):
                continue

            if raw_amount <= 0:
                continue

            key = (owner, actual_mint, actual_decimals)
            matching_burns[key] = (
                matching_burns.get(key, 0) + raw_amount
            )

        if len(matching_burns) != 1:
            return None

        (wallet, mint, decimals), raw_total = next(
            iter(matching_burns.items())
        )

        amount = Decimal(raw_total) / (Decimal(10) ** decimals)

        return {
            "wallet_address": wallet,
            "token_contract": mint,
            "amount": format(amount, "f"),
            "block_number": slot,
        }