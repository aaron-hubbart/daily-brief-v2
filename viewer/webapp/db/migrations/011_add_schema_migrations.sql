-- Migration 011: Track which migrations have been applied.
--
-- Migration 010 shipped a db.touch_last_active() call on every authenticated
-- request without the migration itself being applied in production, which
-- 500'd every authenticated page until caught and fixed by hand. app.py now
-- refuses to start if db/migrations/*.sql contains a file not recorded here
-- (see db.get_pending_migrations), so that gap fails loudly at deploy time
-- instead of silently at request time.
--
-- Applying this migration assumes 001-010 are already applied in this
-- database (true for any database the app is currently running against,
-- since the app wouldn't function otherwise) -- it seeds them as already
-- applied rather than re-running them.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,  -- migration filename, e.g. '010_add_last_active_at.sql'
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES
    ('001_add_api_token.sql'),
    ('002_add_onboarding_completed.sql'),
    ('003_add_asana_pat.sql'),
    ('004_add_account_projects.sql'),
    ('005_add_google_refresh_token.sql'),
    ('006_add_google_drive_folder_id.sql'),
    ('007_drop_api_token_and_account_projects.sql'),
    ('008_add_sso_sessions.sql'),
    ('009_add_notification_prefs.sql'),
    ('010_add_last_active_at.sql'),
    ('011_add_schema_migrations.sql')
ON CONFLICT (version) DO NOTHING;
-- Down (rollback)
-- DROP TABLE schema_migrations;
