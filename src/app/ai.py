"""
AI analysis layer using the Anthropic Claude API.
Prompts live in src/app/prompts/ as plain text files named {key}_v{n}.txt.
The loader always picks the highest version for each key.
Add ANTHROPIC_API_KEY to your .env to enable this feature.
"""

import json
import os
import re
from pathlib import Path
import anthropic
import logging as _logging
try:
    from langfuse import Langfuse
    _langfuse_client = Langfuse() if (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")) else None
    _LANGFUSE = _langfuse_client is not None
    _logging.getLogger(__name__).info("Langfuse initialised: %s", _LANGFUSE)
except Exception as _lf_exc:
    _logging.getLogger(__name__).warning("Langfuse disabled: %s", _lf_exc)
    _LANGFUSE = False
    _langfuse_client = None

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

    generation = None
    if _langfuse_client:
        trace = _langfuse_client.trace(name="analyze", metadata={"mp": mp_name, "prompt_key": prompt_key})
        generation = trace.generation(
            name="claude-sonnet-4-6",
            model="claude-sonnet-4-6",
            input=user_message,
            metadata={"prompt_version": prompt_cfg["version"]},
        )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1200,
        system=prompt_cfg["system"] + _SHARED_RULES,
        messages=[{"role": "user", "content": user_message}],
    )

    if generation:
        generation.end(
            output=message.content[0].text,
            usage={"input": message.usage.input_tokens, "output": message.usage.output_tokens, "unit": "TOKENS"},
        )
        _langfuse_client.flush()

    return message.content[0].text


_RESOLVE_PERSON_SYSTEM = """\
You are a UK political research assistant. Given a donor name from the UK Parliament
Register of Members' Financial Interests, determine whether this person is the founder,
owner, or controlling shareholder of a well-known company.

Reply ONLY with a JSON object — no prose, no markdown fences:
  {"company_name": "Sainsbury's", "domain": "sainsburys.co.uk"}
or, if no clear corporate link exists:
  {"company_name": null, "domain": null}

Rules:
- Only return a company if the association is well-established and publicly known.
- Use the company's primary web domain (not a social media URL).
- For supermarkets/retailers use the .co.uk domain if one exists.
- If the name is clearly a company (Ltd, PLC, Trust, Foundation suffix) return null/null.
- If uncertain, return null/null."""

_RESOLVE_COMPANY_SYSTEM = """\
You are a research assistant. Given a company or organisation name, return its primary
website domain so a logo can be fetched.

Reply ONLY with a JSON object — no prose, no markdown fences:
  {"domain": "ndtv.com"}
or, if you do not know a reliable domain:
  {"domain": null}

Rules:
- Return only the root domain (e.g. barings.com, not www.barings.com/investments).
- Use the .co.uk domain for UK companies where that is their primary web presence.
- If the name is a person rather than a company, return null.
- If uncertain, return null."""


def resolve_person_to_company(donor_name: str) -> tuple[str | None, str | None]:
    """
    Ask Claude whether a donor name belongs to a known company owner/founder.
    Returns (company_name, logo_domain) or (None, None).
    Falls back to (None, None) on any error so the caller always gets a safe result.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=_RESOLVE_PERSON_SYSTEM,
            messages=[{"role": "user", "content": donor_name}],
        )
        raw = msg.content[0].text.strip()
        if not raw:
            return None, None
        # Strip accidental markdown fences if the model ignores instructions
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        data = json.loads(raw)
        return data.get("company_name"), data.get("domain")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("resolve_person_to_company failed: %s", exc)
        return None, None


def resolve_company_domain(company_name: str) -> str | None:
    """
    Ask Claude Haiku for the primary web domain of a company or organisation.
    Returns a domain string or None. Never raises.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=40,
            system=_RESOLVE_COMPANY_SYSTEM,
            messages=[{"role": "user", "content": company_name}],
        )
        raw = msg.content[0].text.strip()
        if not raw:
            return None
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        data = json.loads(raw)
        return data.get("domain")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("resolve_company_domain failed: %s", exc)
        return None


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
