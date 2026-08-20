-- Add Google refresh token storage for per-user Google Drive authentication
ALTER TABLE users ADD COLUMN google_refresh_token TEXT;

CREATE INDEX IF NOT EXISTS idx_users_google_token ON users (google_refresh_token);
