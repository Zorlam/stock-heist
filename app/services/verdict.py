"""
The one function that decides whether a player wins. Kept deliberately
tiny and boring — this is the piece where "clever" is a liability.
"""


def evaluate_response(response_text: str, expected_code: str) -> bool:
    """Exact, case-sensitive substring match. That's the entire rule.

    Case-sensitive and exact on purpose: the brief is explicit that
    something like "you convinced me" must never count, only the literal
    code appearing in the response. Being lenient here (case-insensitive,
    whitespace-normalized, fuzzy) only widens the surface for an
    accidental/unintended win — a far worse failure mode than a real win
    being narrowly missed on a technicality, since the code is something
    we control the exact format of (see the architecture note on choosing
    a long, effectively-unguessable code — a well-chosen code doesn't
    have plausible near-miss casing/spacing variants in the first place).
    """
    if not response_text or not expected_code:
        return False
    return expected_code in response_text
