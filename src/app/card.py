"""
Generates a donor card image — MP photo with sponsor badges overlaid.
"""

import requests
import textwrap
from PIL import Image, ImageDraw, ImageFont
from app.parliament import get_thumbnail_url

CARD_W, CARD_H = 800, 500
PHOTO_W, PHOTO_H = 300, 400
BADGE_COLS = 2
BADGE_W, BADGE_H = 220, 60
BADGE_GAP = 12
BG_COLOUR = "#1a1a2e"
BADGE_COLOUR = "#e63946"
BADGE_TEXT_COLOUR = "#ffffff"
NAME_COLOUR = "#ffffff"
TOTAL_COLOUR = "#f4d03f"


def _fetch_photo(member_id: int) -> Image.Image | None:
    try:
        r = requests.get(get_thumbnail_url(member_id), timeout=5)
        r.raise_for_status()
        from io import BytesIO
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def _draw_badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, value: float):
    draw.rounded_rectangle([x, y, x + BADGE_W, y + BADGE_H], radius=8, fill=BADGE_COLOUR)
    try:
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 11)
        font_val = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except Exception:
        font_sm = ImageFont.load_default()
        font_val = font_sm

    label = textwrap.shorten(text, width=28, placeholder="…")
    draw.text((x + 10, y + 8), label, fill=BADGE_TEXT_COLOUR, font=font_sm)
    val_str = f"£{value:,.0f}" if value else "In kind"
    draw.text((x + 10, y + 36), val_str, fill=TOTAL_COLOUR, font=font_val)


def generate_card(member_id: int, name: str, interests: list[dict]) -> Image.Image:
    card = Image.new("RGB", (CARD_W, CARD_H), BG_COLOUR)
    draw = ImageDraw.Draw(card)

    # MP photo
    photo = _fetch_photo(member_id)
    if photo:
        photo = photo.resize((PHOTO_W, PHOTO_H))
        card.paste(photo, (0, (CARD_H - PHOTO_H) // 2))

    # Name + party
    try:
        font_name = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
        font_sub = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
    except Exception:
        font_name = ImageFont.load_default()
        font_sub = font_name

    draw.text((PHOTO_W + 20, 20), name, fill=NAME_COLOUR, font=font_name)

    total = sum(i["value"] for i in interests)
    draw.text((PHOTO_W + 20, 52), f"Total declared: £{total:,.0f}", fill=TOTAL_COLOUR, font=font_sub)
    draw.text((PHOTO_W + 20, 72), "Paid up by:", fill="#aaaaaa", font=font_sub)

    # Sponsor badges
    donors = [i for i in interests if i["donor"] != "Unknown"][:10]
    start_x = PHOTO_W + 20
    start_y = 100

    for idx, donor in enumerate(donors):
        col = idx % BADGE_COLS
        row = idx // BADGE_COLS
        x = start_x + col * (BADGE_W + BADGE_GAP)
        y = start_y + row * (BADGE_H + BADGE_GAP)
        if y + BADGE_H > CARD_H - 20:
            break
        _draw_badge(draw, x, y, donor["donor"], donor["value"])

    return card
