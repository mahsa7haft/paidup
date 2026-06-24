-- PaidUp database security roles.
-- Run once in psql as the database owner/superuser. See docs/decisions/001-database-security.md
--
-- Usage:
--   psql "postgresql://<superuser>...@<host>/railway" -f docs/security-roles.sql
--
-- Tables are created by ensure_tables() in src/app/database.py. Run the app once
-- (or run ensure_tables manually) so the tables exist before granting on them.

-- ── Least-privilege web role ────────────────────────────────────────────────────
-- The request-handling code reads reference data and reads/writes the analyses
-- cache. It never needs DROP or DELETE. Replace 'CHANGE_ME' with a real password.

CREATE ROLE paidup_web LOGIN PASSWORD 'CHANGE_ME';

GRANT CONNECT ON DATABASE railway TO paidup_web;
GRANT USAGE   ON SCHEMA public    TO paidup_web;

-- Read all reference tables (members, donor_company_links, etc.)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO paidup_web;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO paidup_web;

-- Write only the analyses cache
GRANT INSERT, UPDATE ON analyses TO paidup_web;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO paidup_web;

-- ── After running ───────────────────────────────────────────────────────────────
-- 1. Build a connection string for paidup_web and set it as the app's DATABASE_URL
--    in the Railway PaidUp service.
-- 2. Keep ensure_tables() / migrations running as the owner role (DDL needs more
--    than paidup_web has) — see ADR 001.
-- 3. Enable Railway automated backups on paidup-postgres.
-- 4. Remove the superuser connection string from the app env — manual psql only.
