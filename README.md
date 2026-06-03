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
```

> The Parliament APIs require no key. Only the AI features need `ANTHROPIC_API_KEY`.

### 4. Run the app

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
| `PORT` | Railway sets this automatically — do not override |

### 4. Set the start command

In Railway, go to **Settings → Deploy** and set the start command to:

```
PYTHONPATH=src python -m app.main
```

> If Railway uses `uv`, the command would be:
> `PYTHONPATH=src uv run python -m app.main`

### 5. Deploy

Railway deploys automatically on every push to `main`. Once the build completes, click the generated URL to open the live app.

---

## Project Structure

```
paidup/
├── src/
│   └── app/
│       ├── main.py              # Flask entry point + routes
│       ├── parliament.py        # UK Parliament API client
│       ├── theyworkforyou.py    # TheyWorkForYou API client
│       ├── ai.py                # Claude AI analysis layer
│       ├── card.py              # Donor card image generator (Pillow)
│       ├── prompts/             # Versioned AI prompt files
│       │   ├── summary_v1.txt
│       │   ├── investigative_v1.txt
│       │   ├── donor_profiles_v1.txt
│       │   ├── factional_v1.txt
│       │   └── gaps_v1.txt
│       └── templates/
│           └── index.html       # Web UI
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
