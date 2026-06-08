#!/usr/bin/env python3
"""Register an existing workspace image as a PPT asset.

This script does not download network resources. It copies an existing local
workspace file, such as a browser screenshot, into the task asset directory and
updates asset-manifest.json.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from statistics import median
from pathlib import Path
from xml.etree import ElementTree


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}
CONTENT_DIFF_THRESHOLD = 54
AUTO_CROP_MAX_AREA_RATIO = 0.92


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip()).strip("-").lower()
    return slug[:80] or "asset"


def resolve_workspace_path(raw_path: str | Path, workspace: str | Path | None = None) -> Path:
    workspace_dir = Path(workspace or Path.cwd()).resolve()
    path = Path(raw_path)
    candidate = path.resolve() if path.is_absolute() else (workspace_dir / path).resolve()
    try:
        candidate.relative_to(workspace_dir)
    except ValueError as exc:
        raise ValueError(f"Path escapes workspace: {raw_path}") from exc
    return candidate


def load_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"assets": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("asset manifest must be a JSON object.")
    assets = data.get("assets")
    if not isinstance(assets, list):
        data["assets"] = []
    return data


def workspace_relative(path: Path, workspace: Path) -> str:
    return str(path.resolve().relative_to(workspace.resolve()))


def _aspect_ratio(width: int | None, height: int | None) -> float | None:
    if not width or not height:
        return None
    return round(width / height, 4)


def _svg_number(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
    return int(float(match.group(1))) if match else None


def _svg_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        root = ElementTree.fromstring(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None, None
    width = _svg_number(root.get("width"))
    height = _svg_number(root.get("height"))
    if width and height:
        return width, height
    view_box = root.get("viewBox")
    if not view_box:
        return width, height
    parts = re.split(r"[\s,]+", view_box.strip())
    if len(parts) != 4:
        return width, height
    try:
        return width or int(float(parts[2])), height or int(float(parts[3]))
    except ValueError:
        return width, height


def _detect_content_bbox(path: Path) -> dict[str, object]:
    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as raw_image:
            image = raw_image.convert("RGB")
            width, height = image.size
            if width <= 0 or height <= 0:
                return {}
            max_side = 420
            scale = min(1.0, max_side / max(width, height))
            if scale < 1.0:
                sample = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
            else:
                sample = image.copy()
            sample_width, sample_height = sample.size
            pixels = sample.load()
            border_pixels: list[tuple[int, int, int]] = []
            step_x = max(1, sample_width // 120)
            step_y = max(1, sample_height // 120)
            for x in range(0, sample_width, step_x):
                border_pixels.append(pixels[x, 0])
                border_pixels.append(pixels[x, sample_height - 1])
            for y in range(0, sample_height, step_y):
                border_pixels.append(pixels[0, y])
                border_pixels.append(pixels[sample_width - 1, y])
            if not border_pixels:
                return {}
            bg = tuple(int(median(channel)) for channel in zip(*border_pixels))

            min_x = sample_width
            min_y = sample_height
            max_x = -1
            max_y = -1
            for y in range(sample_height):
                for x in range(sample_width):
                    pixel = pixels[x, y]
                    diff = sum(abs(pixel[index] - bg[index]) for index in range(3))
                    if diff >= CONTENT_DIFF_THRESHOLD:
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        max_x = max(max_x, x)
                        max_y = max(max_y, y)
            if max_x < min_x or max_y < min_y:
                return {
                    "content_bbox": None,
                    "content_area_ratio": 0,
                    "content_background_rgb": list(bg),
                }

            # Expand slightly so cropped photos keep a little breathing room.
            pad = max(2, int(0.012 * max(sample_width, sample_height)))
            min_x = max(0, min_x - pad)
            min_y = max(0, min_y - pad)
            max_x = min(sample_width - 1, max_x + pad)
            max_y = min(sample_height - 1, max_y + pad)
            inv_scale = 1.0 / scale
            x0 = int(min_x * inv_scale)
            y0 = int(min_y * inv_scale)
            x1 = min(width, int((max_x + 1) * inv_scale))
            y1 = min(height, int((max_y + 1) * inv_scale))
            bbox_width = max(0, x1 - x0)
            bbox_height = max(0, y1 - y0)
            area_ratio = round((bbox_width * bbox_height) / (width * height), 4)
            return {
                "content_bbox": {
                    "x": x0,
                    "y": y0,
                    "width": bbox_width,
                    "height": bbox_height,
                },
                "content_area_ratio": area_ratio,
                "content_background_rgb": list(bg),
            }
    except Exception as exc:  # noqa: BLE001 - detection should not block registration.
        return {"content_detection_error": str(exc)}


def image_metadata(path: Path) -> dict[str, object]:
    metadata: dict[str, object] = {
        "bytes": path.stat().st_size,
        "width": None,
        "height": None,
        "format": path.suffix.lower().lstrip(".").upper() or None,
        "aspect_ratio": None,
    }
    if path.suffix.lower() == ".svg":
        width, height = _svg_dimensions(path)
        metadata.update(
            {
                "width": width,
                "height": height,
                "format": "SVG",
                "aspect_ratio": _aspect_ratio(width, height),
            }
        )
        return metadata

    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as image:
            width, height = image.size
            metadata.update(
                {
                    "width": width,
                    "height": height,
                    "format": image.format or metadata["format"],
                    "aspect_ratio": _aspect_ratio(width, height),
                }
            )
            metadata.update(_detect_content_bbox(path))
    except Exception as exc:  # noqa: BLE001 - metadata should not block registration.
        metadata["metadata_error"] = str(exc)
    return metadata


def _should_crop_padding(metadata: dict[str, object]) -> bool:
    bbox = metadata.get("content_bbox")
    ratio = metadata.get("content_area_ratio")
    width = metadata.get("width")
    height = metadata.get("height")
    if not isinstance(bbox, dict) or not isinstance(ratio, (int, float)):
        return False
    if not isinstance(width, int) or not isinstance(height, int):
        return False
    if ratio <= 0 or ratio >= AUTO_CROP_MAX_AREA_RATIO:
        return False
    bbox_width = bbox.get("width")
    bbox_height = bbox.get("height")
    if not isinstance(bbox_width, int) or not isinstance(bbox_height, int):
        return False
    return bbox_width >= 120 and bbox_height >= 90


def _copy_or_crop_image(source_path: Path, target_path: Path, raw_metadata: dict[str, object]) -> bool:
    if not _should_crop_padding(raw_metadata):
        shutil.copy2(source_path, target_path)
        return False
    try:
        from PIL import Image  # type: ignore

        bbox = raw_metadata["content_bbox"]
        assert isinstance(bbox, dict)
        with Image.open(source_path) as image:
            crop_box = (
                int(bbox["x"]),
                int(bbox["y"]),
                int(bbox["x"]) + int(bbox["width"]),
                int(bbox["y"]) + int(bbox["height"]),
            )
            cropped = image.crop(crop_box)
            save_kwargs = {}
            if image.format:
                save_kwargs["format"] = image.format
            cropped.save(target_path, **save_kwargs)
        return True
    except Exception:
        shutil.copy2(source_path, target_path)
        return False


def register_asset(
    *,
    source: str | Path,
    asset_id: str,
    asset_dir: str | Path,
    manifest_path: str | Path,
    source_note: str = "",
    role: str = "",
    alt: str = "",
    workspace: str | Path | None = None,
) -> dict[str, object]:
    workspace_dir = Path(workspace or Path.cwd()).resolve()
    source_path = resolve_workspace_path(source, workspace_dir)
    target_dir = resolve_workspace_path(asset_dir, workspace_dir)
    manifest = resolve_workspace_path(manifest_path, workspace_dir)

    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(f"Source asset not found: {source_path}")
    extension = source_path.suffix.lower()
    if extension not in IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image extension: {extension}")

    normalized_id = slugify(asset_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{normalized_id}{extension}"
    raw_metadata = image_metadata(source_path)
    cropped = False
    if source_path.resolve() != target_path.resolve():
        cropped = _copy_or_crop_image(source_path, target_path, raw_metadata)
    metadata = image_metadata(target_path)

    data = load_manifest(manifest)
    assets = [item for item in data.get("assets", []) if not (isinstance(item, dict) and item.get("id") == normalized_id)]
    record = {
        "id": normalized_id,
        "path": workspace_relative(target_path, workspace_dir),
        "source": source_note,
        "role": role,
        "alt": alt,
        "source_file": workspace_relative(source_path, workspace_dir),
        "raw_width": raw_metadata.get("width"),
        "raw_height": raw_metadata.get("height"),
        "raw_aspect_ratio": raw_metadata.get("aspect_ratio"),
        "raw_content_bbox": raw_metadata.get("content_bbox"),
        "raw_content_area_ratio": raw_metadata.get("content_area_ratio"),
        "content_crop_applied": cropped,
        **metadata,
    }
    assets.append(record)
    data["assets"] = assets
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "asset": record,
        "manifest": workspace_relative(manifest, workspace_dir),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register an existing workspace image as a PPT asset.")
    parser.add_argument("--source", required=True, help="Existing workspace image path.")
    parser.add_argument("--id", required=True, help="Stable asset id.")
    parser.add_argument("--asset-dir", required=True, help="Workspace-relative asset output directory.")
    parser.add_argument("--manifest", required=True, help="Workspace-relative asset-manifest.json path.")
    parser.add_argument("--source-note", default="", help="URL or provenance note.")
    parser.add_argument("--role", default="", help="Slide role, e.g. cover hero.")
    parser.add_argument("--alt", default="", help="Alt text.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = register_asset(
            source=args.source,
            asset_id=args.id,
            asset_dir=args.asset_dir,
            manifest_path=args.manifest,
            source_note=args.source_note,
            role=args.role,
            alt=args.alt,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should report any failure.
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
