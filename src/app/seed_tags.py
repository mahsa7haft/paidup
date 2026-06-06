"""
Sync data/donor_tags.csv into the donor_tags Postgres table.

Usage:
    PYTHONPATH=src uv run python -m app.seed_tags

Safe to run repeatedly — rows are upserted, not duplicated.
"""

import csv
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app import database as db

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "donor_tags.csv")


def main() -> None:
    db.ensure_tables()
    try:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("name_pattern", "").strip()]
    except FileNotFoundError:
        print(f"ERROR: {CSV_PATH} not found", file=sys.stderr)
        sys.exit(1)

    n = db.seed_donor_tags(rows)
    print(f"Seeded {n} donor tag row(s) into donor_tags.")


if __name__ == "__main__":
    main()
