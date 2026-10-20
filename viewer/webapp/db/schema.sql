-- Daily Brief storage schema.
--
-- Replaces the old file-based data/{user-slug}/Daily Brief_*.html model.
-- Structured by user -> day -> item, so a single item (one meeting row, one
-- account's customer-update card, the manager update) can be created or
-- refreshed independently via an upsert, and a day's brief is rendered
-- dynamically from current rows at request time rather than read back as a
-- static pre-built file.

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    slug        TEXT NOT NULL UNIQUE,
    -- Per-user Asana Personal Access Token — see migrations/003_add_asana_pat.sql
    -- for what it's used for. NULL means the person skipped that step of
    -- setup; the webapp treats that as "live Action Items pull disabled."
    asana_pat   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Set once the person has clicked through the in-app setup walkthrough
    -- (or dismissed it). NULL means "show it automatically on next login."
    onboarding_completed_at TIMESTAMPTZ,
    -- Admin-created throwaway account for testing the new-user experience
    -- via impersonation (see migrations/007_...sql) — never a real person.
    is_test     BOOLEAN NOT NULL DEFAULT FALSE,
    -- Slack notification preferences — see migrations/009_add_notification_prefs.sql.
    -- Whether this user wants Slack notifications sent to them, and which
    -- channel/DM id to send them to (NULL until they configure it).
    slack_notify_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    slack_notify_channel_id TEXT,
    -- Bumped to now() on every authenticated request (see login_required in
    -- app.py) — see migrations/010_add_last_active_at.sql. NULL until the
    -- person's first request after this column existed.
    last_active_at TIMESTAMPTZ,
    -- How many recent brief dates /api/briefs returns — see
    -- migrations/012_add_max_briefs_to_load.sql.
    max_briefs_to_load INTEGER NOT NULL DEFAULT 10
        CHECK (max_briefs_to_load BETWEEN 1 AND 20)
);

-- One row per user per calendar date. This is the "day" the requirement
-- describes -- multiple runs/refreshes during the day update items within
-- the same brief_day row rather than creating parallel snapshot rows,
-- since items are now individually upsertable instead of whole-file
-- replacements.
CREATE TABLE IF NOT EXISTS brief_days (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    brief_date      DATE NOT NULL,
    brief_type      TEXT,                         -- 'morning' | 'midday' | 'evening', informational only
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at     TIMESTAMPTZ,
    UNIQUE (user_id, brief_date)
);

CREATE INDEX IF NOT EXISTS idx_brief_days_user_date ON brief_days (user_id, brief_date DESC);
-- Used by the daily archive job to find candidates without a full table scan.
CREATE INDEX IF NOT EXISTS idx_brief_days_status_date ON brief_days (status, brief_date);

-- One row per item within a day: a meeting, an account recap entry, a
-- customer-update card, the manager update, an FYI line, etc. `section`
-- is one of the fixed slugs the daily-brief skill already uses
-- (yesterday-meetings, account-recap, today, action-items, fyi,
-- customer-updates, manager-update). `content` is JSONB so different
-- section types (a checkable row vs. an editable account-update card) can
-- carry different shaped payloads without needing separate tables per type.
CREATE TABLE IF NOT EXISTS items (
    id            SERIAL PRIMARY KEY,
    brief_day_id  INTEGER NOT NULL REFERENCES brief_days(id) ON DELETE CASCADE,
    section       TEXT NOT NULL,
    item_key      TEXT NOT NULL,                  -- e.g. 'ym-1', 'cust-update-acme-financial', 'mgr-update'
    item_type     TEXT NOT NULL DEFAULT 'checkable' CHECK (item_type IN ('checkable', 'card', 'fyi', 'text-block')),
    title         TEXT,
    subtitle      TEXT,
    badge         JSONB,                          -- {"label": "overdue", "class": "bbad"} or null
    links         JSONB NOT NULL DEFAULT '[]',     -- [{"label": "Open PR #112", "url": "...", "class": "lbtn primary"}]
    content       JSONB NOT NULL DEFAULT '{}',     -- type-specific payload (see db/README.md)
    checked       BOOLEAN,                         -- null for non-checkable item types
    display_order INTEGER NOT NULL DEFAULT 0,
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),  -- when this item's content was last (re)generated
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brief_day_id, section, item_key)
);

CREATE INDEX IF NOT EXISTS idx_items_brief_day ON items (brief_day_id, section, display_order);

-- Shared cross-app SSO session store — see migrations/008_add_sso_sessions.sql
-- for why this exists (lets the TAM Dashboard's Express proxy recognize a
-- signed-in user via /internal/sso/verify instead of replicating Flask's
-- own cookie-signing scheme).
CREATE TABLE IF NOT EXISTS sso_sessions (
    token        TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sso_sessions_user ON sso_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sso_sessions_expires ON sso_sessions (expires_at);

-- Tracks which db/migrations/*.sql files have been applied -- see
-- migrations/011_add_schema_migrations.sql and db.get_pending_migrations.
-- app.py refuses to start if a migration file exists on disk that isn't
-- recorded here, so a schema change can't silently go live without being
-- applied (see migration 011's comment for the incident this prevents).
-- A fresh install via this file already has every column/table below, so
-- every migration up to this schema's own revision is seeded as applied.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
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
    ('011_add_schema_migrations.sql'),
    ('012_add_max_briefs_to_load.sql')
ON CONFLICT (version) DO NOTHING;

