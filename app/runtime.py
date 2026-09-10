"""
Shared, per-app runtime dependencies for the API layer: the chain client,
the AI client, and the secrets provider that game_service.submit_attempt
needs on every call.

Deliberately simple — one instance per Flask app, attached via
app.extensions, not a full DI framework. That's the right amount of
machinery for where this project actually is: one process, a mock chain
(no real chain integration yet), and either a mock or real AI client
depending on configuration. When a real chain client and/or a background
worker exist, this is the one place that needs to change — no route
should ever import MockChainClient or MiniMaxClient directly.
"""

import os

from app.services.mock_chain import MockChainClient
from app.services.mock_minimax import MockMiniMaxClient
from app.services.secrets_provider import MutableInMemorySecretsProvider


class Runtime:
    def __init__(self):
        # No real chain integration yet (see README — EVM-compatibility
        # and burn mechanism are still open questions), so this is always
        # the mock for now. Swapping in a real client later is a matter
        # of changing this one line, not touching any route.
        self.chain_client = MockChainClient()

        # Round secrets: see MutableInMemorySecretsProvider's docstring
        # for exactly why this is dev/local-only and must be replaced
        # before any real deployment (in-process memory, doesn't survive
        # a restart, not shared across worker processes).
        self.secrets_provider = MutableInMemorySecretsProvider()

        self._ai_client = None

    @property
    def ai_client(self):
        """Lazy so importing this module never requires MINIMAX_API_KEY
        to be set — only constructing a real client does, and only when
        AI_CLIENT=real is actually configured."""
        if self._ai_client is None:
            if os.environ.get("AI_CLIENT", "mock") == "real":
                from app.services.minimax_client import MiniMaxClient

                self._ai_client = MiniMaxClient()
            else:
                self._ai_client = MockMiniMaxClient()
        return self._ai_client


def init_runtime(app):
    app.extensions["runtime"] = Runtime()


def get_runtime() -> Runtime:
    from flask import current_app

    return current_app.extensions["runtime"]
