-- Mirror of the account -> Asana project GID mapping the daily-brief skill
-- already reads from Meeting Manager Config.xlsx (the Accounts sheet's
-- Asana Project GID column). The webapp has no Google Drive access of its
-- own, so it can't read that sheet directly to know which boards to poll
-- for the live Action Items pull (see app.py's _fetch_live_action_items).
--
-- The skill re-syncs this table on every brief run via the
-- daily_brief_sync_account_projects MCP tool, as a full replace-per-user —
-- see db.replace_account_projects. This keeps the webapp's copy from
-- drifting when accounts are added, renamed, or removed in the source
-- sheet, without the webapp ever touching Drive itself.
CREATE TABLE IF NOT EXISTS account_projects (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_name TEXT NOT NULL,
    project_gid  TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, account_name)
);

CREATE INDEX IF NOT EXISTS idx_account_projects_user ON account_projects (user_id);
