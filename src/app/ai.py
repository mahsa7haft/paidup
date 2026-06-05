"""
AI analysis layer using the Anthropic Claude API.
Prompts live in src/app/prompts/ as plain text files named {key}_v{n}.txt.
The loader always picks the highest version for each key.
Add ANTHROPIC_API_KEY to your .env to enable this feature.
"""

import os
import re
from pathlib import Path
import anthropic

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Appended to every system prompt — keeps responses focused on analysis, not raw data.
_SHARED_RULES = """
Format your response using markdown (headings, bold, bullet points).
Do NOT reproduce or list the raw donor entries — the user can see that data separately.
Focus entirely on patterns, insights, conflicts of interest, and conclusions drawn from the data."""

# Human-readable labels for the UI, keyed by prompt base name.
LABELS: dict[str, str] = {
    "summary": "Plain English Summary",
    "investigative": "Investigative Journalist",
    "donor_profiles": "Donor Profiles",
    "gaps": "Gaps & Blind Spots",
}


def _load_prompts() -> dict[str, dict]:
    """
    Scan the prompts/ directory and return the latest version of each prompt.
    File naming convention: {key}_v{n}.txt  e.g. summary_v1.txt, summary_v2.txt
    """
    latest: dict[str, tuple[int, Path]] = {}
    for path in PROMPTS_DIR.glob("*.txt"):
        m = re.match(r"^(.+)_v(\d+)$", path.stem)
        if not m:
            continue
        key, version = m.group(1), int(m.group(2))
        if key not in latest or version > latest[key][0]:
            latest[key] = (version, path)

    prompts = {}
    for key, (version, path) in sorted(latest.items()):
        prompts[key] = {
            "label": LABELS.get(key, key.replace("_", " ").title()),
            "version": version,
            "system": path.read_text().strip(),
        }
    return prompts


def analyze(
    mp_name: str,
    party: str,
    constituency: str,
    interests: list[dict],
    committees: list[str],
    twfy: dict | None = None,
    bio: dict | None = None,
    prompt_key: str = "summary",
) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")

    prompts = _load_prompts()
    if prompt_key not in prompts:
        raise ValueError(f"Unknown prompt key: {prompt_key!r}. Available: {list(prompts)}")

    prompt_cfg = prompts[prompt_key]
    total = sum(i["value"] for i in interests)
    oldest = min((i["date"] for i in interests if i.get("date")), default="unknown")
    newest = max((i["date"] for i in interests if i.get("date")), default="unknown")

    lines = []
    for i in interests:
        parts = [f"{i['donor']}: £{i['value']:,.0f}" if i["value"] else f"{i['donor']}: in-kind"]
        parts.append(f"({i['category']})")
        if i.get("date"):
            parts.append(f"registered {i['date']}")
        if i.get("summary"):
            parts.append(f"— {i['summary']}")
        extra = {k: v for k, v in i.get("raw_fields", {}).items()
                 if k not in ("DonorName", "DonorCompanyName", "Value", "AmountOfDonation")}
        if extra:
            parts.append(f"[{', '.join(f'{k}: {v}' for k, v in extra.items())}]")
        lines.append("- " + " ".join(parts))

    interests_text = "\n".join(lines) or "None declared."
    committee_text = ", ".join(committees) if committees else "none on record"

    # Build TheyWorkForYou section if available
    twfy_section = ""
    if twfy:
        twfy_parts = []
        if twfy.get("votes_with_party_pct") is not None:
            twfy_parts.append(f"Votes with party: {twfy['votes_with_party_pct']}%")
        if twfy.get("rebellions") is not None:
            twfy_parts.append(f"Rebellions: {twfy['rebellions']}")
        if twfy.get("debates_count"):
            twfy_parts.append(f"Debates: {twfy['debates_count']}")
        if twfy.get("appg_roles"):
            twfy_parts.append(f"APPG roles: {'; '.join(twfy['appg_roles'])}")
        if twfy_parts:
            twfy_section = "\nParliamentary activity (TheyWorkForYou):\n" + "\n".join(f"  {p}" for p in twfy_parts)

    # Bio extras
    bio_section = ""
    if bio:
        bio_parts = []
        if bio.get("govt_posts"):
            bio_parts.append(f"Current government posts: {', '.join(bio['govt_posts'])}")
        if bio.get("opposition_posts"):
            bio_parts.append(f"Opposition posts: {', '.join(bio['opposition_posts'])}")
        if bio_parts:
            bio_section = "\nCareer / roles:\n" + "\n".join(f"  {p}" for p in bio_parts)

    user_message = (
        f"MP: {mp_name}\n"
        f"Party: {party}\n"
        f"Constituency: {constituency}\n"
        f"Committee memberships: {committee_text}\n"
        f"Total declared: £{total:,.0f}\n"
        f"Register entries: {len(interests)} (oldest: {oldest}, newest: {newest})"
        f"{twfy_section}"
        f"{bio_section}\n\n"
        f"Declared financial interests:\n{interests_text}"
    )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=prompt_cfg["system"] + _SHARED_RULES,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


def prompt_options() -> list[dict]:
    """Return prompt keys, labels, and current versions for the UI dropdown."""
    return [
        {"key": k, "label": v["label"], "version": v["version"]}
        for k, v in _load_prompts().items()
    ]


def get_prompt_version(prompt_key: str) -> int:
    """Return the current version number for a prompt key (used in cache keys)."""
    prompts = _load_prompts()
    return prompts.get(prompt_key, {}).get("version", 1)
