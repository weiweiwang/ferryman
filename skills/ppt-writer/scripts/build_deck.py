#!/usr/bin/env python3
"""Ferryman run_skill_script wrapper for the Node PPTX builder."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a PPTX deck from deck-spec.json.")
    parser.add_argument("--spec", required=True, help="Workspace-relative or absolute deck spec JSON.")
    parser.add_argument("--out", required=True, help="Workspace-relative or absolute PPTX output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    node = shutil.which("node")
    if not node:
        print("Node.js is required to run build_deck.js.", file=sys.stderr)
        return 1

    script = Path(__file__).with_name("build_deck.js").resolve()
    command = [
        node,
        str(script),
        "--spec",
        args.spec,
        "--out",
        args.out,
    ]
    result = subprocess.run(
        command,
        cwd=Path.cwd(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
