"""Genereert de app-iconen (φ op indigo). Eenmalig draaien: python scripts/make_icons.py"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"
BG = (47, 40, 80)
FG = (245, 239, 227)
ACCENT = (224, 118, 91)
FONTS = ["C:/Windows/Fonts/georgia.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]


def font(size: int):
    for f in FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def icon(size: int, padding: float, rounded: bool) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if rounded:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=BG)
    else:
        d.rectangle([0, 0, size, size], fill=BG)
    inner = size * (1 - 2 * padding)
    f = font(int(inner * 0.78))
    d.text((size / 2, size / 2 + inner * 0.02), "φ", font=f, fill=FG, anchor="mm")
    r = inner * 0.06
    cx, cy = size / 2 + inner * 0.3, size / 2 - inner * 0.3
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT)
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192, 0.08, False).save(OUT / "icon-192.png")
    icon(512, 0.08, False).save(OUT / "icon-512.png")
    icon(512, 0.2, False).save(OUT / "icon-maskable-512.png")
    icon(180, 0.08, False).convert("RGB").save(OUT / "apple-touch-icon.png")
    icon(64, 0.04, True).save(OUT / "favicon.png")
    badge = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
    ImageDraw.Draw(badge).text((36, 38), "φ", font=font(60), fill=(255, 255, 255, 255), anchor="mm")
    badge.save(OUT / "badge-72.png")


if __name__ == "__main__":
    main()
