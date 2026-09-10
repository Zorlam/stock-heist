"""
Real MiniMax client, behind the exact same interface as MockMiniMaxClient
(`send_message(system_prompt, user_message) -> str`), so game_service.py
needs zero changes to use this instead of the mock.

Uses MiniMax's OpenAI-compatible Chat Completions endpoint:
    POST {base_url}/chat/completions

Configuration is via environment variables, loaded from .env by
app/config.py (imported below for its side effect — see that module's
docstring for why importing it, rather than calling load_dotenv() here
directly, is what makes this work regardless of import order):
    MINIMAX_API_KEY   (required)
    MINIMAX_MODEL     (default: "MiniMax-M3" — confirm the right model
                       with the project owner; MiniMax has several
                       current model lines and this is a guess at the
                       most likely default, not a confirmed requirement)
    MINIMAX_BASE_URL  (default: "https://api.minimax.io/v1" — the
                       international endpoint; MiniMax also has a
                       mainland-China endpoint at api.minimax.cn/v1 if
                       that turns out to be the right one instead)
"""

import os
import re

import requests

import app.config  # noqa: F401 — imported for its side effect: loads .env
from app.services.mock_minimax import MiniMaxRequestError  # same exception type as the mock

DEFAULT_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_MODEL = "MiniMax-M3"
REQUEST_TIMEOUT_SECONDS = 30

THINK_TAG_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_thinking(content: str) -> str:
    """Defense-in-depth: strip any <think>...</think> reasoning block from
    the model's raw content before it's used anywhere downstream (stored,
    evaluated, or ever shown to a player).

    We also ask the API not to emit this in the first place (see the
    `thinking` / `reasoning_split` payload fields in send_message below),
    but a real transcript review caught the model's raw output containing
    its own rule-by-rule reasoning inline in `content` as <think>...</think>
    — a significant leak, since that reasoning explicitly named which
    hard rules it was applying. Trusting a request-side flag alone, with
    no verification on the response side, is exactly the kind of gap
    that produced that leak. This function is the actual guarantee;
    the request parameters below are a best-effort reduction in how
    often it has anything to strip.
    """
    return THINK_TAG_PATTERN.sub("", content).strip()


class MiniMaxClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        if not self.api_key:
            raise ValueError(
                "MINIMAX_API_KEY is not set. Add it to your .env file "
                "(see README) or pass api_key= explicitly."
            )
        self.model = model or os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")

    def send_message(self, system_prompt: str, user_message: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_completion_tokens": 500,
            # Ask MiniMax-M3 not to emit visible reasoning at all. Per
            # MiniMax's docs this is supported on M3 but NOT on M2.x
            # models ("thinking cannot be disabled") — so if MINIMAX_MODEL
            # ends up pointing at an M2.x variant, this is silently
            # ignored by the API, which is exactly why _strip_thinking()
            # exists as a backstop rather than relying on this alone.
            "thinking": {"type": "disabled"},
            # Belt-and-suspenders: if thinking happens anyway, ask for it
            # in a separate response field instead of inlined into
            # `content` as <think>...</think>. We never read that field —
            # we only rely on `content` being cleaner as a result — but
            # combined with the disabled flag above and the strip below,
            # there are three independent reasons this shouldn't leak.
            "reasoning_split": True,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise MiniMaxRequestError(f"MiniMax request failed: {exc}") from exc

        if response.status_code != 200:
            raise MiniMaxRequestError(
                f"MiniMax returned HTTP {response.status_code}: {response.text[:500]}"
            )

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise MiniMaxRequestError(f"MiniMax response did not match expected shape: {exc}") from exc

        return _strip_thinking(content)
