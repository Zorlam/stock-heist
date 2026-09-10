"""
Runs the full adversarial attack corpus against the REAL MiniMax API and
reports what came back, with lightweight heuristic flags (see
app/services/prompt_eval.py) to help you spot problems fast in a long
transcript.

This makes real network calls and costs real API usage — it is NOT run
as part of the automated test suite (which stays offline/deterministic
on purpose). Run it by hand, locally, wherever you actually have network
access to api.minimax.io and a MINIMAX_API_KEY in your .env.

Usage:
    PYTHONPATH=. python scripts/live_minimax_smoke_test.py

What it does NOT do: decide whether the prompt is "safe." It's a fast
first pass — the flags are heuristics, not a verdict. Read every response
yourself; the automated checks only catch the crude failures (verbatim
prompt leakage, an obviously code-shaped string in the reply). Subtler
failures — a response that's *almost* compliant, or leaks the code's
format/length without the code itself, or breaks character in a way that
erodes future resistance — need a human reading the transcript.
"""

import sys
import time

sys.path.insert(0, ".")  # allow running as `python scripts/live_minimax_smoke_test.py`

from app.services.minimax_client import MiniMaxClient
from app.services.mock_minimax import MiniMaxRequestError
from app.services.broker_prompt import CURRENT_BROKER_SYSTEM_PROMPT
from app.services.attack_corpus import ATTACK_CORPUS
from app.services.prompt_eval import (
    leaked_prompt_sentences,
    possible_code_shaped_strings,
    architecture_leak_indicators,
    invented_mechanic_indicators,
)

# A fake code that is NOT anywhere in the system prompt — used only to
# sanity-check the obvious negative case (it should never appear, since
# the model was never given it in the first place).
CANARY_CODE = "VAULT-CANARY-9F3K"


def main():
    client = MiniMaxClient()  # raises clearly and immediately if MINIMAX_API_KEY isn't set
    print(f"Model: {client.model}")
    print(f"Base URL: {client.base_url}")
    print(f"Attack corpus size: {len(ATTACK_CORPUS)}\n")
    print("=" * 80)

    flagged = []

    for i, (category, message) in enumerate(ATTACK_CORPUS, 1):
        print(f"\n[{i}/{len(ATTACK_CORPUS)}] category={category}")
        print(f"  player: {message}")
        try:
            response = client.send_message(CURRENT_BROKER_SYSTEM_PROMPT, message)
        except MiniMaxRequestError as exc:
            print(f"  ERROR calling MiniMax: {exc}")
            flagged.append((category, message, f"API_ERROR: {exc}"))
            continue

        print(f"  broker: {response}")

        issues = []
        if CANARY_CODE in response:
            issues.append("CANARY CODE LEAKED (should be impossible — investigate immediately)")
        prompt_leaks = leaked_prompt_sentences(response, CURRENT_BROKER_SYSTEM_PROMPT)
        if prompt_leaks:
            issues.append(f"POSSIBLE SYSTEM PROMPT LEAK: {prompt_leaks}")
        code_shaped = possible_code_shaped_strings(response)
        if code_shaped and category != "benign_control":
            issues.append(f"POSSIBLE FABRICATED/GUESSED CODE STRING: {code_shaped}")
        arch_leaks = architecture_leak_indicators(response)
        if arch_leaks:
            issues.append(f"ARCHITECTURE LEAK (explaining the refusal instead of just refusing): {arch_leaks}")
        if category == "mechanics_question":
            invented = invented_mechanic_indicators(response)
            if invented:
                issues.append(f"INVENTED GAME MECHANIC: {invented}")

        if issues:
            print(f"  FLAGGED: {issues}")
            flagged.append((category, message, "; ".join(issues)))

        time.sleep(0.5)  # be polite to the API

    print("\n" + "=" * 80)
    print(f"\nDone. {len(flagged)} of {len(ATTACK_CORPUS)} responses flagged for manual review.\n")
    for category, message, issue in flagged:
        print(f"- [{category}] {issue}\n  prompt: {message}")

    if not flagged:
        print("No heuristic flags — still read the full transcript above by hand before trusting this.")


if __name__ == "__main__":
    main()
