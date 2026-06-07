# CLAUDE.md — PaidUp

This file is for Claude Code. It documents the run commands, architecture, and non-obvious design decisions that aren't obvious from reading individual files.

## Run commands

```bash
# Install dependencies
uv sync

# Run locally
PYTHONPATH=src uv run python -m app.main
# → http://localhost:5002

# Run on a custom port
PORT=8080 PYTHONPATH=src uv run python -m app.main
```

## Architecture

### Request flow

```
Browser POST /lookup
  → L1 cache.get("paidup:lookup:{name}")   return immediately if hit (Redis)
  → search_mp()           Parliament Members API — find member ID, name, party
  → get_interests()       Parliament Interests API — all declared financial interests
  → parse_interests()     normalise fields, extract donor/value/date/category
  → deduplicate_donors()  fuzzy-merge near-identical donor names (see below)
  → get_biography()       Parliament Members API — committees, career posts
  → parse_biography()     extract current committees, govt/opposition posts
  → get_twfy_data()       TheyWorkForYou API — voting stats, APPG roles (optional)
  → cache.set(result, ttl=1h)
  → return JSON

Browser POST /analyze  ← two-level cache
  → L1 cache.get(...)                  Redis, 24h TTL
  → L2 db.get_analysis(...)            Postgres analyses table, 28-day TTL
  → analyze() in ai.py                 Claude API — only reached on full miss
      → loads prompt from prompts/{key}_v{n}.txt
      → calls claude-sonnet-4-6
  → db.save_analysis(...)              write to Postgres
  → cache.set(...)                     write to Redis
  → return text

GET /card/{member_id}
  → fetches interests (same pipeline as /lookup, no cache)
  → aggregate donors by name, compute proportional circle radii
  → overlays circular badges on MP photo in suit area (Pillow)
  → returns PNG
```

### Module responsibilities

| File | Responsibility |
|---|---|
| `main.py` | Flask routes only. Orchestrates calls to other modules; no business logic. |
| `parliament.py` | All UK Parliament API calls (Members + Interests). Also owns `deduplicate_donors`. |
| `theyworkforyou.py` | TheyWorkForYou API. Always returns `None` gracefully if key not set. |
| `ai.py` | Anthropic SDK call. Loads prompts from disk at call time (not cached in memory). |
| `card.py` | Pillow image generation. Reads from no external state except the MP photo URL. |
| `cache.py` | Redis wrapper (L1). Returns `None` / no-ops silently when Redis is unavailable. |
| `database.py` | PostgreSQL layer (L2). Stores AI analyses for 28 days. No-ops when DATABASE_URL is unset. |

## Key design decisions

### Two-level cache for `/analyze`

`/analyze` uses L1 (Redis, 24h) → L2 (Postgres, 28 days) → Claude API.

- **L1 Redis**: answers "did someone ask this in the last 24 hours?" — instant, in-memory
- **L2 Postgres**: answers "have we ever run this analysis and is it still fresh?" — persistent across restarts and deploys
- **Claude**: only reached when both miss — the expensive call

On an L2 hit, Redis is repopulated so the next request doesn't reach Postgres either.

The `_cached` field in the response shows which layer served it (`"redis"`, `"db"`, or absent for a fresh Claude call) — visible in the browser network tab.

### Why 28 days for Postgres TTL

Parliament's Register of Members' Financial Interests is updated within 28 days of any change. After 28 days an analysis result could reference stale data so it is discarded and regenerated.

### Prompt version in cache keys

Both the Redis key and the Postgres query include `prompt_version`. Bumping `summary_v1.txt` to `summary_v2.txt` changes the version, which changes the Redis key (cache miss) and fails the Postgres WHERE clause (DB miss), so Claude is always called fresh after a prompt edit.

### Deduplication happens at the `lookup` level, not in `parse_interests`

`parse_interests` produces one dict per raw register entry — it does no grouping. `deduplicate_donors` is called in `main.py` after parsing, so the deduplicated names flow through to the JSON response, the card, and the AI context consistently. If you call `parse_interests` elsewhere (e.g. the `/card` route), call `deduplicate_donors` on the result too.

### Constituency can be an empty string

`mp.get("memberFrom", "")` returns `""` for some serving MPs (e.g. the Prime Minister). The `/analyze` validation checks `"interests" not in data`, not that constituency is truthy. Do not tighten this to a truthiness check.

### TheyWorkForYou is optional

`get_twfy_data()` returns `None` if `THEYWORKFORYOU_API_KEY` is not set. All callers handle `None` gracefully. The UI hides the TWFY stats section when `twfy` is null.

### Prompt versioning

Prompts live in `src/app/prompts/` as plain text files named `{key}_v{n}.txt`. `ai.py` scans the directory at call time and picks the highest version number for each key. To experiment:

1. Copy `summary_v1.txt` → `summary_v2.txt`
2. Edit freely
3. Restart — the new version is picked up and both caches are automatically invalidated
4. The UI dropdown shows the version number

### Fuzzy donor deduplication

`deduplicate_donors` in `parliament.py` uses `rapidfuzz.fuzz.token_sort_ratio` at a threshold of 88 to cluster near-identical donor names. The canonical name is whichever variant appeared first in the sorted-by-value list. Merged variants are stored in an `aliases` field and shown in the UI.

Known limitation: legal suffixes (`Ltd`, `Limited`, `plc`) can push similar names below the threshold. Fix planned: normalise suffixes before fuzzy comparison.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (for AI features) | sk-ant-... |
| `THEYWORKFORYOU_API_KEY` | No | Free at theyworkforyou.com/api/key |
| `FLASK_SECRET_KEY` | No (dev default exists) | Set to a long random string in production |
| `REDIS_URL` | No | L1 cache; Railway Redis plugin sets this automatically |
| `DATABASE_URL` | No | L2 persistent store; Railway Postgres plugin sets this automatically |
| `PORT` | No | Defaults to 5002; Railway sets this automatically |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse observability — token usage, cost, latency per Claude call |
| `LANGFUSE_SECRET_KEY` | No | Langfuse observability — token usage, cost, latency per Claude call |
| `LANGFUSE_HOST` | No | Defaults to `https://cloud.langfuse.com`; set for self-hosted |
