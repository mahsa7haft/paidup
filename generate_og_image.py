"""Generate src/app/static/og-image.png — run once with: uv run python generate_og_image.py"""
from PIL import Image, ImageDraw, ImageFont
import math, os

W, H = 1200, 630
BG     = "#f0ebe0"
GREEN  = "#1D9E75"
DARK   = "#141413"
GRAY   = "#888888"

def load_font(size):
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

img  = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(img)

# ── Logo mark ────────────────────────────────────────────────────────────────
cx, cy = 370, 270
r      = 90
stroke = 11

# Circle: draw green disc then white inner disc for stroke effect
draw.ellipse([cx-r-stroke, cy-r-stroke, cx+r+stroke, cy+r+stroke], fill=GREEN)
draw.ellipse([cx-r,        cy-r,        cx+r,        cy+r       ], fill="white")

# £ symbol centred inside circle
font_pound = load_font(86)
bbox = draw.textbbox((0, 0), "£", font=font_pound)
tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
draw.text((cx - tw//2 - bbox[0], cy - th//2 - bbox[1] - 4), "£", fill=DARK, font=font_pound)

# Magnifying-glass handle: diagonal line from circle edge at 45°
angle = math.radians(45)
x1 = int(cx + r * math.cos(angle))
y1 = int(cy + r * math.sin(angle))
x2 = int(x1 + 70 * math.cos(angle))
y2 = int(y1 + 70 * math.sin(angle))
draw.line([x1, y1, x2, y2], fill=GREEN, width=18)

# ── Wordmark ─────────────────────────────────────────────────────────────────
font_wm  = load_font(96)
wm_x     = x2 + 52
wm_y     = cy - 52

draw.text((wm_x, wm_y), "Paid", fill=DARK, font=font_wm)
paid_w = draw.textbbox((wm_x, wm_y), "Paid", font=font_wm)[2] - wm_x
draw.text((wm_x + paid_w + 14, wm_y), "Up", fill=GREEN, font=font_wm)

# ── Tagline ───────────────────────────────────────────────────────────────────
font_tag = load_font(44)
draw.text((wm_x, wm_y + 118), "See who funds your MP.", fill=GRAY, font=font_tag)

# ── Attribution ───────────────────────────────────────────────────────────────
font_attr = load_font(26)
attr_text = "paidup.app"
attr_bbox = draw.textbbox((0, 0), attr_text, font=font_attr)
attr_w = attr_bbox[2] - attr_bbox[0]
draw.text((W - attr_w - 48, H - 52), attr_text, fill=GRAY, font=font_attr)

# ── Save ──────────────────────────────────────────────────────────────────────
out = "src/app/static/og-image.png"
os.makedirs(os.path.dirname(out), exist_ok=True)
img.save(out, optimize=True)
print(f"Saved {out}  ({W}×{H})")
