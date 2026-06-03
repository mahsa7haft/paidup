# PaidUp

**See who funds UK politicians.**

Search any MP by name and instantly see their declared financial interests — donors, gifts, hospitality, and shareholdings — pulled live from the official UK Parliament Register of Members' Financial Interests.

## What it does

1. You type an MP's name
2. PaidUp fetches their declared financial interests from the UK Parliament API
3. Generates a visual donor card showing who has paid them and how much
4. Displays a full breakdown table of all declared interests

## Tech Stack

| Layer | Technology |
|---|---|
| Data | UK Parliament Register of Interests API (free, official) |
| Data | UK Parliament Members API (MP photos and details) |
| Image generation | Pillow |
| Web framework | Flask |
| Package manager | uv |

## Data Source

All data comes directly from the **Register of Members' Financial Interests**, published by the UK Parliament. MPs are legally required to declare:

- Employment and earnings
- Donations and support received
- Gifts, benefits and hospitality
- Visits outside the UK
- Land and property
- Shareholdings
- Family members employed or engaged in lobbying

Data is updated within 28 days of any change. Source: [interests-api.parliament.uk](https://interests-api.parliament.uk)

## Quick Start

### 1. Clone and set up

```bash
git clone https://github.com/yourusername/paidup
cd paidup
uv sync
```

### 2. Run locally

```bash
PYTHONPATH=src uv run python -m app.main
```

Open http://localhost:5002

### 3. Run with Docker

```bash
docker compose up --build
```

Open http://localhost:5002

## Project Structure

```
paidup/
├── src/
│   └── app/
│       ├── main.py          # Flask entry point
│       ├── parliament.py    # UK Parliament API client
│       ├── card.py          # Donor card image generator (Pillow)
│       └── templates/
│           └── index.html   # Web UI
├── pyproject.toml
└── .env.example
```

## How It Works

```
User types MP name
      ↓
Members API → find MP ID, photo, party, constituency
      ↓
Interests API → fetch all declared financial interests
      ↓
Parse and sort by value
      ↓
Pillow composites MP photo + sponsor badges → donor card image
      ↓
Flask returns card image + breakdown table
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

## No API key required

PaidUp uses only free, open government data. No sign-up, no API key, no cost to run.
