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
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
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
