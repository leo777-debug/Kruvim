-- Observed PostgreSQL delta rehearsal, 19 November 2026.
-- Creates only a new schema, clones schema shape (no customer rows), tests DDL,
-- then rolls the entire transaction back. Requires production baseline 0019.
BEGIN;
CREATE SCHEMA release_verify_20261119_a7c4;
SET LOCAL search_path TO release_verify_20261119_a7c4, pg_temp;
CREATE TABLE users (LIKE kruvim.users INCLUDING ALL);
INSERT INTO users (id,email,name,password_hash,is_active,is_superuser,created_at) VALUES ('release-fixture','release-fixture@example.invalid','Fixture','fixture-only',true,false,now());
CREATE TABLE alembic_version(version_num varchar(32) PRIMARY KEY);
INSERT INTO alembic_version VALUES('0019');

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

DO $$ BEGIN
IF (SELECT version_num FROM alembic_version) <> '0021' OR NOT EXISTS (SELECT 1 FROM users WHERE id='release-fixture' AND auth_version=0 AND password_hash='fixture-only') THEN RAISE EXCEPTION 'Upgrade data/default assertion failed'; END IF;
IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='release_verify_20261119_a7c4' AND c.relname IN ('account_tokens','mail_outbox','rate_counters') AND c.relrowsecurity) <> 3 THEN RAISE EXCEPTION 'Security table/RLS assertion failed'; END IF;
END $$;

-- Running downgrade 0021 -> 0019

DROP TABLE rate_counters;

DROP TABLE mail_outbox;

DROP TABLE account_tokens;

ALTER TABLE users DROP COLUMN auth_version;

ALTER TABLE users DROP COLUMN email_verified_at;

UPDATE alembic_version SET version_num='0019' WHERE alembic_version.version_num = '0021';

DO $$ BEGIN
IF (SELECT version_num FROM alembic_version) <> '0019' OR NOT EXISTS (SELECT 1 FROM users WHERE id='release-fixture' AND password_hash='fixture-only') OR EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='release_verify_20261119_a7c4' AND table_name='users' AND column_name='auth_version') THEN RAISE EXCEPTION 'Rollback data/schema assertion failed'; END IF;
END $$;

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

DO $$ BEGIN
IF (SELECT version_num FROM alembic_version) <> '0021' OR NOT EXISTS (SELECT 1 FROM users WHERE id='release-fixture' AND auth_version=0 AND password_hash='fixture-only') THEN RAISE EXCEPTION 'Upgrade data/default assertion failed'; END IF;
IF (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='release_verify_20261119_a7c4' AND c.relname IN ('account_tokens','mail_outbox','rate_counters') AND c.relrowsecurity) <> 3 THEN RAISE EXCEPTION 'Security table/RLS assertion failed'; END IF;
END $$;
ROLLBACK;
SELECT 'passed: PostgreSQL 0019 -> 0021 -> 0019 -> 0021, synthetic user preserved, RLS verified, all test DDL rolled back' AS result, to_regnamespace('release_verify_20261119_a7c4') IS NULL AS isolated_schema_removed, (SELECT version_num FROM kruvim.alembic_version) AS production_revision;
