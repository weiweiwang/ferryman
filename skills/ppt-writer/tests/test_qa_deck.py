import importlib.util
import zipfile
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "qa_deck.py"


def load_module():
    spec = importlib.util.spec_from_file_location("qa_deck", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_minimal_pptx(path: Path, *, slides: int = 2) -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "[Content_Types].xml",
            "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>",
        )
        package.writestr(
            "ppt/presentation.xml",
            "<p:presentation xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"/>",
        )
        for index in range(1, slides + 1):
            package.writestr(
                f"ppt/slides/slide{index}.xml",
                f"<p:sld xmlns:p=\"http://schemas.openxmlformats.org/presentationml/2006/main\"><p:cSld>Slide {index}</p:cSld></p:sld>",
            )


def valid_spec():
    return {
        "title": "AI Sales Agent Plan",
        "audience": "Management",
        "task_mode": "create",
        "primary_profile": "product-platform",
        "secondary_gates": [],
        "slides": [
            {
                "number": 1,
                "type": "cover",
                "layout": "cover-process",
                "layout_family": "cover",
                "claim": "Sales expertise should be structured before automation.",
                "proof_object": "three-stage process",
                "support": "Based on user-provided project notes.",
            },
            {
                "number": 2,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "The lead-cleaning layer turns messy conversations into sales-ready handoffs.",
                "proof_object": "three-driver diagnosis",
                "support": "Each driver maps to one observable operating problem.",
            },
        ],
    }


def test_validate_spec_passes_for_complete_spec():
    module = load_module()

    report = module.validate_spec(valid_spec())

    assert report["ok"] is True
    assert report["errors"] == []
    assert report["metrics"]["slide_count"] == 2


def test_validate_spec_blocks_three_repeated_layout_families():
    module = load_module()
    spec = valid_spec()
    spec["slides"].append(
        {
            "number": 3,
            "type": "generic",
            "layout": "big-claim",
            "layout_family": "thesis",
            "claim": "Repeated family should be caught.",
            "proof_object": "QA rule",
            "support": "Test fixture.",
        }
    )
    spec["slides"][0]["layout_family"] = "thesis"

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("repeat layout_family" in error for error in report["errors"])


def test_validate_spec_blocks_media_required_without_enough_images():
    module = load_module()
    spec = valid_spec()
    spec["media_required"] = True

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("media_required=true needs images" in error for error in report["errors"])


def test_validate_spec_blocks_requires_image_without_image_spec():
    module = load_module()
    spec = valid_spec()
    spec["slides"][0]["requires_image"] = True

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("sets requires_image" in error for error in report["errors"])


def test_validate_spec_blocks_unsupported_image_url_contract():
    module = load_module()
    spec = valid_spec()
    spec["download_images"] = True
    spec["image_urls"] = {"cover": "https://example.test/cover.jpg"}
    spec["slides"][0]["image_idx"] = 1

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("unsupported field 'download_images'" in error for error in report["errors"])
    assert any("unsupported field 'image_urls'" in error for error in report["errors"])
    assert any("unsupported field 'image_idx'" in error for error in report["errors"])


def test_validate_spec_blocks_bad_image_object_paths():
    module = load_module()
    spec = valid_spec()
    spec["slides"][0]["image"] = {
        "url": "https://example.test/cover.jpg",
        "path": "https://example.test/cover.jpg",
        "source": "example",
    }
    spec["slides"][1]["images"] = [
        {"path": "/tmp/outside.png", "source": "absolute"},
        {"path": "../outside.png", "source": "escape"},
    ]

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("unsupported field 'url'" in error for error in report["errors"])
    assert any("path must be workspace-relative: https://example.test/cover.jpg" in error for error in report["errors"])
    assert any("path must be workspace-relative: /tmp/outside.png" in error for error in report["errors"])
    assert any("path must be workspace-relative: ../outside.png" in error for error in report["errors"])


def test_validate_spec_blocks_visible_urls_but_allows_source_urls():
    module = load_module()
    spec = valid_spec()
    spec["slides"][0]["support"] = "Visible source https://example.test/article"
    spec["slides"][1]["sources"] = ["https://example.test/source"]

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("contains a visible URL" in error for error in report["errors"])
    assert not any("Slide 2 contains a visible URL" in error for error in report["errors"])


def test_validate_spec_requires_profile_router_fields():
    module = load_module()
    spec = valid_spec()
    spec.pop("task_mode")
    spec.pop("primary_profile")

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert "Spec is missing task_mode." in report["errors"]
    assert "Spec is missing primary_profile." in report["errors"]


def test_validate_reference_constraints_blocks_text_heavy_output():
    module = load_module()
    spec = valid_spec()
    spec["reference_constraints"] = {
        "max_avg_text_chars_per_slide": 50,
        "max_text_chars_per_slide": 80,
        "min_image_slide_ratio": 0.8,
        "min_media_per_slide": 1,
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 2,
            "media_count": 0,
            "slides": [
                {"slide": 1, "text_chars": 120, "pictures": 0},
                {"slide": 2, "text_chars": 90, "pictures": 0},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert any("Average text chars" in error for error in report["errors"])
    assert any("Image slide ratio" in error for error in report["errors"])
    assert report["metrics"]["pictures_per_slide"] == 0


def test_media_required_allows_some_non_image_slides_when_overall_coverage_is_good():
    module = load_module()
    spec = {
        **valid_spec(),
        "media_required": True,
        "slides": [
            {
                "number": 1,
                "type": "cover",
                "layout": "photo-caption",
                "layout_family": "photo-caption",
                "claim": "Opening image establishes the event.",
                "proof_object": "photo",
                "support": "Fixture.",
                "image": {"path": "assets/one.png", "source": "fixture"},
            },
            {
                "number": 2,
                "type": "generic",
                "layout": "image-grid",
                "layout_family": "topic-grid",
                "claim": "The visit had several visible moments.",
                "proof_object": "image grid",
                "support": "Fixture.",
                "images": [{"path": "assets/two.png", "source": "fixture"}],
            },
            {
                "number": 3,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "One analysis page can stay text-only.",
                "proof_object": "summary claim",
                "support": "Fixture.",
            },
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 3,
            "media_count": 2,
            "naked_url_slides": [],
            "slides": [
                {"slide": 1, "text_chars": 40, "pictures": 1},
                {"slide": 2, "text_chars": 50, "pictures": 1},
                {"slide": 3, "text_chars": 80, "pictures": 0},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is True
    assert report["metrics"]["image_slide_ratio"] == 0.667
    assert report["metrics"]["missing_expected_image_slides"] == []


def test_output_qa_blocks_naked_urls_and_missing_expected_images():
    module = load_module()
    spec = {
        **valid_spec(),
        "media_required": True,
        "slides": [
            {
                "number": 1,
                "type": "generic",
                "layout": "photo-caption",
                "layout_family": "photo-caption",
                "claim": "Photo slide needs a real image.",
                "proof_object": "photo",
                "support": "Fixture.",
                "image": {"path": "assets/one.png", "source": "fixture"},
            },
            {
                "number": 2,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "Analysis can be text-only.",
                "proof_object": "summary",
                "support": "Fixture.",
            },
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 2,
            "media_count": 0,
            "naked_url_slides": [1],
            "naked_url_count": 1,
            "slides": [
                {"slide": 1, "text_chars": 80, "pictures": 0},
                {"slide": 2, "text_chars": 80, "pictures": 0},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert any("visible URLs" in error for error in report["errors"])
    assert any("rendered without pictures: 1" in error for error in report["errors"])


def test_media_required_blocks_extreme_report_like_slide_text():
    module = load_module()
    spec = {**valid_spec(), "media_required": True}
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 2,
            "media_count": 2,
            "naked_url_slides": [],
            "slides": [
                {"slide": 1, "text_chars": 380, "pictures": 1},
                {"slide": 2, "text_chars": 80, "pictures": 1},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert any("report-like slide" in error for error in report["errors"])


def test_qa_combines_spec_and_pptx(tmp_path):
    module = load_module()
    spec = valid_spec()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=2)

    spec_report = module.validate_spec(spec)
    pptx_report = module.inspect_pptx(pptx, expected_slides=2)

    assert spec_report["ok"] is True
    assert pptx_report["ok"] is True
