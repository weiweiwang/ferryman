#!/usr/bin/env python3
"""Check portable ppt-writer runtime dependencies."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def check_node_dependency() -> dict[str, object]:
    node = shutil.which("node")
    result: dict[str, object] = {
        "node": node,
        "pptxgenjs": False,
        "image_size": False,
        "errors": [],
    }
    errors: list[str] = result["errors"]  # type: ignore[assignment]
    if not node:
        errors.append("Node.js is not available on PATH.")
        return result

    probe = subprocess.run(
        [
            node,
            "-e",
            "const p=require.resolve('pptxgenjs'); const pkg=require('pptxgenjs/package.json'); const ip=require.resolve('image-size'); const ipkg=require('image-size/package.json'); console.log(JSON.stringify({pptxgenjs:{path:p,version:pkg.version},imageSize:{path:ip,version:ipkg.version}}))",
        ],
        cwd=SCRIPT_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if probe.returncode != 0:
        errors.append(
            "pptxgenjs is not resolvable from the ppt-writer skill package. "
            "Run npm install for the skill package or bundle node_modules."
        )
        result["stderr"] = probe.stderr.strip()
        return result
    try:
        payload = json.loads(probe.stdout.strip())
    except json.JSONDecodeError:
        payload = {"raw": probe.stdout.strip()}
    result["pptxgenjs"] = True
    result["image_size"] = True
    result["node_dependency_info"] = payload
    return result


def check_render_dependencies() -> dict[str, object]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    mac_soffice = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    if not soffice and mac_soffice.exists():
        soffice = str(mac_soffice)
    pymupdf = importlib.util.find_spec("fitz") is not None
    pillow = importlib.util.find_spec("PIL") is not None
    pdftoppm = shutil.which("pdftoppm")
    return {
        "soffice": soffice,
        "pymupdf": pymupdf,
        "pillow": pillow,
        "pdftoppm": pdftoppm,
        "render_available": bool(soffice and (pymupdf or pdftoppm)),
        "contact_sheet_available": pillow,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check ppt-writer runtime dependencies.")
    parser.add_argument("--require-render", action="store_true", help="Fail when render QA dependencies are missing.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    node_report = check_node_dependency()
    render_report = check_render_dependencies()
    errors = list(node_report.get("errors", []))
    warnings: list[str] = []
    if not render_report["render_available"]:
        message = "Render QA is unavailable; install LibreOffice plus PyMuPDF or pdftoppm for slide PNG previews."
        if args.require_render:
            errors.append(message)
        else:
            warnings.append(message)
    if not render_report["contact_sheet_available"]:
        warnings.append("Contact-sheet generation is unavailable because Pillow is not installed.")
    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "node": node_report,
        "render": render_report,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
