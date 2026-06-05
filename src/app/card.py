"""
Generates a donor card image.
Donor badges are drawn as circles on the MP's suit, sized proportionally
to the total donated — bigger donor = bigger badge, like F1 sponsor logos.
"""

import math
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont
from app.parliament import get_thumbnail_url

CARD_W, CARD_H = 900, 500
PHOTO_W, PHOTO_H = 320, 480   # taller photo so suit is visible

BG        = "#1a1a2e"
TEXT_W    = "#ffffff"
TEXT_DIM  = "#aaaaaa"
GOLD      = "#f4d03f"
RED       = "#e63946"
RED_LIGHT = "#ff6b6b"


# ── helpers ──────────────────────────────────────────────────────────────────

def _fetch_photo(member_id: int) -> Image.Image | None:
    try:
        from io import BytesIO
        r = requests.get(get_thumbnail_url(member_id), timeout=5)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None


def _fonts(sizes: list[int]) -> list[ImageFont.FreeTypeFont]:
    paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
    ]
    for path in paths:
        try:
            return [ImageFont.truetype(path, s) for s in sizes]
        except Exception:
            pass
    fallback = ImageFont.load_default()
    return [fallback] * len(sizes)


def _fmt(value: float) -> str:
    """Short-form value for inside badges."""
    if value >= 1_000_000:
        return f"£{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"£{value / 1_000:.0f}k"
    if value > 0:
        return f"£{int(value)}"
    return "In kind"


def _badge_radius(value: float, max_value: float,
                  min_r: int = 16, max_r: int = 54) -> int:
    """Radius scaled so visual area is proportional to donation amount."""
    if max_value == 0 or value <= 0:
        return min_r
    return int(min_r + (max_r - min_r) * math.sqrt(value / max_value))


def _aggregate(interests: list[dict]) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for i in interests:
        if i["donor"] != "Unknown":
            totals[i["donor"]] = totals.get(i["donor"], 0.0) + i["value"]
    return sorted(totals.items(), key=lambda x: x[1], reverse=True)


def _pack(badges: list[tuple[str, float, int]],
          x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int, int, str, float]]:
    """
    Row-pack circular badges into the given rect.
    Returns list of (cx, cy, r, name, value).
    Largest badges first; each row's height = diameter of tallest badge in row.
    """
    PAD = 5
    placed: list[tuple[int, int, int, str, float]] = []
    row_x = x0
    row_y = y0
    row_h = 0   # tallest diameter in current row

    for name, value, r in badges:
        d = r * 2
        if row_x + d > x1:          # wrap to next row
            row_y += row_h + PAD
            row_x = x0
            row_h = 0
        if row_y + d > y1:           # no more vertical space
            break
        cx = row_x + r
        cy = row_y + r
        placed.append((cx, cy, r, name, value))
        row_x += d + PAD
        row_h = max(row_h, d)

    return placed


def _draw_circle_badge(draw: ImageDraw.ImageDraw,
                       cx: int, cy: int, r: int,
                       name: str, value: float,
                       font_name: ImageFont.FreeTypeFont,
                       font_val: ImageFont.FreeTypeFont) -> None:
    # Shadow
    draw.ellipse([cx - r + 2, cy - r + 2, cx + r + 2, cy + r + 2],
                 fill="#000000aa" if hasattr(draw, "_image") else "#111111")
    # Fill
    draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                 fill=RED, outline=RED_LIGHT, width=2)

    val_str = _fmt(value)

    if r >= 36:
        # Large: name on top, value below
        short = textwrap.shorten(name, width=max(6, r // 4), placeholder="…")
        draw.text((cx, cy - r // 4), short,
                  fill=TEXT_W, font=font_name, anchor="mm")
        draw.text((cx, cy + r // 4), val_str,
                  fill=GOLD, font=font_val, anchor="mm")
    elif r >= 22:
        # Medium: value only
        draw.text((cx, cy), val_str, fill=TEXT_W, font=font_val, anchor="mm")
    else:
        # Small: abbreviated value, tiny font
        draw.text((cx, cy), val_str, fill=TEXT_W, font=font_name, anchor="mm")


# ── main ─────────────────────────────────────────────────────────────────────

def generate_card(member_id: int, name: str, interests: list[dict]) -> Image.Image:
    card = Image.new("RGB", (CARD_W, CARD_H), BG)
    draw = ImageDraw.Draw(card)

    # ── fonts ──
    (font_name_lg, font_name_sm, font_sub,
     font_badge_lg, font_badge_sm, font_badge_xs) = _fonts([22, 14, 13, 11, 9, 9])

    # ── photo ──
    photo = _fetch_photo(member_id)
    photo_x = 0
    photo_y = (CARD_H - PHOTO_H) // 2      # vertically centred
    if photo:
        photo = photo.resize((PHOTO_W, PHOTO_H), Image.LANCZOS)
        # Paste with alpha if available
        if photo.mode == "RGBA":
            card.paste(photo, (photo_x, photo_y), photo)
        else:
            card.paste(photo.convert("RGB"), (photo_x, photo_y))

    # ── suit-area badge overlay ──
    donors = _aggregate(interests)
    if donors:
        max_val = max(v for _, v in donors if v > 0) or 1

        # Compute radii and sort largest first
        sized = [(n, v, _badge_radius(v, max_val)) for n, v in donors]
        sized.sort(key=lambda x: x[2], reverse=True)

        # Suit area: lower ~38% of the photo — Parliament headshots
        # are tight crops so the jacket starts around 62% down.
        suit_top    = photo_y + int(PHOTO_H * 0.62)
        suit_bottom = photo_y + PHOTO_H - 8
        suit_left   = photo_x + 8
        suit_right  = photo_x + PHOTO_W - 8

        placed = _pack(sized, suit_left, suit_top, suit_right, suit_bottom)

        for cx, cy, r, dname, dval in placed:
            _draw_circle_badge(
                draw, cx, cy, r, dname, dval,
                font_badge_xs if r < 22 else font_badge_sm,
                font_badge_lg,
            )

    # ── right panel: name, total, donor count ──
    rx = PHOTO_W + 24
    ry = 20

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
    draw.text((rx, ry), f"{donor_count} declared donor{'' if donor_count == 1 else 's'}", fill=TEXT_DIM, font=font_sub)
    ry += 20
    draw.text((rx, ry), "Badge size = total donated", fill="#555577", font=font_badge_sm)

    # PaidUp watermark bottom-right
    draw.text((CARD_W - 16, CARD_H - 14), "paidup.app", fill="#333355", font=font_badge_sm, anchor="ra")

    return card
