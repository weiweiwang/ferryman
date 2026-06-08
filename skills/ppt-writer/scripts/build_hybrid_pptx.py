#!/usr/bin/env python3
"""Ferryman wrapper for building hybrid PPTX from rendered HTML layout."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a hybrid PPTX from rendered HTML layout JSON.")
    parser.add_argument("--spec", required=True, help="Workspace-relative or absolute deck spec JSON.")
    parser.add_argument("--layout", required=True, help="Workspace-relative or absolute layout JSON.")
    parser.add_argument("--out", required=True, help="Workspace-relative or absolute PPTX output path.")
    parser.add_argument("--editable-layer", choices=["visible", "none"], default="visible")
    return parser


def run_node(args: argparse.Namespace) -> int:
    node = shutil.which("node")
    if not node:
        print("Node.js is required to run build_hybrid_pptx.js.", file=sys.stderr)
        return 1
    script = Path(__file__).with_name("build_hybrid_pptx.js").resolve()
    command = [
        node,
        str(script),
        "--spec",
        args.spec,
        "--layout",
        args.layout,
        "--out",
        args.out,
        "--editable-layer",
        args.editable_layer,
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
