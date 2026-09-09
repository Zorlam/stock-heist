# Stock Heist — Data Layer

Step 1 of the build: the database schema only. No blockchain, no MiniMax,
no frontend, no 3D. This exists to prove the state machine and its
concurrency guarantees are correct before anything is layered on top of it.

## Structure

```
app/
  models/
    base.py                  # db instance, GUID (cross-dialect UUID) column, pg_enum() helper
    enums.py                 # RoundStatus, BurnTxStatus, AttemptStatus, PayoutStatus
    player.py                # Player
    round.py                 # Round (the vault)
    burn_transaction.py      # BurnTransaction
    attempt.py                # Attempt (the central entity)
    ai_response.py           # AIResponse
    payout_transaction.py    # PayoutTransaction
    attempt_status_history.py # AttemptStatusHistory (audit trail)
  factory.py                 # minimal Flask app factory wiring db.init_app
tests/
  conftest.py                # in-memory SQLite fixtures (fast structural verification)
  test_data_model.py         # one test per requirement in the brief
schema_postgres.sql          # exact DDL SQLAlchemy will run against Postgres (generated, for review)
```

## Running the verification suite

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest tests/ -v
```

14 tests, all passing. They verify against SQLite in-memory (fast, no
external DB needed) but exercise the *same* constraints Postgres will
enforce — see the note in `tests/conftest.py` for exactly what that does
and doesn't cover. Re-run the same suite against a real
`DATABASE_URL=postgresql://...` before deploying, as a final check —
nothing here should behave differently, but it's cheap insurance.

## How the required guarantees map to constraints

| Requirement | Mechanism |
|---|---|
| 1 burn = exactly 1 attempt | `burn_transactions.tx_hash` UNIQUE + `attempts.burn_transaction_id` UNIQUE |
| Burn tx can't be reused | same as above — a duplicate insert attempt fails at the DB level |
| Idempotent processing | `tx_hash` UNIQUE is the idempotency key; insert-or-fetch-existing on it |
| Pending/processing/completed/failed attempt states | `AttemptStatus` enum (11 states) + `attempt_status_history` audit trail |
| Round closure | `RoundStatus` enum + `ck_round_closed_at_consistency` CHECK constraint |
| No multiple winners per vault | partial unique index `ix_one_winner_per_round ON attempts(round_id) WHERE status='won'` |
| Payout tracking | `payout_transactions`, with UNIQUE `round_id` and UNIQUE `attempt_id` as a second, independent backstop against double payout |
| Full lifecycle audit | `attempt_status_history` — one row per transition, written in the same DB transaction as the status change |

The one-winner-per-round guarantee is the most important constraint in
this schema — it's a **partial unique index**, not application logic, so
it holds even if two backend processes race to record a win at the same
moment. See the docstring in `attempt.py` for why you still want a
`SELECT ... FOR UPDATE` row lock on the round in the service layer on top
of this: the index guarantees correctness, the lock is what makes the
*second* racer fail gracefully (→ `LOST_ROUND_CLOSED`) instead of just
throwing an unhandled `IntegrityError`.

## Deliberate simplifications / open items

- **Secret code storage**: `rounds.secret_code_hash` + `secret_code_salt`,
  not the plaintext. The verdict engine (next layer, not built yet) will
  need to hash candidate substrings of the AI response with the stored
  salt and compare — worth designing carefully once we get there, since
  "does response contain code" is a substring-match problem, not an
  equality-match problem, which doesn't hash-compare as cleanly as a
  password would. Flagging this now so it's not a surprise in the verdict
  engine step.
- **"Only one OPEN round at a time"** is *not* enforced at the DB level —
  see the docstring in `round.py`. This was ambiguity #4 from the
  architecture doc and hasn't been resolved yet. If the answer ends up
  being "always exactly one active round," add a partial unique index the
  same way `ix_one_winner_per_round` works.
- **Wallet address normalization** (lowercasing) is assumed to happen at
  the application layer before insert, not enforced by a DB constraint —
  flagging so it doesn't get missed when the wallet integration layer is
  built.
- No Alembic/migration setup yet — `schema_postgres.sql` is generated
  directly from the models for review purposes. Once this is approved,
  the natural next step is `flask db init` (Alembic) so future schema
  changes are tracked as migrations rather than `create_all()` diffs.

## What's next

Per the agreed development order: mock AI + mock chain integration on top
of this data layer, to prove the full payment → AI → verdict → payout
pipeline's state transitions before touching the real MiniMax API or real
chain calls. **This is now done — see below.**

---

# Service Layer (mock AI + mock chain)

`app/services/` orchestrates the full pipeline on top of the data model
above, using scriptable fake clients (`MockMiniMaxClient`,
`MockChainClient`) so the state machine and its concurrency handling can
be proven correct before any real network call is involved.

```
app/services/
  game_service.py       # the orchestrator: submit_attempt, retry_ai_call, retry_payout
  verdict.py             # the one function that decides win/loss (exact substring match)
  secrets_provider.py    # where the plaintext code actually lives (not the DB — see below)
  mock_minimax.py         # scriptable fake AI client
  mock_chain.py            # scriptable fake chain client
tests/test_game_service.py # 16 tests covering the pipeline + edge cases
```

Run everything (data model + service layer):

```bash
PYTHONPATH=. pytest tests/ -v
```

30 tests, all passing.

## Key design decisions in this layer

**The secret code doesn't live as a hash for live verification.**
`rounds.secret_code_hash` (from the data layer) is good for audit/
detecting corruption, but "does this AI response *contain* the code" is a
substring-match problem — you can't hash-compare your way through that.
`RoundSecretsProvider` is the abstraction: plaintext code lives outside
the main DB (a real secrets manager in production; `InMemorySecretsProvider`
for now), and `get_verified_code()` re-hashes it against the round's
stored hash before trusting it — a `SecretMismatchError` on any drift
between the two, rather than silently producing a wrong verdict.

**The round is only locked at the moment of claiming a win**, not across
the AI call. Holding a DB row lock for the duration of a slow external
API call would serialize every attempt on a round through the AI's
response latency — the exact opposite of what you want for a game meant
to be playable by multiple people. See `_claim_win_or_lose_the_race` in
`game_service.py`.

**Two independent mechanisms prevent a double win**, on purpose:
1. The row lock + status check in `_claim_win_or_lose_the_race`, which is
   what makes the *loser* of a race fail gracefully into
   `LOST_ROUND_CLOSED` instead of an ugly error.
2. The partial unique index from the data layer, as a backstop if the
   lock is ever weaker than expected (e.g. isolation-level surprises).
   `test_genuine_race_is_caught_by_the_index_backstop` forces this path
   directly and confirms it degrades cleanly rather than crashing.

**Every state transition is retryable from where it failed.**
`AI_REQUEST_FAILED` and `PAYOUT_FAILED` are real, queryable states — a
background worker (not built yet) would poll for
`ATTEMPT_ACTIONABLE_STATUSES` and call `retry_ai_call` / `retry_payout`.
Retrying never re-charges the player or creates a second AI/payout row —
same message, same payout, tried again.

**A player who paid before round closure still gets their AI response.**
If their message happens to match the code but the round already closed
in the meantime, they're marked `LOST_ROUND_CLOSED` — not silently
dropped, and not billed twice to find out. See
`test_second_winning_message_after_round_already_closed`.

## What this layer still doesn't cover (deliberately)

- No background worker — retries are manual function calls for now, not
  polled automatically. That's a natural next slice once the real
  MiniMax/chain clients exist and failures become an operational reality
  rather than a test scenario.
- No API routes / HTTP layer yet — `game_service.submit_attempt(...)` is
  called directly in tests. Wiring this behind a Flask blueprint is a
  small, mostly mechanical step once we're ready for it.
- No real MiniMax or chain client implementations yet — the mocks define
  the exact interface (`send_message`, `get_burn`, `submit_payout`) the
  real clients need to satisfy, so swapping them in later shouldn't
  touch `game_service.py` at all.

## Suggested next step

Given the two open blockchain questions from the architecture doc are
still unanswered (EVM-compatibility, exact burn mechanism), a reasonable
next slice that doesn't block on them: **wire up the real MiniMax
integration** behind the same `send_message` interface the mock uses,
and iterate on the actual broker system prompt against it — that's
useful and testable regardless of how the chain questions resolve.
**This is now done — see below.**

---

# Real MiniMax Client

`app/services/minimax_client.py` implements `MiniMaxClient`, satisfying
the exact same interface as `MockMiniMaxClient`
(`send_message(system_prompt, user_message) -> str`), so it drops into
`game_service.submit_attempt(..., ai_client=...)` with zero changes to
the orchestrator. `tests/test_minimax_client.py::test_real_client_drops_into_game_service_unchanged`
proves this directly.

## Configuration

Set these in your `.env` file (never commit it — already in `.gitignore`):

```
MINIMAX_API_KEY=your-key-here
MINIMAX_MODEL=MiniMax-M3          # optional, see note below
MINIMAX_BASE_URL=https://api.minimax.io/v1   # optional, see note below
```

`app/factory.py` now calls `load_dotenv()` on startup, so these are
picked up automatically when you run the app or the test suite locally.

**Two things to confirm with the project owner before going live:**
1. **Which MiniMax model** — MiniMax currently has several active model
   lines (`MiniMax-M3`, `MiniMax-Text-01`, `M2-her`, and others).
   `MiniMax-M3` is set as the default because it's the model shown in
   MiniMax's current primary API docs, but this is a best guess, not a
   confirmed requirement — override via `MINIMAX_MODEL` once you know.
2. **Which endpoint region** — `https://api.minimax.io/v1` is the
   international endpoint; there's also a mainland-China endpoint at
   `https://api.minimax.cn/v1`. Override via `MINIMAX_BASE_URL` if needed.

## What it does

Calls MiniMax's OpenAI-compatible endpoint (`POST /chat/completions`)
with the broker system prompt and the player's message, and returns the
response text. Any failure — network error, timeout, non-200 status, or
a response that doesn't match the expected shape — raises the same
`MiniMaxRequestError` the mock uses, so `game_service`'s existing
failure/retry handling (`AI_REQUEST_FAILED` → `retry_ai_call`) applies
unchanged.

## Testing without live network access

All tests mock `requests.post` directly (`unittest.mock.patch`), so they
run offline and verify the actual request-building and response-parsing
logic — not just scripted behavior like the `MockMiniMaxClient` tests do.
This environment has no network access to `api.minimax.io`, so **the
client has not been exercised against the real MiniMax API yet** — that
first live call is worth doing deliberately (e.g. a short throwaway
script hitting the real endpoint with a trivial prompt) once you have
confirmed the model/endpoint details above, before wiring it into any
real round.

## What's next

With the real AI integration in place, natural next steps:
1. **Iterate on the actual broker system prompt** against the real
   model — this is genuinely useful design work independent of anything
   else, and the current placeholder prompt (`BROKER_SYSTEM_PROMPT` in
   `game_service.py`) is intentionally minimal, not tuned.
2. Still-open blockchain questions (EVM-compatibility, exact burn
   mechanism) — once answered, the same pattern used here (mock →
   real client, same interface, zero orchestrator changes) applies to
   swapping `MockChainClient` for a real one.

