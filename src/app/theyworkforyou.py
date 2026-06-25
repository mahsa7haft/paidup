"""
TheyWorkForYou API client.
Provides voting records, party rebellion stats, and APPG roles.
Get a free API key at https://www.theyworkforyou.com/api/key
Set THEYWORKFORYOU_API_KEY in your .env to enable this.
"""

import os
import requests

BASE = os.environ.get("TWFY_API_URL", "https://www.theyworkforyou.com/api")


def _key() -> str | None:
    return os.environ.get("THEYWORKFORYOU_API_KEY")


def get_mp_data(name: str) -> dict | None:
    """
    Look up an MP by name and return their voting stats and APPG roles.
    Returns None if the API key is not set or the MP is not found.
    """
    key = _key()
    if not key:
        return None

    try:
        # Step 1: find the person_id
        r = requests.get(f"{BASE}/getMP", params={
            "name": name, "key": key, "output": "json"
        }, timeout=5)
        if r.status_code != 200:
            return None
        data = r.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        person_id = data.get("person_id")
        if not person_id:
            return None

        # Step 2: get full info including voting stats and office/APPG roles
        r2 = requests.get(f"{BASE}/getMPInfo", params={
            "id": person_id, "key": key, "output": "json"
        }, timeout=5)
        if r2.status_code != 200:
            return None
        info = r2.json()

        # Pull out APPG and other parliamentary roles from the office array
        appg_roles = []
        other_roles = []
        for entry in info.get("office", []):
            org = entry.get("org_name", "")
            position = entry.get("position", "")
            to_date = entry.get("to_date", "")
            # Only current roles (to_date far future means still active)
            if to_date and to_date < "2024-01-01":
                continue
            if "all-party" in org.lower() or "appg" in org.lower():
                appg_roles.append(f"{position}, {org}" if position else org)
            else:
                other_roles.append(f"{position}, {org}" if position else org)

        votes_with_party = info.get("votes_with_party_pct")
        rebellions = info.get("rebellions")

        return {
            "person_id": person_id,
            "twfy_url": f"https://www.theyworkforyou.com/mp/{person_id}",
            "votes_with_party_pct": round(float(votes_with_party), 1) if votes_with_party else None,
            "rebellions": int(rebellions) if rebellions else None,
            "debates_count": info.get("debates_count"),
            "written_answers_count": info.get("written_answers_count"),
            "appg_roles": appg_roles,
            "other_roles": other_roles,
        }

    except Exception:
        return None
