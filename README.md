# PaidUp

**See who funds UK politicians.**

![PaidUp demo](demo.gif)

Search any MP by name and instantly see their declared financial interests — donors, gifts, hospitality, and shareholdings — pulled live from the official UK Parliament Register of Members' Financial Interests. Includes AI-powered analysis to surface conflicts of interest, donor profiles, and factional leanings.

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
7. Known donor affiliations (e.g. Friends of Israel, BICOM) are shown as coloured tag pills in the interests table
6. AI analysis via Claude: plain English summary, investigative angle, donor profiles, and gap detection — with an animated magnifying glass while the report generates

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
| Observability | Langfuse (token usage, cost, latency per Claude call) |
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
# DATABASE_URL=postgresql://paidup:paidup_dev@localhost:5432/paidup

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
  -e POSTGRES_PASSWORD=paidup_dev \
  -p 5432:5432 \
  postgres:16-alpine
```

Then add this to your `.env`:

```
DATABASE_URL=postgresql://paidup:paidup_dev@localhost:5432/paidup
```

The app creates the required tables automatically on startup. To stop and restart the container between sessions:

```bash
docker stop paidup-postgres   # stop (data is preserved)
docker start paidup-postgres  # restart
docker rm -f paidup-postgres  # delete completely
```

#### Inspecting and editing the database

Open an interactive Postgres shell:

```bash
docker exec -it paidup-postgres psql -U paidup -d paidup
```

Useful commands once inside:

```sql
\dt                             -- list all tables
SELECT * FROM donor_company_links;
SELECT member_id, prompt_key, generated_at FROM analyses ORDER BY generated_at DESC;
\q                              -- quit
```

Run a one-off query without entering the shell:

```bash
docker exec paidup-postgres psql -U paidup -d paidup \
  -c "SELECT * FROM donor_company_links;"
```

#### The three tables

**`donor_company_links`** — maps donor names to company logo domains. Seeded lazily by Claude Haiku the first time a new donor is seen; never re-queried after that.

| Column | Meaning |
|---|---|
| `donor_name` | Name as it appears in the Parliament register |
| `company_name` | Display name of the linked company (if any) |
| `logo_domain` | Domain used to fetch a logo via Google Favicons — or `__person__` if confirmed to be a private individual with no company link |
| `source` | `ai` (resolved by Claude Haiku) or `manual` (hand-corrected) |

Manually correct a wrong domain:

```bash
docker exec paidup-postgres psql -U paidup -d paidup \
  -c "UPDATE donor_company_links SET logo_domain = 'correct-domain.com', source = 'manual' \
      WHERE donor_name = 'Donor Name Here';"
```

Manually seed a known person → company link (e.g. before any card is rendered):

```bash
docker exec paidup-postgres psql -U paidup -d paidup \
  -c "INSERT INTO donor_company_links (donor_name, company_name, logo_domain, source) \
      VALUES ('Lord David Sainsbury', 'Sainsbury''s', 'sainsburys.co.uk', 'manual') \
      ON CONFLICT (donor_name) DO UPDATE \
        SET logo_domain = EXCLUDED.logo_domain, source = 'manual';"
```

**`donor_tags`** — affiliation labels applied to donors whose names match a known pattern. Managed via `data/donor_tags.csv` — see [Donor Affiliation Tags](#donor-affiliation-tags) below.

| Column | Meaning |
|---|---|
| `name_pattern` | Lowercase substring to match against the donor name (e.g. `friends of israel`) |
| `tag` | Machine-readable category slug (e.g. `pro-israel`) |
| `label` | Human-readable label shown as a pill in the UI (e.g. `Friends of Israel`) |
| `notes` | Optional context (not displayed) |

**`analyses`** — cached AI analysis reports, kept for 28 days (Parliament's register update cycle). Cleared automatically when stale.

```bash
# See all cached analyses
docker exec paidup-postgres psql -U paidup -d paidup \
  -c "SELECT member_id, prompt_key, prompt_version, generated_at FROM analyses ORDER BY generated_at DESC;"

# Force re-analysis for a specific MP (deletes their cached result)
docker exec paidup-postgres psql -U paidup -d paidup \
  -c "DELETE FROM analyses WHERE member_id = 4514;"
```

### 5. Run the app

```bash
PYTHONPATH=src uv run python -m app.main
```

Open [http://localhost:5002](http://localhost:5002)

---

## Deploying to Railway

[Railway](https://railway.app) is the recommended deployment platform. It supports Python and environment variables out of the box.

### 1. Push your code to GitHub

Make sure your latest code is on the `main` branch:

```bash
git push origin main
```

> **Never commit your `.env` file.** It is listed in `.gitignore`. Add secrets via Railway's environment variable UI instead.

### 2. Create a new Railway project

1. Go to [railway.app](https://railway.app) and sign in
2. Click **New Project → Deploy from GitHub repo**
3. Select your `paidup` repository
4. Railway will auto-detect Python and start a build

### 3. Set environment variables

In your Railway project, go to **Variables** and add:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `THEYWORKFORYOU_API_KEY` | Your TheyWorkForYou key (optional) |
| `FLASK_SECRET_KEY` | Any long random string |
| `REDIS_URL` | Set automatically by the Railway Redis plugin (see below) |
| `DATABASE_URL` | Set automatically by the Railway Postgres plugin (see below) |
| `PORT` | Railway sets this automatically — do not override |
| `LANGFUSE_PUBLIC_KEY` | Optional — Langfuse observability ([cloud.langfuse.com](https://cloud.langfuse.com)) |
| `LANGFUSE_SECRET_KEY` | Optional — Langfuse observability |
| `R2_ACCOUNT_ID` | Optional — Cloudflare account ID (enables card CDN caching) |
| `R2_ACCESS_KEY_ID` | Optional — R2 API token access key |
| `R2_SECRET_ACCESS_KEY` | Optional — R2 API token secret |
| `R2_BUCKET_NAME` | Optional — R2 bucket name (e.g. `paidup`) |
| `R2_PUBLIC_URL` | Optional — public bucket URL e.g. `https://pub-xxxx.r2.dev` |

### 4. Start command

The `railway.toml` in the repo root configures the start command automatically — no manual setup needed.

### 5. Add Postgres (recommended)

In your Railway project, click **+ New** → **Database** → **PostgreSQL**. Railway provisions a Postgres instance and injects `DATABASE_URL` automatically.

With Postgres enabled, AI analysis results are stored persistently for **28 days** (Parliament's register update cycle). The first analysis for each MP + prompt style costs one Claude API call — every subsequent request within 28 days is free and instant, and survives app restarts and redeployments.

The `/health` endpoint reports `"db": true` when the connection is live.

### 6. Add Redis (recommended)

In your Railway project, click **+ New** → **Database** → **Redis**. Railway provisions a Redis instance and automatically injects `REDIS_URL` into your app's environment. No extra configuration needed.

With Redis enabled:
- Parliament lookups are cached for **1 hour** — repeated searches for the same MP are instant
- AI analysis results are cached for **24 hours** per MP + prompt style combination
- Prompt version is included in the cache key, so saving a new prompt version (`summary_v2.txt`) automatically invalidates old cached results

Without Redis the app works identically — caching is silently disabled.

### 7. Deploy

Railway deploys automatically on every push to `main`. Once the build completes, click the generated URL to open the live app.

---

## Donor Affiliation Tags

PaidUp can flag donors with known political or ideological affiliations — shown as coloured pills in the interests table. The tag list is stored in `data/donor_tags.csv` (version-controlled, editable without touching code) and synced into the `donor_tags` Postgres table.

### How matching works

Each row in the CSV has a `name_pattern` column — a lowercase substring. If that substring appears anywhere in a donor's name (case-insensitive), the tag is attached to every interest entry from that donor. One pattern can match many organisations:

```
friends of israel  →  Conservative Friends of Israel
                       Labour Friends of Israel
                       Liberal Democrat Friends of Israel
                       SNP Friends of Israel
```

### Adding or updating tags

1. Open `data/donor_tags.csv` and add or edit rows:

```csv
name_pattern,tag,label,notes
friends of israel,pro-israel,Friends of Israel,Catches all party chapters
fossil fuel industry,fossil-fuel,Fossil Fuel Industry,Oil / gas / coal donors
```

2. Run the seed command to push changes into the DB:

```bash
PYTHONPATH=src uv run python -m app.seed_tags
```

Safe to run repeatedly — rows are upserted. The in-process cache refreshes automatically within 5 minutes; no app restart needed.

3. Commit the updated CSV. The DB on Railway must be re-seeded after each deploy that changes the file — run the same command against the Railway environment, or add it to your deploy script.

### Adding a custom colour for a new tag

By default, unrecognised tags display in a neutral cream colour. To give a tag its own colour, add a CSS class to `src/app/templates/index.html`:

```css
.donor-tag-fossil-fuel { background: #fef3cd; color: #7a4f00; border-color: #f0c070; }
```

The class name is always `.donor-tag-{tag}` with any non-alphanumeric characters replaced by `-`.

### Initial tag set

| Pattern | Tag | Label |
|---|---|---|
| `friends of israel` | `pro-israel` | Friends of Israel |
| `bicom` | `pro-israel` | BICOM |
| `uk israel business` | `pro-israel` | UK Israel Business |
| `anglo-israel association` | `pro-israel` | Anglo-Israel Association |
| `jewish labour movement` | `pro-israel` | Jewish Labour Movement |
| `jlm` | `pro-israel` | Jewish Labour Movement |
| `cfoi` | `pro-israel` | Conservative Friends of Israel |

---

## Running Tests

```bash
uv run pytest tests/ -v
```

64 tests across four modules — no database or API key needed (all external calls are mocked):

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
│       ├── database.py          # PostgreSQL layer — analysis cache + donor_company_links + donor_tags
│       ├── cache.py             # Redis wrapper (L1 cache)
│       ├── text_utils.py        # Shared name normalisation + TF-IDF fuzzy matching
│       ├── seed_tags.py         # CLI: sync data/donor_tags.csv into donor_tags table
│       ├── fonts/               # Bundled Inter typeface (Regular, Medium, SemiBold)
│       ├── prompts/             # Versioned AI prompt files
│       │   ├── summary_v1.txt
│       │   ├── investigative_v1.txt
│       │   ├── donor_profiles_v1.txt
│       │   └── gaps_v1.txt
│       └── templates/
│           └── index.html       # Web UI (cream / brand F theme)
├── data/
│   └── donor_tags.csv           # Editable affiliation tag list — sync with seed_tags.py
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
apply_donor_tags() → substring match against donor_tags table
                     attaches [{tag, label}] to each interest entry
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
Data Sources footer always visible at bottom of page
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
| [#8](https://github.com/mahsa7haft/paidup/issues/8) | Party logos on card instead of party name text |
| [#22](https://github.com/mahsa7haft/paidup/issues/22) | Exclude Unknown donors from declared donor count and interests table |
| [#23](https://github.com/mahsa7haft/paidup/issues/23) | Company logos not rendering on donor badges |
| [#24](https://github.com/mahsa7haft/paidup/issues/24) | Add Claude/Anthropic as data source; AI reports should cite sources |
| [#25](https://github.com/mahsa7haft/paidup/issues/25) | Clearbit logos not rendering despite correct domains in DB |
| [#33](https://github.com/mahsa7haft/paidup/issues/33) | Transparency: add AI usage and environmental impact page |
| [#34](https://github.com/mahsa7haft/paidup/issues/34) | Company logo badges not visually proportional to donation amount |
| [#37](https://github.com/mahsa7haft/paidup/issues/37) | Epic: share MP donor card on social media |

## Roadmap

- [ ] US politicians via OpenSecrets API
- [ ] Bluesky misinformation monitor integration — flag a claim, see who funds the politician making it
- [ ] Industry breakdown (oil & gas, finance, pharma, etc.)
- [ ] Historical comparison — how interests have changed over time
- [ ] Full APPG membership list (currently shows only named roles)
