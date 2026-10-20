# Stock Heist API

A Flask-based backend for Stock Heist, a game that integrates AI interactions with Solana token-burn verification and round-based gameplay.

## Features

* **Game rounds:** Manage rounds, prizes, and gameplay state.
* **Solana verification:** Verify token-burn transactions and validate token mints and burn amounts.
* **AI Broker:** Process player messages through an AI client.
* **Game logic:** Manage attempts, determine outcomes, and prevent multiple winning attempts in the same round.
* **Database:** Store game data, transactions, and attempt history.

## Tech Stack

* Python
* Flask
* SQLAlchemy
* PostgreSQL
* Solana RPC integration
* Pytest
github actions

## Getting Started

### 1. Clone the repository

```bash
git clone <repository-url>
cd <repository-directory>
```

### 2. Set up a virtual environment

```bash
python -m venv venv
```

Activate it:

**Windows**

```bash
venv\Scripts\activate
```

**Linux/macOS**

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Configure the required environment variables for the database, Solana RPC connection, and other application services.

### 4. Run the API

Start the Flask application using the project's configured entry point.

The development server has previously been run at:

```text
http://127.0.0.1:5000 (On your browser)
```

## API Usage

### Submit a Game Attempt

**Endpoint:** `POST /api/attempts`

Submit a player attempt using a Solana transaction hash and a message for the AI Broker.

Example request body:

```json
{
  "round_id": "<round-id>",
  "tx_hash": "<solana-transaction-signature>",
  "message": "Your message to the AI Broker"
}
```

The backend verifies the transaction, checks the required burn amount, records the attempt, and processes the game logic.

## Running Tests

Run the test suite with:

```bash
python -m pytest -q
```

Run the Solana verification tests separately:

```bash
python -m pytest tests/test_solana_chain.py -q
```

## Development Status

The backend includes game logic, AI integration, database operations, and Solana burn-verification functionality. Runtime configuration and external service integrations should be verified in the target environment before any deployment
