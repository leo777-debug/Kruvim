BEGIN;

-- Running upgrade 0019 -> 0021

ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE users ADD COLUMN auth_version INTEGER DEFAULT '0' NOT NULL;

CREATE TABLE account_tokens (
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    user_id VARCHAR(32) NOT NULL, 
    purpose VARCHAR(20) NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_account_tokens PRIMARY KEY (id), 
    CONSTRAINT fk_account_tokens_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
    CONSTRAINT uq_account_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_account_tokens_user_id ON account_tokens (user_id);

CREATE INDEX ix_account_tokens_created_at ON account_tokens (created_at);

CREATE TABLE mail_outbox (
    id VARCHAR(32) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    recipient VARCHAR(320) NOT NULL, 
    subject VARCHAR(200) NOT NULL, 
    encrypted_body TEXT NOT NULL, 
    attempts INTEGER NOT NULL, 
    next_attempt_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    delivered_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_mail_outbox PRIMARY KEY (id)
);

CREATE INDEX ix_mail_outbox_next_attempt_at ON mail_outbox (next_attempt_at);

CREATE INDEX ix_mail_outbox_created_at ON mail_outbox (created_at);

CREATE TABLE rate_counters (
    key VARCHAR(64) NOT NULL, 
    bucket INTEGER NOT NULL, 
    count INTEGER NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_rate_counters PRIMARY KEY (key, bucket)
);

CREATE INDEX ix_rate_counters_expires_at ON rate_counters (expires_at);

ALTER TABLE account_tokens ENABLE ROW LEVEL SECURITY;

ALTER TABLE mail_outbox ENABLE ROW LEVEL SECURITY;

ALTER TABLE rate_counters ENABLE ROW LEVEL SECURITY;

UPDATE alembic_version SET version_num='0021' WHERE alembic_version.version_num = '0019';

COMMIT;

