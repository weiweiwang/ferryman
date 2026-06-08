#!/usr/bin/env python3
"""Create a labeled contact sheet from slide PNG previews."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def natural_key(path: Path) -> list[object]:
    parts = re.split(r"(\d+)", path.name)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def make_contact_sheet(images: list[Path], output: Path, thumb_width: int = 320, columns: int | None = None) -> Path:
    if not images:
        raise ValueError("No input images provided.")
    images = sorted(images, key=natural_key)
    opened = [Image.open(path).convert("RGB") for path in images]
    ratios = [image.height / image.width for image in opened if image.width]
    thumb_height = int(thumb_width * (sum(ratios) / len(ratios))) if ratios else 180
    columns = columns or min(4, max(1, math.ceil(math.sqrt(len(opened)))))
    rows = math.ceil(len(opened) / columns)
    label_h = 26
    pad = 14
    width = columns * thumb_width + (columns + 1) * pad
    height = rows * (thumb_height + label_h) + (rows + 1) * pad
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for index, (source, image) in enumerate(zip(images, opened, strict=True)):
        row, col = divmod(index, columns)
        x = pad + col * (thumb_width + pad)
        y = pad + row * (thumb_height + label_h + pad)
        image.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (thumb_width, thumb_height), "white")
        frame.paste(image, ((thumb_width - image.width) // 2, (thumb_height - image.height) // 2))
        sheet.paste(frame, (x, y))
        draw.rectangle((x, y, x + thumb_width, y + thumb_height), outline=(210, 210, 210), width=1)
        draw.text((x, y + thumb_height + 7), source.name, fill=(40, 40, 40), font=font)

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a contact sheet from slide PNGs.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--thumb-width", type=int, default=320)
    parser.add_argument("--columns", type=int, default=None)
    parser.add_argument("images", nargs="+")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    images = [Path(value).resolve() for value in args.images]
    output = make_contact_sheet(images, Path(args.output).resolve(), args.thumb_width, args.columns)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
