-- Migration 009: Add Slack notification preferences
-- Up
ALTER TABLE users ADD COLUMN slack_notify_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN slack_notify_channel_id TEXT;
-- Down (rollback)
-- ALTER TABLE users DROP COLUMN slack_notify_enabled;
-- ALTER TABLE users DROP COLUMN slack_notify_channel_id;
