-- For installs that already have a running Postgres from before api_token
-- existed (schema.sql only auto-applies on the very first init — see
-- DEPLOYMENT.md). Safe to run more than once (IF NOT EXISTS throughout).
--
-- Apply with:
--   kubectl exec -i -n daily-brief postgres-0 -- \
--     psql -U dailybrief -d dailybrief < viewer/webapp/db/migrations/001_add_api_token.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token TEXT UNIQUE;
CREATE INDEX IF NOT EXISTS idx_users_api_token ON users (api_token);

-- Existing users don't get backfilled here on purpose — get_or_create_user
-- in db.py assigns a token lazily the next time each of them signs in
-- (COALESCE-guarded, so it's a no-op for anyone who already has one). No
-- separate backfill pass needed; just have them sign in once after this
-- migration runs.
