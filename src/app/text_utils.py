"""
Shared text normalisation and fuzzy-matching helpers.

Used by parliament.py (donor deduplication) and database.py (DB name lookup)
so that misspellings and legal-suffix variants resolve to the same entry.
"""

import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_SUFFIXES = re.compile(
    r"\b(limited|ltd|plc|llp|lp|l\.p\.|corp|corporation|"
    r"incorporated|inc|group|holdings|& co|and co|co)\b\.?",
    re.IGNORECASE,
)
_TITLES = re.compile(
    r"^(the|mr|mrs|ms|miss|dr|prof|lord|lady|sir|dame|baroness|baron|earl|"
    r"viscount|rt\s+hon|the\s+rt\s+hon)\s+",
    re.IGNORECASE,
)
_SPACE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """
    Strip honorifics, 'The' prefix, and legal suffixes; collapse whitespace; lowercase.
    Used for comparison only — original name is always preserved for display.

    Examples:
      'The Arsenal Football Club Limited' → 'arsenal football club'
      'Lord David Sainsbury'             → 'david sainsbury'
      'Arsenal Football Club'            → 'arsenal football club'
    """
    name = _TITLES.sub("", name.strip())
    name = _SUFFIXES.sub("", name)
    return _SPACE.sub(" ", name).strip().lower()


def best_fuzzy_match(query: str, candidates: list[str],
                     threshold: float = 0.82) -> str | None:
    """
    Return the candidate from `candidates` whose normalised form is most similar
    to the normalised `query`, provided the cosine similarity is >= threshold.
    Returns None if no candidate clears the threshold or the list is empty.

    Uses TF-IDF character 2-3 gram cosine similarity — the same algorithm as
    deduplicate_donors — so results are consistent across the codebase.
    """
    if not candidates:
        return None

    norm_query = normalize_name(query)
    norm_cands = [normalize_name(c) for c in candidates]

    # Exact normalised match first (faster, no sklearn needed)
    for i, nc in enumerate(norm_cands):
        if nc == norm_query:
            return candidates[i]

    all_texts = [norm_query] + norm_cands
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 3), min_df=1)
        matrix = vec.fit_transform(all_texts)
    except ValueError:
        return None

    sims = cosine_similarity(matrix[0:1], matrix[1:])[0]
    best_idx = int(sims.argmax())
    if sims[best_idx] >= threshold:
        return candidates[best_idx]
    return None
