#!/usr/bin/env python3
"""Ferryman wrapper for rendering controlled slide HTML and extracting layout JSON."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render controlled slide HTML for hybrid PPTX generation.")
    parser.add_argument("--manifest", required=True, help="Workspace-relative or absolute HTML manifest path.")
    parser.add_argument("--out-dir", required=True, help="Workspace-relative or absolute preview output directory.")
    parser.add_argument("--layout-out", required=True, help="Workspace-relative or absolute layout JSON output path.")
    parser.add_argument("--background-mode", choices=["skeleton", "visual"], default="skeleton")
    return parser


def run_node(args: argparse.Namespace) -> int:
    node = shutil.which("node")
    if not node:
        print("Node.js is required to run render_html_deck.js.", file=sys.stderr)
        return 1
    script = Path(__file__).with_name("render_html_deck.js").resolve()
    command = [
        node,
        str(script),
        "--manifest",
        args.manifest,
        "--out-dir",
        args.out_dir,
        "--layout-out",
        args.layout_out,
        "--background-mode",
        args.background_mode,
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


def main(argv: list[str] | None = None) -> int:
    return run_node(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
