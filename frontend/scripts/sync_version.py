#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TAURI_CONFIG = ROOT_DIR / "src-tauri" / "tauri.conf.json"
PACKAGE_JSON = ROOT_DIR / "package.json"
PACKAGE_LOCK_JSON = ROOT_DIR / "package-lock.json"
CARGO_TOML = ROOT_DIR / "src-tauri" / "Cargo.toml"

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def replace_cargo_package_version(content: str, version: str) -> str:
    lines = content.splitlines(keepends=True)
    in_package = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[package]":
            in_package = True
            continue
        if in_package and stripped.startswith("[") and stripped.endswith("]"):
            break
        if in_package and re.match(r"^version\s*=", stripped):
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f'version = "{version}"{newline}'
            return "".join(lines)

    raise RuntimeError("Could not find [package] version in Cargo.toml.")


def read_source_version() -> str:
    tauri_config = load_json(TAURI_CONFIG)
    version = str(tauri_config.get("version", "")).strip()
    if not VERSION_RE.fullmatch(version):
        raise RuntimeError(f"Invalid Tauri version: {version!r}")
    return version


def set_source_version(version: str) -> None:
    if not VERSION_RE.fullmatch(version):
        raise RuntimeError(f"Invalid version: {version!r}")

    tauri_config = load_json(TAURI_CONFIG)
    tauri_config["version"] = version
    write_json(TAURI_CONFIG, tauri_config)


def sync_version(version: str) -> None:
    package_json = load_json(PACKAGE_JSON)
    package_json["version"] = version
    write_json(PACKAGE_JSON, package_json)

    if PACKAGE_LOCK_JSON.exists():
        package_lock = load_json(PACKAGE_LOCK_JSON)
        package_lock["version"] = version
        root_package = package_lock.get("packages", {}).get("")
        if isinstance(root_package, dict):
            root_package["version"] = version
        write_json(PACKAGE_LOCK_JSON, package_lock)

    cargo_toml = CARGO_TOML.read_text(encoding="utf-8")
    CARGO_TOML.write_text(
        replace_cargo_package_version(cargo_toml, version),
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) > 2:
        print("Usage: sync_version.py [version]", file=sys.stderr)
        return 2

    if len(sys.argv) == 2:
        set_source_version(sys.argv[1])

    version = read_source_version()
    sync_version(version)
    print(f"Synchronized Ferryman version: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
