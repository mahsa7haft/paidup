"""
UK Parliament API client.
Fetches MP details and financial interests from the official Parliament APIs.
"""

import re
import requests
from rapidfuzz import fuzz

MEMBERS_API = "https://members-api.parliament.uk/api"
INTERESTS_API = "https://interests-api.parliament.uk/api/v1"

_STRIP_PREFIXES = re.compile(r"^(the\s+)", re.IGNORECASE)


def _normalize(name: str) -> str:
    """Strip leading 'The', collapse whitespace, lowercase — for comparison only."""
    return _STRIP_PREFIXES.sub("", name.strip()).lower()


def deduplicate_donors(interests: list[dict], threshold: int = 88) -> list[dict]:
    """
    Normalise donor names so that near-identical spellings (typos, 'The ' prefix,
    minor punctuation differences) map to a single canonical name.

    The canonical name for a cluster is whichever variant appeared first.
    A 'aliases' key is added to each interest listing the other names that were merged.
    """
    # Build canonical map: raw_name -> canonical_name
    canonical: dict[str, str] = {}   # raw -> canonical raw
    norm_to_canonical: dict[str, str] = {}  # normalised -> canonical raw

    unique_names = list(dict.fromkeys(
        i["donor"] for i in interests if i["donor"] != "Unknown"
    ))

    for name in unique_names:
        norm = _normalize(name)
        best: str | None = None
        best_score = 0
        for existing_norm, existing_canonical in norm_to_canonical.items():
            score = fuzz.token_sort_ratio(norm, existing_norm)
            if score >= threshold and score > best_score:
                best = existing_canonical
                best_score = score
        if best:
            canonical[name] = best
        else:
            canonical[name] = name
            norm_to_canonical[norm] = name

    # Build alias map: canonical -> set of merged raw names
    aliases: dict[str, set] = {}
    for raw, canon in canonical.items():
        if raw != canon:
            aliases.setdefault(canon, set()).add(raw)

    # Apply to interests list
    result = []
    for i in interests:
        entry = dict(i)
        if entry["donor"] != "Unknown":
            canon = canonical.get(entry["donor"], entry["donor"])
            entry["aliases"] = sorted(aliases.get(canon, set()))
            entry["donor"] = canon
        result.append(entry)

    return result


def search_mp(name: str) -> dict | None:
    r = requests.get(f"{MEMBERS_API}/Members/Search", params={"Name": name, "House": 1})
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return None
    return items[0]["value"]


def get_interests(member_id: int) -> list[dict]:
    r = requests.get(f"{INTERESTS_API}/Interests", params={"MemberId": member_id})
    r.raise_for_status()
    return r.json().get("items", [])


def get_biography(member_id: int) -> dict:
    """Fetch MP biography including committee memberships. Returns {} on failure."""
    try:
        r = requests.get(f"{MEMBERS_API}/Members/{member_id}/Biography", timeout=5)
        r.raise_for_status()
        return r.json().get("value", {})
    except Exception:
        return {}


def get_thumbnail_url(member_id: int) -> str:
    return f"{MEMBERS_API}/Members/{member_id}/Thumbnail"


def parse_interests(interests: list[dict]) -> list[dict]:
    parsed = []
    for item in interests:
        fields = {f["name"]: f["value"] for f in item.get("fields", [])}
        donor = fields.get("DonorName") or fields.get("DonorCompanyName")
        value = fields.get("Value") or fields.get("AmountOfDonation")
        category = item.get("category", {}).get("name", "Other")
        summary = item.get("summary", "")
        reg_date = item.get("registrationDate", "")
        # Normalise to YYYY-MM-DD
        date_short = reg_date[:10] if reg_date else ""

        # Keep all non-empty fields for AI context
        raw_fields = {k: v for k, v in fields.items() if v}

        parsed.append({
            "donor": donor or "Unknown",
            "value": float(value) if value else 0.0,
            "category": category,
            "summary": summary,
            "date": date_short,
            "raw_fields": raw_fields,
        })

    return sorted(parsed, key=lambda x: x["value"], reverse=True)


def date_range(interests: list[dict]) -> tuple[str, str]:
    """Return (oldest, newest) registration dates from parsed interests."""
    dates = sorted(i["date"] for i in interests if i.get("date"))
    if not dates:
        return ("", "")
    return (dates[0], dates[-1])


def parse_biography(biography: dict) -> dict:
    """Extract committee memberships, current posts, and career history from a biography."""
    def _current(entries: list[dict]) -> list[str]:
        return [e["name"] for e in entries if e.get("name") and not e.get("endDate")]

    def _all_names(entries: list[dict]) -> list[str]:
        return [e["name"] for e in entries if e.get("name")]

    committees = [
        e["name"] for e in biography.get("committeeMemberships", [])
        if e.get("name") and not e.get("endDate")
    ]
    govt_posts = _current(biography.get("governmentPosts", []))
    opposition_posts = _current(biography.get("oppositionPosts", []))
    other_posts = _current(biography.get("otherPosts", []))

    return {
        "committees": committees,
        "govt_posts": govt_posts,
        "opposition_posts": opposition_posts,
        "other_posts": other_posts,
        "party_history": _all_names(biography.get("partyAffiliations", [])),
    }
