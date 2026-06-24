# PaidUp

**See who funds UK politicians.**

![PaidUp demo](demo.gif)

Search any MP by name and instantly see their declared financial interests — donors, gifts, hospitality, and shareholdings — pulled live from the official UK Parliament Register of Members' Financial Interests. Includes AI-powered analysis to surface conflicts of interest, donor profiles, and factional leanings.

> **Sister project:** [PaidUp Intelligence](https://github.com/mahsa7haft/paidup-intelligence) answers the reverse question — *"which MPs are funded by X?"* — using RAG and semantic search across Parliament and Electoral Commission data. See [Sister Project](#sister-project--paidup-intelligence) below.

## What it does

1. Search any MP by name
2. PaidUp fetches their declared financial interests live from the UK Parliament API
3. Generates a visual donor card — MP photo with sponsor-style badges on the suit, sized by donation amount
4. Each badge adapts to who the donor is:
   - **Company with logo** — real brand logo from Google Favicons
   - **Company without logo** — dark circle with two-letter initials
   - **Person** — dark green circle with person silhouette
   - **Unattributed** — dark grey circle with "?" (hover to see the combined total)
5. Hover any badge on the card for a tooltip showing the donor name and amount
6. Displays a full breakdown table of all declared interests (unattributable entries shown as *Payer not named*)
7. AI analysis via Claude: plain English summary, investigative angle, donor profiles, and gap detection — with an animated magnifying glass while the report generates

## Tech Stack

| Layer | Technology |
|---|---|
| Data | UK Parliament Register of Interests API (free, official) |
| Data | UK Parliament Members API (MP photos, biography, committees) |
| Data | TheyWorkForYou API (voting record, rebellion stats, APPG roles) |
| AI — analysis | Anthropic Claude Sonnet (analysis reports) |
| AI — donor resolution | Anthropic Claude Haiku (company/person → domain lookup, ~$0.001/call) |
| Logos | Google Favicons API (no auth, works for any domain) |
| Image generation | Pillow (Inter font bundled) |
| Web framework | Flask |
| Caching L1 | Redis (Parliament lookups 1h, AI results 24h) |
| Caching L2 | PostgreSQL (AI results 28 days, donor links permanent) |
| Card CDN | Cloudflare R2 (generated cards cached monthly, served from edge) |
| Package manager | uv |
| Observability — LLM | Langfuse (token usage, cost, latency per Claude call) |
| Observability — service | Prometheus metrics at `/metrics` + Grafana Alloy (request rate, latency, error rate, cache hit/miss) |
| Deployment | Railway (auto-deploy from GitHub, Postgres + Redis plugins) |

## Data Sources

All financial interest data comes directly from the **Register of Members' Financial Interests**, published by the UK Parliament. MPs are legally required to declare:

- Employment and earnings
- Donations and support received
- Gifts, benefits and hospitality
- Visits outside the UK
- Land and property
- Shareholdings
- Family members employed or engaged in lobbying

Data is updated within 28 days of any change. Source: [interests-api.parliament.uk](https://interests-api.parliament.uk)

---

## Running Locally

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — install with `curl -LsSf https://astral.sh/uv/install.sh | sh`

### 1. Clone the repo

```bash
git clone https://github.com/mahsa7haft/paidup
cd paidup
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Set up environment variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Then open `.env` and fill in your keys:

```
# Required for AI analysis
ANTHROPIC_API_KEY=sk-ant-...

# Optional — enables voting record, rebellion stats, and APPG roles
# Get a free key at https://www.theyworkforyou.com/api/key
THEYWORKFORYOU_API_KEY=your-key-here

# Flask session secret (any random string is fine locally)
FLASK_SECRET_KEY=change-me

# Optional — local Postgres (see step 4 below)
# DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DB

# Optional — local Redis
# REDIS_URL=redis://localhost:6379

# Optional — Langfuse observability (token usage, cost, latency per Claude call)
# Get keys at https://cloud.langfuse.com → Settings → API Keys
# LANGFUSE_PUBLIC_KEY=pk-lf-...
# LANGFUSE_SECRET_KEY=sk-lf-...
```

> The Parliament APIs require no key. Only the AI features need `ANTHROPIC_API_KEY`.

> **Cost note:** each click of "Analyse with Claude" makes one API call using `claude-sonnet-4-6`. At typical interest-register sizes (~1,000 tokens in, ~400 out) this costs roughly **$0.003–0.005 per analysis**. Running all five prompt styles on one MP costs under $0.025. There is no background polling — the API is only called when you explicitly click the button.

### 4. (Optional) Run Postgres locally with Docker

The app works without a database — Postgres is only needed for two features:
- **Persistent AI analysis cache** (28-day TTL, survives restarts)
- **Smart donor badge resolution** — stores whether a titled donor (Lord, Sir, etc.) is linked to a company, so Claude is only asked once per person

If you have [Docker](https://www.docker.com) installed, spin up a local Postgres instance in one command:

```bash
docker run -d \
  --name paidup-postgres \
  -e POSTGRES_DB=paidup \
  -e POSTGRES_USER=paidup \
  -e POSTGRES_PASSWORD=YOUR_DEV_PASSWORD \
  -p HOST_PORT:5432 \
  postgres:16-alpine
```

Choose your own `YOUR_DEV_PASSWORD` and `HOST_PORT` (the container always listens on the Postgres default `5432` — `HOST_PORT` is whatever free port you map it to on your machine).

Then add this to your `.env`, filling in the values you set in the `docker run` command above (`USER` / `PASSWORD` / `DB` come from the `POSTGRES_*` flags, `HOST` is `localhost`, `PORT` is your chosen `HOST_PORT`):

```
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/DB
```

The app creates the required tables automatically on startup. To stop and restart the container between sessions:

```bash
docker stop paidup-postgres   # stop (data is preserved)
docker start paidup-postgres  # restart
docker rm -f paidup-postgres  # delete completely
```

The app creates two tables automatically on startup:

- **`donor_company_links`** — maps donor names to company logo domains. Seeded lazily by Claude Haiku the first time a new donor is seen, then cached permanently (`logo_domain` is `__person__` when the donor is a private individual with no company link).
- **`analyses`** — cached AI analysis reports, kept for 28 days (Parliament's register update cycle), cleared automatically when stale.

Inspect them with `docker exec -it paidup-postgres psql -U paidup -d paidup`.

### 5. Run the app

```bash
PYTHONPATH=src uv run python -m app.main
```

Open [http://localhost:5002](http://localhost:5002)

---

## Deploying to Railway

PaidUp deploys on [Railway](https://railway.app): connect the GitHub repo and it auto-detects Python and redeploys on every push to `main`. The `railway.toml` in the repo root sets the start command — no manual config needed.

Add the **Postgres** and **Redis** plugins (**+ New → Database**) and Railway injects `DATABASE_URL` / `REDIS_URL` automatically. Both are optional — the app degrades gracefully without them:
- **Postgres** persists AI analyses for 28 days across restarts and redeploys. `/health` reports `"db": true` when connected.
- **Redis** caches Parliament lookups for 1h and analyses for 24h (the prompt version is part of the cache key, so a new prompt version invalidates old results).

Set these under **Variables** (never commit `.env` — it's gitignored):

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `THEYWORKFORYOU_API_KEY` | Your TheyWorkForYou key (optional) |
| `FLASK_SECRET_KEY` | Any long random string |
| `REDIS_URL` / `DATABASE_URL` / `PORT` | Set automatically by Railway — do not override |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Optional — Langfuse observability ([cloud.langfuse.com](https://cloud.langfuse.com)) |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | Optional — Cloudflare R2 card CDN caching |
| `R2_BUCKET_NAME` / `R2_PUBLIC_URL` | Optional — R2 bucket name and public URL |

---

## Running Tests

```bash
uv run pytest tests/ -v
```

65 tests across four modules — no database or API key needed (all external calls are mocked):

| File | What it covers |
|---|---|
| `tests/test_text_utils.py` | Name normalisation, TF-IDF fuzzy matching |
| `tests/test_card_badges.py` | Person/company detection, initials, badge classification |
| `tests/test_database_links.py` | Donor→company DB helpers, fuzzy fallback, rollback on error |
| `tests/test_ai_resolve.py` | Claude Haiku resolver — valid JSON, empty response, markdown fences, exceptions |

## Project Structure

```
paidup/
├── src/
│   └── app/
│       ├── main.py              # Flask entry point + routes
│       ├── parliament.py        # UK Parliament API client
│       ├── theyworkforyou.py    # TheyWorkForYou API client
│       ├── ai.py                # Claude AI analysis + donor company resolver (Haiku)
│       ├── card.py              # Donor card image generator (Pillow, Inter font)
│       ├── r2.py                # Cloudflare R2 card image cache (CDN upload/lookup)
│       ├── database.py          # PostgreSQL layer — analysis cache + donor_company_links
│       ├── cache.py             # Redis wrapper (L1 cache)
│       ├── metrics.py           # Prometheus counters (cache hit/miss) exposed at /metrics
│       ├── text_utils.py        # Shared name normalisation + TF-IDF fuzzy matching
│       ├── fonts/               # Bundled Inter typeface (Regular, Medium, SemiBold)
│       ├── prompts/             # Versioned AI prompt files
│       │   ├── summary_v1.txt
│       │   ├── investigative_v1.txt
│       │   ├── donor_profiles_v1.txt
│       │   └── gaps_v1.txt
│       └── templates/
│           └── index.html       # Web UI (cream / brand F theme)
├── tests/
│   ├── test_text_utils.py
│   ├── test_card_badges.py
│   ├── test_database_links.py
│   └── test_ai_resolve.py
├── railway.toml                 # Railway deployment config (start command, health check)
├── pyproject.toml
├── .env.example
└── uv.lock
```

## Experimenting with AI Prompts

Prompt files live in `src/app/prompts/` as plain text files. The naming convention is `{name}_v{n}.txt`. To create a new version:

1. Duplicate an existing file and increment the version number, e.g. `summary_v2.txt`
2. Edit the prompt freely
3. Restart the app — it picks up the highest version automatically

Bumping the version number automatically busts both the Redis and Postgres caches, so Claude is always called fresh after a prompt edit. No Python changes needed to iterate on prompts.

## How It Works

```
User types MP name
      ↓
Parliament Members API → MP ID, photo, party, constituency, committees
      ↓
Parliament Interests API → all declared financial interests
      ↓
TheyWorkForYou API → voting record, rebellions, APPG roles (optional)
      ↓
parse_interests() → resolve donor name from DonorName / DonorCompanyName
                    / UltimatePayerName / PayerName (in that order)
      ↓
deduplicate_donors() → TF-IDF cosine similarity clusters near-identical names
      ↓
For each donor → check donor_company_links DB (fuzzy match, threshold 0.75)
                 → DB miss: ask Claude Haiku for company domain (~$0.001)
                 → store result permanently
      ↓
Pillow card generation:
  • Company with domain → Google Favicons logo floats on suit
  • Company no logo     → dark circle with 2-letter initials
  • Person              → dark green circle with person silhouette
  • Unattributed        → dark grey circle with "?"
  (badge positions exported as JSON for frontend hover tooltips)
      ↓
User clicks "Open Donor Analysis"
      ↓
/analyze → L1 Redis (24h) → L2 Postgres (28d) → Claude Sonnet (fresh call)
         → animated magnifying glass + rotating phrases while generating
      ↓
Markdown report rendered in slide-in drawer
      ↓
Data Sources footer revealed once an MP card loads (collapsible on mobile)
```

## Example Searches

- `Keir Starmer`
- `Rishi Sunak`
- `Jeremy Corbyn`
- `Boris Johnson`

## Open Issues

See the [GitHub Issues](https://github.com/mahsa7haft/paidup/issues) board for the full list. Current priorities:

| # | Title |
|---|---|
| [#60](https://github.com/mahsa7haft/paidup/issues/60) | Emergency: restore PaidUp after Railway Postgres crash |
| [#54](https://github.com/mahsa7haft/paidup/issues/54) | Perf: donor classification calls Claude Haiku once per unknown donor, sequentially |
| [#49](https://github.com/mahsa7haft/paidup/issues/49) | Ops: schedule monthly card regeneration in R2 + keep manual trigger |
| [#47](https://github.com/mahsa7haft/paidup/issues/47) | Mobile: donor badge tooltips and card details not usable on small screens |
| [#46](https://github.com/mahsa7haft/paidup/issues/46) | Bug: companies frequently misclassified as persons in donor table |
| [#43](https://github.com/mahsa7haft/paidup/issues/43) | Legal: review AI output framing and UK defamation exposure before monetisation |
| [#42](https://github.com/mahsa7haft/paidup/issues/42) | Card: display committee memberships with visual distinction from roles |
| [#37](https://github.com/mahsa7haft/paidup/issues/37) | Epic: share MP donor card on social media |
| [#33](https://github.com/mahsa7haft/paidup/issues/33) | Transparency: add AI usage and environmental impact page |
| [#24](https://github.com/mahsa7haft/paidup/issues/24) | Transparency: add Claude/Anthropic as data source; AI reports should cite sources |
| [#8](https://github.com/mahsa7haft/paidup/issues/8) | Card: show party logo instead of party name text |

## Sister Project — PaidUp Intelligence

[**PaidUp Intelligence**](https://github.com/mahsa7haft/paidup-intelligence) is a companion service that inverts what PaidUp does. PaidUp surfaces *who funds a given MP*; PaidUp Intelligence answers *which MPs are funded by X* — and cross-references donors, votes, party funding, and APPG memberships to surface conflicts of interest that would take hours to find by hand.

It uses Retrieval-Augmented Generation (RAG): Parliament Register and Electoral Commission data are embedded into a pgvector store, queried by MCP tools, and reasoned over by a LangGraph agent. Example questions it can answer:

- *"Which MPs received money from fossil fuel companies?"*
- *"Are there any donors who give to both Labour and Conservative MPs?"*
- *"Which MPs are in the fossil fuel APPG, voted against green energy bills, AND whose party received oil company donations?"*

The two projects share the same data sources and are designed to be deployed alongside each other.

## Roadmap

- [ ] US politicians via OpenSecrets API
- [ ] Bluesky misinformation monitor integration — flag a claim, see who funds the politician making it
- [ ] Industry breakdown (oil & gas, finance, pharma, etc.)
- [ ] Historical comparison — how interests have changed over time
- [ ] Full APPG membership list (currently shows only named roles)
