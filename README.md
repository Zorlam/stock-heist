# Stock Heist — Backend API

Flask + PostgreSQL backend for **Stock Heist**, a 3D web game built around an AI broker guarding a vault.

> **"Convince the AI to give you Nvidia."**

A player submits a project-token burn transaction and a message to the AI broker. The backend verifies the payment, sends the message to the broker, and independently evaluates the broker's reply against the round's secret code.

The backend is authoritative for the verdict. The AI does not decide whether an attempt wins, and the frontend does not determine the outcome.

---

## Table of Contents

* [Tech Stack](#tech-stack)
* [Project Structure](#project-structure)
* [Getting Started](#getting-started)
* [Configuration](#configuration)
* [Running the Server](#running-the-server)
* [Testing](#testing)
* [API Reference](#api-reference)
* [Attempt Lifecycle](#attempt-lifecycle)
* [Data Model](#data-model)
* [How a Request Flows Through the System](#how-a-request-flows-through-the-system)
* [AI Broker and Prompt Hardening](#ai-broker-and-prompt-hardening)
* [Current Limitations](#current-limitations)
* [Before Production](#before-production)

---

## Tech Stack

| Layer                   | Technology                                               |
| ----------------------- | -------------------------------------------------------- |
| Web framework           | Flask 3                                                  |
| ORM                     | Flask-SQLAlchemy 3 / SQLAlchemy 2                        |
| Database                | PostgreSQL; SQLite for local development and tests       |
| Blockchain              | Solana                                                   |
| Token standard          | Solana SPL Token and Token-2022                          |
| Blockchain verification | Solana JSON-RPC                                          |
| AI                      | MiniMax, using an OpenAI-compatible Chat Completions API |
| Configuration           | python-dotenv                                            |
| CORS                    | Flask-Cors                                               |
| Testing                 | pytest                                                   |

---

## Project Structure

```text
app/
  config.py
  factory.py
  runtime.py
  routes.py

  models/
    base.py
    enums.py
    player.py
    round.py
    burn_transaction.py
    attempt.py
    ai_response.py
    payout_transaction.py
    attempt_status_history.py

  services/
    game_service.py
    verdict.py
    secrets_provider.py
    broker_prompt.py
    minimax_client.py
    mock_minimax.py
    mock_chain.py
    solana_chain.py
    attack_corpus.py
    prompt_eval.py

scripts/
  live_minimax_smoke_test.py

tests/
  test_data_model.py
  test_game_service.py
  test_minimax_client.py
  test_prompt_eval.py
  test_api.py
  test_solana_chain.py

run.py
requirements.txt
schema_postgres.sql
```

**Important components**

* `app/runtime.py`: Creates the application's chain client, AI client, and secrets provider.
* `app/services/game_service.py`: Coordinates payment verification, attempts, AI responses, verdict evaluation, and the existing payout workflow.
* `app/services/mock_chain.py`: Provides simulated burns for development and tests.
* `app/services/solana_chain.py`: Implements `SolanaBurnVerifier` for verifying real Solana token burns.
* `app/services/verdict.py`: Implements the win/loss rule.
* `app/services/secrets_provider.py`: Provides the secret code to the verdict service without storing its plaintext in the database.
* `app/routes.py`: Exposes the HTTP API.

---

## Getting Started

### Prerequisites

* Python 3.10 or newer
* PostgreSQL for a persistent deployment
* A Solana RPC endpoint and the project's SPL token mint when using real Solana verification
* A MiniMax API key when using the real AI client

### 1. Create and activate a virtual environment

```bash
python -m venv venv
```

On Windows:

```powershell
venv\Scripts\activate
```

On Linux or macOS:

```bash
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root. See [Configuration](#configuration).

### 4. Create the database tables

```bash
python -c "from app.factory import create_app; from app.models import db; app = create_app(); ctx = app.app_context(); ctx.push(); db.create_all(); print('tables created')"
```

There are no database migrations configured yet. `db.create_all()` creates the tables defined by the models.

---

## Configuration

The application reads configuration from environment variables. `app/config.py` loads the project's `.env` file.

Keep `.env` out of version control. Do not commit API keys or other environment-specific credentials.

Example configuration:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/stock_heist

# AI client
AI_CLIENT=mock
MINIMAX_API_KEY=your-minimax-api-key
MINIMAX_MODEL=MiniMax-M3
MINIMAX_BASE_URL=https://api.minimax.io/v1

# Blockchain client
CHAIN_CLIENT=mock
SOLANA_RPC_URL=your-solana-rpc-endpoint
PROJECT_TOKEN_MINT=your-spl-token-mint-address

# API behaviour
ENABLE_DEV_ADMIN_ROUTES=true
CORS_ALLOWED_ORIGINS=*
```

### Environment variables

| Variable                  | Default                              | Description                                                                                 |
| ------------------------- | ------------------------------------ | ------------------------------------------------------------------------------------------- |
| `DATABASE_URL`            | `postgresql://localhost/stock_heist` | Database connection string. Use `sqlite:///dev.db` for a quick local run.                   |
| `AI_CLIENT`               | `mock`                               | Selects the mock AI client or the real MiniMax client.                                      |
| `MINIMAX_API_KEY`         | None                                 | Required when `AI_CLIENT=real`.                                                             |
| `MINIMAX_MODEL`           | `MiniMax-M3`                         | MiniMax model identifier. Confirm the intended production model before deployment.          |
| `MINIMAX_BASE_URL`        | `https://api.minimax.io/v1`          | MiniMax API base URL.                                                                       |
| `CHAIN_CLIENT`            | `mock`                               | Selects simulated chain verification or real Solana burn verification.                      |
| `SOLANA_RPC_URL`          | None                                 | Solana JSON-RPC endpoint required when `CHAIN_CLIENT=solana`.                               |
| `PROJECT_TOKEN_MINT`      | None                                 | Mint address of the SPL token accepted as payment. Required when `CHAIN_CLIENT=solana`.     |
| `ENABLE_DEV_ADMIN_ROUTES` | `true`                               | Enables development-only administration endpoints. Disable outside local development.       |
| `CORS_ALLOWED_ORIGINS`    | `*`                                  | Allowed frontend origins. Restrict this to the deployed frontend's origin when appropriate. |

### Selecting the blockchain client

#### Mock mode

```env
CHAIN_CLIENT=mock
```

The application uses `MockChainClient`. Burns must be seeded into the mock client, making this mode suitable for local development and deterministic tests.

#### Solana mode

```env
CHAIN_CLIENT=solana
SOLANA_RPC_URL=your-solana-rpc-endpoint
PROJECT_TOKEN_MINT=your-spl-token-mint-address
```

The application uses `SolanaBurnVerifier` to retrieve and validate Solana transactions through JSON-RPC.

The verifier checks finalized transactions and validates supported SPL token burn instructions against the configured project-token mint. It also checks transaction success, signer/owner information, and burn amounts.

**Important:** The real Solana integration described here covers burn verification. It does not, by itself, implement real prize transfers. See [Current Limitations](#current-limitations).

Do not silently fall back to mock verification when real-chain configuration is missing. Real mode should fail clearly if its required configuration is absent or invalid.

---

## Running the Server

Start the local development server:

```bash
python run.py
```

The default local address is:

```text
http://127.0.0.1:5000
```

For a quick local run using SQLite:

```bash
DATABASE_URL=sqlite:///dev.db python run.py
```

On Windows PowerShell:

```powershell
$env:DATABASE_URL="sqlite:///dev.db"
python run.py
```

`run.py` is intended for local development. Use a production WSGI server, such as Gunicorn, for deployment.

---

## Testing

Run the full test suite:

```bash
python -m pytest -q
```

Or run the tests with verbose output:

```bash
PYTHONPATH=. pytest tests/ -v
```

The automated tests use SQLite and mocked external services, allowing them to run without a live Solana RPC endpoint or a paid MiniMax request.

### Test coverage

| Test file                | Coverage                                                                                                            |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `test_data_model.py`     | Database constraints and model behaviour                                                                            |
| `test_game_service.py`   | Attempt processing, idempotency, AI failures, verdicts, round closure, and existing payout workflow                 |
| `test_minimax_client.py` | MiniMax request construction, error handling, and removal of `<think>` blocks                                       |
| `test_prompt_eval.py`    | Heuristic checks for prompt and architecture leakage                                                                |
| `test_api.py`            | HTTP routes through Flask's test client                                                                             |
| `test_solana_chain.py`   | Solana burn verification, transaction validation, token-mint matching, signer checks, amount checks, and RPC errors |

### Solana verifier tests

Run the focused Solana tests:

```bash
python -m pytest tests/test_solana_chain.py -q
```

The focused verifier suite contains seven tests. They mock HTTP responses, so passing them confirms the tested validation logic but does not establish that a live transaction has been verified against the Solana network.

Before deploying, test the integration against a suitable Solana RPC endpoint and a known transaction for the configured token mint.

### Live MiniMax smoke test

```bash
PYTHONPATH=. python scripts/live_minimax_smoke_test.py
```

This sends the adversarial attack corpus to the configured live MiniMax API and checks for crude failure modes, including prompt leakage, fabricated code-shaped strings, architecture leakage, and invented mechanics.

The test consumes real API usage and is not part of the automated test suite. Its checks are heuristic, so review the complete transcripts rather than treating its flags as definitive security findings.

SQLite tests do not establish PostgreSQL-specific concurrency behaviour. Run the full suite against a real PostgreSQL database before deployment.

---

## API Reference

Local base URL:

```text
http://127.0.0.1:5000
```

### Player-facing routes

#### `GET /api/rounds/active`

Returns the currently open round.

Returns `404` if no round is open.

Example response:

```json
{
  "id": "ROUND_ID",
  "status": "open",
  "asset_symbol": "NVDA",
  "asset_token_contract": "ASSET_TOKEN_ADDRESS",
  "prize_amount": "50.000000000000000000",
  "project_token_contract": "PROJECT_TOKEN_MINT_ADDRESS",
  "burn_amount": "10000.000000000000000000",
  "opened_at": "2026-09-10T22:00:00+00:00",
  "closed_at": null,
  "winning_attempt_id": null
}
```

The `project_token_contract` field retains the existing API/database field name. In Solana mode, its value represents the configured project-token mint address, not an EVM contract address.

#### `GET /api/rounds/<id>`

Returns a specific round, whether open, won, or cancelled.

Returns `404` if the round does not exist.

#### `POST /api/attempts`

Submits a burn transaction and the player's message.

Request:

```json
{
  "round_id": "ROUND_ID",
  "tx_hash": "SOLANA_TRANSACTION_SIGNATURE",
  "message": "the player's message to the broker"
}
```

The `tx_hash` field retains its existing name. On Solana, its value is a transaction signature.

Rules:

* `message` must be a string no longer than 2,000 characters.
* The submitted transaction must be verifiable by the selected chain client.
* The verified token mint must match the round's configured project token.
* The verified burn amount must meet the round's required burn amount.
* A transaction signature is used for idempotency. Resubmitting a signature that has already been processed returns the existing attempt rather than creating another attempt or making another AI request.
* Processing is currently synchronous: the request waits for payment verification, the AI call, verdict evaluation, and any subsequent payout handling.

A successful request returns `201` according to the existing API contract.

Example response:

```json
{
  "id": "ATTEMPT_ID",
  "round_id": "ROUND_ID",
  "status": "lost",
  "message": "the player's message to the broker",
  "ai_response": {
    "text": "The broker's reply."
  },
  "payout": null,
  "created_at": "...",
  "updated_at": "..."
}
```

The status and payout fields depend on the actual attempt outcome and processing state. The example above illustrates a losing attempt; it is not a guarantee of a particular response for every submission.

Expected error categories include:

| HTTP status | Meaning                                                                                           |
| ----------- | ------------------------------------------------------------------------------------------------- |
| `400`       | Missing or invalid request fields                                                                 |
| `402`       | Payment verification failed, such as an unverified burn, wrong token mint, or insufficient amount |
| `404`       | The requested round or attempt was not found                                                      |
| `500`       | An unexpected internal error occurred                                                             |

Exact error responses depend on the route's error handling.

#### `GET /api/attempts/<id>`

Returns the current state of an attempt. Returns `404` if the attempt does not exist.

Numeric amounts are serialized as decimal strings to preserve precision. Parse them as decimal values rather than comparing them lexicographically as strings.

### Development-only administration routes

These endpoints support local testing without requiring a real wallet transaction or paid AI request.

They are controlled by `ENABLE_DEV_ADMIN_ROUTES`. Keep them disabled outside local development.

#### `POST /api/admin/rounds`

Creates a round.

Example request:

```json
{
  "asset_symbol": "NVDA",
  "asset_token_contract": "ASSET_TOKEN_ADDRESS",
  "prize_amount": "50.0",
  "project_token_contract": "PROJECT_TOKEN_MINT_ADDRESS",
  "burn_amount": "10000",
  "secret_code": "VAULT-TEST-CODE"
}
```

The secret is registered with the secrets provider and its hash is stored with the round. The endpoint should not return the plaintext secret.

#### `POST /api/admin/burns/seed`

Seeds a simulated burn into `MockChainClient`.

Example request:

```json
{
  "tx_hash": "mock-transaction-1",
  "wallet_address": "MOCK_WALLET_ADDRESS",
  "token_contract": "PROJECT_TOKEN_MINT_ADDRESS",
  "amount": "10000"
}
```

This endpoint is for mock-chain development and testing. It does not create a real Solana transaction and cannot seed a transaction into the live Solana network.

#### `POST /api/admin/ai/queue-response`

Queues the mock broker's next response. This endpoint works with `AI_CLIENT=mock`.

Example request:

```json
{
  "text": "Ugh, fine. VAULT-TEST-CODE. Happy now?"
}
```

The queued reply can be used to test the verdict path.

### Development example

The following illustrates the mock workflow. It does not require a real Solana transaction.

1. Set `CHAIN_CLIENT=mock` and `AI_CLIENT=mock`.
2. Create a round using `POST /api/admin/rounds`.
3. Seed a mock burn using `POST /api/admin/burns/seed`.
4. Optionally queue a broker reply using `POST /api/admin/ai/queue-response`.
5. Submit the attempt using `POST /api/attempts`.

The submitted `round_id` and transaction signature must correspond to the created round and seeded burn.

---

## Attempt Lifecycle

The attempt's `status` is the primary state consumed by the frontend.

The lifecycle includes the following states:

```text
pending_payment
    |
payment_confirmed
    |
ai_request_in_progress
    |                 \
    |                  ai_request_failed
    |                  (retryable)
    |
evaluating
    |
    +---- lost
    |
    +---- lost_round_closed
    |
    +---- won
             |
        payout_pending
          /       \
 payout_failed   payout_completed
   (retryable)
```

| Status                   | Meaning                                                                      |
| ------------------------ | ---------------------------------------------------------------------------- |
| `pending_payment`        | Attempt created; payment has not yet been confirmed                          |
| `payment_confirmed`      | Burn verified                                                                |
| `ai_request_in_progress` | Waiting for the broker's response                                            |
| `ai_request_failed`      | AI request failed; retryable without a new payment                           |
| `evaluating`             | Broker response received; verdict being evaluated                            |
| `lost`                   | The response did not match the secret code                                   |
| `lost_round_closed`      | The response matched the code, but another attempt had already won the round |
| `won`                    | The verdict succeeded and the win was recorded                               |
| `payout_pending`         | The existing payout workflow is processing the transfer                      |
| `payout_failed`          | Payout attempt failed; retryable without re-evaluating the AI response       |
| `payout_completed`       | Payout workflow completed                                                    |

Terminal states include `lost`, `lost_round_closed`, and `payout_completed`.

A payment made before a round closes is not silently discarded simply because another player wins while the AI request is in progress. The result is evaluated against the round's state when the attempt tries to claim the win.

**Payout status describes the existing payout workflow; it should not be interpreted as proof that real Solana prize transfers have been implemented.**

---

## Data Model

The application uses seven tables.

| Table                    | Purpose                                                                    |
| ------------------------ | -------------------------------------------------------------------------- |
| `players`                | Player wallet identity                                                     |
| `rounds`                 | Round configuration, prize details, required burn, status, and secret hash |
| `burn_transactions`      | Verified payment transactions, keyed by transaction signature              |
| `attempts`               | The central attempt record                                                 |
| `ai_responses`           | AI request and response records                                            |
| `payout_transactions`    | Records for the existing payout workflow                                   |
| `attempt_status_history` | Audit trail of attempt status transitions                                  |

Important database-level guarantees include:

| Requirement                           | Mechanism                                                             |
| ------------------------------------- | --------------------------------------------------------------------- |
| A burn cannot fund multiple attempts  | Unique transaction signature and unique burn-transaction relationship |
| Idempotent processing                 | Transaction signature used as the idempotency key                     |
| At most one winning attempt per round | Database uniqueness constraint/index                                  |
| No duplicate payout records           | Unique round and attempt constraints on payout records                |
| Consistent round closure              | Database constraints on round status and closure fields               |
| Status history                        | Records of attempt state transitions                                  |

`schema_postgres.sql` contains the generated PostgreSQL DDL for review.

---

## How a Request Flows Through the System

`POST /api/attempts` delegates to `game_service.submit_attempt`.

1. **Idempotency check:** If the transaction signature has already been processed, the existing attempt is returned.
2. **Payment verification:** The selected chain client retrieves the transaction's burn information. The service checks the configured token and required amount.
3. **Record creation:** The player, burn transaction, and attempt are recorded, and the relevant status history is updated.
4. **AI request:** The broker system prompt and player's message are sent to the selected AI client. A failed request leaves the attempt in a retryable state.
5. **Verdict evaluation:** The service retrieves the plaintext secret through the secrets provider and checks it against the stored hash before evaluating the broker's reply.
6. **Win claim:** The service attempts to claim the round for the winning attempt. Database constraints protect against multiple winners when attempts race.
7. **Payout handling:** The existing service contains a payout workflow. Real Solana prize-transfer submission is not implemented by `SolanaBurnVerifier`.

The round is not held locked across the AI call. This prevents a slow AI response from forcing all attempts for the same round to wait behind one long-running operation.

---

## AI Broker and Prompt Hardening

The broker, Marlowe, is defined in `app/services/broker_prompt.py`. The current prompt is versioned so that previously stored AI responses can be interpreted in the context of the prompt used at the time.

Key design decisions:

* The secret code is not included in the broker's system prompt.
* The backend evaluates the broker's response independently.
* Refusals should not reveal hints about the secret or internal implementation.
* The broker should describe only established game mechanics and should not invent bonuses, attempts, or other mechanics.
* `MiniMaxClient` requests disabled reasoning output and strips `<think>...</think>` blocks from returned content.
* `attack_corpus.py` contains adversarial messages for testing.
* `prompt_eval.py` provides heuristic checks for common prompt and architecture leakage patterns.

When changing the prompt, add a new version constant instead of silently replacing an old version. This helps keep stored prompt records interpretable.

---

## Current Limitations

The backend has automated tests for its application logic, including focused tests for Solana burn verification. The following limitations remain relevant to deployment.

### 1. Real Solana burn verification is implemented, but live-network verification must be tested

`app/services/solana_chain.py` implements `SolanaBurnVerifier`.

The verifier uses Solana JSON-RPC to retrieve transaction details and checks supported SPL Token and Token-2022 burn instructions against the configured project-token mint.

It validates relevant transaction details, including transaction success, signer/owner information, token mint, and burn amount.

The automated verifier tests mock RPC responses. They establish that the tested validation paths work, but do not replace integration testing against a real Solana RPC endpoint and known transactions.

### 2. Real prize transfers are not implemented by the Solana verifier

`SolanaBurnVerifier` verifies burns through `get_burn(tx_hash)`. It does not implement `submit_payout()`.

The existing game service has a payout workflow and expects a chain client with the required payout interface when that workflow is reached. Consequently, the burn-verification integration must not be described as a complete real-payment-and-payout implementation.

### 3. Secrets are stored in process memory

`MutableInMemorySecretsProvider` does not persist across restarts and is not shared across multiple worker processes. A persistent deployment needs a suitable secrets-management implementation.

### 4. Attempt processing is synchronous

`POST /api/attempts` waits for processing to finish. There is no background worker automatically polling actionable attempts and running retry functions.

### 5. No database migrations are configured

The schema is currently created from the models using `db.create_all()`. Alembic migrations are not configured.

### 6. MiniMax deployment configuration must be confirmed

The default model and API endpoint should be confirmed for the intended deployment.

### 7. Production API controls need deployment configuration

The development server is not a production WSGI server. Configure the intended frontend origin and production access controls before deployment.

---

## Before Production

* [ ] Test Solana burn verification against a real RPC endpoint and known transactions for the configured project-token mint.
* [ ] Verify that the runtime selects the intended chain client and does not silently fall back to mock verification.
* [ ] Implement and test real Solana prize-transfer handling if real payouts are required.
* [ ] Replace in-memory secret storage with a persistent, appropriately managed secrets provider.
* [ ] Disable development-only administration endpoints outside local development.
* [ ] Add background processing for retryable AI and payout states.
* [ ] Consider asynchronous attempt submission and status polling for longer-running requests.
* [ ] Set up database migrations.
* [ ] Run the complete test suite against PostgreSQL.
* [ ] Confirm the intended MiniMax model and API endpoint.
* [ ] Restrict `CORS_ALLOWED_ORIGINS` to the intended frontend origin.
* [ ] Use a production WSGI server rather than Flask's development server.
* [ ] Run the live MiniMax smoke test and review its transcripts.
