"""Generate crisp whitish-grey IBM Retro app launcher icons for Android & iOS stores."""
from __future__ import annotations

import pathlib
from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "store_icons"

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


def load_mono_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/consolab.ttf",
        "C:/Windows/Fonts/courbd.ttf",
        "C:/Windows/Fonts/lucon.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ]
    for path in candidates:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def render_master_1024() -> Image.Image:
    s = 1024
    # Opaque RGB (required by Apple App Store for AppIcon)
    img = Image.new("RGB", (s, s), "#E4E4DF")
    draw = ImageDraw.Draw(img)

    # Subtle workstation dot grid
    for y in range(64, s, 64):
        for x in range(64, s, 64):
            draw.rectangle([x - 3, y - 3, x + 3, y + 3], fill="#C7C7BE")

    # Outer retro window drop shadow & panel frame
    pad = 112
    draw.rectangle([pad + 26, pad + 26, s - pad + 26, s - pad + 26], fill="#B6B6AE")
    draw.rectangle([pad, pad, s - pad, s - pad], fill="#F5F5F1", outline="#1B2026", width=18)

    # IBM Cobalt titlebar inside the window
    bar_h = 152
    draw.rectangle([pad, pad, s - pad, pad + bar_h], fill="#0043CE", outline="#1B2026", width=18)

    # Inner bevel accent in titlebar
    draw.line([pad + 20, pad + 20, s - pad - 20, pad + 20], fill="#6CA0FF", width=8)

    # Titlebar label "BTC // v4.0"
    f_bar = load_mono_font(72)
    draw.text((pad + 44, pad + 38), "BTC // v4", fill="#FFFFFF", font=f_bar)

    # Subtle horizontal grid inside chart pane
    pane_top = pad + bar_h + 44
    pane_bot = s - pad - 150
    for gy in range(pane_top + 40, pane_bot, 90):
        draw.line([pad + 44, gy, s - pad - 44, gy], fill="#E0E0D8", width=4)

    # Crisp 4H Candlesticks (Long/Short protocol motif)
    candles = [
        # (cx, wick_top, wick_bot, body_top, body_bot, color)
        (284, 340, 560, 410, 515, "#A2191F"),
        (414, 415, 655, 480, 595, "#A2191F"),
        (544, 430, 675, 470, 560, "#0E6027"),
        (674, 325, 535, 365, 495, "#0E6027"),
        (784, 295, 465, 320, 405, "#0043CE"),
    ]
    for cx, wt, wb, bt, bb, col in candles:
        draw.line([cx, wt, cx, wb], fill="#1B2026", width=12)
        draw.rectangle([cx - 34, bt, cx + 34, bb], fill=col, outline="#1B2026", width=10)

    # Footer badge "4H · 1:2" centered cleanly
    f_sub = load_mono_font(62)
    badge_text = "4H · 1:2"
    badge_y0 = s - pad - 122
    draw.rectangle([pad + 44, badge_y0, s - pad - 44, s - pad - 36], fill="#DCDCD5", outline="#1B2026", width=10)
    tb = draw.textbbox((0, 0), badge_text, font=f_sub)
    tw = tb[2] - tb[0]
    draw.text(((s - tw) // 2 - tb[0], badge_y0 + 12), badge_text, fill="#14181D", font=f_sub)

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

    print(f"[OK] Generated {len(ANDROID_SIZES)} Android + {len(IOS_SIZES)} iOS icons + store masters.")


if __name__ == "__main__":
    main()
