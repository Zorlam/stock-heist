CREATE TABLE players (
	id UUID NOT NULL, 
	wallet_address VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_players_wallet_address ON players (wallet_address);

CREATE TABLE rounds (
	id UUID NOT NULL, 
	status VARCHAR(9) NOT NULL, 
	asset_symbol VARCHAR(32) NOT NULL, 
	asset_token_contract VARCHAR(255) NOT NULL, 
	prize_amount NUMERIC(38, 18) NOT NULL, 
	project_token_contract VARCHAR(255) NOT NULL, 
	burn_amount NUMERIC(38, 18) NOT NULL, 
	secret_code_hash VARCHAR(255) NOT NULL, 
	secret_code_salt VARCHAR(64) NOT NULL, 
	opened_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	winning_attempt_id UUID, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_round_closed_at_consistency CHECK ((status = 'open' AND closed_at IS NULL) OR (status != 'open' AND closed_at IS NOT NULL)), 
	CONSTRAINT ck_round_prize_amount_positive CHECK (prize_amount > 0), 
	CONSTRAINT ck_round_burn_amount_positive CHECK (burn_amount > 0), 
	UNIQUE (winning_attempt_id)
);

CREATE INDEX ix_rounds_status ON rounds (status);

CREATE TABLE burn_transactions (
	id UUID NOT NULL, 
	tx_hash VARCHAR(255) NOT NULL, 
	wallet_address VARCHAR(255) NOT NULL, 
	round_id UUID NOT NULL, 
	token_contract VARCHAR(255) NOT NULL, 
	amount NUMERIC(38, 18) NOT NULL, 
	status VARCHAR(9) NOT NULL, 
	block_number BIGINT, 
	submitted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	confirmed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_burn_amount_positive CHECK (amount > 0), 
	FOREIGN KEY(round_id) REFERENCES rounds (id)
);

CREATE INDEX ix_burn_transactions_round_id ON burn_transactions (round_id);

CREATE UNIQUE INDEX ix_burn_transactions_tx_hash ON burn_transactions (tx_hash);

CREATE INDEX ix_burn_transactions_wallet_address ON burn_transactions (wallet_address);

CREATE INDEX ix_burn_transactions_round_status ON burn_transactions (round_id, status);

CREATE INDEX ix_burn_transactions_status ON burn_transactions (status);

CREATE TABLE attempts (
	id UUID NOT NULL, 
	round_id UUID NOT NULL, 
	player_id UUID NOT NULL, 
	burn_transaction_id UUID NOT NULL, 
	message TEXT NOT NULL, 
	status VARCHAR(22) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(round_id) REFERENCES rounds (id), 
	FOREIGN KEY(player_id) REFERENCES players (id), 
	UNIQUE (burn_transaction_id), 
	FOREIGN KEY(burn_transaction_id) REFERENCES burn_transactions (id)
);

CREATE INDEX ix_attempts_player_created ON attempts (player_id, created_at);

CREATE INDEX ix_attempts_round_id ON attempts (round_id);

CREATE INDEX ix_attempts_status ON attempts (status);

CREATE INDEX ix_attempts_round_status ON attempts (round_id, status);

CREATE UNIQUE INDEX ix_one_winner_per_round ON attempts (round_id) WHERE status = 'won';

CREATE INDEX ix_attempts_player_id ON attempts (player_id);

CREATE TABLE ai_responses (
	id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	model_used VARCHAR(64) NOT NULL, 
	prompt_sent TEXT, 
	raw_response TEXT, 
	is_match BOOLEAN, 
	requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	received_at TIMESTAMP WITH TIME ZONE, 
	evaluated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (attempt_id), 
	FOREIGN KEY(attempt_id) REFERENCES attempts (id)
);

CREATE TABLE payout_transactions (
	id UUID NOT NULL, 
	round_id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	wallet_address VARCHAR(255) NOT NULL, 
	asset_token_contract VARCHAR(255) NOT NULL, 
	amount NUMERIC(38, 18) NOT NULL, 
	tx_hash VARCHAR(255), 
	status VARCHAR(9) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	confirmed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_payout_amount_positive CHECK (amount > 0), 
	UNIQUE (round_id), 
	FOREIGN KEY(round_id) REFERENCES rounds (id), 
	UNIQUE (attempt_id), 
	FOREIGN KEY(attempt_id) REFERENCES attempts (id), 
	UNIQUE (tx_hash)
);

CREATE INDEX ix_payout_transactions_status ON payout_transactions (status);

CREATE TABLE attempt_status_history (
	id UUID NOT NULL, 
	attempt_id UUID NOT NULL, 
	from_status VARCHAR(22), 
	to_status VARCHAR(22) NOT NULL, 
	note TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(attempt_id) REFERENCES attempts (id)
);

CREATE INDEX ix_attempt_status_history_created_at ON attempt_status_history (created_at);

CREATE INDEX ix_attempt_status_history_attempt_id ON attempt_status_history (attempt_id);

ALTER TABLE rounds ADD CONSTRAINT fk_round_winning_attempt FOREIGN KEY(winning_attempt_id) REFERENCES attempts (id);
