-- Shared cross-app SSO session store. Lets a second app on the same host
-- (the TAM Dashboard's Express proxy) recognize a signed-in user by calling
-- this app's /internal/sso/verify with the token from a shared cookie,
-- rather than replicating Flask's itsdangerous cookie-signing scheme.
-- Distinct from Flask's own `daily_brief_session` cookie, which stays
-- path-scoped to this app and holds only its own CSRF state / post-login
-- redirect — nothing another app needs.
CREATE TABLE IF NOT EXISTS sso_sessions (
    token        TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sso_sessions_user ON sso_sessions (user_id);
-- Used by a future cleanup pass to find expired rows without a full table scan.
CREATE INDEX IF NOT EXISTS idx_sso_sessions_expires ON sso_sessions (expires_at);
