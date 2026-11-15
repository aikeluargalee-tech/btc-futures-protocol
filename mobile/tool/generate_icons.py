"""Generate a bold, minimalist IBM Retro emblem for BTC Desk v4 (Android & iOS stores)."""
from __future__ import annotations

import pathlib
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "store_icons"
FONT_BOLD = ROOT / "assets" / "fonts" / "IBMPlexMono-Bold.ttf"

ANDROID_SIZES = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}

IOS_SIZES = {
    "Icon-App-20x20@1x.png": 20,
    "Icon-App-20x20@2x.png": 40,
    "Icon-App-20x20@3x.png": 60,
    "Icon-App-29x29@1x.png": 29,
    "Icon-App-29x29@2x.png": 58,
    "Icon-App-29x29@3x.png": 87,
    "Icon-App-40x40@1x.png": 40,
    "Icon-App-40x40@2x.png": 80,
    "Icon-App-40x40@3x.png": 120,
    "Icon-App-60x60@2x.png": 120,
    "Icon-App-60x60@3x.png": 180,
    "Icon-App-76x76@1x.png": 76,
    "Icon-App-76x76@2x.png": 152,
    "Icon-App-83.5x83.5@2x.png": 167,
    "Icon-App-1024x1024@1x.png": 1024,
}


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_BOLD.exists():
        return ImageFont.truetype(str(FONT_BOLD), size=size)
    return ImageFont.load_default()


def render_master_1024() -> Image.Image:
    s = 1024
    # Opaque RGB required for iOS App Store icons
    img = Image.new("RGB", (s, s), "#E4E4DF")
    draw = ImageDraw.Draw(img)

    # Outer square hardware badge with hard retro shadow
    pad = 128
    draw.rectangle([pad + 34, pad + 34, s - pad + 34, s - pad + 34], fill="#B6B6AE")
    draw.rectangle([pad, pad, s - pad, s - pad], fill="#0043CE", outline="#1B2026", width=22)

    # Bold geometric 'B' + 4H bullish step motif in pure white / mint accent
    # Crisp 2-bar IBM scan-line accent at top inside cobalt square
    draw.line([pad + 34, pad + 42, s - pad - 34, pad + 42], fill="#6CA0FF", width=10)

    # Bold geometric 'B' monogram (drawn cleanly with overlapping crisp rectangles)
    bx = 276
    by = 236
    # Vertical spine & BTC prongs
    draw.rectangle([bx + 54, by - 46, bx + 98, by + 356], fill="#FFFFFF")
    draw.rectangle([bx + 146, by - 46, bx + 192, by + 356], fill="#FFFFFF")
    draw.rectangle([bx, by, bx + 54, by + 310], fill="#FFFFFF")
    # Upper loop
    draw.rectangle([bx, by, bx + 230, by + 54], fill="#FFFFFF")
    draw.rectangle([bx + 172, by + 44, bx + 230, by + 144], fill="#FFFFFF")
    # Mid crossbar
    draw.rectangle([bx, by + 132, bx + 252, by + 184], fill="#FFFFFF")
    # Lower loop (overlaps cleanly with right prong)
    draw.rectangle([bx + 184, by + 174, bx + 252, by + 276], fill="#FFFFFF")
    draw.rectangle([bx, by + 258, bx + 252, by + 310], fill="#FFFFFF")

    # Sharp emerald-mint + crimson 4H step bars on right side of emblem
    px = 602
    draw.rectangle([px, 415, px + 54, 546], fill="#FF8389", outline="#1B2026", width=8)
    draw.rectangle([px + 78, 300, px + 132, 546], fill="#42BE65", outline="#1B2026", width=8)

    # Crisp ivory footer bar inside icon with centered "DESK v4"
    foot_top = s - pad - 186
    draw.rectangle([pad, foot_top, s - pad, s - pad], fill="#F5F5F1", outline="#1B2026", width=22)
    f_lbl = load_font(104)
    lbl = "DESK v4"
    tb = draw.textbbox((0, 0), lbl, font=f_lbl)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    tx = (s - tw) // 2 - tb[0]
    ty = foot_top + ((s - pad - foot_top) - th) // 2 - tb[1] - 4
    draw.text((tx, ty), lbl, fill="#14181D", font=f_lbl)

    return img


def main() -> None:
    master = render_master_1024()
    OUT.mkdir(parents=True, exist_ok=True)
    master.save(OUT / "app_icon_1024.png", format="PNG")
    master.resize((512, 512), Image.Resampling.LANCZOS).save(OUT / "play_store_512.png", format="PNG")

    android_root = OUT / "android"
    for folder, px in ANDROID_SIZES.items():
        d = android_root / folder
        d.mkdir(parents=True, exist_ok=True)
        master.resize((px, px), Image.Resampling.LANCZOS).save(d / "ic_launcher.png", format="PNG")

    ios_root = OUT / "ios" / "AppIcon.appiconset"
    ios_root.mkdir(parents=True, exist_ok=True)
    for fname, px in IOS_SIZES.items():
        master.resize((px, px), Image.Resampling.LANCZOS).save(ios_root / fname, format="PNG")

    print(f"[OK] Generated {len(ANDROID_SIZES)} Android + {len(IOS_SIZES)} iOS BTC Desk v4 icons.")


if __name__ == "__main__":
    main()
