-- Migration 012: Add per-user "Max briefs to load" setting
-- Up
ALTER TABLE users ADD COLUMN max_briefs_to_load INTEGER NOT NULL DEFAULT 10
    CHECK (max_briefs_to_load BETWEEN 1 AND 20);

INSERT INTO schema_migrations (version) VALUES ('012_add_max_briefs_to_load.sql')
ON CONFLICT (version) DO NOTHING;
-- Down (rollback)
-- ALTER TABLE users DROP COLUMN max_briefs_to_load;
