#!/usr/bin/env python3

import argparse
import re
from datetime import date
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize a Ferryman skill draft in the current workspace.")
    parser.add_argument("skill_name", help="Hyphen-case skill name.")
    parser.add_argument("--description", default="", help="Short trigger-oriented description.")
    parser.add_argument("--output-dir", default=".", help="Workspace-relative or absolute output directory.")
    parser.add_argument("--with-scripts", action="store_true", help="Create an empty scripts directory.")
    parser.add_argument("--with-references", action="store_true", help="Create an empty references directory.")
    parser.add_argument("--with-assets", action="store_true", help="Create an empty assets directory.")
    return parser


def normalize_output_dir(value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def main() -> int:
    args = build_parser().parse_args()
    if not NAME_RE.fullmatch(args.skill_name):
        raise SystemExit("skill_name must use lowercase letters, digits, and hyphens only.")

    target_dir = normalize_output_dir(args.output_dir) / args.skill_name
    if target_dir.exists():
        raise SystemExit(f"Target skill directory already exists: {target_dir}")

    target_dir.mkdir(parents=True, exist_ok=False)
    skill_md = target_dir / "SKILL.md"
    description = args.description.strip() or f"Describe when to use the {args.skill_name} skill."
    today = date.today().isoformat()
    skill_md.write_text(
        f"""---
name: {args.skill_name}
description: {description}
version: 0.1.0
author: Ferryman
created: {today}
updated: {today}
---

# {args.skill_name.replace('-', ' ').title()}

Describe the workflow, constraints, and outputs for this skill.
""",
        encoding="utf-8",
    )

    if args.with_scripts:
        (target_dir / "scripts").mkdir()
    if args.with_references:
        (target_dir / "references").mkdir()
    if args.with_assets:
        (target_dir / "assets").mkdir()

    print(target_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
