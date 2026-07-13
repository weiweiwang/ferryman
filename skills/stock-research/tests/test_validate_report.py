from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_report.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_report_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load report validator from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_report() -> str:
    return """---
ticker: TEST
company:
  zh: 测试公司
  en: Test Company
exchange: NASDAQ
report_date: 2026-07-13
fetched_at: 2026-07-13 00:00 UTC
signal: WATCHLIST
quality_score: 80
summary: 当前价格尚未达到买入门槛。
current_price:
  value: 50
  currency: USD
fair_value:
  conservative: 45
  base: 60
  optimistic: 75
  currency: USD
tags:
  market: [us]
  sector: [technology]
  industry: [saas]
  theme: [ai-cloud]
---

# 测试公司投资质量评估（TEST）

## 核心结论
结论。
## 业务拆解
业务。
## 好公司评分
评分。
## 财务审计
审计。
## 估值
估值。
## 需要跟踪的风险
风险。
## 数据来源
| 用途 | 来源 | 日期 | URL |
|:---|:---|:---|:---|
| 年报 | SEC | 2026-07-13 | https://www.sec.gov/ |

本报告仅作个人研究，不是个性化投资建议。
"""


def english_report() -> str:
    return """---
ticker: TEST
company:
  zh: null
  en: Test Company
exchange: NASDAQ
report_date: 2026-07-13
fetched_at: 2026-07-13 00:00 UTC
signal: WATCHLIST
quality_score: 80
summary: The price remains above the buy threshold.
current_price:
  value: 50
  currency: USD
fair_value:
  conservative: 45
  base: 60
  optimistic: 75
  currency: USD
tags:
  market: [us]
  sector: [technology]
  industry: [saas]
  theme: [ai-cloud]
---

# Test Company Investment Quality Review (TEST)

## Core Conclusion
The price remains above the buy threshold.
## Business Breakdown
The business has recurring revenue.
## Quality Score
The evidence supports the score.
## Financial Audit
Five complete fiscal years were reviewed.
## Valuation
The base value is below the current price.
## Risks To Track
Execution and valuation remain the main risks.
## Data Sources
| Use | Source | Date | URL |
|:---|:---|:---|:---|
| Annual report | SEC | 2026-07-13 | https://www.sec.gov/ |

This report is for research only and is not personalized investment advice.
"""


def valid_evidence_note(language: str = "zh") -> dict:
    module = load_validator()
    source = ["https://www.sec.gov/"]
    checks = {
        check_id: {"class": "required", "state": "verified", "source_urls": source}
        for check_id in module.COMPLETION_CHECK_IDS
    }
    checks.update(
        {
            check_id: {"class": "material", "state": "verified", "source_urls": source}
            for check_id in module.MANAGEMENT_CHECK_IDS | (module.THESIS_CHECK_IDS - {"avoid_failure"})
        }
    )
    checks["avoid_failure"] = {
        "class": "material",
        "state": "not_applicable",
        "rationale": "No quality or value-trap failure was identified.",
    }
    return {
        "version": 1,
        "report_language": language,
        "ticker": "TEST",
        "report_date": "2026-07-13",
        "checks": checks,
        "valuation_anchors": [
            {
                "family": "normalized_fcf",
                "supports_2x": False,
                "source_urls": source,
            }
        ],
        "gates": {
            "publication": True,
            "buy_evidence": True,
            "strong_buy_evidence": False,
        },
        "signal_decision": {
            "selected": "WATCHLIST",
            "reasons": ["Current price is above the BUY threshold."],
        },
    }


def write_report_and_note(tmp_path: Path, report: str | None = None, note: dict | None = None) -> Path:
    path = tmp_path / "stock-audit-TEST-2026-07-13.md"
    path.write_text(report or valid_report(), encoding="utf-8")
    note_path = tmp_path / "evidence-TEST-2026-07-13.yaml"
    note_path.write_text(
        yaml.safe_dump(note or valid_evidence_note(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_validator_accepts_canonical_structured_report_with_evidence_sidecar(tmp_path):
    module = load_validator()
    path = write_report_and_note(tmp_path)

    assert module.validate_path(path) == []


def test_validator_requires_evidence_sidecar_for_stock_audit(tmp_path):
    module = load_validator()
    path = tmp_path / "stock-audit-TEST-2026-07-13.md"
    path.write_text(valid_report(), encoding="utf-8")

    assert "missing evidence sidecar: evidence-TEST-2026-07-13.yaml" in module.validate_path(path)


def test_validator_rejects_string_score_and_unknown_tag(tmp_path):
    module = load_validator()
    report = (
        valid_report()
        .replace("quality_score: 80", 'quality_score: "80/100"')
        .replace("industry: [saas]", "industry: [not-controlled]")
    )
    path = write_report_and_note(tmp_path, report)

    errors = module.validate_path(path)

    assert "quality_score must be an unquoted number greater than 0 and at most 100" in errors
    assert "tags.industry contains unknown values: not-controlled" in errors


def test_validator_rejects_buy_when_ratios_miss_decision_table(tmp_path):
    module = load_validator()
    report = valid_report().replace("signal: WATCHLIST", "signal: BUY")
    note = valid_evidence_note()
    note["signal_decision"]["selected"] = "BUY"
    path = write_report_and_note(tmp_path, report, note)

    errors = module.validate_path(path)

    assert "signal BUY violates the decision table; expected WATCHLIST" in errors


def test_validator_recomputes_watchlist_minimum_score(tmp_path):
    module = load_validator()
    path = write_report_and_note(tmp_path, valid_report().replace("quality_score: 80", "quality_score: 10"))

    errors = module.validate_path(path)

    assert "signal WATCHLIST violates the decision table; expected AVOID" in errors
    assert "signal_decision.selected must match the report and computed decision-table signal" in errors


def test_validator_requires_avoid_failure_or_sub_65_score_for_avoid(tmp_path):
    module = load_validator()
    report = valid_report().replace("signal: WATCHLIST", "signal: AVOID")
    note = valid_evidence_note()
    note["signal_decision"]["selected"] = "AVOID"
    path = write_report_and_note(tmp_path, report, note)

    assert "signal AVOID violates the decision table; expected WATCHLIST" in module.validate_path(path)


def test_validator_accepts_avoid_when_primary_evidence_establishes_failure(tmp_path):
    module = load_validator()
    report = valid_report().replace("signal: WATCHLIST", "signal: AVOID")
    note = valid_evidence_note()
    note["checks"]["avoid_failure"] = {
        "class": "material",
        "state": "verified_adverse",
        "source_urls": ["https://www.sec.gov/"],
    }
    note["gates"]["buy_evidence"] = False
    note["signal_decision"] = {
        "selected": "AVOID",
        "reasons": ["Primary evidence establishes a value-trap failure."],
    }
    path = write_report_and_note(tmp_path, report, note)

    assert module.validate_path(path) == []


def test_validator_recomputes_publication_and_buy_gates(tmp_path):
    module = load_validator()
    note = valid_evidence_note()
    note["checks"]["accounting_quality"] = {
        "class": "material",
        "state": "unresolved",
        "gap": "The audit opinion has not been checked.",
    }
    path = write_report_and_note(tmp_path, note=note)

    errors = module.validate_path(path)

    assert "gates.publication must be false from evidence states" in errors
    assert "a stock-audit report requires a true Publication Gate; output blocked-data instead" in errors
    assert "gates.buy_evidence must be false from evidence states" in errors


def test_validator_requires_all_management_checks_and_sources(tmp_path):
    module = load_validator()
    note = valid_evidence_note()
    del note["checks"]["incentives_dilution"]
    note["checks"]["capital_allocation"]["source_urls"] = []
    path = write_report_and_note(tmp_path, note=note)

    errors = module.validate_path(path)

    assert "evidence sidecar missing mandatory checks: incentives_dilution" in errors
    assert "evidence check capital_allocation in state verified requires at least one http(s) source URL" in errors


def test_validator_accepts_localized_english_report_from_shared_template(tmp_path):
    module = load_validator()
    path = write_report_and_note(tmp_path, english_report(), valid_evidence_note(language="en"))

    assert module.validate_path(path) == []


def test_validator_rejects_excessive_chinese_in_english_report(tmp_path):
    module = load_validator()
    report = english_report().replace(
        "The business has recurring revenue.",
        "这是一段没有完成英文重写的中文正文，包含投资判断、估值假设、证据限制和跟踪纪律。",
    )
    path = write_report_and_note(tmp_path, report, valid_evidence_note(language="en"))

    assert any("English report contains excessive Chinese text" in error for error in module.validate_path(path))


def test_validator_rejects_report_language_that_does_not_match_localized_title(tmp_path):
    module = load_validator()
    path = write_report_and_note(tmp_path, english_report(), valid_evidence_note(language="zh"))

    assert "Chinese evidence sidecar requires a Chinese 投资质量评估 title" in module.validate_path(path)


def valid_blocked_data() -> str:
    return """# 数据缺口清单（TEST）

**公司**：测试公司
**数据时间**：2026-07-13 00:00 UTC
**阻塞原因**：缺少五年FCF的一手口径核验。

## 缺失项

| 项目 | 缺失内容 | 需要来源 | 处理状态 |
|:---|:---|:---|:---|
| 五年FCF | 2021年capex口径不完整 | 年报现金流量表 | 待补齐 |

## 已查来源

| 来源 | 日期 | URL | 结果 |
|:---|:---|:---|:---|
| SEC年报 | 2026-07-13 | https://www.sec.gov/ | 口径不完整 |

## 下一步

- 核对现金流量表附注后重新分析。
"""


def test_validator_accepts_complete_blocked_data_checklist(tmp_path):
    module = load_validator()
    path = tmp_path / "blocked-data-TEST-2026-07-13.md"
    path.write_text(valid_blocked_data(), encoding="utf-8")

    assert module.validate_path(path) == []


def test_validator_rejects_minimal_blocked_data_checklist(tmp_path):
    module = load_validator()
    path = tmp_path / "blocked-data-TEST-2026-07-13.md"
    path.write_text(
        """# 数据缺口清单（TEST）

## 缺失项
缺少五年FCF。

## 已查来源
官方年报未找到完整口径。

## 下一步
补齐数据后重新分析。
""",
        encoding="utf-8",
    )

    errors = module.validate_path(path)

    assert "blocked-data checklist requires a non-empty company" in errors
    assert "blocked-data checklist requires a non-empty data time" in errors
    assert "blocked-data checklist requires a non-empty blocking reason" in errors
    assert "Missing Items must contain a table with at least one concrete gap row" in errors
    assert "Sources Checked must contain at least one concrete source row with a URL" in errors
    assert "blocked-data checklist requires at least one concrete next-step bullet" in errors


def test_validator_rejects_blocked_data_without_source_url_or_with_report_fields(tmp_path):
    module = load_validator()
    report = (
        valid_blocked_data()
        .replace("https://www.sec.gov/", "未取得")
        .replace("## 下一步", "**质量评分**：80/100\n\n## 下一步")
    )
    path = tmp_path / "blocked-data-TEST-2026-07-13.md"
    path.write_text(report, encoding="utf-8")

    errors = module.validate_path(path)

    assert "Sources Checked must contain at least one concrete source row with a URL" in errors
    assert "blocked-data checklist contains report-only fields: quality score" in errors


def test_validator_rejects_empty_blocked_data_table_rows(tmp_path):
    module = load_validator()
    report = (
        valid_blocked_data()
        .replace("| 五年FCF | 2021年capex口径不完整 | 年报现金流量表 | 待补齐 |", "| | | | |")
        .replace(
            "| SEC年报 | 2026-07-13 | https://www.sec.gov/ | 口径不完整 |",
            "| | | | |\n\nhttps://www.sec.gov/",
        )
    )
    path = tmp_path / "blocked-data-TEST-2026-07-13.md"
    path.write_text(report, encoding="utf-8")

    errors = module.validate_path(path)

    assert "Missing Items must contain a table with at least one concrete gap row" in errors
    assert "Sources Checked must contain a table with at least one source row" in errors
    assert "Sources Checked must contain at least one concrete source row with a URL" in errors
