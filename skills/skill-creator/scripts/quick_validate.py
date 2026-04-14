#!/usr/bin/env python3

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import yaml


NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
REQUIRED_FRONTMATTER_FIELDS = ("name", "description", "version", "author", "created", "updated")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Quick validation for a Ferryman skill draft.")
    parser.add_argument("skill_dir", help="Path to the draft skill directory.")
    return parser


def load_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        raise ValueError("SKILL.md must start with YAML frontmatter.")
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md frontmatter is incomplete.")
    data = yaml.safe_load(parts[1]) or {}
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter must parse to a mapping.")
    return data


def collect_local_link_errors(skill_dir: Path, content: str) -> list[str]:
    errors: list[str] = []
    for match in LOCAL_LINK_RE.finditer(content):
        target = match.group(1).strip()
        if not target or "://" in target or target.startswith("#"):
            continue
        resolved = (skill_dir / target).resolve()
        if not resolved.exists():
            errors.append(f"Referenced file does not exist: {target}")
    return errors


def normalize_metadata_value(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_iso_date(value) -> bool:
    text = normalize_metadata_value(value)
    if not DATE_RE.fullmatch(text):
        return False
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        return False
    return True


def main() -> int:
    args = build_parser().parse_args()
    skill_dir = Path(args.skill_dir).expanduser()
    if not skill_dir.is_absolute():
        skill_dir = (Path.cwd() / skill_dir).resolve()
    else:
        skill_dir = skill_dir.resolve()

    errors: list[str] = []
    warnings: list[str] = []

    if not skill_dir.exists():
        errors.append(f"Skill directory not found: {skill_dir}")
    elif not skill_dir.is_dir():
        errors.append(f"Skill path is not a directory: {skill_dir}")

    skill_md = skill_dir / "SKILL.md"
    content = ""
    metadata: dict = {}
    if not errors:
        if not skill_md.exists():
            errors.append("Missing SKILL.md")
        else:
            content = skill_md.read_text(encoding="utf-8")
            try:
                metadata = load_frontmatter(content)
            except Exception as exc:
                errors.append(str(exc))

    if metadata:
        for field in REQUIRED_FRONTMATTER_FIELDS:
            if not normalize_metadata_value(metadata.get(field)):
                errors.append(f"Frontmatter field '{field}' is required.")

        name = str(metadata.get("name", "")).strip()
        description = str(metadata.get("description", "")).strip()
        if name and not NAME_RE.fullmatch(name):
            errors.append("Frontmatter field 'name' must use lowercase letters, digits, and hyphens only.")
        elif skill_dir.name != name:
            errors.append(f"Directory name '{skill_dir.name}' must match skill name '{name}'.")

        if metadata.get("version") != "0.1.0":
            errors.append("Frontmatter field 'version' must be '0.1.0'.")

        if metadata.get("created") and not is_iso_date(metadata.get("created")):
            errors.append("Frontmatter field 'created' must use YYYY-MM-DD format.")

        if metadata.get("updated") and not is_iso_date(metadata.get("updated")):
            errors.append("Frontmatter field 'updated' must use YYYY-MM-DD format.")

        if len(content.splitlines()) > 500:
            warnings.append("SKILL.md is longer than 500 lines; consider moving detail into references/.")

        errors.extend(collect_local_link_errors(skill_dir, content))

    result = {
        "ok": not errors,
        "skill_dir": str(skill_dir),
        "errors": errors,
        "warnings": warnings,
        "metadata": {
            "name": metadata.get("name"),
            "description": metadata.get("description"),
            "version": metadata.get("version"),
            "author": metadata.get("author"),
            "created": normalize_metadata_value(metadata.get("created")) or None,
            "updated": normalize_metadata_value(metadata.get("updated")) or None,
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
