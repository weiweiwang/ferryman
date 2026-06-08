#!/usr/bin/env python3
"""Create a reference-audit report from a PPTX sample deck."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from inspect_pptx import inspect_pptx  # noqa: E402


SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
EMU_PER_INCH = 914400
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}


def _slide_number(name: str) -> int:
    match = SLIDE_RE.match(name)
    return int(match.group(1)) if match else 0


def _emu_to_in(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return round(int(value) / EMU_PER_INCH, 3)
    except ValueError:
        return None


def _bbox(element: ElementTree.Element) -> dict[str, float] | None:
    xfrm = element.find(".//a:xfrm", NS)
    if xfrm is None:
        return None
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    if off is None or ext is None:
        return None
    x = _emu_to_in(off.get("x"))
    y = _emu_to_in(off.get("y"))
    w = _emu_to_in(ext.get("cx"))
    h = _emu_to_in(ext.get("cy"))
    if None in (x, y, w, h):
        return None
    return {"x": x, "y": y, "w": w, "h": h}  # type: ignore[dict-item]


def _font_points(shape: ElementTree.Element) -> list[float]:
    sizes: list[float] = []
    for node in shape.findall(".//a:rPr", NS) + shape.findall(".//a:endParaRPr", NS):
        raw = node.get("sz")
        if raw and raw.isdigit():
            sizes.append(round(int(raw) / 100, 1))
    return sizes


def _text_blocks(root: ElementTree.Element) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    for shape in root.findall(".//p:sp", NS):
        text = "".join(node.text or "" for node in shape.findall(".//a:t", NS)).strip()
        if not text:
            continue
        sizes = _font_points(shape)
        blocks.append(
            {
                "text": " ".join(text.split()),
                "chars": len(text),
                "bbox": _bbox(shape),
                "max_font_pt": max(sizes) if sizes else None,
            }
        )
    return blocks


def _dominant_text_block(blocks: list[dict[str, object]]) -> dict[str, object] | None:
    if not blocks:
        return None
    return max(
        blocks,
        key=lambda block: (
            float(block.get("max_font_pt") or 0),
            int(block.get("chars") or 0),
        ),
    )


def _colors(root: ElementTree.Element) -> Counter[str]:
    colors: Counter[str] = Counter()
    for node in root.findall(".//a:srgbClr", NS):
        value = (node.get("val") or "").upper()
        if re.fullmatch(r"[0-9A-F]{6}", value):
            colors[value] += 1
    for node in root.findall(".//a:schemeClr", NS):
        value = (node.get("val") or "").strip()
        if value:
            colors[f"scheme:{value}"] += 1
    return colors


def _layout_label(chars: int, pictures: int, shapes: int) -> str:
    if pictures >= 1 and chars <= 80:
        return "image-led"
    if pictures >= 2:
        return "multi-image"
    if chars >= 180:
        return "text-heavy"
    if shapes >= 18:
        return "shape-system"
    return "balanced"


def audit_reference(pptx_path: str | Path) -> dict[str, object]:
    path = Path(pptx_path).expanduser()
    package_report = inspect_pptx(path)
    slides: list[dict[str, object]] = []
    color_counter: Counter[str] = Counter()

    with zipfile.ZipFile(path) as package:
        slide_names = sorted(
            (name for name in package.namelist() if SLIDE_RE.match(name)),
            key=_slide_number,
        )
        for slide_name in slide_names:
            root = ElementTree.fromstring(package.read(slide_name))
            text = "".join(node.text or "" for node in root.findall(".//a:t", NS))
            blocks = _text_blocks(root)
            dominant = _dominant_text_block(blocks)
            pictures = len(root.findall(".//p:pic", NS))
            shapes = len(root.findall(".//p:sp", NS))
            slide_colors = _colors(root)
            color_counter.update(slide_colors)
            slides.append(
                {
                    "slide": _slide_number(slide_name),
                    "text_chars": len(text),
                    "pictures": pictures,
                    "shapes": shapes,
                    "layout_label": _layout_label(len(text), pictures, shapes),
                    "dominant_text": {
                        "text": (dominant or {}).get("text", "")[:100] if dominant else "",
                        "max_font_pt": (dominant or {}).get("max_font_pt") if dominant else None,
                        "bbox": (dominant or {}).get("bbox") if dominant else None,
                    },
                    "top_colors": slide_colors.most_common(5),
                    "text_preview": " ".join(text.split())[:180],
                }
            )

    slide_count = len(slides)
    text_chars = [int(slide["text_chars"]) for slide in slides]
    picture_counts = [int(slide["pictures"]) for slide in slides]
    image_slide_count = sum(1 for count in picture_counts if count > 0)
    total_pictures = sum(picture_counts)
    summary = {
        "pptx": str(path),
        "package_bytes": package_report.get("metrics", {}).get("package_bytes", 0),
        "slide_count": slide_count,
        "media_count": package_report.get("metrics", {}).get("media_count", 0),
        "total_pictures_on_slides": total_pictures,
        "image_slide_count": image_slide_count,
        "image_slide_ratio": round(image_slide_count / slide_count, 3) if slide_count else 0,
        "pictures_per_slide": round(total_pictures / slide_count, 3) if slide_count else 0,
        "media_per_slide": round(
            int(package_report.get("metrics", {}).get("media_count", 0)) / slide_count,
            3,
        )
        if slide_count
        else 0,
        "avg_text_chars_per_slide": round(sum(text_chars) / slide_count, 1) if slide_count else 0,
        "max_text_chars_per_slide": max(text_chars) if text_chars else 0,
        "layout_labels": dict(Counter(str(slide["layout_label"]) for slide in slides)),
        "top_colors": color_counter.most_common(10),
    }
    return {
        "ok": bool(package_report.get("ok")),
        "summary": summary,
        "slides": slides,
        "package_report": package_report,
        "recommended_constraints": _recommended_constraints(summary),
    }


def _recommended_constraints(summary: dict[str, object]) -> dict[str, object]:
    avg_chars = float(summary.get("avg_text_chars_per_slide") or 0)
    max_chars = int(summary.get("max_text_chars_per_slide") or 0)
    image_ratio = float(summary.get("image_slide_ratio") or 0)
    media_per_slide = float(summary.get("media_per_slide") or 0)
    return {
        "target_slide_count": summary.get("slide_count", 0),
        "max_avg_text_chars_per_slide": max(40, int(avg_chars * 1.25)),
        "max_text_chars_per_slide": max(70, int(max_chars * 1.2)),
        "min_image_slide_ratio": max(0.6, round(image_ratio * 0.9, 2)),
        "min_media_per_slide": round(max(0.5, media_per_slide * 0.75), 2),
    }


def markdown_report(report: dict[str, object]) -> str:
    summary = report["summary"]  # type: ignore[index]
    constraints = report["recommended_constraints"]  # type: ignore[index]
    slides = report["slides"]  # type: ignore[index]
    lines = [
        "# Reference Audit",
        "",
        "## Summary",
        "",
        f"- PPTX: `{summary['pptx']}`",
        f"- Slides: {summary['slide_count']}",
        f"- Package bytes: {summary['package_bytes']}",
        f"- Media files: {summary['media_count']}",
        f"- Pictures on slides: {summary['total_pictures_on_slides']}",
        f"- Image slide ratio: {summary['image_slide_ratio']}",
        f"- Pictures per slide: {summary['pictures_per_slide']}",
        f"- Media per slide: {summary['media_per_slide']}",
        f"- Avg text chars / slide: {summary['avg_text_chars_per_slide']}",
        f"- Max text chars / slide: {summary['max_text_chars_per_slide']}",
        f"- Layout labels: {json.dumps(summary['layout_labels'], ensure_ascii=False)}",
        "",
        "## Recommended Constraints",
        "",
    ]
    lines.extend(f"- `{key}`: {value}" for key, value in constraints.items())
    lines.extend(
        [
            "",
            "## Slide Inventory",
            "",
            "| Slide | Text chars | Pictures | Shapes | Rhythm | Dominant text | Title box |",
            "|---:|---:|---:|---:|---|---|---|",
        ]
    )
    for slide in slides:  # type: ignore[assignment]
        dominant = slide.get("dominant_text", {}) if isinstance(slide, dict) else {}
        bbox = dominant.get("bbox") if isinstance(dominant, dict) else None
        bbox_text = ""
        if isinstance(bbox, dict):
            bbox_text = f"x={bbox.get('x')}, y={bbox.get('y')}, w={bbox.get('w')}, h={bbox.get('h')}"
        font = dominant.get("max_font_pt") if isinstance(dominant, dict) else None
        dominant_text = dominant.get("text", "") if isinstance(dominant, dict) else ""
        if font:
            dominant_text = f"{dominant_text} ({font}pt)"
        lines.append(
            f"| {slide['slide']} | {slide['text_chars']} | {slide['pictures']} | {slide['shapes']} | {slide['layout_label']} | {dominant_text} | {bbox_text} |"
        )
    lines.extend(
        [
            "",
            "## How To Use",
            "",
            "- Treat this as a quality reference, not an exact clone contract.",
            "- Match the slide rhythm, image density, text density, and hierarchy unless the user asks for a different direction.",
            "- Convert recommended constraints into `deck-spec.json.reference_constraints` before building.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit a reference PPTX deck.")
    parser.add_argument("--pptx", required=True, help="Reference PPTX path.")
    parser.add_argument("--out", required=True, help="Markdown audit report path.")
    parser.add_argument("--json-out", default=None, help="Optional JSON audit path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit_reference(args.pptx)
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown_report(report), encoding="utf-8")
    if args.json_out:
        json_path = Path(args.json_out).resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
