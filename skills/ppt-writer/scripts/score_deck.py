#!/usr/bin/env python3
"""Score a generated deck against the ppt-writer comeback rubric."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import median


TOPIC_LIKE_RE = re.compile(
    r"^(overview|introduction|summary|agenda|timeline|roadmap|metrics|data|"
    r"background|analysis|recommendations|next steps)$",
    re.IGNORECASE,
)
DIMENSIONS = (
    "story",
    "specificity",
    "rhythm",
    "whitespace",
    "visual_proof",
    "asset_quality",
    "precision",
    "coherence",
)


def load_json(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _text(value: object) -> str:
    return str(value or "").strip()


def _slides(spec: dict[str, object]) -> list[dict[str, object]]:
    raw = spec.get("slides")
    return [slide for slide in raw if isinstance(slide, dict)] if isinstance(raw, list) else []


def _score(value: float) -> int:
    return max(0, min(5, int(round(value))))


def _qa_part(qa: dict[str, object], key: str) -> dict[str, object]:
    value = qa.get(key)
    return value if isinstance(value, dict) else {}


def _qa_metrics(qa: dict[str, object]) -> dict[str, object]:
    reference = _qa_part(qa, "reference_report")
    metrics = reference.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _constraint_number(spec: dict[str, object], name: str, default: float) -> float:
    constraints = spec.get("reference_constraints")
    if isinstance(constraints, dict):
        value = constraints.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return default


def _qa_errors(qa: dict[str, object]) -> list[str]:
    errors: list[str] = []
    for key in ("spec_report", "pptx_report", "reference_report"):
        report = _qa_part(qa, key)
        raw_errors = report.get("errors")
        if isinstance(raw_errors, list):
            errors.extend(str(error) for error in raw_errors)
    return errors


def _qa_warnings(qa: dict[str, object]) -> list[str]:
    warnings: list[str] = []
    for key in ("spec_report", "pptx_report", "reference_report"):
        report = _qa_part(qa, key)
        raw_warnings = report.get("warnings")
        if isinstance(raw_warnings, list):
            warnings.extend(str(warning) for warning in raw_warnings)
    return warnings


def _slide_text_rows(qa: dict[str, object]) -> list[dict[str, object]]:
    pptx = _qa_part(qa, "pptx_report")
    metrics = pptx.get("metrics")
    if not isinstance(metrics, dict):
        return []
    slides = metrics.get("slides")
    return [slide for slide in slides if isinstance(slide, dict)] if isinstance(slides, list) else []


def _layout_families(spec: dict[str, object]) -> list[str]:
    families: list[str] = []
    for slide in _slides(spec):
        family = _text(slide.get("layout_family") or slide.get("layout") or slide.get("type"))
        if family:
            families.append(family)
    return families


def _repeated_layout_runs(families: list[str]) -> list[int]:
    repeated: list[int] = []
    for index in range(2, len(families)):
        if families[index] == families[index - 1] == families[index - 2]:
            repeated.append(index - 1)
    return repeated


def _preview_light_surface_warnings(preview_dir: Path | None) -> list[dict[str, object]]:
    if not preview_dir or not preview_dir.exists():
        return []
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return []

    warnings: list[dict[str, object]] = []
    for path in sorted(preview_dir.glob("slide-*.png")):
        match = re.search(r"slide-(\d+)", path.name)
        slide_number = int(match.group(1)) if match else len(warnings) + 1
        try:
            with Image.open(path) as raw_image:
                image = raw_image.convert("RGB").resize((160, 90))
                width, height = image.size
                raw_pixels = image.tobytes()
        except Exception:
            continue
        border: list[tuple[int, int, int]] = []
        for x in range(width):
            border.append(image.getpixel((x, 0)))
            border.append(image.getpixel((x, height - 1)))
        for y in range(height):
            border.append(image.getpixel((0, y)))
            border.append(image.getpixel((width - 1, y)))
        bg = tuple(int(median(channel)) for channel in zip(*border)) if border else (0, 0, 0)
        bg_brightness = sum(bg) / 3
        light_pixels = sum(
            1
            for index in range(0, len(raw_pixels), 3)
            if raw_pixels[index] > 238 and raw_pixels[index + 1] > 238 and raw_pixels[index + 2] > 238
        )
        light_ratio = round(light_pixels / max(1, width * height), 4)
        if bg_brightness < 100 and light_ratio > 0.18:
            warnings.append(
                {
                    "slide": slide_number,
                    "light_surface_ratio": light_ratio,
                    "reason": "large light surfaces on a dark slide; verify these panels contain visible content",
                }
            )
    return warnings


def _dimension_scores(spec: dict[str, object], qa: dict[str, object], render_warnings: list[dict[str, object]]) -> dict[str, int]:
    slides = _slides(spec)
    non_appendix = [slide for slide in slides if _text(slide.get("type")).lower() != "appendix"]
    slide_count = len(slides)
    metrics = _qa_metrics(qa)
    errors = _qa_errors(qa)
    warnings = _qa_warnings(qa)
    text_rows = _slide_text_rows(qa)
    families = _layout_families(spec)
    repeated_runs = _repeated_layout_runs(families)

    claim_count = sum(1 for slide in non_appendix if _text(slide.get("claim")))
    proof_count = sum(1 for slide in non_appendix if _text(slide.get("proof_object")))
    support_count = sum(1 for slide in non_appendix if _text(slide.get("support")))
    required = max(1, len(non_appendix))
    topic_like = sum(1 for slide in non_appendix if TOPIC_LIKE_RE.fullmatch(_text(slide.get("claim"))))
    sourced = sum(1 for slide in non_appendix if slide.get("sources") or _text(slide.get("support")))

    layout_family_count = len(set(families))
    image_slide_ratio = float(metrics.get("image_slide_ratio") or 0)
    effective_image_slide_ratio = float(metrics.get("effective_image_slide_ratio") or 0)
    min_image_ratio = max(0.3, min(0.8, _constraint_number(spec, "min_image_slide_ratio", 0.5)))
    min_effective_image_ratio = max(0.3, min(0.8, _constraint_number(spec, "min_effective_image_slide_ratio", 0.5)))
    avg_text = float(metrics.get("avg_text_chars_per_slide") or 0)
    max_text = float(metrics.get("max_text_chars_per_slide") or 0)
    weak_images = metrics.get("weak_expected_image_slides")
    missing_images = metrics.get("missing_expected_image_slides")
    weak_image_count = len(weak_images) if isinstance(weak_images, list) else 0
    missing_image_count = len(missing_images) if isinstance(missing_images, list) else 0
    naked_urls = int(metrics.get("naked_url_count") or 0)
    dense_slide_count = sum(1 for slide in text_rows if int(slide.get("text_chars") or 0) > 240)

    story = 5 * min(claim_count, proof_count, support_count) / required
    specificity = 5 - min(2, topic_like) - (0 if sourced == required else 1)
    rhythm = 5
    if slide_count >= 10 and layout_family_count < 5:
        rhythm -= 1
    elif slide_count >= 8 and layout_family_count < 4:
        rhythm -= 1
    rhythm -= min(2, len(repeated_runs))
    whitespace = 5
    if avg_text > 180:
        whitespace -= 1
    if max_text > 260:
        whitespace -= 1
    if dense_slide_count >= 2:
        whitespace -= 1
    if render_warnings:
        whitespace -= 1
    visual_proof = 5 - min(3, weak_image_count + missing_image_count * 2)
    if bool(spec.get("media_required")) and effective_image_slide_ratio < min_effective_image_ratio:
        visual_proof -= 1
    asset_quality = 5
    if bool(spec.get("media_required")) and image_slide_ratio < min_image_ratio:
        asset_quality -= 2
    if bool(spec.get("media_required")) and effective_image_slide_ratio < min_effective_image_ratio:
        asset_quality -= 1
    if weak_image_count:
        asset_quality -= 1
    precision = 5
    if naked_urls:
        precision -= 2
    if any("unsupported field" in error for error in errors):
        precision -= 2
    if any("visible URL" in error for error in errors):
        precision -= 1
    coherence = 5
    if not isinstance(spec.get("theme"), dict):
        coherence -= 1
    if slide_count >= 8 and layout_family_count < 4:
        coherence -= 1
    if repeated_runs:
        coherence -= 1
    if len(warnings) >= 3:
        coherence -= 1

    return {
        "story": _score(story),
        "specificity": _score(specificity),
        "rhythm": _score(rhythm),
        "whitespace": _score(whitespace),
        "visual_proof": _score(visual_proof),
        "asset_quality": _score(asset_quality),
        "precision": _score(precision),
        "coherence": _score(coherence),
    }


def _weak_slides(spec: dict[str, object], qa: dict[str, object], render_warnings: list[dict[str, object]]) -> list[dict[str, object]]:
    metrics = _qa_metrics(qa)
    weak: dict[int, set[str]] = {}
    for item in metrics.get("weak_expected_image_slides", []) if isinstance(metrics.get("weak_expected_image_slides"), list) else []:
        if isinstance(item, dict):
            slide = int(item.get("slide") or 0)
            if slide:
                weak.setdefault(slide, set()).add("image frame is too small for the promised visual role")
    for slide in metrics.get("missing_expected_image_slides", []) if isinstance(metrics.get("missing_expected_image_slides"), list) else []:
        try:
            weak.setdefault(int(slide), set()).add("expected image is missing")
        except (TypeError, ValueError):
            pass
    for row in _slide_text_rows(qa):
        slide = int(row.get("slide") or 0)
        text_chars = int(row.get("text_chars") or 0)
        if slide and text_chars > 240:
            weak.setdefault(slide, set()).add(f"dense slide text ({text_chars} chars)")
    for warning in render_warnings:
        slide = int(warning.get("slide") or 0)
        if slide:
            weak.setdefault(slide, set()).add(str(warning.get("reason") or "render visual warning"))
    for index, slide in enumerate(_slides(spec), start=1):
        if TOPIC_LIKE_RE.fullmatch(_text(slide.get("claim"))):
            weak.setdefault(index, set()).add("claim reads like a topic label")
        if not _text(slide.get("proof_object")):
            weak.setdefault(index, set()).add("missing proof object")
    return [
        {"slide": slide, "reasons": sorted(reasons)}
        for slide, reasons in sorted(weak.items())
    ]


def score_deck(spec: dict[str, object], qa: dict[str, object], preview_dir: str | Path | None = None) -> dict[str, object]:
    render_warnings = _preview_light_surface_warnings(Path(preview_dir) if preview_dir else None)
    dimensions = _dimension_scores(spec, qa, render_warnings)
    errors = _qa_errors(qa)
    weak_slides = _weak_slides(spec, qa, render_warnings)
    total = sum(dimensions.values())
    min_dimension = min(dimensions.values()) if dimensions else 0
    threshold = 32
    blocking = []
    if errors:
        blocking.append("underlying QA has errors")
    if total < threshold:
        blocking.append(f"score {total}/{len(DIMENSIONS) * 5} is below threshold {threshold}")
    if min_dimension < 4:
        blocking.append(f"at least one dimension is below 4 (min={min_dimension})")
    if weak_slides:
        blocking.append("weak slides require iteration")
    return {
        "ok": not blocking,
        "total_score": total,
        "max_score": len(DIMENSIONS) * 5,
        "threshold": threshold,
        "dimension_scores": dimensions,
        "blocking_reasons": blocking,
        "weak_slides": weak_slides,
        "render_warnings": render_warnings,
    }


def markdown_report(spec_path: Path, qa_path: Path, report: dict[str, object]) -> str:
    lines = [
        f"# Contact Sheet Scorecard: {'PASS' if report.get('ok') else 'FAIL'}",
        "",
        f"- Spec: `{spec_path}`",
        f"- QA JSON: `{qa_path}`",
        f"- Total score: {report.get('total_score')}/{report.get('max_score')}",
        f"- Threshold: {report.get('threshold')}",
        "",
        "## Dimensions",
        "",
    ]
    dimensions = report.get("dimension_scores", {})
    if isinstance(dimensions, dict):
        lines.extend(f"- {name}: {score}/5" for name, score in dimensions.items())
    lines.extend(["", "## Blocking Reasons", ""])
    blocking = report.get("blocking_reasons", [])
    lines.extend([f"- {reason}" for reason in blocking] if isinstance(blocking, list) and blocking else ["- None"])
    lines.extend(["", "## Weak Slides", ""])
    weak_slides = report.get("weak_slides", [])
    if isinstance(weak_slides, list) and weak_slides:
        for item in weak_slides:
            if not isinstance(item, dict):
                continue
            reasons = item.get("reasons", [])
            reason_text = "; ".join(str(reason) for reason in reasons) if isinstance(reasons, list) else str(reasons)
            lines.append(f"- Slide {item.get('slide')}: {reason_text}")
    else:
        lines.append("- None")
    render_warnings = report.get("render_warnings", [])
    if isinstance(render_warnings, list) and render_warnings:
        lines.extend(["", "## Render Warnings", ""])
        for item in render_warnings:
            lines.append(f"- Slide {item.get('slide')}: {item.get('reason')} ({item.get('light_surface_ratio')})")
    lines.extend(
        [
            "",
            "## Next Steps",
            "",
            "- If status is FAIL, rebuild the weak slides and rerun build, render, QA, and this scorecard.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score PPT output against the ppt-writer comeback rubric.")
    parser.add_argument("--spec", required=True, help="Path to deck-spec.json.")
    parser.add_argument("--qa-json", required=True, help="JSON output from qa_deck.py --json-out.")
    parser.add_argument("--out", required=True, help="Markdown scorecard output path.")
    parser.add_argument("--json-out", default=None, help="Optional scorecard JSON output path.")
    parser.add_argument("--preview-dir", default=None, help="Optional directory with rendered slide-*.png files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec_path = Path(args.spec).resolve()
    qa_path = Path(args.qa_json).resolve()
    out_path = Path(args.out).resolve()
    spec = load_json(spec_path)
    qa = load_json(qa_path)
    report = score_deck(spec, qa, args.preview_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown_report(spec_path, qa_path, report), encoding="utf-8")
    if args.json_out:
        json_path = Path(args.json_out).resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
