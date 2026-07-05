from pathlib import Path
import importlib.util
import json
import subprocess
import sys


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_coverage_history.py"
SPEC = importlib.util.spec_from_file_location("build_coverage_history", SCRIPT_PATH)
build_coverage_history = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = build_coverage_history
SPEC.loader.exec_module(build_coverage_history)


def test_builds_history_from_brief_article_and_assets(tmp_path):
    reports = tmp_path / "reports"
    day = reports / "2026-07-05"
    day.mkdir(parents=True)
    (day / "ai-product-scout-pylon-b2b-support-ai.md").write_text(
        """# AI Product Case Brief

- **Product Name**: Pylon
- **URL**: https://www.usepylon.com/

## Featured Case
""",
        encoding="utf-8",
    )
    (day / "ai-product-case-article-pylon-b2b-support-ai.md").write_text(
        "# Pylon把客服入口做成了B2B增长入口\n\n正文。",
        encoding="utf-8",
    )
    (day / "ai-product-case-article-pylon-b2b-support-ai.html").write_text("<html></html>", encoding="utf-8")
    (day / "ai-product-media-pylon-b2b-support-ai.mp4").write_bytes(b"video")

    history = build_coverage_history.build_history(reports)

    assert history["schema"] == "ai-product-scout-history.v1"
    assert history["caseCount"] == 1
    case = history["cases"][0]
    assert case["date"] == "2026-07-05"
    assert case["slug"] == "pylon-b2b-support-ai"
    assert case["productName"] == "Pylon"
    assert case["url"] == "https://usepylon.com"
    assert case["sourceRoot"] == str(reports.resolve())
    assert case["sourceName"] == "current"
    assert case["articleTitle"] == "Pylon把客服入口做成了B2B增长入口"
    assert "media" in case["files"]
    assert "pylon" in history["aliases"]
    assert "usepylon.com" in history["aliases"]
    assert "https://usepylon.com" in history["aliases"]


def test_merges_existing_imported_history_and_enriches_original_files(tmp_path):
    reports = tmp_path / "reports"
    current_day = reports / "2026-07-05"
    current_day.mkdir(parents=True)
    (current_day / "ai-product-scout-pylon.md").write_text(
        "- **Product Name**: Pylon\n- **URL**: https://usepylon.com\n",
        encoding="utf-8",
    )
    (current_day / "ai-product-case-article-pylon.md").write_text("# Pylon案例\n\n正文", encoding="utf-8")

    legacy_root = tmp_path / "legacy-reports"
    legacy_root.mkdir()
    legacy_brief = legacy_root / "ai-product-scout-2026-04-26.md"
    legacy_article = legacy_root / "ai-product-case-article-2026-04-26.md"
    legacy_brief.write_text(
        "| 字段 | 内容 |\n|---|---|\n| **产品名** | **Granola** |\n| **官网** | https://www.granola.ai/ |\n",
        encoding="utf-8",
    )
    legacy_article.write_text("# 公众号案例初稿：Granola\n\n正文", encoding="utf-8")
    output = reports / "ai-product-scout-history.json"
    output.write_text(
        json.dumps(
            {
                "schema": "ai-product-scout-history.v1",
                "reportsRoot": str(reports.resolve()),
                "importedReportsRoots": [str(legacy_root.resolve())],
                "caseCount": 1,
                "cases": [
                    {
                        "date": "",
                        "slug": "2026-04-26",
                        "productName": "",
                        "url": "",
                        "articleTitle": "",
                        "sourceRoot": str(legacy_root.resolve()),
                        "sourceName": "legacy-ferryman-workspace",
                        "files": {"brief": str(legacy_brief), "article": str(legacy_article)},
                    }
                ],
                "aliases": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    current = build_coverage_history.build_history(reports)
    merged = build_coverage_history.merge_existing_history(
        current,
        build_coverage_history.load_existing_history(output),
        reports,
    )

    assert merged["caseCount"] == 2
    assert merged["importedReportsRoots"] == [str(legacy_root.resolve())]
    legacy = next(case for case in merged["cases"] if case["sourceName"] == "legacy-ferryman-workspace")
    assert legacy["productName"] == "Granola"
    assert legacy["url"] == "https://granola.ai"
    assert legacy["articleTitle"] == "公众号案例初稿：Granola"
    assert "granola.ai" in merged["aliases"]
    assert "https://granola.ai" in merged["aliases"]


def test_replace_mode_drops_existing_imported_history(tmp_path):
    reports = tmp_path / "reports"
    day = reports / "2026-07-05"
    day.mkdir(parents=True)
    (day / "ai-product-scout-pylon.md").write_text("- **Product Name**: Pylon\n", encoding="utf-8")
    current = build_coverage_history.build_history(reports)

    merged = build_coverage_history.merge_existing_history(current, None, reports)

    assert merged["caseCount"] == 1
    assert merged["cases"][0]["productName"] == "Pylon"


def test_noop_write_preserves_existing_generated_at_and_bytes(tmp_path):
    reports = tmp_path / "reports"
    day = reports / "2026-07-05"
    day.mkdir(parents=True)
    (day / "ai-product-scout-pylon.md").write_text("- **Product Name**: Pylon\n", encoding="utf-8")
    output = reports / "ai-product-scout-history.json"
    history = build_coverage_history.build_history(reports)
    history["generatedAt"] = "2026-01-01T00:00:00+00:00"
    expected = json.dumps(history, ensure_ascii=False, indent=2) + "\n"
    output.write_text(expected, encoding="utf-8")

    result, changed = build_coverage_history.write_history_if_changed(
        build_coverage_history.build_history(reports),
        output,
    )

    assert changed is False
    assert result["generatedAt"] == "2026-01-01T00:00:00+00:00"
    assert output.read_text(encoding="utf-8") == expected


def test_cli_merges_by_default_and_replace_rebuilds_current_root_only(tmp_path):
    reports = tmp_path / "reports"
    current_day = reports / "2026-07-05"
    current_day.mkdir(parents=True)
    (current_day / "ai-product-scout-pylon.md").write_text(
        "- **Product Name**: Pylon\n- **URL**: https://usepylon.com\n",
        encoding="utf-8",
    )
    (current_day / "ai-product-case-article-pylon.md").write_text("# Pylon案例\n\n正文", encoding="utf-8")

    legacy_root = tmp_path / "legacy-reports"
    legacy_root.mkdir()
    legacy_brief = legacy_root / "ai-product-scout-2026-04-26.md"
    legacy_brief.write_text("| **产品名** | Granola |\n| **官网** | https://www.granola.ai/ |\n", encoding="utf-8")
    output = reports / "ai-product-scout-history.json"
    output.write_text(
        json.dumps(
            {
                "schema": "ai-product-scout-history.v1",
                "generatedAt": "2026-01-01T00:00:00+00:00",
                "reportsRoot": str(reports.resolve()),
                "importedReportsRoots": [str(legacy_root.resolve())],
                "caseCount": 1,
                "cases": [
                    {
                        "date": "",
                        "slug": "2026-04-26",
                        "productName": "",
                        "url": "",
                        "articleTitle": "",
                        "sourceRoot": str(legacy_root.resolve()),
                        "sourceName": "legacy-ferryman-workspace",
                        "files": {"brief": str(legacy_brief)},
                    }
                ],
                "aliases": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    merge_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(reports), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    merged = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(merge_result.stdout)["changed"] is True
    assert merged["caseCount"] == 2
    assert merged["importedReportsRoots"] == [str(legacy_root.resolve())]
    assert "granola.ai" in merged["aliases"]

    stable_bytes = output.read_bytes()
    stable_mtime = output.stat().st_mtime_ns
    noop_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(reports), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(noop_result.stdout)["changed"] is False
    assert output.read_bytes() == stable_bytes
    assert output.stat().st_mtime_ns == stable_mtime

    replace_result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(reports), "--output", str(output), "--replace"],
        check=True,
        capture_output=True,
        text=True,
    )
    replaced = json.loads(output.read_text(encoding="utf-8"))
    assert json.loads(replace_result.stdout)["changed"] is True
    assert replaced["caseCount"] == 1
    assert replaced["importedReportsRoots"] == []
    assert replaced["cases"][0]["sourceName"] == "current"
