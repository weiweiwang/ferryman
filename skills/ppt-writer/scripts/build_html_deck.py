#!/usr/bin/env python3
"""Ferryman wrapper for generating controlled HTML slides from deck-spec.json."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build controlled slide HTML for hybrid PPTX generation.")
    parser.add_argument("--spec", required=True, help="Workspace-relative or absolute deck spec JSON.")
    parser.add_argument("--out-dir", required=True, help="Workspace-relative or absolute HTML output directory.")
    parser.add_argument("--manifest", help="Workspace-relative or absolute HTML manifest path.")
    return parser


def run_node(args: argparse.Namespace) -> int:
    node = shutil.which("node")
    if not node:
        print("Node.js is required to run build_html_deck.js.", file=sys.stderr)
        return 1
    script = Path(__file__).with_name("build_html_deck.js").resolve()
    command = [node, str(script), "--spec", args.spec, "--out-dir", args.out_dir]
    if args.manifest:
        command.extend(["--manifest", args.manifest])
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


def main(argv: list[str] | None = None) -> int:
    return run_node(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
