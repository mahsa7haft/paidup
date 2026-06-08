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
import os
import re
import requests
from io import BytesIO

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
from app import database as db
from app.ai import resolve_person_to_company, resolve_company_domain
from PIL import Image, ImageDraw, ImageFont
from app.parliament import get_thumbnail_url

# Drop PNG files here to override the coloured-pill party indicator.
# Filename = party name slug (lowercase, spaces→hyphens). E.g. "labour.png".
_PARTY_LOGOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "party_logos")
_party_logo_cache: dict[str, "Image.Image | None"] = {}


_face_cache: dict[int, int | None] = {}  # member_id → face_bottom px (fitted photo coords)


def _detect_face_bottom(photo: Image.Image) -> int | None:
    """
    Run OpenCV Haar-cascade face detection on a fitted PIL photo.
    Returns the y-coordinate of the bottom of the largest detected face,
    or None if detection fails or cv2 is unavailable.
    """
    if not _HAS_CV2:
        return None
    try:
        gray    = np.array(photo.convert("L"))
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50)
        )
        if not len(faces):
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])  # largest by area
        return int(y + h)
    except Exception:
        return None


def _suit_top(member_id: int | None, fitted_photo: "Image.Image | None") -> int:
    """
    Return the y-coordinate (in card pixels) where badges may start.
    Uses face detection when possible; falls back to 65% of photo height.
    Clamped to [55%, 78%] of PHOTO_H so detection errors can't produce
    absurd values.
    """
    photo_y   = (CARD_H - PHOTO_H) // 2
    fallback  = photo_y + int(PHOTO_H * 0.65)
    clamp_min = photo_y + int(PHOTO_H * 0.55)
    clamp_max = photo_y + int(PHOTO_H * 0.78)

    face_bottom: int | None = None

    if member_id is not None and member_id in _face_cache:
        face_bottom = _face_cache[member_id]
    elif fitted_photo is not None:
        face_bottom = _detect_face_bottom(fitted_photo)
        if member_id is not None:
            _face_cache[member_id] = face_bottom

    if face_bottom is None:
        return fallback

    margin = int(PHOTO_H * 0.05)   # 5% clearance below chin
    raw    = photo_y + face_bottom + margin
    return max(clamp_min, min(clamp_max, raw))


def _load_party_logo(party: str) -> "Image.Image | None":
    slug = re.sub(r"[^a-z0-9]+", "-", party.lower()).strip("-")
    if slug in _party_logo_cache:
        return _party_logo_cache[slug]
    path = os.path.join(_PARTY_LOGOS_DIR, f"{slug}.png")
    if os.path.exists(path):
        try:
            _party_logo_cache[slug] = Image.open(path).convert("RGBA")
            return _party_logo_cache[slug]
        except Exception:
            pass
    _party_logo_cache[slug] = None
    return None

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
ANON_FILL    = "#5a5a5a"
ANON_RIM     = "#888888"

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
        # Google Favicons API — reliable, no auth, works for virtually any domain
        url = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        r = requests.get(url, timeout=5)
        if r.status_code == 200 and len(r.content) > 200:
            img = Image.open(BytesIO(r.content)).convert("RGBA")
            # Reject tiny default favicons (Google returns 16×16 grey square for unknowns)
            if img.size[0] >= 32:
                return img
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
    return "Non-cash"


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
    unknown_total = 0.0
    has_unknown = False
    for i in interests:
        if i["donor"] != "Unknown":
            totals[i["donor"]] = totals.get(i["donor"], 0.0) + i["value"]
        else:
            unknown_total += i["value"]
            has_unknown = True
    result = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    if has_unknown:  # include even when all unknown entries are in-kind (value=0)
        result.append(("Unknown", unknown_total))
    return result


def _is_person(name: str) -> bool:
    if _COMPANY_SUFFIXES.search(name):
        return False
    return bool(_PERSON_PREFIXES.match(name.strip()))


def _classify_donor(name: str) -> tuple[str, str | None]:
    """
    Return (badge_type, logo_domain).
    badge_type is one of: 'company_logo', 'company_initials', 'person'.

    All donors — company or person — go through the DB first (fast, cached),
    then fall back to Claude Haiku (one call per unknown name, stored forever).
    """
    link = db.get_donor_company_link(name)
    if link is not None:
        domain = link["logo_domain"]
        if domain and domain != db.NO_COMPANY:
            badge = "person" if _is_person(name) and not domain else "company_logo"
            return badge, domain
        return "person" if _is_person(name) else "company_initials", None

    # DB miss — ask Claude Haiku
    if _is_person(name):
        company_name, domain = resolve_person_to_company(name)
        if domain:
            db.save_donor_company_link(name, company_name, domain, source="ai")
            return "company_logo", domain
        db.save_donor_company_link(name, None, db.NO_COMPANY, source="ai")
        return "person", None
    else:
        domain = resolve_company_domain(name)
        if domain:
            db.save_donor_company_link(name, name, domain, source="ai")
            return "company_logo", domain
        db.save_donor_company_link(name, None, db.NO_COMPANY, source="ai")
        return "company_initials", None


def _pack(badges: list[tuple[str, float, int]],
          x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int, int, str, float]]:
    PAD = 6
    placed: list[tuple[int, int, int, str, float]] = []
    row_x, row_y, row_h = x0, y0, 0
    for name, value, r in badges:
        bw = bh = r * 2
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


def _layout_badges(interests: list[dict],
                   member_id: int | None = None,
                   fitted_photo: "Image.Image | None" = None) -> list[dict]:
    """
    Compute badge positions and classifications using the same algorithm as
    generate_card. Separating this lets the /badges endpoint return positions
    without re-rendering the PNG.
    Pass member_id (and optionally the already-fetched fitted_photo) so face
    detection can determine where badges may safely start.
    """
    donors = _aggregate(interests)
    if not donors:
        return []

    top         = _suit_top(member_id, fitted_photo)
    suit_bottom = (CARD_H - PHOTO_H) // 2 + PHOTO_H - 8

    # Guarantee at least one row of minimum-size badges
    MIN_ZONE = 12 * 2 + 8
    if suit_bottom - top < MIN_ZONE:
        top = suit_bottom - MIN_ZONE

    zone_h  = suit_bottom - top
    zone_w  = PHOTO_W - 16          # 8px margin each side
    n       = len(donors)
    PAD     = 6

    # Find the largest badge radius that fits all n donors in the zone.
    # MIN_R=24 → 48px badges → ~43px on a typical screen. Never go smaller;
    # if not all badges fit at that size, _pack drops the overflow.
    # opt_min_r is kept within 8px of max so no donor's badge is dramatically
    # smaller than the largest — the set reads as uniform rather than wildly scaled.
    MIN_R = 24
    opt_max_r = MIN_R
    for r in range(54, MIN_R - 1, -1):
        bpr    = max(1, (zone_w + PAD) // (2 * r + PAD))
        rows   = math.ceil(n / bpr)
        needed = rows * (2 * r + PAD) - PAD
        if needed <= zone_h:
            opt_max_r = r
            break
    opt_min_r = max(MIN_R, opt_max_r - 8)

    max_val = max(v for _, v in donors if v > 0) or 1
    sized = sorted(
        [(dn, v, _badge_radius(v, max_val, min_r=opt_min_r, max_r=opt_max_r))
         for dn, v in donors],
        key=lambda x: x[2], reverse=True,
    )
    placed = _pack(sized, 8, top, PHOTO_W - 8, suit_bottom)

    # Shift all badges down so they sit at the bottom of the suit area.
    # With few badges they hug the bottom; only climb upward when there are too many.
    if placed:
        lowest = max(cy + r for _, cy, r, _, _ in placed)
        shift  = max(0, suit_bottom - lowest - 4)
        placed = [(cx, cy + shift, r, n, v) for cx, cy, r, n, v in placed]

    result = []
    for cx, cy, r, dname, dval in placed:
        if dname == "Unknown":
            result.append({"cx": cx, "cy": cy, "r": r, "name": dname,
                           "value": dval, "badge_type": "anonymous", "domain": None})
        else:
            badge_type, domain = _classify_donor(dname)
            result.append({"cx": cx, "cy": cy, "r": r, "name": dname,
                           "value": dval, "badge_type": badge_type, "domain": domain})
    return result


def get_badge_layout(interests: list[dict], member_id: int | None = None) -> dict:
    """Return card dimensions + badge positions for the /badges endpoint."""
    # Fetch and fit the photo so face detection uses the same image as generate_card
    fitted = None
    if member_id is not None:
        raw = _fetch_photo(member_id)
        if raw:
            fitted = _fit_photo(raw, PHOTO_W, PHOTO_H)
    return {"card_w": CARD_W, "card_h": CARD_H,
            "badges": _layout_badges(interests, member_id, fitted)}


# ── Badge drawing ─────────────────────────────────────────────────────────────

def _draw_company_logo_badge(img: Image.Image, draw: ImageDraw.ImageDraw,
                              cx: int, cy: int, r: int,
                              name: str, value: float, domain: str,
                              font_val: ImageFont.FreeTypeFont,
                              font_name: ImageFont.FreeTypeFont) -> None:
    logo = _fetch_logo(domain)
    if logo:
        logo_size = r * 2
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
        img.paste(logo, (cx - logo_size // 2, cy - logo_size // 2), logo)
    else:
        _draw_anonymous_badge(draw, cx, cy, r, value, font_val, font_name, show_q=False)


def _draw_company_initials_badge(draw: ImageDraw.ImageDraw,
                                  cx: int, cy: int, r: int,
                                  name: str, value: float,
                                  font_val: ImageFont.FreeTypeFont,
                                  font_name: ImageFont.FreeTypeFont) -> None:
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


def _person_silhouette(draw: ImageDraw.ImageDraw,
                       head_cx: int, head_cy: int, head_r: int,
                       color: str, outline: str | None = None) -> None:
    """
    Head circle + cubic-bezier arch shoulders, replicating the SVG reference.
    Optional `outline` adds a 1px contrasting border — use "white" so the
    silhouette reads on both dark and light suit fabrics.
    """
    ow = 1 if outline else 0
    # Head
    draw.ellipse([head_cx-head_r, head_cy-head_r,
                  head_cx+head_r, head_cy+head_r],
                 fill=color, outline=outline, width=ow)
    # Arch — proportions from SVG: arch_hw/head_r≈1.78, gap/head_r≈0.43, depth/head_r≈2.14
    arch_hw = int(head_r * 1.78)
    y_bot   = head_cy + head_r + int(head_r * 2.14)
    y_top   = head_cy + head_r + int(head_r * 0.43)
    x1, x2  = head_cx - arch_hw, head_cx + arch_hw
    pts = []
    for i in range(21):
        t  = i / 20
        bx = int(x1 * (1-t)**2 * (1 + 2*t) + x2 * t**2 * (3 - 2*t))
        by = int(y_bot * ((1-t)**3 + t**3) + y_top * 3*t*(1-t))
        pts.append((bx, by))
    draw.polygon(pts, fill=color, outline=outline, width=ow)


def _draw_person_badge(draw: ImageDraw.ImageDraw,
                        cx: int, cy: int, r: int,
                        name: str, value: float,
                        font_val: ImageFont.FreeTypeFont,
                        font_name: ImageFont.FreeTypeFont) -> None:
    """Brand-green silhouette on the suit with white outline for contrast on dark fabric."""
    head_r  = max(4, int(r * 0.25))
    head_cy = cy - int(r * 0.27)
    _person_silhouette(draw, cx, head_cy, head_r, BRAND_GREEN, outline="white")


def _draw_anonymous_badge(draw: ImageDraw.ImageDraw,
                          cx: int, cy: int, r: int,
                          value: float,
                          font_val: ImageFont.FreeTypeFont,
                          font_name: ImageFont.FreeTypeFont,
                          show_q: bool = True) -> None:
    """
    Ghost figure (light grey, offset) behind a brand-green foreground figure.
    show_q=True  → white '?' on the head (unknown/unnamed payer).
    show_q=False → no mark (named donor with no logo).
    """
    head_r  = max(4, int(r * 0.25))
    head_cy = cy - int(r * 0.27)

    if r >= 26:
        g_hr  = max(3, int(head_r * 0.80))
        g_cx  = cx + int(r * 0.14)
        g_cy  = head_cy - int(r * 0.06)
        _person_silhouette(draw, g_cx, g_cy, g_hr, "#c0c0c0")
        fg_cx = cx - int(r * 0.07)
    else:
        fg_cx = cx

    _person_silhouette(draw, fg_cx, head_cy, head_r, BRAND_GREEN, outline="white")

    if show_q:
        q_size = max(8, int(head_r * 1.3))
        qfont  = font_name
        for path in ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf"]:
            try:
                qfont = ImageFont.truetype(path, q_size)
                break
            except Exception:
                pass
        draw.text((fg_cx, head_cy), "?", fill="white", font=qfont, anchor="mm")




# ── Main ──────────────────────────────────────────────────────────────────────

def generate_card(member_id: int, name: str, interests: list[dict],
                  party: str = "", title: str = "",
                  date_from: str = "", date_to: str = "") -> Image.Image:
    card = Image.new("RGB", (CARD_W, CARD_H), CREAM)
    draw = ImageDraw.Draw(card)

    (font_name_lg, font_party, font_total, font_sub,
     font_badge_val, font_badge_name,
     font_dim) = _fonts([24, 14, 32, 13, 13, 11, 11])

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
    layout = _layout_badges(interests, member_id, photo)
    for badge in layout:
        cx, cy, r = badge["cx"], badge["cy"], badge["r"]
        dname, dval = badge["name"], badge["value"]
        badge_type, domain = badge["badge_type"], badge["domain"]
        fv = font_badge_val if r >= 22 else font_badge_name
        fn = font_badge_name
        if badge_type == "anonymous":
            _draw_anonymous_badge(draw, cx, cy, r, dval, fv, fn, show_q=True)
        elif badge_type == "company_logo" and domain:
            _draw_company_logo_badge(card, draw, cx, cy, r, dname, dval, domain, fv, fn)
        elif badge_type == "person":
            _draw_person_badge(draw, cx, cy, r, dname, dval, fv, fn)
        else:
            # Named donor with no logo — same silhouette as anonymous but no '?'
            _draw_anonymous_badge(draw, cx, cy, r, dval, fv, fn, show_q=False)

    # ── Right panel ──
    rx, ry = PHOTO_W + 28, 30

    draw.text((rx, ry), name, fill=TEXT_DARK, font=font_name_lg)
    ry += 30
    for role in [r for r in title.split("|") if r]:
        draw.text((rx, ry), role, fill=TEXT_MID, font=font_dim)
        ry += 15
    ry += 4

    if party:
        logo_img = _load_party_logo(party)
        if logo_img:
            logo_h = 32
            logo_w = int(logo_img.width * logo_h / logo_img.height)
            scaled = logo_img.resize((logo_w, logo_h), Image.LANCZOS)
            card_rgba = card.convert("RGBA")
            card_rgba.paste(scaled, (rx, ry), scaled)
            card = card_rgba.convert("RGB")
            draw = ImageDraw.Draw(card)
            ry += logo_h + 10
        else:
            # Coloured pill fallback until a logo file is added
            colour = _party_colour(party)
            bb = draw.textbbox((0, 0), party, font=font_party)
            tw, th = bb[2] - bb[0], bb[3] - bb[1]
            px, py = 10, 5
            draw.rounded_rectangle(
                [rx, ry, rx + tw + px * 2, ry + th + py * 2],
                radius=5, fill=colour,
            )
            draw.text((rx + px, ry + py), party, fill="white", font=font_party)
            ry += th + py * 2 + 10

    ry += 6

    total = sum(i["value"] for i in interests)
    draw.text((rx, ry), f"£{round(total):,}", fill=TEXT_DARK, font=font_total)
    ry += 42
    draw.text((rx, ry), "declared to Parliament", fill=TEXT_DIM, font=font_sub)
    ry += 24

    draw.line([(rx, ry), (CARD_W - 24, ry)], fill=PANEL_LINE, width=1)
    ry += 16

    all_donors  = _aggregate(interests)
    named_count = sum(1 for n, _ in all_donors if n != "Unknown")
    anon_count  = sum(1 for n, _ in all_donors if n == "Unknown")
    count_str = f"{named_count} declared donor{'' if named_count == 1 else 's'}"
    if anon_count:
        count_str += f" + {anon_count} unknown"
    draw.text((rx, ry), count_str, fill=TEXT_MID, font=font_sub)
    ry += 20
    draw.text((rx, ry), "Badge size = total donated", fill=TEXT_DIM, font=font_dim)
    ry += 20

    if date_from and date_to:
        draw.text((rx, ry), f"Data covers {date_from} to {date_to}",
                  fill=TEXT_DIM, font=font_dim)

    return card
