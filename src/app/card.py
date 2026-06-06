"""
Generates a donor card image.
Donor badges come in three shapes based on who the donor is:
  - Company with logo   → blue circle, Clearbit logo overlaid
  - Company no logo     → blue circle, 2-letter initials
  - Person              → green rounded-rect, person icon + readable name
For titled individuals (Lord, Sir, etc.) we first check whether they are known
company owners via the donor_company_links DB table (seeded lazily by Claude).
"""

import math
import re
import textwrap
import requests
from io import BytesIO
from app import database as db
from app.ai import resolve_person_to_company
from PIL import Image, ImageDraw, ImageFont
from app.parliament import get_thumbnail_url

CARD_W, CARD_H = 900, 500
PHOTO_W, PHOTO_H = 320, 480

BG           = "#1a1a2e"
TEXT_W       = "#ffffff"
TEXT_DIM     = "#aaaaaa"
GOLD         = "#f4d03f"
COMPANY_FILL = "#1e3a5f"
COMPANY_RIM  = "#2a5298"
PERSON_FILL  = "#1a4a2e"
PERSON_RIM   = "#27ae60"

_PERSON_PREFIXES = re.compile(
    r"^(mr|mrs|ms|miss|dr|prof|lord|lady|sir|dame|baroness|baron|earl|viscount|"
    r"the\s+rt\s+hon|rt\s+hon)\b",
    re.IGNORECASE,
)
_COMPANY_SUFFIXES = re.compile(
    r"\b(ltd|limited|plc|llp|llc|inc|group|trust|foundation|charity|fund|"
    r"association|society|union|party|council|committee|corp|corporation)\b",
    re.IGNORECASE,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _fetch_photo(member_id: int) -> Image.Image | None:
    try:
        r = requests.get(get_thumbnail_url(member_id), timeout=5)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None


def _fetch_logo(domain: str) -> Image.Image | None:
    try:
        r = requests.get(f"https://logo.clearbit.com/{domain}", timeout=4)
        if r.status_code == 200:
            return Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception:
        pass
    return None


def _fonts(sizes: list[int]) -> list[ImageFont.FreeTypeFont]:
    for path in ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf"]:
        try:
            return [ImageFont.truetype(path, s) for s in sizes]
        except Exception:
            pass
    fb = ImageFont.load_default()
    return [fb] * len(sizes)


def _fmt(value: float) -> str:
    if value >= 1_000_000:
        return f"£{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"£{value / 1_000:.0f}k"
    if value > 0:
        return f"£{int(value)}"
    return "In kind"


def _badge_radius(value: float, max_value: float,
                  min_r: int = 18, max_r: int = 54) -> int:
    if max_value == 0 or value <= 0:
        return min_r
    return int(min_r + (max_r - min_r) * math.sqrt(value / max_value))


def _initials(name: str) -> str:
    skip = {"the", "of", "and", "&", "ltd", "plc", "limited", "group", "trust",
            "holdings", "company", "services", "international"}
    # Strip punctuation from each token before checking
    clean_words = [re.sub(r"[^a-zA-Z0-9]", "", w) for w in name.split()]
    words = [w for w in clean_words if w and w.lower() not in skip]
    if len(words) >= 2:
        return (words[0][0] + words[-1][0]).upper()
    if words:
        return words[0][:2].upper()
    return name[:2].upper() if name else "??"


def _aggregate(interests: list[dict]) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for i in interests:
        if i["donor"] != "Unknown":
            totals[i["donor"]] = totals.get(i["donor"], 0.0) + i["value"]
    return sorted(totals.items(), key=lambda x: x[1], reverse=True)


def _is_person(name: str) -> bool:
    """True if name looks like an individual rather than an organisation."""
    if _COMPANY_SUFFIXES.search(name):
        return False
    return bool(_PERSON_PREFIXES.match(name.strip()))


def _classify_donor(name: str) -> tuple[str, str | None]:
    """
    Return (badge_type, logo_domain).
    badge_type is one of: 'company_logo', 'company_initials', 'person'.

    For person-looking names we check the DB for a stored company association,
    then fall back to asking Claude (result stored for next time).
    """
    if not _is_person(name):
        # Straightforward company — try Clearbit
        domain = _guess_domain(name)
        if domain:
            return "company_logo", domain
        return "company_initials", None

    # Person prefix detected — check DB first
    link = db.get_donor_company_link(name)
    if link is not None:
        if link["logo_domain"] and link["logo_domain"] != db.NO_COMPANY:
            return "company_logo", link["logo_domain"]
        return "person", None

    # Not in DB → ask Claude (uses Haiku, ~0.001 USD per call)
    company_name, domain = resolve_person_to_company(name)
    if domain:
        db.save_donor_company_link(name, company_name, domain, source="ai")
        return "company_logo", domain
    else:
        db.save_donor_company_link(name, None, db.NO_COMPANY, source="ai")
        return "person", None


def _guess_domain(name: str) -> str | None:
    """
    Very lightweight heuristic — strips common suffixes and builds a .com domain.
    Only used as a first-pass; Clearbit will reject unknown domains silently.
    """
    cleaned = _COMPANY_SUFFIXES.sub("", name).strip().lower()
    cleaned = re.sub(r"[^a-z0-9\s]", "", cleaned).strip()
    if not cleaned:
        return None
    slug = cleaned.replace(" ", "")
    return f"{slug}.com" if len(slug) >= 3 else None


def _pack(badges: list[tuple[str, float, int]],
          x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int, int, str, float]]:
    PAD = 6
    placed: list[tuple[int, int, int, str, float]] = []
    row_x, row_y, row_h = x0, y0, 0

    for name, value, r in badges:
        bw = r * 2 if not _is_person(name) else int(r * 2.2)
        bh = r * 2 if not _is_person(name) else int(r * 2.0)
        if row_x + bw > x1:
            row_y += row_h + PAD
            row_x = x0
            row_h = 0
        if row_y + bh > y1:
            break
        cx = row_x + bw // 2
        cy = row_y + bh // 2
        placed.append((cx, cy, r, name, value))
        row_x += bw + PAD
        row_h = max(row_h, bh)

    return placed


# ── badge drawing ─────────────────────────────────────────────────────────────

def _draw_company_logo_badge(img: Image.Image, draw: ImageDraw.ImageDraw,
                              cx: int, cy: int, r: int,
                              name: str, value: float, domain: str,
                              font_val: ImageFont.FreeTypeFont,
                              font_name: ImageFont.FreeTypeFont) -> None:
    draw.ellipse([cx-r+2, cy-r+2, cx+r+2, cy+r+2], fill="#000000")
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=COMPANY_FILL, outline=COMPANY_RIM, width=2)

    logo = _fetch_logo(domain)
    if logo:
        logo_size = int(r * 1.5)
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
        img.paste(logo, (cx - logo_size // 2, cy - logo_size // 2), logo)
        draw.text((cx, cy + r + 10), _fmt(value), fill=GOLD, font=font_val, anchor="mm")
    else:
        # Logo fetch failed — fall back to initials inside circle
        inits = _initials(name)
        draw.text((cx, cy - r // 4), inits, fill=TEXT_W, font=font_val, anchor="mm")
        draw.text((cx, cy + r // 4 + 2), _fmt(value), fill=GOLD, font=font_val, anchor="mm")


def _draw_company_initials_badge(draw: ImageDraw.ImageDraw,
                                  cx: int, cy: int, r: int,
                                  name: str, value: float,
                                  font_val: ImageFont.FreeTypeFont,
                                  font_name: ImageFont.FreeTypeFont) -> None:
    draw.ellipse([cx-r+2, cy-r+2, cx+r+2, cy+r+2], fill="#000000")
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=COMPANY_FILL, outline=COMPANY_RIM, width=2)

    inits = _initials(name)
    val_str = _fmt(value)
    if r >= 36:
        draw.text((cx, cy - r // 4), inits, fill=TEXT_W, font=font_val, anchor="mm")
        draw.text((cx, cy + r // 4 + 2), val_str, fill=GOLD, font=font_val, anchor="mm")
    elif r >= 22:
        draw.text((cx, cy - 6), inits, fill=TEXT_W, font=font_name, anchor="mm")
        draw.text((cx, cy + 8), val_str, fill=GOLD, font=font_name, anchor="mm")
    else:
        draw.text((cx, cy), val_str, fill=TEXT_W, font=font_name, anchor="mm")


def _draw_person_badge(draw: ImageDraw.ImageDraw,
                        cx: int, cy: int, r: int,
                        name: str, value: float,
                        font_val: ImageFont.FreeTypeFont,
                        font_name: ImageFont.FreeTypeFont) -> None:
    bw = int(r * 2.2)
    bh = int(r * 2.0)
    bx0, by0 = cx - bw // 2, cy - bh // 2
    bx1, by1 = cx + bw // 2, cy + bh // 2
    radius = max(4, r // 7)

    # Shadow
    draw.rounded_rectangle([bx0+2, by0+2, bx1+2, by1+2], radius=radius, fill="#000000")
    # Body
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=radius,
                            fill=PERSON_FILL, outline=PERSON_RIM, width=2)
    # Header strip
    strip_h = max(14, r // 3)
    draw.rounded_rectangle([bx0, by0, bx1, by0 + strip_h], radius=radius, fill=PERSON_RIM)
    draw.rectangle([bx0, by0 + strip_h // 2, bx1, by0 + strip_h], fill=PERSON_RIM)

    if r >= 30:
        # Person silhouette icon
        icon_cy = by0 + strip_h + (bh - strip_h) // 3
        ir = max(5, r // 8)
        draw.ellipse([cx - ir, icon_cy - ir, cx + ir, icon_cy + ir], fill=TEXT_W)
        draw.arc([cx - ir*2, icon_cy + ir//2, cx + ir*2, icon_cy + ir*3],
                 start=0, end=180, fill=TEXT_W, width=2)

        # Name — split across two lines if needed
        parts = name.split()
        # Drop titles for display to save space
        title_words = {"mr", "mrs", "ms", "miss", "dr", "prof", "lord", "lady",
                       "sir", "dame", "baroness", "baron", "earl", "viscount", "the", "rt", "hon"}
        display_parts = [p for p in parts if p.lower() not in title_words] or parts
        line1 = " ".join(display_parts[:2])
        line2 = " ".join(display_parts[2:]) if len(display_parts) > 2 else ""

        ty = icon_cy + ir * 3 + 4
        draw.text((cx, ty), line1, fill=TEXT_W, font=font_name, anchor="mm")
        if line2:
            draw.text((cx, ty + 13), line2, fill=TEXT_W, font=font_name, anchor="mm")
            draw.text((cx, ty + 27), _fmt(value), fill=GOLD, font=font_name, anchor="mm")
        else:
            draw.text((cx, ty + 14), _fmt(value), fill=GOLD, font=font_name, anchor="mm")
    elif r >= 20:
        short = name.split()[-1]
        draw.text((cx, cy - 6), short, fill=TEXT_W, font=font_name, anchor="mm")
        draw.text((cx, cy + 8), _fmt(value), fill=GOLD, font=font_name, anchor="mm")
    else:
        draw.text((cx, cy), _fmt(value), fill=TEXT_W, font=font_name, anchor="mm")


# ── main ─────────────────────────────────────────────────────────────────────

def generate_card(member_id: int, name: str, interests: list[dict]) -> Image.Image:
    card = Image.new("RGB", (CARD_W, CARD_H), BG)
    draw = ImageDraw.Draw(card)

    (font_name_lg, font_name_sm, font_sub,
     font_badge_val, font_badge_name) = _fonts([22, 14, 13, 12, 10])

    # ── photo ──
    photo = _fetch_photo(member_id)
    photo_x, photo_y = 0, (CARD_H - PHOTO_H) // 2
    if photo:
        photo = photo.resize((PHOTO_W, PHOTO_H), Image.LANCZOS)
        if photo.mode == "RGBA":
            card.paste(photo, (photo_x, photo_y), photo)
        else:
            card.paste(photo.convert("RGB"), (photo_x, photo_y))

    # ── badges ──
    donors = _aggregate(interests)
    if donors:
        max_val = max(v for _, v in donors if v > 0) or 1
        sized = [(n, v, _badge_radius(v, max_val)) for n, v in donors]
        sized.sort(key=lambda x: x[2], reverse=True)

        suit_top    = photo_y + int(PHOTO_H * 0.62)
        suit_bottom = photo_y + PHOTO_H - 8
        suit_left   = photo_x + 8
        suit_right  = photo_x + PHOTO_W - 8

        placed = _pack(sized, suit_left, suit_top, suit_right, suit_bottom)

        for cx, cy, r, dname, dval in placed:
            badge_type, domain = _classify_donor(dname)
            fv = font_badge_val if r >= 22 else font_badge_name
            fn = font_badge_name

            if badge_type == "company_logo" and domain:
                _draw_company_logo_badge(card, draw, cx, cy, r, dname, dval, domain, fv, fn)
            elif badge_type == "person":
                _draw_person_badge(draw, cx, cy, r, dname, dval, fv, fn)
            else:
                _draw_company_initials_badge(draw, cx, cy, r, dname, dval, fv, fn)

    # ── right panel ──
    rx, ry = PHOTO_W + 24, 20
    draw.text((rx, ry), name, fill=TEXT_W, font=font_name_lg)
    ry += 34

    total = sum(i["value"] for i in interests)
    draw.text((rx, ry), f"£{round(total):,}", fill=GOLD, font=font_name_lg)
    ry += 30
    draw.text((rx, ry), "total declared", fill=TEXT_DIM, font=font_sub)
    ry += 28

    draw.line([(rx, ry), (CARD_W - 20, ry)], fill="#2e2e50", width=1)
    ry += 16

    donor_count = len(donors)
    draw.text((rx, ry), f"{donor_count} declared donor{'' if donor_count == 1 else 's'}",
              fill=TEXT_DIM, font=font_sub)
    ry += 20
    draw.text((rx, ry), "Badge size = total donated", fill="#555577", font=font_badge_name)

    draw.text((CARD_W - 16, CARD_H - 14), "paidup.app",
              fill="#333355", font=font_badge_name, anchor="ra")

    return card
