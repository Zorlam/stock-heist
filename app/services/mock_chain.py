"""
Stand-in for real Robinhood Chain RPC calls. Same interface shape the
real client will need: something that can look up whether a given burn
tx actually happened on-chain, and something that can submit a payout.

Note what this deliberately does NOT do: it never creates a burn on the
player's behalf. In reality the burn is broadcast by the player's own
wallet, entirely outside our backend — our only job is to *verify* it
happened. `seed_burn()` exists purely so tests can simulate "this
transaction already exists on-chain" before the service asks about it.
"""


class ChainRequestError(Exception):
    """Raised on any failure to submit or confirm a chain transaction."""


class MockChainClient:
    def __init__(self):
        self._burns = {}
        self._fail_next_payout = 0

    def seed_burn(self, tx_hash, wallet_address, token_contract, amount, block_number=1):
        """Simulate a burn transaction already existing on-chain."""
        self._burns[tx_hash] = dict(
            wallet_address=wallet_address,
            token_contract=token_contract,
            amount=amount,
            block_number=block_number,
        )

    def get_burn(self, tx_hash):
        """Returns the on-chain burn record as a dict, or None if no such
        transaction exists (yet, or ever). A real implementation queries
        an RPC node or indexer for the transaction receipt and decodes
        the burn event/transfer-to-burn-address."""
        return self._burns.get(tx_hash)

    def fail_next_payout(self, n: int = 1):
        self._fail_next_payout += n

    def submit_payout(self, *, wallet_address, token_contract, amount) -> str:
        if self._fail_next_payout > 0:
            self._fail_next_payout -= 1
            raise ChainRequestError("simulated payout submission failure")
        return f"0xpayout_{wallet_address}_{amount}"
