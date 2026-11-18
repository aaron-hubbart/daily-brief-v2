-- Migration 013: Add item_subchecks for checkable bucket bullets / sub-items
-- Up
CREATE TABLE IF NOT EXISTS item_subchecks (
    id            SERIAL PRIMARY KEY,
    brief_day_id  INTEGER NOT NULL REFERENCES brief_days(id) ON DELETE CASCADE,
    section       TEXT NOT NULL,
    item_key      TEXT NOT NULL,
    subitem_key   TEXT NOT NULL,
    checked       BOOLEAN NOT NULL DEFAULT false,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brief_day_id, section, item_key, subitem_key)
);
CREATE INDEX IF NOT EXISTS idx_item_subchecks_lookup ON item_subchecks (brief_day_id, section, item_key);

INSERT INTO schema_migrations (version) VALUES ('013_add_item_subchecks.sql')
ON CONFLICT (version) DO NOTHING;
-- Down (rollback)
-- DROP TABLE item_subchecks;
