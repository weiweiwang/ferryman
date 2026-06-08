#!/usr/bin/env python3
"""Render a PPTX to slide PNGs when local render tools are available."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def resolve_workspace_path(raw_path: str | Path, workspace: str | Path | None = None, *, label: str = "path") -> Path:
    raw = str(raw_path)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", raw):
        raise ValueError(f"{label} must be a workspace file path, not a URL: {raw}")
    workspace_dir = Path(workspace or Path.cwd()).resolve()
    path = Path(raw_path)
    candidate = path.resolve() if path.is_absolute() else (workspace_dir / path).resolve()
    try:
        candidate.relative_to(workspace_dir)
    except ValueError as exc:
        raise ValueError(f"{label} escapes workspace: {raw_path}") from exc
    return candidate


def clean_render_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("slide-*.png"):
        if stale.is_file():
            stale.unlink()


def find_libreoffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        path = shutil.which(name)
        if path:
            return path
    mac_path = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return str(mac_path) if mac_path.exists() else None


def convert_pptx_to_pdf(pptx: Path, output_dir: Path) -> Path:
    soffice = find_libreoffice()
    if not soffice:
        raise RuntimeError("LibreOffice/soffice not found; cannot convert PPTX to PDF.")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(pptx),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "LibreOffice conversion failed:\n"
            f"stdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}"
        )
    pdf = output_dir / f"{pptx.stem}.pdf"
    if not pdf.exists():
        matches = list(output_dir.glob("*.pdf"))
        if len(matches) == 1:
            return matches[0]
        raise RuntimeError(f"LibreOffice did not create expected PDF: {pdf}")
    return pdf


def render_pdf_with_pymupdf(pdf: Path, output_dir: Path, scale: float) -> list[Path]:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("PyMuPDF is not installed.") from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf))
    paths: list[Path] = []
    matrix = fitz.Matrix(scale, scale)
    for index, page in enumerate(doc, start=1):
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        out = output_dir / f"slide-{index:02d}.png"
        pix.save(str(out))
        paths.append(out)
    return paths


def render_pdf_with_pdftoppm(pdf: Path, output_dir: Path) -> list[Path]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("Neither PyMuPDF nor pdftoppm is available.")
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = output_dir / "slide"
    result = subprocess.run(
        [pdftoppm, "-png", "-r", "144", str(pdf), str(prefix)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "pdftoppm render failed:\n"
            f"stdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}"
        )
    paths = sorted(output_dir.glob("slide-*.png"))
    renamed: list[Path] = []
    for index, path in enumerate(paths, start=1):
        target = output_dir / f"slide-{index:02d}.png"
        if path != target:
            path.rename(target)
        renamed.append(target)
    return renamed


def render_deck(pptx: str | Path, out_dir: str | Path, scale: float = 2.0) -> dict[str, object]:
    pptx_path = resolve_workspace_path(pptx, label="PPTX path")
    out_path = resolve_workspace_path(out_dir, label="render output directory")
    if not pptx_path.exists():
        raise RuntimeError(f"PPTX not found: {pptx_path}")
    clean_render_output_dir(out_path)
    with tempfile.TemporaryDirectory(prefix="ppt-writer-render-") as tmp:
        pdf_dir = Path(tmp)
        pdf = convert_pptx_to_pdf(pptx_path, pdf_dir)
        try:
            slides = render_pdf_with_pymupdf(pdf, out_path, scale)
            renderer = "pymupdf"
        except RuntimeError:
            slides = render_pdf_with_pdftoppm(pdf, out_path)
            renderer = "pdftoppm"
    return {
        "ok": True,
        "pptx": str(pptx_path),
        "out_dir": str(out_path),
        "renderer": renderer,
        "slide_count": len(slides),
        "slides": [str(path) for path in slides],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render PPTX to PNG slide previews.")
    parser.add_argument("--pptx", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--json-out", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = render_deck(args.pptx, args.out_dir, args.scale)
    except Exception as exc:  # noqa: BLE001
        report = {"ok": False, "errors": [str(exc)], "pptx": str(Path(args.pptx).resolve())}
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        out = resolve_workspace_path(args.json_out, label="JSON output path")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
