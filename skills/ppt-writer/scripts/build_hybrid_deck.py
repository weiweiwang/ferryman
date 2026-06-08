#!/usr/bin/env python3
"""End-to-end HTML-first hybrid PPTX builder for Ferryman ppt-writer."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a hybrid PPTX deck from deck-spec.json.")
    parser.add_argument("--spec", required=True, help="Workspace-relative or absolute deck spec JSON.")
    parser.add_argument("--out", required=True, help="Workspace-relative or absolute PPTX output path.")
    parser.add_argument("--html-dir", help="Workspace-relative or absolute HTML output directory.")
    parser.add_argument("--preview-dir", help="Workspace-relative or absolute screenshot output directory.")
    parser.add_argument("--layout-out", help="Workspace-relative or absolute layout JSON output path.")
    parser.add_argument(
        "--background-mode",
        choices=["skeleton", "visual"],
        default=None,
        help="skeleton hides editable elements for native overlays; visual keeps full HTML screenshots.",
    )
    parser.add_argument(
        "--editable-layer",
        choices=["visible", "none"],
        default=None,
        help="Whether to add visible native PPTX elements over the rendered background.",
    )
    parser.add_argument(
        "--allow-text-overflow",
        action="store_true",
        help="Debug only: continue even when rendered HTML text boxes overflow.",
    )
    return parser


def default_artifact_paths(spec_path: Path, args: argparse.Namespace) -> tuple[str, str, str, str]:
    spec_dir = spec_path.parent
    html_dir = args.html_dir or str(spec_dir / "html")
    preview_dir = args.preview_dir or str(spec_dir / "preview-hybrid")
    layout_out = args.layout_out or str(spec_dir / "layout.json")
    manifest = str(Path(html_dir) / "deck-html-manifest.json")
    return html_dir, preview_dir, layout_out, manifest


def hybrid_modes(spec_path: Path, args: argparse.Namespace) -> tuple[str, str]:
    background_mode = args.background_mode
    editable_layer = args.editable_layer
    if background_mode and editable_layer:
        return background_mode, editable_layer
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        spec = {}
    hybrid = spec.get("hybrid") if isinstance(spec, dict) else {}
    if not isinstance(hybrid, dict):
        hybrid = {}
    background_mode = background_mode or str(hybrid.get("background_mode") or "skeleton")
    editable_layer = editable_layer or str(hybrid.get("editable_layer") or "visible")
    if background_mode not in {"visual", "skeleton"}:
        background_mode = "skeleton"
    if editable_layer not in {"none", "visible"}:
        editable_layer = "visible"
    return background_mode, editable_layer


def validate_hybrid_mode_pair(background_mode: str, editable_layer: str) -> str | None:
    if background_mode == "skeleton" and editable_layer == "visible":
        return None
    if background_mode == "visual" and editable_layer == "none":
        return None
    return (
        "Invalid hybrid mode pair: "
        f"--background-mode {background_mode} with --editable-layer {editable_layer}. "
        "Use skeleton+visible for editable decks, or visual+none for screenshot-only ceiling tests."
    )


def summarize_step_output(stdout: str, stderr: str) -> None:
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            print(stdout, end="")
        else:
            if isinstance(payload, dict):
                summary = {
                    key: payload.get(key)
                    for key in (
                        "ok",
                        "mode",
                        "output",
                        "output_bytes",
                        "slide_count",
                        "background_mode",
                        "overflow_warning_count",
                    )
                    if key in payload
                }
                if summary:
                    print(json.dumps(summary, ensure_ascii=False, indent=2))
                else:
                    print(stdout, end="")
            else:
                print(stdout, end="")
    if stderr:
        print(stderr, file=sys.stderr, end="")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    node = shutil.which("node")
    if not node:
        print("Node.js is required to build hybrid decks.", file=sys.stderr)
        return 1

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = Path.cwd() / spec_path
    html_dir, preview_dir, layout_out, manifest = default_artifact_paths(spec_path.resolve(), args)
    background_mode, editable_layer = hybrid_modes(spec_path.resolve(), args)
    mode_error = validate_hybrid_mode_pair(background_mode, editable_layer)
    if mode_error:
        print(mode_error, file=sys.stderr)
        return 2
    scripts_dir = Path(__file__).resolve().parent
    steps = [
        [
            node,
            str(scripts_dir / "build_html_deck.js"),
            "--spec",
            args.spec,
            "--out-dir",
            html_dir,
            "--manifest",
            manifest,
        ],
        [
            node,
            str(scripts_dir / "render_html_deck.js"),
            "--manifest",
            manifest,
            "--out-dir",
            preview_dir,
            "--layout-out",
            layout_out,
            "--background-mode",
            background_mode,
        ],
        [
            node,
            str(scripts_dir / "build_hybrid_pptx.js"),
            "--spec",
            args.spec,
            "--layout",
            layout_out,
            "--out",
            args.out,
            "--editable-layer",
            editable_layer,
        ],
    ]
    for step_index, step in enumerate(steps):
        result = subprocess.run(
            step,
            cwd=Path.cwd(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        summarize_step_output(result.stdout, result.stderr)
        code = result.returncode
        if code:
            return code
        if step_index == 1:
            try:
                layout = json.loads(Path(layout_out).read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - bad layout is a build blocker.
                print(f"Failed to read rendered layout JSON: {exc}", file=sys.stderr)
                return 1
            overflow_warnings = layout.get("overflow_warnings") if isinstance(layout, dict) else []
            if isinstance(overflow_warnings, list) and overflow_warnings and not args.allow_text_overflow:
                print(
                    "Rendered HTML has text overflow; rebuild the affected slides or pass "
                    "--allow-text-overflow only for debugging.",
                    file=sys.stderr,
                )
                print(json.dumps(overflow_warnings[:10], ensure_ascii=False, indent=2), file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
