#!/usr/bin/env python3
"""Structural inspection for PPTX files.

This script intentionally uses only Python's standard library so it can run in
Ferryman workspaces without Office, LibreOffice, or Codex internal runtimes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree


SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
REQUIRED_PARTS = ("[Content_Types].xml", "ppt/presentation.xml")
EMU_PER_INCH = 914400
DEFAULT_SLIDE_CX = int(13.333 * EMU_PER_INCH)
DEFAULT_SLIDE_CY = int(7.5 * EMU_PER_INCH)
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
}
URL_IN_TEXT_RE = re.compile(r"(?:https?://|www\.)[^\s\u4e00-\u9fff]+", re.IGNORECASE)


def _slide_number(name: str) -> int:
    match = SLIDE_RE.match(name)
    return int(match.group(1)) if match else 0


def _parse_xml_entry(package: zipfile.ZipFile, name: str) -> str | None:
    try:
        ElementTree.fromstring(package.read(name))
    except Exception as exc:  # noqa: BLE001 - report any XML parse failure.
        return f"{name}: {exc}"
    return None


def _presentation_size(package: zipfile.ZipFile) -> tuple[int, int]:
    try:
        root = ElementTree.fromstring(package.read("ppt/presentation.xml"))
        slide_size = root.find(".//p:sldSz", NS)
        if slide_size is not None:
            cx = int(slide_size.get("cx") or DEFAULT_SLIDE_CX)
            cy = int(slide_size.get("cy") or DEFAULT_SLIDE_CY)
            if cx > 0 and cy > 0:
                return cx, cy
    except Exception:
        pass
    return DEFAULT_SLIDE_CX, DEFAULT_SLIDE_CY


def _emu_to_inches(value: int) -> float:
    return round(value / EMU_PER_INCH, 3)


def _picture_boxes(root: ElementTree.Element, slide_cx: int, slide_cy: int) -> list[dict[str, object]]:
    slide_area = max(1, slide_cx * slide_cy)
    boxes: list[dict[str, object]] = []
    for picture_index, picture in enumerate(root.findall(".//p:pic", NS), start=1):
        off = picture.find(".//a:xfrm/a:off", NS)
        ext = picture.find(".//a:xfrm/a:ext", NS)
        if off is None or ext is None:
            boxes.append({"index": picture_index})
            continue
        try:
            x = int(off.get("x") or 0)
            y = int(off.get("y") or 0)
            w = int(ext.get("cx") or 0)
            h = int(ext.get("cy") or 0)
        except ValueError:
            boxes.append({"index": picture_index})
            continue
        area_ratio = round((w * h) / slide_area, 4) if w > 0 and h > 0 else 0
        boxes.append(
            {
                "index": picture_index,
                "x": _emu_to_inches(x),
                "y": _emu_to_inches(y),
                "w": _emu_to_inches(w),
                "h": _emu_to_inches(h),
                "area_ratio": area_ratio,
            }
        )
    return boxes


def _slide_metrics(root: ElementTree.Element, slide_number: int, slide_cx: int, slide_cy: int) -> dict[str, object]:
    text = "".join(node.text or "" for node in root.findall(".//a:t", NS))
    urls = URL_IN_TEXT_RE.findall(text)
    picture_boxes = _picture_boxes(root, slide_cx, slide_cy)
    picture_area_ratios = [
        float(box.get("area_ratio") or 0)
        for box in picture_boxes
        if isinstance(box, dict)
    ]
    return {
        "slide": slide_number,
        "text_chars": len(text),
        "pictures": len(picture_boxes),
        "picture_boxes": picture_boxes,
        "picture_area_ratio": round(sum(picture_area_ratios), 4),
        "max_picture_area_ratio": round(max(picture_area_ratios), 4) if picture_area_ratios else 0,
        "shapes": len(root.findall(".//p:sp", NS)),
        "graphic_frames": len(root.findall(".//p:graphicFrame", NS)),
        "naked_urls": urls[:5],
        "naked_url_count": len(urls),
        "text_preview": " ".join(text.split())[:220],
    }


def inspect_pptx(pptx_path: str | Path, expected_slides: int | None = None) -> dict[str, object]:
    path = Path(pptx_path).expanduser()
    result: dict[str, object] = {
        "ok": False,
        "pptx": str(path),
        "errors": [],
        "warnings": [],
        "metrics": {},
    }
    errors: list[str] = result["errors"]  # type: ignore[assignment]
    warnings: list[str] = result["warnings"]  # type: ignore[assignment]
    metrics: dict[str, object] = result["metrics"]  # type: ignore[assignment]

    if not path.exists():
        errors.append(f"PPTX not found: {path}")
        return result
    if not path.is_file():
        errors.append(f"PPTX path is not a file: {path}")
        return result

    size = path.stat().st_size
    metrics["package_bytes"] = size
    if size <= 0:
        errors.append(f"PPTX is empty: {path}")
        return result
    if size < 4096:
        warnings.append("PPTX package is very small; verify it is not a placeholder.")

    try:
        with zipfile.ZipFile(path) as package:
            names = package.namelist()
            name_set = set(names)

            for required in REQUIRED_PARTS:
                if required not in name_set:
                    errors.append(f"Missing required package part: {required}")

            slide_names = sorted(
                (name for name in names if SLIDE_RE.match(name)),
                key=_slide_number,
            )
            media_names = [
                name for name in names if name.startswith("ppt/media/") and not name.endswith("/")
            ]
            chart_names = [
                name for name in names if name.startswith("ppt/charts/") and name.endswith(".xml")
            ]

            metrics["slide_count"] = len(slide_names)
            slide_cx, slide_cy = _presentation_size(package)
            metrics["slide_width_inches"] = _emu_to_inches(slide_cx)
            metrics["slide_height_inches"] = _emu_to_inches(slide_cy)
            metrics["media_count"] = len(media_names)
            metrics["chart_count"] = len(chart_names)

            if not slide_names:
                errors.append("No slide XML files found under ppt/slides/.")
            if expected_slides is not None and len(slide_names) != expected_slides:
                errors.append(
                    f"Expected {expected_slides} slides, found {len(slide_names)}."
                )

            empty_media = [
                name for name in media_names if package.getinfo(name).file_size == 0
            ]
            if empty_media:
                errors.append(f"Empty media files: {', '.join(empty_media[:8])}")

            xml_names = [
                name
                for name in names
                if name.endswith(".xml") and not name.startswith("docProps/thumbnail")
            ]
            xml_errors = [
                error
                for name in xml_names
                if (error := _parse_xml_entry(package, name)) is not None
            ]
            if xml_errors:
                errors.extend(xml_errors[:20])
                if len(xml_errors) > 20:
                    warnings.append(f"Suppressed {len(xml_errors) - 20} additional XML parse errors.")

            slide_text_chars = 0
            slide_metrics: list[dict[str, object]] = []
            for slide_name in slide_names:
                try:
                    root = ElementTree.fromstring(package.read(slide_name))
                except Exception:
                    continue
                metrics_for_slide = _slide_metrics(root, _slide_number(slide_name), slide_cx, slide_cy)
                slide_text_chars += int(metrics_for_slide["text_chars"])
                slide_metrics.append(metrics_for_slide)
            metrics["slide_text_chars"] = slide_text_chars
            metrics["slides"] = slide_metrics
            metrics["naked_url_count"] = sum(int(slide.get("naked_url_count") or 0) for slide in slide_metrics)
            metrics["naked_url_slides"] = [
                int(slide["slide"])
                for slide in slide_metrics
                if int(slide.get("naked_url_count") or 0) > 0
            ]
            if slide_names and slide_text_chars == 0:
                warnings.append("Slides contain no extractable text; verify this is intentional.")

    except zipfile.BadZipFile:
        errors.append("PPTX is not a valid zip package.")
    except Exception as exc:  # noqa: BLE001 - top-level inspection should report.
        errors.append(f"Failed to inspect PPTX: {exc}")

    result["ok"] = not errors
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect PPTX package structure.")
    parser.add_argument("--pptx", required=True, help="Path to PPTX file.")
    parser.add_argument("--expected-slides", type=int, default=None)
    parser.add_argument("--json-out", default=None, help="Optional JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = inspect_pptx(args.pptx, args.expected_slides)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(f"{output}\n", encoding="utf-8")
    print(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
