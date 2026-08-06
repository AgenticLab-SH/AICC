#!/usr/bin/env python3
"""Create a browser icon with a compact, high-contrast identity badge."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CANVAS = 1024
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--badge", required=True)
    parser.add_argument("--badge-color", required=True)
    parser.add_argument("--text-color", default="#FFFFFF")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_icon(base_path: Path, badge: str, badge_color: str, text_color: str) -> Image.Image:
    if not 1 <= len(badge) <= 2:
        raise ValueError("badge must contain one or two characters")

    base = Image.open(base_path).convert("RGBA")
    visible_bounds = base.getbbox()
    if visible_bounds:
        base = base.crop(visible_bounds)
    target = CANVAS - 96
    scale = min(target / base.width, target / base.height)
    base = base.resize(
        (max(1, round(base.width * scale)), max(1, round(base.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.alpha_composite(base, ((CANVAS - base.width) // 2, (CANVAS - base.height) // 2))

    draw = ImageDraw.Draw(canvas)
    diameter = 390
    margin = 36
    left = CANVAS - diameter - margin
    top = CANVAS - diameter - margin
    outline = max(18, diameter // 14)
    draw.ellipse(
        (left, top, left + diameter, top + diameter),
        fill=badge_color,
        outline="#FFFFFF",
        width=outline,
    )

    font = load_font(235 if len(badge) == 1 else 190)
    box = draw.textbbox((0, 0), badge, font=font, stroke_width=2)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = left + (diameter - width) / 2 - box[0]
    y = top + (diameter - height) / 2 - box[1] - 8
    draw.text((x, y), badge, font=font, fill=text_color, stroke_width=2, stroke_fill=text_color)
    return canvas


def save_icon(image: Image.Image, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    if suffix == ".png":
        image.save(output, format="PNG")
    elif suffix == ".ico":
        image.save(output, format="ICO", sizes=ICO_SIZES)
    else:
        raise ValueError("output must end in .png or .ico")


def main() -> None:
    args = parse_args()
    if not args.base.is_file():
        raise FileNotFoundError(args.base)
    icon = build_icon(args.base, args.badge, args.badge_color, args.text_color)
    save_icon(icon, args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
