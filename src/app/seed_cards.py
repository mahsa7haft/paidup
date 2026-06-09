"""
Regenerate all MP donor cards and upload to Cloudflare R2.

Usage:
    # Regenerate only missing/expired cards
    PYTHONPATH=src uv run python -m app.seed_cards

    # Clear R2 bucket first, then regenerate everything
    PYTHONPATH=src uv run python -m app.seed_cards --clear

    # Dry run — list MPs but don't generate cards
    PYTHONPATH=src uv run python -m app.seed_cards --dry-run

Runs through all 647 current Commons MPs. Skips MPs with no declared
interests. Safe to interrupt and re-run — already-uploaded cards are
skipped unless --clear is used.
"""

import argparse
import io
import sys
import time

import requests

from app.card import generate_card
from app.parliament import (
    get_biography, get_interests, parse_biography,
    parse_interests, deduplicate_donors, date_range,
)
import app.r2 as r2


MEMBERS_API = "https://members-api.parliament.uk/api"
PAGE_SIZE   = 100


def _all_mps() -> list[dict]:
    """Return all current Commons MPs from the Parliament Members API."""
    mps, skip = [], 0
    while True:
        r = requests.get(
            f"{MEMBERS_API}/Members/Search",
            params={"House": 1, "IsCurrentMember": "true", "take": PAGE_SIZE, "skip": skip},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            break
        mps.extend(m["value"] for m in items)
        skip += PAGE_SIZE
        if skip >= data.get("totalResults", 0):
            break
    return mps


def _clear_r2() -> None:
    """Delete all card objects from the R2 bucket."""
    import os
    client  = r2._get_client()
    bucket  = os.environ.get("R2_BUCKET_NAME")
    if not (client and bucket):
        print("R2 not configured — cannot clear.", file=sys.stderr)
        sys.exit(1)
    paginator = client.get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=bucket, Prefix="cards/"):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if keys:
            client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
            deleted += len(keys)
    print(f"Cleared {deleted} card(s) from R2.")


def _generate_and_upload(mp: dict) -> str:
    """Generate card for one MP and upload to R2. Returns status string."""
    member_id = mp["id"]
    name      = mp["nameDisplayAs"]
    party     = mp["latestParty"]["name"]

    # Skip if already cached this month (unless --clear was used)
    if r2.get_card_url(member_id):
        return "skip"

    interests = deduplicate_donors(parse_interests(get_interests(member_id)))
    if not interests:
        return "no-interests"

    oldest, newest = date_range(interests)
    bio   = parse_biography(get_biography(member_id))
    title = (bio["govt_posts"] + bio["other_posts"] + [""])[0]

    img = generate_card(member_id, name, interests, party=party,
                        title=title, date_from=oldest, date_to=newest)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    cdn_url = r2.upload_card(member_id, buf.getvalue())
    return "uploaded" if cdn_url else "r2-error"


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate all MP cards in R2.")
    parser.add_argument("--clear",   action="store_true", help="Delete existing R2 cards before regenerating")
    parser.add_argument("--dry-run", action="store_true", help="List MPs without generating cards")
    args = parser.parse_args()

    if not r2._get_client():
        print("R2 not configured (R2_ACCOUNT_ID etc. not set). Aborting.", file=sys.stderr)
        sys.exit(1)

    if args.clear:
        _clear_r2()

    print("Fetching MP list from Parliament API…")
    mps = _all_mps()
    print(f"Found {len(mps)} current MPs.")

    if args.dry_run:
        for mp in mps:
            print(f"  {mp['id']:6}  {mp['nameDisplayAs']}")
        return

    counts = {"uploaded": 0, "skip": 0, "no-interests": 0, "r2-error": 0, "error": 0}
    for i, mp in enumerate(mps, 1):
        name = mp["nameDisplayAs"]
        try:
            status = _generate_and_upload(mp)
        except Exception as exc:
            status = "error"
            print(f"  ERROR {name}: {exc}", file=sys.stderr)
        counts[status] += 1
        print(f"[{i:3}/{len(mps)}] {status:14} {name}")
        # Polite pause between MPs to avoid hammering Parliament API
        time.sleep(0.5)

    print(f"\nDone. uploaded={counts['uploaded']}  skipped={counts['skip']}  "
          f"no-interests={counts['no-interests']}  errors={counts['error']}")


if __name__ == "__main__":
    main()
