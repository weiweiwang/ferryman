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
        "min_effective_image_slide_ratio": 0.8,
        "min_media_per_slide": 1,
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 2,
            "media_count": 0,
            "slides": [
                {"slide": 1, "text_chars": 120, "pictures": 0, "max_picture_area_ratio": 0},
                {"slide": 2, "text_chars": 90, "pictures": 0, "max_picture_area_ratio": 0},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert any("Average text chars" in error for error in report["errors"])
    assert any("Image slide ratio" in error for error in report["errors"])
    assert any("Effective image slide ratio" in error for error in report["errors"])
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
                {"slide": 1, "text_chars": 40, "pictures": 1, "picture_area_ratio": 0.45, "max_picture_area_ratio": 0.45},
                {"slide": 2, "text_chars": 50, "pictures": 1, "picture_area_ratio": 0.18, "max_picture_area_ratio": 0.18},
                {"slide": 3, "text_chars": 80, "pictures": 0, "picture_area_ratio": 0, "max_picture_area_ratio": 0},
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
                {"slide": 1, "text_chars": 80, "pictures": 0, "max_picture_area_ratio": 0},
                {"slide": 2, "text_chars": 80, "pictures": 0, "max_picture_area_ratio": 0},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert any("visible URLs" in error for error in report["errors"])
    assert any("rendered without pictures: 1" in error for error in report["errors"])


def test_output_qa_does_not_count_hybrid_background_as_slide_media():
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
                "claim": "A photo-led cover needs a real content image.",
                "proof_object": "cover photo",
                "support": "Fixture.",
                "image": {"path": "assets/cover.png", "source": "fixture"},
            },
            {
                "number": 2,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "Text-only analysis remains allowed.",
                "proof_object": "summary",
                "support": "Fixture.",
            },
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 2,
            "media_count": 2,
            "hybrid_background_count": 2,
            "naked_url_slides": [],
            "slides": [
                {
                    "slide": 1,
                    "text_chars": 80,
                    "pictures": 1,
                    "content_pictures": 0,
                    "hybrid_background_pictures": 1,
                    "picture_area_ratio": 1.0,
                    "max_picture_area_ratio": 1.0,
                    "content_picture_area_ratio": 0,
                    "max_content_picture_area_ratio": 0,
                },
                {
                    "slide": 2,
                    "text_chars": 80,
                    "pictures": 1,
                    "content_pictures": 0,
                    "hybrid_background_pictures": 1,
                    "picture_area_ratio": 1.0,
                    "max_picture_area_ratio": 1.0,
                    "content_picture_area_ratio": 0,
                    "max_content_picture_area_ratio": 0,
                },
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert report["metrics"]["media_per_slide"] == 0
    assert report["metrics"]["raw_media_per_slide"] == 1
    assert report["metrics"]["pictures_per_slide"] == 0
    assert report["metrics"]["hybrid_background_count"] == 2
    assert any("rendered without pictures: 1" in error for error in report["errors"])


def test_output_qa_counts_visual_background_image_metadata():
    module = load_module()
    spec = {
        **valid_spec(),
        "media_required": True,
        "slides": [
            {
                "number": 1,
                "type": "cover",
                "layout": "cover-photo",
                "layout_family": "cover-photo",
                "claim": "A visual-first cover can satisfy image proof through the rendered HTML screenshot.",
                "proof_object": "cover photo",
                "support": "Fixture.",
                "image": {"path": "assets/cover.png", "source": "fixture"},
            }
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 1,
            "media_count": 1,
            "hybrid_background_count": 1,
            "visual_content_image_count": 1,
            "naked_url_slides": [],
            "slides": [
                {
                    "slide": 1,
                    "text_chars": 80,
                    "pictures": 1,
                    "content_pictures": 0,
                    "hybrid_background_pictures": 1,
                    "visual_content_images": 1,
                    "picture_area_ratio": 1.0,
                    "max_picture_area_ratio": 1.0,
                    "content_picture_area_ratio": 0,
                    "max_content_picture_area_ratio": 0,
                    "visual_content_image_area_ratio": 0.4609,
                    "visual_max_content_image_area_ratio": 0.4609,
                }
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is True
    assert report["metrics"]["media_per_slide"] == 1
    assert report["metrics"]["pictures_per_slide"] == 1
    assert report["metrics"]["avg_picture_area_ratio"] == 0.4609
    assert report["metrics"]["weak_expected_image_slides"] == []


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
                {"slide": 1, "text_chars": 380, "pictures": 1, "picture_area_ratio": 0.45, "max_picture_area_ratio": 0.45},
                {"slide": 2, "text_chars": 80, "pictures": 1, "picture_area_ratio": 0.20, "max_picture_area_ratio": 0.20},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert any("report-like slide" in error for error in report["errors"])


def test_output_qa_blocks_tiny_expected_image_frames():
    module = load_module()
    spec = {
        **valid_spec(),
        "slides": [
            {
                "number": 1,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "A supporting image should be large enough to read.",
                "proof_object": "evidence photo",
                "support": "Fixture.",
                "image": {"path": "assets/evidence.png", "source": "fixture"},
            },
            {
                "number": 2,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "Text-only analysis remains allowed.",
                "proof_object": "summary",
                "support": "Fixture.",
            },
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 2,
            "media_count": 1,
            "naked_url_slides": [],
            "slides": [
                {"slide": 1, "text_chars": 80, "pictures": 1, "picture_area_ratio": 0.075, "max_picture_area_ratio": 0.075},
                {"slide": 2, "text_chars": 80, "pictures": 0, "picture_area_ratio": 0, "max_picture_area_ratio": 0},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert any("too-small picture frames" in error for error in report["errors"])
    assert report["metrics"]["weak_expected_image_slides"][0]["slide"] == 1


def test_validate_spec_blocks_science_patterns_that_require_images():
    module = load_module()
    spec = {
        **valid_spec(),
        "media_required": True,
        "theme": {"template": "science-storybook"},
        "slides": [
            {
                "number": 1,
                "type": "evidence",
                "layout": "evidence-triptych",
                "layout_family": "evidence-triptych",
                "claim": "关键证据需要多张图像对照。",
                "proof_object": "evidence triptych",
                "support": "Fixture.",
            },
            {
                "number": 2,
                "type": "impact",
                "layout": "impact-reset",
                "layout_family": "impact-reset",
                "claim": "大灭绝之后生命重新打开舞台。",
                "proof_object": "impact visual",
                "support": "Fixture.",
            },
        ],
    }

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("layout expects image/images" in error for error in report["errors"])


def test_validate_spec_blocks_science_triptych_with_too_few_planned_images():
    module = load_module()
    spec = {
        **valid_spec(),
        "slides": [
            {
                "number": 1,
                "type": "evidence",
                "layout": "evidence-triptych",
                "layout_family": "evidence-triptych",
                "claim": "三张证据图共同说明生命重启。",
                "proof_object": "evidence triptych",
                "support": "Fixture.",
                "images": [{"path": "assets/a.png", "source": "fixture"}],
            }
        ],
    }

    report = module.validate_spec(spec)

    assert report["ok"] is False
    assert any("expects at least 3 images" in error for error in report["errors"])


def test_output_qa_blocks_science_impact_when_image_area_is_too_small():
    module = load_module()
    spec = {
        **valid_spec(),
        "slides": [
            {
                "number": 1,
                "type": "impact",
                "layout": "impact-reset",
                "layout_family": "impact-reset",
                "claim": "灾难之后，生命重新打开舞台。",
                "proof_object": "impact visual",
                "support": "Fixture.",
                "image": {"path": "assets/impact.png", "source": "fixture"},
            }
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 1,
            "media_count": 1,
            "naked_url_slides": [],
            "slides": [
                {"slide": 1, "text_chars": 80, "pictures": 1, "picture_area_ratio": 0.12, "max_picture_area_ratio": 0.12},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert report["metrics"]["weak_expected_image_slides"][0]["min_required_area_ratio"] == 0.30


def test_output_qa_blocks_science_triptych_with_too_few_images():
    module = load_module()
    spec = {
        **valid_spec(),
        "slides": [
            {
                "number": 1,
                "type": "evidence",
                "layout": "evidence-triptych",
                "layout_family": "evidence-triptych",
                "claim": "三张证据图共同说明生命重启。",
                "proof_object": "evidence triptych",
                "support": "Fixture.",
                "images": [
                    {"path": "assets/a.png", "source": "fixture"},
                    {"path": "assets/b.png", "source": "fixture"},
                    {"path": "assets/c.png", "source": "fixture"},
                ],
            }
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 1,
            "media_count": 1,
            "naked_url_slides": [],
            "slides": [
                {"slide": 1, "text_chars": 80, "pictures": 1, "picture_area_ratio": 0.12, "max_picture_area_ratio": 0.12},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is False
    assert report["metrics"]["insufficient_expected_image_counts"][0]["min_required_pictures"] == 3
    assert any("too few pictures" in error for error in report["errors"])


def test_output_qa_allows_text_only_analysis_slide_with_media_required():
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
                "claim": "The first slide uses a large image.",
                "proof_object": "cover photo",
                "support": "Fixture.",
                "image": {"path": "assets/cover.png", "source": "fixture"},
            },
            {
                "number": 2,
                "type": "generic",
                "layout": "image-grid",
                "layout_family": "topic-grid",
                "claim": "The second slide uses a visual grid.",
                "proof_object": "image grid",
                "support": "Fixture.",
                "images": [{"path": "assets/grid.png", "source": "fixture"}],
            },
            {
                "number": 3,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "The final analysis slide can stay text-only.",
                "proof_object": "decision summary",
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
                {"slide": 1, "text_chars": 50, "pictures": 1, "picture_area_ratio": 0.60, "max_picture_area_ratio": 0.60},
                {"slide": 2, "text_chars": 70, "pictures": 1, "picture_area_ratio": 0.16, "max_picture_area_ratio": 0.16},
                {"slide": 3, "text_chars": 95, "pictures": 0, "picture_area_ratio": 0, "max_picture_area_ratio": 0},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is True
    assert report["metrics"]["effective_image_slide_ratio"] == 0.667


def test_output_qa_does_not_require_images_for_text_only_grid_families():
    module = load_module()
    spec = {
        **valid_spec(),
        "media_required": True,
        "reference_constraints": {
            "min_image_slide_ratio": 0.5,
            "min_effective_image_slide_ratio": 0.5,
        },
        "slides": [
            {
                "number": 1,
                "type": "cover",
                "layout": "photo-caption",
                "layout_family": "photo-caption",
                "claim": "The first slide uses a large image.",
                "proof_object": "cover photo",
                "support": "Fixture.",
                "image": {"path": "assets/cover.png", "source": "fixture"},
            },
            {
                "number": 2,
                "type": "timeline",
                "layout": "timeline",
                "layout_family": "timeline-grid",
                "claim": "A timeline page can be text-only.",
                "proof_object": "timeline",
                "support": "Fixture.",
            },
            {
                "number": 3,
                "type": "comparison",
                "layout": "two-column-compare",
                "layout_family": "topic-grid",
                "claim": "A comparison page can be text-only.",
                "proof_object": "two-column comparison",
                "support": "Fixture.",
            },
            {
                "number": 4,
                "type": "takeaway",
                "layout": "classroom-takeaway",
                "layout_family": "takeaway-photo",
                "claim": "The final slide uses a large image.",
                "proof_object": "takeaway photo",
                "support": "Fixture.",
                "image": {"path": "assets/final.png", "source": "fixture"},
            },
        ],
    }
    pptx_report = {
        "ok": True,
        "metrics": {
            "slide_count": 4,
            "media_count": 2,
            "naked_url_slides": [],
            "slides": [
                {"slide": 1, "text_chars": 50, "pictures": 1, "picture_area_ratio": 0.60, "max_picture_area_ratio": 0.60},
                {"slide": 2, "text_chars": 95, "pictures": 0, "picture_area_ratio": 0, "max_picture_area_ratio": 0},
                {"slide": 3, "text_chars": 110, "pictures": 0, "picture_area_ratio": 0, "max_picture_area_ratio": 0},
                {"slide": 4, "text_chars": 55, "pictures": 1, "picture_area_ratio": 0.65, "max_picture_area_ratio": 0.65},
            ],
        },
    }

    report = module.validate_reference_constraints(spec, pptx_report)

    assert report["ok"] is True
    assert report["metrics"]["weak_expected_image_slides"] == []


def test_qa_combines_spec_and_pptx(tmp_path):
    module = load_module()
    spec = valid_spec()
    pptx = tmp_path / "deck.pptx"
    write_minimal_pptx(pptx, slides=2)

    spec_report = module.validate_spec(spec)
    pptx_report = module.inspect_pptx(pptx, expected_slides=2)

    assert spec_report["ok"] is True
    assert pptx_report["ok"] is True
