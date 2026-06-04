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
  → cache.get("paidup:lookup:{name}")   return immediately if hit
  → search_mp()           Parliament Members API — find member ID, name, party
  → get_interests()       Parliament Interests API — all declared financial interests
  → parse_interests()     normalise fields, extract donor/value/date/category
  → deduplicate_donors()  fuzzy-merge near-identical donor names (see below)
  → get_biography()       Parliament Members API — committees, career posts
  → parse_biography()     extract current committees, govt/opposition posts
  → get_twfy_data()       TheyWorkForYou API — voting stats, APPG roles (optional)
  → cache.set(result, ttl=1h)
  → return JSON

Browser POST /analyze
  → cache.get("paidup:analyze:{id}:{prompt_key}:{version}")   return if hit
  → analyze() in ai.py
      → loads prompt from prompts/{key}_v{n}.txt
      → builds structured user message with all MP context
      → calls claude-sonnet-4-6 via Anthropic SDK
  → cache.set(result, ttl=24h)
  → return plain text

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
| `cache.py` | Redis wrapper. Returns `None` / no-ops silently when Redis is unavailable. |

## Key design decisions

### Caching

`cache.py` wraps Redis with a graceful no-op fallback — when `REDIS_URL` is unset or Redis is unreachable the app behaves identically, just without caching. TTLs:

| Route | Key | TTL |
|---|---|---|
| `/lookup` | `paidup:lookup:{normalised_name}` | 1 hour |
| `/analyze` | `paidup:analyze:{member_id}:{prompt_key}:{prompt_version}` | 24 hours |

The prompt version is included in the analyze key deliberately — bumping `summary_v1.txt` to `summary_v2.txt` changes the key and therefore invalidates stale cached results automatically.

Cached responses include `"_cached": true` so you can spot them in the browser network tab.

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
3. Restart — the new version is picked up and the old analysis cache is automatically invalidated
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
| `REDIS_URL` | No | Enables caching; Railway Redis plugin sets this automatically |
| `PORT` | No | Defaults to 5002; Railway sets this automatically |
