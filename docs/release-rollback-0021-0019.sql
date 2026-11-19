BEGIN;

-- Running downgrade 0021 -> 0019

DROP TABLE rate_counters;

DROP TABLE mail_outbox;

DROP TABLE account_tokens;

ALTER TABLE users DROP COLUMN auth_version;

ALTER TABLE users DROP COLUMN email_verified_at;

UPDATE alembic_version SET version_num='0019' WHERE alembic_version.version_num = '0021';

COMMIT;

