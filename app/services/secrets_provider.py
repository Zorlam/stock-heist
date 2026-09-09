"""
Where the plaintext secret code actually lives.

Deliberately NOT a column read straight off the `rounds` row for live
verdict checks — `rounds.secret_code_hash` exists for audit/verification
purposes (e.g. proving after the fact what the code was, or detecting a
corrupted config), not as the thing the verdict engine hashes and
compares. Hash equality can't answer "does this 400-word AI response
contain this code as a substring" — that requires the plaintext.

In production this should be backed by a real secrets manager (KMS,
Vault, or at minimum a tightly access-controlled env var) keyed by
round_id, populated once at round-creation time by admin tooling and
never written to application logs. `InMemorySecretsProvider` below is a
stand-in for tests and local dev only — do not use it past this layer.
"""

import hashlib


class SecretMismatchError(Exception):
    """Raised when the plaintext code fetched for a round doesn't match
    that round's stored hash. This should never happen in correct
    operation — it means either the wrong code was loaded for this round,
    or the round's stored hash is stale/corrupted. Either way, refusing to
    evaluate is much safer than silently producing a wrong verdict in
    either direction."""


class RoundSecretsProvider:
    def get_code(self, round_id) -> str:
        raise NotImplementedError

    @staticmethod
    def hash_code(code: str, salt: str) -> str:
        return hashlib.sha256((salt + code).encode("utf-8")).hexdigest()

    def get_verified_code(self, round_) -> str:
        code = self.get_code(round_.id)
        if self.hash_code(code, round_.secret_code_salt) != round_.secret_code_hash:
            raise SecretMismatchError(
                f"plaintext code for round {round_.id} does not match its stored hash"
            )
        return code


class InMemorySecretsProvider(RoundSecretsProvider):
    """Test/dev only. Codes supplied directly at construction time."""

    def __init__(self, codes_by_round_id: dict):
        self._codes = {str(k): v for k, v in codes_by_round_id.items()}

    def get_code(self, round_id) -> str:
        return self._codes[str(round_id)]
