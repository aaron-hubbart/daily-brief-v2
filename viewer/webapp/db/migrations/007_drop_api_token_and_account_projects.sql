-- Decommission the v1 bearer-token/MCP-connector sync path (confirmed
-- fully unused — every user is on the v2 Drive-backed skill now) and add
-- support for admin-created throwaway test users (impersonation feature).

-- Postgres automatically drops any indexes/constraints defined directly on
-- a dropped column or table (idx_users_api_token, idx_account_projects_user,
-- and account_projects' own PK/unique constraints all go with it) — no
-- separate DROP INDEX statements needed.
ALTER TABLE users DROP COLUMN api_token;
DROP TABLE IF EXISTS account_projects;

ALTER TABLE users ADD COLUMN is_test BOOLEAN NOT NULL DEFAULT FALSE;
