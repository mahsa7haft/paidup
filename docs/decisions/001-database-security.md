---
title: Database security — least-privilege web role, backups, parameterized SQL
status: Accepted
date: 2026-06-24
---

## Context

Security audit of PaidUp and paidup-intelligence (June 2026), prompted by the
question: *can a database be deleted from a chat / agent?*

PaidUp's code came out clean:

```
.env tracked in git ............ no (gitignored) ✓
destructive SQL in code ........ none ✓
schema ops ..................... CREATE TABLE IF NOT EXISTS only ✓
SQL injection (string SQL) ..... none — all queries parameterized (psycopg2 %s) ✓
```

So the risk is not the code. PaidUp is **public-facing with an LLM in the request
path** (`/analyze`, `/lookup`), which makes it a larger attack surface than the
intelligence service:

1. **Single superuser connection.** PaidUp connects via one `DATABASE_URL`, which on
   Railway is the superuser. The web app only ever needs to read reference data and
   read/write the `analyses` table. It never needs `DROP`. Anything that obtains that
   connection — a bug, a compromised dependency, an injected query — has full power.
2. **Prompt injection through `/analyze`.** User input reaches an LLM (`ai.py`). A
   crafted prompt could try to make the model emit malicious output. This only
   becomes dangerous if model output is ever turned into SQL — which today it is not.
3. **No recovery path.** The sibling intelligence service lost its database to a
   disk-full crash with no PITR/backup (see that repo's ADR 011). PaidUp holds
   user-generated `analyses` that are *not* re-derivable — losing them is worse.

## Decision

### 1. Least-privilege web role (hard control)

Create a role for the app that can read everything and write only `analyses` —
no `DROP`, no `DELETE` on reference tables. Then even a compromised or injected
query path cannot drop a table or wipe reference data; Postgres rejects it.

```sql
CREATE ROLE paidup_web LOGIN PASSWORD 'xxx';
GRANT CONNECT ON DATABASE railway TO paidup_web;
GRANT USAGE ON SCHEMA public TO paidup_web;

-- read reference data
GRANT SELECT ON ALL TABLES IN SCHEMA public TO paidup_web;

-- write only the analyses cache
GRANT INSERT, UPDATE ON analyses TO paidup_web;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO paidup_web;
```

`ensure_tables()` (which runs `CREATE TABLE`) needs DDL, so it must run as a more
privileged role. Run it once during deploy/migration as the owner, not on every
app start under `paidup_web`. Until that split is made, `ensure_tables()` stays on
the owner connection and the request-handling code uses `paidup_web`.

| Path | Role | Privileges |
|---|---|---|
| Request handlers (`/lookup`, `/analyze`, `/card`) | `paidup_web` | SELECT all + INSERT/UPDATE `analyses` |
| `ensure_tables()` / migrations | owner | DDL |
| One-off admin | superuser | full — manual psql only, never in app env |

SQL lives in `docs/security-roles.sql`.

### 2. Backups (recovery control)

Enable Railway automated backups on `paidup-postgres`. The `analyses` table is
user-generated and not re-derivable. This is the undo button the intelligence crash
proved we lacked.

### 3. Credential separation

- Superuser string never lives in the app's `.env` or Railway service env — manual
  psql admin only.
- App env carries only the `paidup_web` role.
- Never commit real credentials.

### Invariant to preserve

**Model output is never interpolated into SQL.** Every query uses psycopg2
parameter placeholders (`%s`). This is what stops prompt injection through the LLM
from becoming SQL injection. Any new query path must keep this invariant.

## Consequences

**Good:**
- A compromised/injected request path *cannot* drop tables or wipe reference data —
  enforced by Postgres, not by hoping the LLM behaves
- Backups give a recovery path for non-re-derivable user data
- Leaked app credentials are bounded to `paidup_web`'s privileges

**Watch out for:**
- `ensure_tables()` needs DDL — must run as owner, not `paidup_web`. Splitting this
  out is the one code change required; until then keep table creation on the owner
  connection.
- `ALTER DEFAULT PRIVILEGES` only covers tables made by the granting role — re-grant
  if a new table is created by a different role.

## Related

- paidup-intelligence ADR 013 — same hardening for the vector/agent service
- paidup-intelligence ADR 011 — the crash that proved we had no recovery path
