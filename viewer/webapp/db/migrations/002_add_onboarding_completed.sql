-- For installs that already have a running Postgres from before the
-- in-app setup walkthrough existed (schema.sql only auto-applies on the
-- very first init — see DEPLOYMENT.md). Safe to run more than once
-- (IF NOT EXISTS throughout).
--
-- Apply with:
--   kubectl exec -i -n daily-brief postgres-0 -- \
--     psql -U dailybrief -d dailybrief < viewer/webapp/db/migrations/002_add_onboarding_completed.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;

-- Existing users don't get backfilled here on purpose — NULL means "show
-- the walkthrough on next login," which is a reasonable default even for
-- people who signed in before this existed. They can dismiss it in one
-- click same as anyone else, and re-open it any time from the Account
-- panel.
