# PaidUp

**See who funds UK politicians.**

Search any MP by name and instantly see their declared financial interests — donors, gifts, hospitality, and shareholdings — pulled live from the official UK Parliament Register of Members' Financial Interests. Includes AI-powered analysis to surface conflicts of interest, donor profiles, and factional leanings.

## What it does

1. You type an MP's name
2. PaidUp fetches their declared financial interests from the UK Parliament API
3. Generates a visual donor card showing who has paid them and how much
4. Displays a full breakdown table of all declared interests
5. AI analysis via Claude: plain English summary, investigative angle, donor profiles, factional analysis, and gap detection

## Tech Stack

| Layer | Technology |
|---|---|
| Data | UK Parliament Register of Interests API (free, official) |
| Data | UK Parliament Members API (MP photos, biography, committees) |
| Data | TheyWorkForYou API (voting record, rebellion stats, APPG roles) |
| AI | Anthropic Claude API |
| Image generation | Pillow |
| Web framework | Flask |
| Package manager | uv |

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
| `PORT` | Railway sets this automatically — do not override |

### 4. Set the start command

In Railway, go to **Settings → Deploy** and set the start command to:

```
PYTHONPATH=src python -m app.main
```

> If Railway uses `uv`, the command would be:
> `PYTHONPATH=src uv run python -m app.main`

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
│       ├── card.py              # Donor card image generator (Pillow, brand F design)
│       ├── database.py          # PostgreSQL layer — analysis cache + donor_company_links
│       ├── cache.py             # Redis wrapper (L1 cache)
│       ├── text_utils.py        # Shared name normalisation + TF-IDF fuzzy matching
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
├── pyproject.toml
├── .env.example
└── uv.lock
```

## Experimenting with AI Prompts

Prompt files live in `src/app/prompts/` as plain text files. The naming convention is `{name}_v{n}.txt`. To create a new version:

1. Duplicate an existing file and increment the version number, e.g. `summary_v2.txt`
2. Edit the prompt freely
3. Restart the app — it picks up the highest version automatically
4. The dropdown in the UI shows the version number so you always know which variant ran

No Python changes needed to iterate on prompts.

## How It Works

```
User types MP name
      ↓
Parliament Members API → find MP ID, photo, party, constituency, committees
      ↓
Parliament Interests API → fetch all declared financial interests
      ↓
TheyWorkForYou API → voting record, rebellion stats, APPG roles (if key set)
      ↓
Parse and sort by value
      ↓
Pillow composites MP photo + sponsor badges → donor card image
      ↓
Claude API → AI analysis using selected prompt style
      ↓
Flask returns card + breakdown table + slide-in analysis drawer
```

## Example Searches

- `Keir Starmer`
- `Rishi Sunak`
- `Jeremy Corbyn`
- `Boris Johnson`

## Roadmap

- [ ] US politicians via OpenSecrets API
- [ ] Bluesky misinformation monitor integration — flag a claim, see who funds the politician making it
- [ ] Industry breakdown (oil & gas, finance, pharma, etc.)
- [ ] Historical comparison — how interests have changed over time
- [ ] Full APPG membership list (currently shows only named roles)
