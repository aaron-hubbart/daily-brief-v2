-- Add per-user Google Drive folder ID for storing briefs
ALTER TABLE users ADD COLUMN google_drive_folder_id TEXT;

CREATE INDEX IF NOT EXISTS idx_users_google_folder ON users (google_drive_folder_id);
