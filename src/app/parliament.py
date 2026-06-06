"""
UK Parliament API client.
Fetches MP details and financial interests from the official Parliament APIs.
"""

import requests
from app.text_utils import normalize_name, best_fuzzy_match
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

MEMBERS_API = "https://members-api.parliament.uk/api"
INTERESTS_API = "https://interests-api.parliament.uk/api/v1"

_normalize = normalize_name


def deduplicate_donors(interests: list[dict], threshold: float = 0.82) -> list[dict]:
    """
    Cluster near-identical donor names using TF-IDF character n-gram cosine similarity.

    Step 1 — normalize: strip legal suffixes ('Limited', 'Ltd', 'plc', etc.)
              and the 'The ' prefix so structural variants become identical.
    Step 2 — vectorise: character 2-3 gram TF-IDF captures remaining typos.
    Step 3 — cosine similarity: cluster names above threshold.

    The canonical name for each cluster is whichever variant appeared first
    in the sorted-by-value interests list. Merged variants are stored in
    'aliases' so the UI can show what was grouped.
    """
    unique_names = list(dict.fromkeys(
        i["donor"] for i in interests if i["donor"] != "Unknown"
    ))

    if len(unique_names) < 2:
        return [dict(i) | {"aliases": []} for i in interests]

    normalized = [_normalize(n) for n in unique_names]

    # Vectorise with character 2-3 grams
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)
    try:
        matrix = vec.fit_transform(normalized)
    except ValueError:
        return [dict(i) | {"aliases": []} for i in interests]

    sim = cosine_similarity(matrix)

    # Greedy clustering — first-seen name in each cluster is canonical
    canonical: dict[str, str] = {}
    clustered: set[str] = set()

    for i, name in enumerate(unique_names):
        if name in clustered:
            continue
        canonical[name] = name
        clustered.add(name)
        for j, other in enumerate(unique_names):
            if j != i and other not in clustered and sim[i, j] >= threshold:
                canonical[other] = name
                clustered.add(other)

    aliases_map: dict[str, set] = {}
    for raw, canon in canonical.items():
        if raw != canon:
            aliases_map.setdefault(canon, set()).add(raw)

    result = []
    for i in interests:
        entry = dict(i)
        if entry["donor"] != "Unknown":
            canon = canonical.get(entry["donor"], entry["donor"])
            entry["aliases"] = sorted(aliases_map.get(canon, set()))
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
        donor = (fields.get("DonorName")
                 or fields.get("DonorCompanyName")
                 or fields.get("UltimatePayerName"))
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
