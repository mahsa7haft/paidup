"""
Generates a donor card image — brand F (cream / light) design.
Donor badges come in three shapes based on who the donor is:
  - Company with logo   → dark circle, Clearbit logo overlaid
  - Company no logo     → dark circle, 2-letter initials
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

# ── Palette (brand F — cream) ─────────────────────────────────────────────────
CREAM       = "#f0ebe0"
PANEL_LINE  = "#d8d0c4"
TEXT_DARK   = "#1a1a1a"
TEXT_MID    = "#555555"
TEXT_DIM    = "#999999"
BRAND_GREEN = "#1D9E75"
COMPANY_FILL = "#1a2a3a"
COMPANY_RIM  = "#2a3a4a"
PERSON_FILL  = "#1a4a2e"
PERSON_RIM   = "#27ae60"
BADGE_TEXT   = "#ffffff"
BADGE_VAL    = "#1D9E75"

# Party brand colours (UK Parliament)
_PARTY_COLOURS: dict[str, str] = {
    "Labour":           "#e4003b",
    "Conservative":     "#0087dc",
    "Liberal Democrat": "#faa61a",
    "SNP":              "#c8a800",
    "Green Party":      "#00b140",
    "Plaid Cymru":      "#005b54",
    "DUP":              "#d46a4c",
    "Sinn Féin":        "#326760",
    "Alliance":         "#e8a020",
    "UUP":              "#48a5ee",
    "Reform UK":        "#12b6cf",
    "Independent":      "#666666",
    "Speaker":          "#888888",
}

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


def _party_colour(party: str) -> str:
    for key, colour in _PARTY_COLOURS.items():
        if key.lower() in party.lower():
            return colour
    return BRAND_GREEN


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fetch_photo(member_id: int) -> Image.Image | None:
    try:
        r = requests.get(get_thumbnail_url(member_id), timeout=5)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None


def _fit_photo(photo: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Scale the photo to fill the target dimensions without stretching.
    Strategy: scale so the image fills the target height, then centre-crop
    to the target width. Parliament headshots are square (240×240), so
    this zooms in slightly and produces a natural portrait crop.
    """
    src_w, src_h = photo.size
    scale = target_h / src_h
    new_w, new_h = int(src_w * scale), target_h
    photo = photo.resize((new_w, new_h), Image.LANCZOS)
    if new_w >= target_w:
        left = (new_w - target_w) // 2
        photo = photo.crop((left, 0, left + target_w, new_h))
    else:
        # Narrower than target — pad sides with cream (rare)
        canvas = Image.new(photo.mode, (target_w, new_h), CREAM[:7])
        canvas.paste(photo, ((target_w - new_w) // 2, 0))
        photo = canvas
    return photo


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
    if _COMPANY_SUFFIXES.search(name):
        return False
    return bool(_PERSON_PREFIXES.match(name.strip()))


def _classify_donor(name: str) -> tuple[str, str | None]:
    """
    Return (badge_type, logo_domain).
    badge_type is one of: 'company_logo', 'company_initials', 'person'.
    """
    if not _is_person(name):
        domain = _guess_domain(name)
        if domain:
            return "company_logo", domain
        return "company_initials", None

    link = db.get_donor_company_link(name)
    if link is not None:
        if link["logo_domain"] and link["logo_domain"] != db.NO_COMPANY:
            return "company_logo", link["logo_domain"]
        return "person", None

    company_name, domain = resolve_person_to_company(name)
    if domain:
        db.save_donor_company_link(name, company_name, domain, source="ai")
        return "company_logo", domain
    else:
        db.save_donor_company_link(name, None, db.NO_COMPANY, source="ai")
        return "person", None


def _guess_domain(name: str) -> str | None:
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
        placed.append((row_x + bw // 2, row_y + bh // 2, r, name, value))
        row_x += bw + PAD
        row_h = max(row_h, bh)
    return placed


# ── Badge drawing ─────────────────────────────────────────────────────────────

def _draw_company_logo_badge(img: Image.Image, draw: ImageDraw.ImageDraw,
                              cx: int, cy: int, r: int,
                              name: str, value: float, domain: str,
                              font_val: ImageFont.FreeTypeFont,
                              font_name: ImageFont.FreeTypeFont) -> None:
    draw.ellipse([cx-r+2, cy-r+2, cx+r+2, cy+r+2], fill="#00000040")
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=COMPANY_FILL, outline=COMPANY_RIM, width=2)
    logo = _fetch_logo(domain)
    if logo:
        # Logo occupies the top ~60% of the circle; value sits in the bottom quarter
        logo_size = int(r * 1.2)
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
        img.paste(logo, (cx - logo_size // 2, cy - logo_size // 2 - r // 6), logo)
        draw.text((cx, cy + r // 3), _fmt(value), fill=BADGE_VAL, font=font_val, anchor="mm")
    else:
        inits = _initials(name)
        draw.text((cx, cy - r // 4), inits, fill=BADGE_TEXT, font=font_val, anchor="mm")
        draw.text((cx, cy + r // 4 + 2), _fmt(value), fill=BADGE_VAL, font=font_val, anchor="mm")


def _draw_company_initials_badge(draw: ImageDraw.ImageDraw,
                                  cx: int, cy: int, r: int,
                                  name: str, value: float,
                                  font_val: ImageFont.FreeTypeFont,
                                  font_name: ImageFont.FreeTypeFont) -> None:
    draw.ellipse([cx-r+2, cy-r+2, cx+r+2, cy+r+2], fill="#00000040")
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=COMPANY_FILL, outline=COMPANY_RIM, width=2)
    inits = _initials(name)
    val_str = _fmt(value)
    if r >= 36:
        draw.text((cx, cy - r // 4), inits, fill=BADGE_TEXT, font=font_val, anchor="mm")
        draw.text((cx, cy + r // 4 + 2), val_str, fill=BADGE_VAL, font=font_val, anchor="mm")
    elif r >= 22:
        draw.text((cx, cy - 6), inits, fill=BADGE_TEXT, font=font_name, anchor="mm")
        draw.text((cx, cy + 8), val_str, fill=BADGE_VAL, font=font_name, anchor="mm")
    else:
        draw.text((cx, cy), val_str, fill=BADGE_TEXT, font=font_name, anchor="mm")


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
    draw.rounded_rectangle([bx0+2, by0+2, bx1+2, by1+2], radius=radius, fill="#00000040")
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=radius,
                            fill=PERSON_FILL, outline=PERSON_RIM, width=2)
    strip_h = max(14, r // 3)
    draw.rounded_rectangle([bx0, by0, bx1, by0 + strip_h], radius=radius, fill=PERSON_RIM)
    draw.rectangle([bx0, by0 + strip_h // 2, bx1, by0 + strip_h], fill=PERSON_RIM)

    if r >= 30:
        icon_cy = by0 + strip_h + (bh - strip_h) // 3
        ir = max(5, r // 8)
        draw.ellipse([cx - ir, icon_cy - ir, cx + ir, icon_cy + ir], fill=BADGE_TEXT)
        draw.arc([cx - ir*2, icon_cy + ir//2, cx + ir*2, icon_cy + ir*3],
                 start=0, end=180, fill=BADGE_TEXT, width=2)
        title_words = {"mr", "mrs", "ms", "miss", "dr", "prof", "lord", "lady",
                       "sir", "dame", "baroness", "baron", "earl", "viscount", "the", "rt", "hon"}
        display_parts = [p for p in name.split() if p.lower() not in title_words] or name.split()
        line1 = " ".join(display_parts[:2])
        line2 = " ".join(display_parts[2:]) if len(display_parts) > 2 else ""
        ty = icon_cy + ir * 3 + 4
        draw.text((cx, ty), line1, fill=BADGE_TEXT, font=font_name, anchor="mm")
        if line2:
            draw.text((cx, ty + 13), line2, fill=BADGE_TEXT, font=font_name, anchor="mm")
            draw.text((cx, ty + 27), _fmt(value), fill=BADGE_VAL, font=font_name, anchor="mm")
        else:
            draw.text((cx, ty + 14), _fmt(value), fill=BADGE_VAL, font=font_name, anchor="mm")
    elif r >= 20:
        short = name.split()[-1]
        draw.text((cx, cy - 6), short, fill=BADGE_TEXT, font=font_name, anchor="mm")
        draw.text((cx, cy + 8), _fmt(value), fill=BADGE_VAL, font=font_name, anchor="mm")
    else:
        draw.text((cx, cy), _fmt(value), fill=BADGE_TEXT, font=font_name, anchor="mm")


def _draw_paidup_logo(draw: ImageDraw.ImageDraw,
                      x: int, y: int,
                      font_brand: ImageFont.FreeTypeFont,
                      font_symbol: ImageFont.FreeTypeFont) -> None:
    r = 14
    cx, cy = x + r, y + r
    # Circle (the lens)
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=CREAM, outline=BRAND_GREEN, width=2)
    draw.text((cx, cy), "£", fill=BRAND_GREEN, font=font_symbol, anchor="mm")
    # Handle: starts at circle edge at 45°, extends ~75% of r further — matches SVG proportions
    import math
    angle = math.radians(45)
    hx0 = cx + int(r * math.cos(angle))
    hy0 = cy + int(r * math.sin(angle))
    handle_len = int(r * 0.8)
    hx1 = hx0 + int(handle_len * math.cos(angle))
    hy1 = hy0 + int(handle_len * math.sin(angle))
    draw.line([hx0, hy0, hx1, hy1], fill=BRAND_GREEN, width=3)
    # Wordmark
    draw.text((cx + r + 7, cy), "Paid Up", fill=BRAND_GREEN, font=font_brand, anchor="lm")


# ── Main ──────────────────────────────────────────────────────────────────────

def generate_card(member_id: int, name: str, interests: list[dict],
                  party: str = "") -> Image.Image:
    card = Image.new("RGB", (CARD_W, CARD_H), CREAM)
    draw = ImageDraw.Draw(card)

    (font_name_lg, font_party, font_total, font_sub,
     font_badge_val, font_badge_name, font_logo, font_logo_sym,
     font_dim) = _fonts([22, 13, 32, 11, 12, 10, 13, 13, 9])

    # ── Photo ──
    photo = _fetch_photo(member_id)
    photo_x, photo_y = 0, (CARD_H - PHOTO_H) // 2
    if photo:
        photo = _fit_photo(photo, PHOTO_W, PHOTO_H)
        if photo.mode == "RGBA":
            card.paste(photo, (photo_x, photo_y), photo)
        else:
            card.paste(photo.convert("RGB"), (photo_x, photo_y))

    draw.line([(PHOTO_W, 0), (PHOTO_W, CARD_H)], fill=PANEL_LINE, width=1)

    # ── Badges on suit ──
    donors = _aggregate(interests)
    if donors:
        max_val = max(v for _, v in donors if v > 0) or 1
        sized = sorted([(n, v, _badge_radius(v, max_val)) for n, v in donors],
                       key=lambda x: x[2], reverse=True)
        suit_top    = photo_y + int(PHOTO_H * 0.62)
        suit_bottom = photo_y + PHOTO_H - 8
        placed = _pack(sized, photo_x + 8, suit_top, photo_x + PHOTO_W - 8, suit_bottom)

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

    # ── Right panel ──
    rx, ry = PHOTO_W + 28, 22

    _draw_paidup_logo(draw, rx, ry, font_logo, font_logo_sym)
    ry += 42

    draw.text((rx, ry), name, fill=TEXT_DARK, font=font_name_lg)
    ry += 28

    if party:
        draw.text((rx, ry), party, fill=_party_colour(party), font=font_party)
        ry += 22

    ry += 8

    total = sum(i["value"] for i in interests)
    draw.text((rx, ry), f"£{round(total):,}", fill=TEXT_DARK, font=font_total)
    ry += 38
    draw.text((rx, ry), "declared to Parliament", fill=TEXT_DIM, font=font_sub)
    ry += 22

    draw.line([(rx, ry), (CARD_W - 24, ry)], fill=PANEL_LINE, width=1)
    ry += 14

    donor_count = len(donors)
    draw.text((rx, ry), f"{donor_count} declared donor{'' if donor_count == 1 else 's'}",
              fill=TEXT_MID, font=font_sub)
    ry += 16
    draw.text((rx, ry), "Badge size = total donated", fill=TEXT_DIM, font=font_dim)

    draw.text((CARD_W - 16, CARD_H - 14), "paidup.app",
              fill=TEXT_DIM, font=font_dim, anchor="ra")

    return card
