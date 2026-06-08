import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "score_deck.py"


def load_module():
    spec = importlib.util.spec_from_file_location("score_deck", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def valid_spec():
    return {
        "title": "Operating Plan",
        "audience": "Leadership",
        "task_mode": "create",
        "primary_profile": "strategy-leadership",
        "theme": {"colors": {"bg": "0A1128", "ink": "FFFFFF"}},
        "slides": [
            {
                "number": 1,
                "type": "cover",
                "layout": "cover-process",
                "layout_family": "cover-photo",
                "claim": "The plan shifts resources toward the highest-confidence bets.",
                "proof_object": "three-step process",
                "support": "Based on source notes.",
            },
            {
                "number": 2,
                "type": "thesis",
                "layout": "big-claim",
                "layout_family": "thesis",
                "claim": "The operating model needs fewer handoffs before automation.",
                "proof_object": "driver diagnosis",
                "support": "Each driver maps to a known execution bottleneck.",
            },
            {
                "number": 3,
                "type": "flow",
                "layout": "horizontal-flow",
                "layout_family": "timeline-grid",
                "claim": "The next two quarters should move from cleanup to repeatability.",
                "proof_object": "phased execution timeline",
                "support": "The sequence follows dependency order.",
            },
            {
                "number": 4,
                "type": "metrics",
                "layout": "metric-rail",
                "layout_family": "metric-rail",
                "claim": "Success depends on adoption quality, not only activity volume.",
                "proof_object": "metric rail",
                "support": "The metrics separate usage, conversion, and retention.",
            },
        ],
    }


def valid_qa():
    return {
        "ok": True,
        "spec_report": {"ok": True, "errors": [], "warnings": [], "metrics": {}},
        "pptx_report": {
            "ok": True,
            "errors": [],
            "warnings": [],
            "metrics": {
                "slide_count": 4,
                "media_count": 0,
                "slides": [
                    {"slide": 1, "text_chars": 80, "pictures": 0, "max_picture_area_ratio": 0},
                    {"slide": 2, "text_chars": 95, "pictures": 0, "max_picture_area_ratio": 0},
                    {"slide": 3, "text_chars": 90, "pictures": 0, "max_picture_area_ratio": 0},
                    {"slide": 4, "text_chars": 105, "pictures": 0, "max_picture_area_ratio": 0},
                ],
            },
        },
        "reference_report": {
            "ok": True,
            "errors": [],
            "warnings": [],
            "metrics": {
                "image_slide_ratio": 0,
                "effective_image_slide_ratio": 0,
                "avg_text_chars_per_slide": 92.5,
                "max_text_chars_per_slide": 105,
                "naked_url_count": 0,
                "weak_expected_image_slides": [],
                "missing_expected_image_slides": [],
            },
        },
    }


def test_score_deck_passes_clean_structured_deck():
    module = load_module()

    report = module.score_deck(valid_spec(), valid_qa())

    assert report["ok"] is True
    assert report["total_score"] >= report["threshold"]
    assert min(report["dimension_scores"].values()) >= 4
    assert report["weak_slides"] == []


def test_score_deck_blocks_weak_slides_and_underlying_qa_errors():
    module = load_module()
    spec = valid_spec()
    spec["media_required"] = True
    spec["slides"][1]["image"] = {"path": "assets/small.png", "source": "fixture"}
    qa = valid_qa()
    qa["reference_report"]["ok"] = False
    qa["reference_report"]["errors"] = ["Slides expected to use images have too-small picture frames: 2."]
    qa["reference_report"]["metrics"]["image_slide_ratio"] = 0.25
    qa["reference_report"]["metrics"]["effective_image_slide_ratio"] = 0
    qa["reference_report"]["metrics"]["max_text_chars_per_slide"] = 270
    qa["reference_report"]["metrics"]["avg_text_chars_per_slide"] = 190
    qa["reference_report"]["metrics"]["weak_expected_image_slides"] = [
        {"slide": 2, "max_picture_area_ratio": 0.05, "min_required_area_ratio": 0.1}
    ]
    qa["pptx_report"]["metrics"]["slides"][1]["text_chars"] = 270

    report = module.score_deck(spec, qa)

    assert report["ok"] is False
    assert "underlying QA has errors" in report["blocking_reasons"]
    assert any(item["slide"] == 2 for item in report["weak_slides"])
    assert report["dimension_scores"]["visual_proof"] < 5


def test_score_deck_cli_writes_markdown_and_json(tmp_path):
    module = load_module()
    spec_path = tmp_path / "deck-spec.json"
    qa_path = tmp_path / "qa-report.json"
    out = tmp_path / "scorecard.md"
    json_out = tmp_path / "scorecard.json"
    spec_path.write_text(json.dumps(valid_spec()), encoding="utf-8")
    qa_path.write_text(json.dumps(valid_qa()), encoding="utf-8")

    code = module.main([
        "--spec",
        str(spec_path),
        "--qa-json",
        str(qa_path),
        "--out",
        str(out),
        "--json-out",
        str(json_out),
    ])

    assert code == 0
    assert "Contact Sheet Scorecard: PASS" in out.read_text(encoding="utf-8")
    assert json.loads(json_out.read_text(encoding="utf-8"))["ok"] is True
