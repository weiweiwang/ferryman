#!/usr/bin/env python3
"""Deck-spec and PPTX QA for the ppt-writer skill."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from inspect_pptx import inspect_pptx  # noqa: E402


TOPIC_LIKE_RE = re.compile(
    r"^(overview|introduction|summary|agenda|timeline|roadmap|metrics|data|"
    r"background|analysis|recommendations|next steps)$",
    re.IGNORECASE,
)
URL_LIKE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
VISIBLE_URL_RE = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
IMAGE_EXPECTING_RE = re.compile(
    r"(image|photo|picture|screenshot|media|visual|gallery|image-grid|"
    r"full-bleed-photo|photo-caption|classroom-takeaway|"
    r"人物|图片|照片|截图|图文|相册)",
    re.IGNORECASE,
)
UNSUPPORTED_IMAGE_FIELDS = {
    "download_images",
    "image_idx",
    "image_url",
    "image_urls",
    "url",
    "urls",
}
ALLOWED_TASK_MODES = {
    "create",
    "source-driven",
    "template-inspired",
    "targeted-regenerate",
    "template-following",
    "targeted-edit",
}
ALLOWED_PROFILES = {
    "finance-ir",
    "product-platform",
    "gtm-growth",
    "engineering-platform",
    "strategy-leadership",
    "consumer-retail",
    "template-following",
    "targeted-edit-data",
    "targeted-edit-media",
    "appendix-heavy",
}
PATTERN_IMAGE_RULES = {
    "science-cover": {"min_area": 0.30, "media_warn_without_image": True},
    "chapter-spread": {"min_area": 0.24, "media_warn_without_image": True},
    "mechanism-light": {"min_area": 0.22},
    "impact-reset": {"expects_image": True, "min_area": 0.30},
    "evidence-triptych": {"expects_image": True, "min_area": 0.09, "min_count": 3},
    "closing-awe": {"min_area": 0.46, "media_warn_without_image": True},
}


def load_spec(spec_path: str | Path) -> dict[str, object]:
    path = Path(spec_path)
    return json.loads(path.read_text(encoding="utf-8"))


def _text(value: object) -> str:
    return str(value or "").strip()


def _images_for_slide(slide: dict[str, object]) -> list[dict[str, object]]:
    images: list[dict[str, object]] = []
    image = slide.get("image")
    if isinstance(image, dict):
        images.append(image)
    raw_images = slide.get("images")
    if isinstance(raw_images, list):
        images.extend([item for item in raw_images if isinstance(item, dict)])
    return images


def _is_relative_workspace_path(value: str) -> bool:
    path = Path(value)
    return not URL_LIKE_RE.match(value) and not path.is_absolute() and ".." not in path.parts


def _text_chars(value: object) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(
            _text_chars(child)
            for key, child in value.items()
            if key not in {"sources", "source", "path", "src", "alt"}
        )
    if isinstance(value, list):
        return sum(_text_chars(child) for child in value)
    return 0


def _visible_text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for key, child in value.items():
            if key in {"sources", "source", "path", "src", "alt"}:
                continue
            values.extend(_visible_text_values(child))
        return values
    if isinstance(value, list):
        values: list[str] = []
        for child in value:
            values.extend(_visible_text_values(child))
        return values
    return []


def _slide_expects_image(slide: dict[str, object]) -> bool:
    if bool(slide.get("requires_image")):
        return True
    if _images_for_slide(slide):
        return True
    layout_text = " ".join(
        _text(slide.get(field))
        for field in ("layout", "layout_family", "type", "proof_object")
    )
    rule = _pattern_image_rule(slide)
    if bool(rule.get("expects_image")):
        return True
    return bool(IMAGE_EXPECTING_RE.search(layout_text))


def _pattern_image_rule(slide: dict[str, object]) -> dict[str, object]:
    layout_text = " ".join(
        _text(slide.get(field))
        for field in ("layout", "layout_family", "type", "proof_object")
    ).lower()
    for key, rule in PATTERN_IMAGE_RULES.items():
        if key in layout_text:
            return rule
    return {}


def _min_picture_area_ratio(slide: dict[str, object]) -> float:
    layout_text = " ".join(
        _text(slide.get(field))
        for field in ("layout", "layout_family", "type", "proof_object")
    ).lower()
    rule = _pattern_image_rule(slide)
    if isinstance(rule.get("min_area"), (int, float)) and (_slide_expects_image(slide) or _images_for_slide(slide)):
        return float(rule["min_area"])
    if re.search(r"(full-bleed|photo-caption|cover-photo|takeaway-photo|classroom)", layout_text):
        return 0.30
    if re.search(r"(image-grid|gallery)", layout_text):
        return 0.10
    if _slide_expects_image(slide):
        return 0.10
    return 0.0


def _min_picture_count(slide: dict[str, object]) -> int:
    rule = _pattern_image_rule(slide)
    if isinstance(rule.get("min_count"), (int, float)):
        return int(rule["min_count"])
    return 1 if _slide_expects_image(slide) else 0


def _number_from_mapping(mapping: object, name: str, default: float) -> float:
    if isinstance(mapping, dict):
        value = mapping.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return default


def validate_spec(spec: dict[str, object]) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, object] = {}

    if not _text(spec.get("title")):
        errors.append("Spec is missing title.")
    if not _text(spec.get("audience")):
        warnings.append("Spec is missing audience.")
    task_mode = _text(spec.get("task_mode"))
    primary_profile = _text(spec.get("primary_profile"))
    if not task_mode:
        errors.append("Spec is missing task_mode.")
    elif task_mode not in ALLOWED_TASK_MODES:
        errors.append(f"Unsupported task_mode '{task_mode}'.")
    if not primary_profile:
        errors.append("Spec is missing primary_profile.")
    elif primary_profile not in ALLOWED_PROFILES:
        errors.append(f"Unsupported primary_profile '{primary_profile}'.")
    secondary_gates = spec.get("secondary_gates", [])
    constraints = spec.get("reference_constraints")
    if secondary_gates is None:
        secondary_gates = []
    if not isinstance(secondary_gates, list) or not all(isinstance(item, str) for item in secondary_gates):
        errors.append("secondary_gates must be a list of strings when present.")
    for field in ("download_images", "image_url", "image_urls"):
        if field in spec:
            errors.append(
                f"Spec uses unsupported field '{field}'. Download or generate images into the workspace and reference them with slide image.path."
            )

    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        errors.append("Spec must include a non-empty slides array.")
        slides = []

    metrics["slide_count"] = len(slides)
    layout_families: list[str] = []
    media_required = bool(spec.get("media_required"))
    image_slide_count = 0
    expected_image_slide_numbers: list[int] = []
    non_appendix_count = 0
    spec_slide_chars: list[int] = []
    expected_number = 1

    for index, raw_slide in enumerate(slides, start=1):
        if not isinstance(raw_slide, dict):
            errors.append(f"Slide {index} is not an object.")
            continue
        slide_number = raw_slide.get("number", index)
        if slide_number != expected_number:
            errors.append(f"Slide {index} has number {slide_number}; expected {expected_number}.")
        expected_number += 1

        slide_type = _text(raw_slide.get("type")).lower()
        layout = _text(raw_slide.get("layout"))
        family = _text(raw_slide.get("layout_family")) or layout or slide_type or "generic"
        layout_families.append(family)

        if not layout:
            errors.append(f"Slide {index} is missing layout.")
        if not _text(raw_slide.get("layout_family")):
            warnings.append(f"Slide {index} is missing layout_family; using '{family}' for rhythm QA.")
        for field in ("download_images", "image_idx", "image_url", "image_urls"):
            if field in raw_slide:
                errors.append(
                    f"Slide {index} uses unsupported field '{field}'. Use image.path or images[].path with a workspace-relative asset path."
                )

        is_appendix = slide_type == "appendix"
        if not is_appendix:
            non_appendix_count += 1
        spec_slide_chars.append(_text_chars(raw_slide))
        for visible_text in _visible_text_values(raw_slide):
            if VISIBLE_URL_RE.search(visible_text):
                errors.append(
                    f"Slide {index} contains a visible URL. Put URLs in sources/source provenance, not rendered slide text."
                )
        images = _images_for_slide(raw_slide)
        pattern_rule = _pattern_image_rule(raw_slide)
        if images or bool(raw_slide.get("requires_image")):
            image_slide_count += 1
        if _slide_expects_image(raw_slide):
            expected_image_slide_numbers.append(index)
        if bool(raw_slide.get("requires_image")) and not images:
            errors.append(f"Slide {index} sets requires_image but does not include image/images.")
        if bool(pattern_rule.get("expects_image")) and not images:
            errors.append(f"Slide {index} layout expects image/images but none were provided.")
        min_image_count = int(pattern_rule.get("min_count") or 0)
        if min_image_count and len(images) < min_image_count:
            errors.append(
                f"Slide {index} layout expects at least {min_image_count} images; found {len(images)}."
            )
        if media_required and bool(pattern_rule.get("media_warn_without_image")) and not images:
            warnings.append(f"Slide {index} uses an image-led pattern but has no image/images; verify the abstract fallback is intentional.")
        for image_index, image in enumerate(images, start=1):
            unsupported_fields = sorted(field for field in image if field in UNSUPPORTED_IMAGE_FIELDS)
            for field in unsupported_fields:
                errors.append(
                    f"Slide {index} image {image_index} uses unsupported field '{field}'. Use a workspace-relative image.path."
                )
            image_path = _text(image.get("path") or image.get("src"))
            if not image_path:
                errors.append(f"Slide {index} image {image_index} is missing path/src.")
            elif not _is_relative_workspace_path(image_path):
                errors.append(f"Slide {index} image {image_index} path must be workspace-relative: {image_path}")
            if not _text(image.get("source")):
                warnings.append(f"Slide {index} image {image_index} is missing source provenance.")

        claim = _text(raw_slide.get("claim"))
        proof = _text(raw_slide.get("proof_object"))
        support = _text(raw_slide.get("support"))
        if not is_appendix and not claim:
            errors.append(f"Slide {index} is missing claim.")
        if not is_appendix and claim and TOPIC_LIKE_RE.fullmatch(claim):
            warnings.append(f"Slide {index} claim looks topic-like: '{claim}'.")
        if not is_appendix and claim and len(claim) < 8:
            warnings.append(f"Slide {index} claim is very short; verify it is a conclusion.")
        if not proof:
            errors.append(f"Slide {index} is missing proof_object.")
        if not support:
            warnings.append(f"Slide {index} is missing support note.")
        if primary_profile == "finance-ir" and not is_appendix and not raw_slide.get("sources"):
            errors.append(f"Slide {index} uses finance-ir profile but has no sources.")

    repeated_runs: list[tuple[int, str]] = []
    for index in range(2, len(layout_families)):
        if layout_families[index] == layout_families[index - 1] == layout_families[index - 2]:
            repeated_runs.append((index - 1, layout_families[index]))
    for start_index, family in repeated_runs:
        errors.append(
            f"Slides {start_index}-{start_index + 2} repeat layout_family '{family}'."
        )

    unique_families = sorted(set(layout_families))
    metrics["layout_family_count"] = len(unique_families)
    metrics["layout_families"] = unique_families
    metrics["media_required"] = media_required
    metrics["image_slide_count"] = image_slide_count
    metrics["expected_image_slide_count"] = len(expected_image_slide_numbers)
    metrics["expected_image_slides"] = expected_image_slide_numbers
    metrics["non_appendix_count"] = non_appendix_count
    metrics["task_mode"] = task_mode
    metrics["primary_profile"] = primary_profile
    metrics["secondary_gates"] = secondary_gates
    metrics["max_spec_text_chars_per_slide"] = max(spec_slide_chars) if spec_slide_chars else 0
    metrics["avg_spec_text_chars_per_slide"] = round(sum(spec_slide_chars) / len(spec_slide_chars), 1) if spec_slide_chars else 0
    if primary_profile == "consumer-retail" and not media_required:
        errors.append("consumer-retail profile requires media_required=true.")
    if "classroom-sharing" in secondary_gates:
        if len(slides) < 3 or len(slides) > 8:
            errors.append("classroom-sharing gate expects 3-8 slides.")
        if spec_slide_chars and max(spec_slide_chars) > 260:
            warnings.append("classroom-sharing planned copy is dense; verify final rendered slide text stays concise.")
        if media_required is False:
            errors.append("classroom-sharing gate requires media_required=true.")
    if media_required:
        min_image_ratio = _number_from_mapping(constraints, "min_image_slide_ratio", 0.5)
        min_image_ratio = max(0.3, min(0.8, min_image_ratio))
        required_image_slides = max(1, int((non_appendix_count * min_image_ratio) + 0.999))
        if image_slide_count < required_image_slides:
            errors.append(
                f"media_required=true needs images on at least {required_image_slides} non-appendix slides; found {image_slide_count}."
            )
    if len(slides) >= 8 and len(unique_families) < 4:
        warnings.append("Deck has 8+ slides but fewer than 4 layout families.")
    if len(slides) >= 10 and len(unique_families) < 5:
        warnings.append("Deck has 10+ slides; aim for at least 5 layout families.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
    }


def validate_reference_constraints(
    spec: dict[str, object],
    pptx_report: dict[str, object],
) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, object] = {}
    constraints = spec.get("reference_constraints")
    if not isinstance(constraints, dict):
        constraints = {}

    pptx_metrics = pptx_report.get("metrics", {}) if isinstance(pptx_report.get("metrics"), dict) else {}
    slides = pptx_metrics.get("slides", [])
    slide_count = int(pptx_metrics.get("slide_count") or 0)
    media_count = int(pptx_metrics.get("media_count") or 0)
    hybrid_background_count = int(pptx_metrics.get("hybrid_background_count") or 0)
    slide_rows = [slide for slide in slides if isinstance(slide, dict)]
    text_counts = [int(slide.get("text_chars") or 0) for slide in slide_rows]
    has_content_picture_metrics = any("content_pictures" in slide for slide in slide_rows)

    def picture_count(slide: dict[str, object]) -> int:
        if has_content_picture_metrics:
            return int(slide.get("content_pictures") or 0) + int(slide.get("visual_content_images") or 0)
        return int(slide.get("pictures") or 0)

    def picture_area(slide: dict[str, object]) -> float:
        if has_content_picture_metrics:
            return float(slide.get("content_picture_area_ratio") or 0) + float(slide.get("visual_content_image_area_ratio") or 0)
        return float(slide.get("picture_area_ratio") or 0)

    def max_picture_area(slide: dict[str, object]) -> float:
        if has_content_picture_metrics:
            return max(
                float(slide.get("max_content_picture_area_ratio") or 0),
                float(slide.get("visual_max_content_image_area_ratio") or 0),
            )
        return float(slide.get("max_picture_area_ratio") or 0)

    picture_counts = [picture_count(slide) for slide in slide_rows]
    picture_area_by_slide = {
        int(slide.get("slide") or 0): picture_area(slide)
        for slide in slide_rows
    }
    max_picture_area_by_slide = {
        int(slide.get("slide") or 0): max_picture_area(slide)
        for slide in slide_rows
    }
    picture_count_by_slide = {
        int(slide.get("slide") or 0): picture_count(slide)
        for slide in slide_rows
    }
    image_slide_count = sum(1 for count in picture_counts if count > 0)
    effective_image_slide_count = sum(
        1 for value in max_picture_area_by_slide.values() if value >= 0.10
    )
    picture_instances = sum(picture_counts)
    image_slide_ratio = round(image_slide_count / slide_count, 3) if slide_count else 0
    effective_image_slide_ratio = round(effective_image_slide_count / slide_count, 3) if slide_count else 0
    # In hybrid decks, each slide carries a full-slide raster background. That
    # background is useful for visual fidelity but must not satisfy media QA.
    media_per_slide = round(
        (picture_instances if hybrid_background_count else media_count) / slide_count,
        3,
    ) if slide_count else 0
    raw_media_per_slide = round(media_count / slide_count, 3) if slide_count else 0
    pictures_per_slide = round(picture_instances / slide_count, 3) if slide_count else 0
    avg_picture_area_ratio = round(
        sum(picture_area_by_slide.values()) / slide_count, 4
    ) if slide_count else 0
    avg_text = round(sum(text_counts) / len(text_counts), 1) if text_counts else 0
    max_text = max(text_counts) if text_counts else 0
    metrics.update(
        {
            "image_slide_ratio": image_slide_ratio,
            "effective_image_slide_ratio": effective_image_slide_ratio,
            "media_per_slide": media_per_slide,
            "raw_media_per_slide": raw_media_per_slide,
            "pictures_per_slide": pictures_per_slide,
            "picture_instances": picture_instances,
            "hybrid_background_count": hybrid_background_count,
            "visual_content_image_count": int(pptx_metrics.get("visual_content_image_count") or 0),
            "content_picture_metrics": has_content_picture_metrics,
            "avg_picture_area_ratio": avg_picture_area_ratio,
            "avg_text_chars_per_slide": avg_text,
            "max_text_chars_per_slide": max_text,
            "naked_url_count": int(pptx_metrics.get("naked_url_count") or 0),
            "naked_url_slides": pptx_metrics.get("naked_url_slides", []),
        }
    )

    naked_url_slides = pptx_metrics.get("naked_url_slides", [])
    if isinstance(naked_url_slides, list) and naked_url_slides:
        errors.append(
            "Final PPTX renders visible URLs on slides "
            f"{', '.join(str(item) for item in naked_url_slides[:8])}; keep URLs in sources/provenance only."
        )

    spec_slides = spec.get("slides") if isinstance(spec.get("slides"), list) else []
    expected_image_slides = [
        index
        for index, slide in enumerate(spec_slides, start=1)
        if isinstance(slide, dict) and _slide_expects_image(slide)
    ]
    missing_expected_images = [
        slide_number
        for slide_number in expected_image_slides
        if picture_count_by_slide.get(slide_number, 0) <= 0
    ]
    insufficient_expected_image_counts: list[dict[str, object]] = []
    for slide_number, slide in enumerate(spec_slides, start=1):
        if not isinstance(slide, dict):
            continue
        min_count = _min_picture_count(slide)
        if min_count <= 1:
            continue
        actual_count = picture_count_by_slide.get(slide_number, 0)
        if actual_count < min_count:
            insufficient_expected_image_counts.append(
                {
                    "slide": slide_number,
                    "picture_count": actual_count,
                    "min_required_pictures": min_count,
                }
            )
    weak_expected_images: list[dict[str, object]] = []
    for slide_number, slide in enumerate(spec_slides, start=1):
        if not isinstance(slide, dict) or slide_number in missing_expected_images:
            continue
        if slide_number not in expected_image_slides:
            continue
        threshold = _min_picture_area_ratio(slide)
        if threshold <= 0:
            continue
        max_area = max_picture_area_by_slide.get(slide_number, 0)
        if max_area < threshold:
            weak_expected_images.append(
                {
                    "slide": slide_number,
                    "max_picture_area_ratio": round(max_area, 4),
                    "min_required_area_ratio": threshold,
                }
            )
    metrics["expected_image_slides"] = expected_image_slides
    metrics["missing_expected_image_slides"] = missing_expected_images
    metrics["insufficient_expected_image_counts"] = insufficient_expected_image_counts
    metrics["weak_expected_image_slides"] = weak_expected_images
    if missing_expected_images:
        errors.append(
            "Slides expected to contain images rendered without pictures: "
            f"{', '.join(str(item) for item in missing_expected_images[:8])}."
        )
    if weak_expected_images:
        formatted = ", ".join(
            f"{item['slide']} ({item['max_picture_area_ratio']} < {item['min_required_area_ratio']})"
            for item in weak_expected_images[:8]
        )
        errors.append(
            "Slides expected to use images have too-small picture frames: "
            f"{formatted}. Increase the image slot, use a more image-led layout, or mark the slide as text-only."
        )
    if insufficient_expected_image_counts:
        formatted = ", ".join(
            f"{item['slide']} ({item['picture_count']} < {item['min_required_pictures']})"
            for item in insufficient_expected_image_counts[:8]
        )
        errors.append(
            "Slides expected to use multiple images rendered too few pictures: "
            f"{formatted}. Use the intended image set or choose a single-image pattern."
        )

    def number_constraint(name: str) -> float | None:
        value = constraints.get(name)
        if isinstance(value, (int, float)):
            return float(value)
        return None

    max_avg = number_constraint("max_avg_text_chars_per_slide")
    if max_avg is not None and avg_text > max_avg:
        errors.append(f"Average text chars per slide {avg_text} exceeds reference constraint {max_avg}.")
    max_slide = number_constraint("max_text_chars_per_slide")
    if max_slide is not None and max_text > max_slide:
        errors.append(f"Max text chars per slide {max_text} exceeds reference constraint {max_slide}.")
    min_image_ratio = number_constraint("min_image_slide_ratio")
    if min_image_ratio is not None and image_slide_ratio < min_image_ratio:
        errors.append(f"Image slide ratio {image_slide_ratio} is below reference constraint {min_image_ratio}.")
    min_media_per_slide = number_constraint("min_media_per_slide")
    if min_media_per_slide is not None and media_per_slide < min_media_per_slide:
        errors.append(f"Media per slide {media_per_slide} is below reference constraint {min_media_per_slide}.")
    min_effective_image_ratio = number_constraint("min_effective_image_slide_ratio")
    if min_effective_image_ratio is not None and effective_image_slide_ratio < min_effective_image_ratio:
        errors.append(
            f"Effective image slide ratio {effective_image_slide_ratio} is below reference constraint {min_effective_image_ratio}."
        )

    primary_profile = _text(spec.get("primary_profile"))
    media_required = bool(spec.get("media_required"))
    secondary_gates = spec.get("secondary_gates") if isinstance(spec.get("secondary_gates"), list) else []
    if media_required:
        min_required_image_ratio = _number_from_mapping(constraints, "min_image_slide_ratio", 0.5)
        min_required_image_ratio = max(0.3, min(0.8, min_required_image_ratio))
        min_required_effective_ratio = _number_from_mapping(constraints, "min_effective_image_slide_ratio", 0.5)
        min_required_effective_ratio = max(0.3, min(0.8, min_required_effective_ratio))
        if image_slide_ratio < min_required_image_ratio:
            errors.append(
                f"media_required=true output needs images on at least {min_required_image_ratio:.0%} of slides; found {image_slide_ratio}."
            )
        if effective_image_slide_ratio < min_required_effective_ratio:
            errors.append(
                f"media_required=true output needs effective images on at least {min_required_effective_ratio:.0%} of slides; found {effective_image_slide_ratio}."
            )
        if max_text > 360:
            errors.append(f"media_required=true output has a report-like slide with {max_text} text chars; split or shorten it.")
        elif max_text > 240:
            warnings.append(f"media_required=true output has a dense slide with {max_text} text chars; review readability.")
        if avg_text > 180:
            warnings.append(f"media_required=true output averages {avg_text} text chars per slide; review whether it still feels like slides.")
    if primary_profile == "consumer-retail":
        if image_slide_ratio < 0.6:
            errors.append("consumer-retail output needs images on at least 60% of slides.")
        if media_per_slide < 0.5:
            errors.append("consumer-retail output media density is too low.")
    if "classroom-sharing" in secondary_gates:
        if slide_count and not 3 <= slide_count <= 8:
            errors.append("classroom-sharing output should have 3-8 slides.")
        if max_text > 180:
            errors.append(f"classroom-sharing output is too text-heavy; max slide text chars is {max_text}.")
        elif max_text > 120:
            warnings.append(f"classroom-sharing output has a dense slide with {max_text} text chars; review readability.")
        if media_required and effective_image_slide_ratio < 0.5:
            errors.append("classroom-sharing output needs effective images on at least 50% of slides when media_required=true.")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
    }


def markdown_report(
    spec_path: Path,
    pptx_path: Path,
    spec_report: dict[str, object],
    pptx_report: dict[str, object],
    reference_report: dict[str, object] | None = None,
) -> str:
    reference_report = reference_report or {"errors": [], "warnings": [], "metrics": {}}
    errors = list(spec_report.get("errors", [])) + list(pptx_report.get("errors", [])) + list(reference_report.get("errors", []))
    warnings = list(spec_report.get("warnings", [])) + list(pptx_report.get("warnings", [])) + list(reference_report.get("warnings", []))
    status = "PASS" if not errors else "FAIL"
    lines = [
        f"# PPT QA Report: {status}",
        "",
        f"- Spec: `{spec_path}`",
        f"- PPTX: `{pptx_path}`",
        f"- Spec QA: {'PASS' if spec_report.get('ok') else 'FAIL'}",
        f"- PPTX structural QA: {'PASS' if pptx_report.get('ok') else 'FAIL'}",
        f"- Profile/reference QA: {'PASS' if reference_report.get('ok', True) else 'FAIL'}",
        "",
        "## Metrics",
        "",
        f"- Spec slides: {spec_report.get('metrics', {}).get('slide_count', 'n/a')}",
        f"- PPTX slides: {pptx_report.get('metrics', {}).get('slide_count', 'n/a')}",
        f"- Layout families: {', '.join(spec_report.get('metrics', {}).get('layout_families', [])) or 'n/a'}",
        f"- Package bytes: {pptx_report.get('metrics', {}).get('package_bytes', 'n/a')}",
        f"- Image slide ratio: {reference_report.get('metrics', {}).get('image_slide_ratio', 'n/a')}",
        f"- Effective image slide ratio: {reference_report.get('metrics', {}).get('effective_image_slide_ratio', 'n/a')}",
        f"- Media per slide: {reference_report.get('metrics', {}).get('media_per_slide', 'n/a')}",
        f"- Raw media per slide: {reference_report.get('metrics', {}).get('raw_media_per_slide', 'n/a')}",
        f"- Pictures per slide: {reference_report.get('metrics', {}).get('pictures_per_slide', 'n/a')}",
        f"- Hybrid background pictures: {reference_report.get('metrics', {}).get('hybrid_background_count', 'n/a')}",
        f"- Avg picture area ratio: {reference_report.get('metrics', {}).get('avg_picture_area_ratio', 'n/a')}",
        f"- Avg text chars / slide: {reference_report.get('metrics', {}).get('avg_text_chars_per_slide', 'n/a')}",
        f"- Max text chars / slide: {reference_report.get('metrics', {}).get('max_text_chars_per_slide', 'n/a')}",
        f"- Naked URL slides: {reference_report.get('metrics', {}).get('naked_url_slides', [])}",
        f"- Missing expected image slides: {reference_report.get('metrics', {}).get('missing_expected_image_slides', [])}",
        f"- Insufficient expected image counts: {reference_report.get('metrics', {}).get('insufficient_expected_image_counts', [])}",
        f"- Weak expected image slides: {reference_report.get('metrics', {}).get('weak_expected_image_slides', [])}",
        "",
        "## Errors",
        "",
    ]
    lines.extend([f"- {error}" for error in errors] or ["- None"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] or ["- None"])
    lines.extend(
        [
            "",
            "## Next Steps",
            "",
            "- If status is FAIL, fix `deck-spec.json` or the generated deck and rerun QA.",
            "- If render QA has not been run, render slides and review the contact sheet before final delivery.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deck-spec and PPTX structural QA.")
    parser.add_argument("--spec", required=True, help="Path to deck-spec.json.")
    parser.add_argument("--pptx", required=True, help="Path to generated PPTX.")
    parser.add_argument("--out", required=True, help="Markdown QA report path.")
    parser.add_argument("--json-out", default=None, help="Optional JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec_path = Path(args.spec).resolve()
    pptx_path = Path(args.pptx).resolve()
    out_path = Path(args.out).resolve()
    spec = load_spec(spec_path)
    spec_report = validate_spec(spec)
    expected = spec_report.get("metrics", {}).get("slide_count") if isinstance(spec_report.get("metrics"), dict) else None
    pptx_report = inspect_pptx(pptx_path, expected_slides=expected if isinstance(expected, int) else None)
    spec_metrics = spec_report.get("metrics", {}) if isinstance(spec_report.get("metrics"), dict) else {}
    pptx_metrics = pptx_report.get("metrics", {}) if isinstance(pptx_report.get("metrics"), dict) else {}
    if spec_metrics.get("media_required") and int(pptx_metrics.get("media_count") or 0) == 0:
        pptx_report.setdefault("errors", []).append("media_required=true but PPTX package contains zero media files.")
        pptx_report["ok"] = False
    reference_report = validate_reference_constraints(spec, pptx_report)
    combined = {
      "ok": bool(spec_report.get("ok")) and bool(pptx_report.get("ok")) and bool(reference_report.get("ok")),
      "spec": str(spec_path),
      "pptx": str(pptx_path),
      "spec_report": spec_report,
      "pptx_report": pptx_report,
      "reference_report": reference_report,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown_report(spec_path, pptx_path, spec_report, pptx_report, reference_report), encoding="utf-8")
    if args.json_out:
        json_path = Path(args.json_out).resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(combined, ensure_ascii=False, indent=2))
    return 0 if combined["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
