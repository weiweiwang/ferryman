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
from pathlib import Path
from xml.etree import ElementTree


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}


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
    except Exception as exc:  # noqa: BLE001 - metadata should not block registration.
        metadata["metadata_error"] = str(exc)
    return metadata


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
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)
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
