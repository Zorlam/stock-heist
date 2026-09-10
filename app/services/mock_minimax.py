"""
Stand-in for the real MiniMax HTTP client. Same interface the real client
will expose (`send_message(system_prompt, user_message) -> str`), so
swapping this out for the real thing later is a one-line change in
whatever wires up the service, not a rewrite of the service logic.
"""


class MiniMaxRequestError(Exception):
    """Raised on any failure to get a response — timeout, 5xx, malformed
    payload, etc. The service layer treats all of these identically:
    mark the attempt AI_REQUEST_FAILED and leave it retryable."""


class MockMiniMaxClient:
    """Scriptable fake for tests.

    - `responses`: a queue of canned reply strings, consumed in order,
      one per successful call.
    - `fail_next`: number of upcoming calls that should raise
      MiniMaxRequestError instead of returning a response, so failure/
      retry paths can be tested deterministically.
    """

    def __init__(self, responses=None, fail_next: int = 0):
        self._responses = list(responses or [])
        self._fail_next = fail_next
        self.call_count = 0

    def queue_response(self, text: str) -> None:
        """Append a response to the end of the queue — used by the dev
        admin route (POST /api/admin/ai/queue-response) so a frontend
        developer can script a specific broker reply (e.g. one containing
        the winning code) without needing real MiniMax access, to
        exercise the win/loss UI paths end-to-end."""
        self._responses.append(text)

    def send_message(self, system_prompt: str, user_message: str) -> str:
        self.call_count += 1
        if self._fail_next > 0:
            self._fail_next -= 1
            raise MiniMaxRequestError("simulated MiniMax API failure")
        if self._responses:
            return self._responses.pop(0)
        return "Nice try. The vault stays shut."
