from __future__ import annotations

import re
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = SKILL_DIR / "assets" / "report-template.md"
BLOCKED_TEMPLATE_PATH = SKILL_DIR / "assets" / "blocked-data-template.md"
SKILL_PATH = SKILL_DIR / "SKILL.md"
TAXONOMY_PATH = SKILL_DIR / "references" / "taxonomy.md"
SCREENER_PATH = SKILL_DIR / "references" / "screener.md"


def compact_whitespace(text: str) -> str:
    return " ".join(text.split())


def assert_compact_contains(text: str, phrase: str) -> None:
    assert compact_whitespace(phrase) in compact_whitespace(text)


def template_placeholders() -> set[str]:
    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    blocked_text = BLOCKED_TEMPLATE_PATH.read_text(encoding="utf-8")
    return set(re.findall(r"\[[^\]\n]+\]", template_text + "\n" + blocked_text))


def assert_clean_published_report(markdown: str) -> None:
    forbidden_terms = [
        "最近完整财年",
        "前1个完整财年",
        "前2个完整财年",
        "前3个完整财年",
        "前4个完整财年",
        "fetch_stock_data.py",
        "fetch_risk_free_rate.py",
        "dataLimits",
        "fxRate",
        "POST",
        "orgId",
    ]

    leaked_placeholders = sorted(placeholder for placeholder in template_placeholders() if placeholder in markdown)
    assert leaked_placeholders == []
    for term in forbidden_terms:
        assert term not in markdown
    for key in ("conservative", "base", "optimistic"):
        match = re.search(rf"^\s+{key}:\s+([0-9]+(?:\.[0-9]+)?)\s*$", markdown, re.MULTILINE)
        assert match, f"missing fair_value.{key}"
        assert float(match.group(1)) > 0


def test_report_template_has_no_internal_or_old_public_branding():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    forbidden = [
        "stock-research",
        "Stock Research",
        "股票研究",
        "screen_stock_candidates.py",
        "fetch_stock_data.py",
        "fetch_risk_free_rate.py",
        "数据脚本",
        "POST",
        "orgId",
        "dataLimits",
        "fxRate",
        "API请求",
        "脚本字段",
        "下载过程",
        "是否过期",
    ]

    for term in forbidden:
        assert term not in template

    assert "tags:\n  market: []\n  sector: []\n  industry: []\n  theme: []" in template
    assert "市场/行业/主题标签" not in template


def test_generated_report_cleanup_contract_accepts_minimal_finished_report():
    report = """---
ticker: "0700.HK"
company:
  zh: "腾讯控股"
  en: "Tencent Holdings Limited"
exchange: "HKEX"
report_date: "2026-07-04"
fetched_at: "2026-07-04 08:30 UTC"
signal: "WATCHLIST"
quality_score: "85/100"
summary: "质量高，但现价/基准FV未到高信号区间。"
current_price:
  value: 434.40
  currency: "HKD"
fair_value:
  conservative: 351.07
  base: 447.50
  optimistic: 520.00
  currency: "HKD"
tags:
  market: [hong-kong]
  sector: [communication-services]
  industry: [gaming]
  theme: [platform]
---

# 腾讯控股投资质量评估（0700.HK）

**数据时间**：2026-07-04 08:30 UTC
**质量评分**：85/100
**估值位置**：现价/基准公允价值(FV) 0.97
**最终信号**：WATCHLIST

## 财务审计

**审计口径**：估值使用2025年、2024年、2023年、2022年、2021年五个完整财年；财务币种CNY，报价币种HKD，使用2026-07-04汇率换算；无风险利率日期为2026-07-03。

## 估值

| 场景 | 核心假设 | 公允市值 | 每股公允价 | 现价/FV | 情景权重 | 后续验证 |
|:---|:---|:---|---:|---:|---:|:---|
| 保守 | 正常化FCF低于近年中枢 | 33000亿CNY/3510亿HKD | 351.07 HKD | 1.24 | 35% | FCF是否回落 |
| 基准 | 正常化FCF维持中枢 | 42100亿CNY/4475亿HKD | 447.50 HKD | 0.97 | 45% | 游戏和广告恢复 |
| 乐观 | 质量重估但不用于升级信号 | 48900亿CNY/5200亿HKD | 520.00 HKD | 0.84 | 20% | 利润率继续改善 |

## 数据来源

| 类别 | 来源 | 日期 | URL | 用途 |
|:---|:---|:---|:---|:---|
| 官方披露 | HKEX 2025年报 | 2026-04-08 | https://www.hkexnews.hk/example.pdf | 年报、治理和风险披露 |
"""

    assert_clean_published_report(report)


def test_generated_report_cleanup_contract_rejects_all_template_placeholders():
    placeholders = template_placeholders()

    assert "[来源名称]" in placeholders
    assert "[公司名]" in placeholders
    assert "[关键数据或证据]" in placeholders

    for placeholder in placeholders:
        try:
            assert_clean_published_report(f"已完成报告正文，但残留{placeholder}")
        except AssertionError:
            continue
        raise AssertionError(f"cleanup did not reject template placeholder {placeholder}")


def test_report_template_uses_base_fair_value_two_x_signal_wording():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "现价/基准FV<=0.50" in template
    assert "现价/基准FV<=0.50是否成立" in template
    assert "高把握信号证据" not in template
    assert "保守公允价值 >= 当前价格 2x" not in template
    assert "是否支持 2x" not in template


def test_report_template_uses_granular_management_score_and_data_sources():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "### 管理层与会计：[x/100，折算x.x/15]" in template
    assert "| **合计** | **100** | **[x/100]**" in template
    assert "## 数据来源" in template
    assert "流动金融资产" in template
    assert "非流动金融资产" in template
    assert "净现金/净债务（现金及等价物-总债务）" in template
    assert "现金折价/扣减（受限/监管/经营必需）" in template
    assert "Use a 100-point management/accounting subscore" in skill
    assert "Cash And Investments" not in skill
    assert "Do not apply one blended" in skill


def test_report_template_includes_shareholder_return_without_double_counting_dividends():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "### 股东回报" in template
    assert "| 股息率 | [xx%] | [股息率区间和变化] | [是否提供等待回报] |" in template
    assert "| 分红支付率 | [xx%] | [分红/净利润是否稳定] | [是否可持续] |" in template
    assert "| 分红/FCF | [xx%] | [是否被FCF覆盖] | [是否透支现金流] |" in template
    assert "| 回购与稀释 | [净变化] | [股本、回购、股权激励和稀释变化] | [是否提高每股价值] |" in template
    assert "分红、稀释与回购质量" in template
    assert "不把分红重复加进FV" in template

    assert "Shareholder return check" in skill
    assert "dividend yield" in skill
    assert "payout ratio" in skill
    assert "dividends/FCF" in skill
    assert "not a Completion Gate field by itself" in skill
    assert "Do not add dividends on top of fair value" in skill
    assert_compact_contains(skill, "A high yield without repeatable FCF coverage is a value-trap warning")


def test_report_template_does_not_use_zero_yaml_placeholders_for_required_positive_values():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    skill = SKILL_PATH.read_text(encoding="utf-8")

    forbidden = [
        "quality_score: 0",
        "  value: 0",
        "  conservative: 0",
        "  base: 0",
        "  optimistic: 0",
    ]

    for term in forbidden:
        assert term not in template

    assert 'quality_score: "[x/100]"' in template
    assert 'value: "[当前价格]"' in template
    assert 'conservative: "[保守每股公允价]"' in template
    assert 'base: "[基准每股公允价]"' in template
    assert 'optimistic: "[乐观每股公允价]"' in template
    assert "quality score" in skill
    assert "conservative/base/optimistic fair values must not be zero" in skill


def test_report_template_clarifies_balance_sheet_adjustment_currencies():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "| 项目 | 账面值（财务币种） | 计入比例 | 计入价值（估值币种） | 理由 |" in template
    assert "| 项目 | 账面值 | 计入比例 | 计入价值 | 理由 |" not in template


def test_skill_centralizes_signal_gate_contract():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "## Signal Gate Contract" in skill
    assert "Use the Signal Gate Contract below" in skill
    assert "Internal evidence caps:" in skill
    assert "Chinese report spacing:" in skill
    assert "ask the user before" in skill
    assert_compact_contains(
        skill,
        "Current price, share count, market cap, revenue, net profit, OCF, FCF, quality score, and conservative/base/optimistic fair values must not be zero",
    )
    assert_compact_contains(skill, "Debt, financial assets, unusual items, and capex may be zero")
    assert "Current and non-current financial-asset fields must stay separate" in skill
    assert_compact_contains(skill, "block only when the missing value is material to valuation")
    assert "Run the fetcher fresh for the target ticker" in skill
    assert "implicit cache" in skill
    assert_compact_contains(
        skill,
        "For every published stock-audit report, run the same-currency risk-free-rate script again",
    )
    assert "Reuse current-thread stock financial and quote data" not in skill
    assert "### Report Writing Style" not in skill
    assert "Safety Margin Confidence" not in skill
    assert "confidence_pct" not in skill
    assert "stale risk-free-rate" not in skill
    assert "stale data" not in skill


def test_skill_excludes_candidate_screening_from_single_stock_contract():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "## Candidate Screening" not in skill
    assert "screen_stock_candidates.py" not in skill
    assert "references/screener.md" not in skill
    assert "candidate pool" not in skill.lower()
    assert "--markets SH SZ HK" not in skill
    assert not SCREENER_PATH.exists()


def test_skill_does_not_advertise_unsupported_japan_single_stock_routing():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "EDINET" not in skill
    assert "TDnet" not in skill


def test_report_template_does_not_allow_unverified_required_checks():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "未验证" not in template
    assert "不适用（说明原因）" in template
    assert "| 异常项目与利润正常化 | [年报注释/业绩公告] | 通过/不通过 |" in template
    assert "| 可重复FCF | [现金流量表/管理层解释] | 通过/不通过 |" in template


def test_blocked_data_template_excludes_report_signals_and_valuation_fields():
    skill = SKILL_PATH.read_text(encoding="utf-8")
    blocked_template = BLOCKED_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "assets/blocked-data-template.md" in skill
    assert "Blocked Data Checklist" not in skill
    assert blocked_template.startswith("# 数据缺口清单")
    assert not blocked_template.startswith("---\n")

    forbidden = [
        "signal:",
        "quality_score",
        "fair_value",
        "现价/基准FV",
        "现价/基准公允价值",
        "最终信号",
        "质量评分",
        "动作价格",
        "买入",
        "观察价",
        "stock-audit",
        "正式",
    ]

    for term in forbidden:
        assert term not in blocked_template

    assert "流动/非流动金融资产" in blocked_template
    assert "对估值重大" in blocked_template
    assert "一手披露有余额" in blocked_template
    assert "- [" not in blocked_template
    assert "assets/blocked-data-template.md" in skill
    assert "Before publishing any user-facing output" in skill


def test_value_trap_risk_cannot_be_marked_not_applicable():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    value_trap_line = next(line for line in template.splitlines() if line.startswith("- **价值陷阱风险**"))
    assert "N/A" not in value_trap_line
    assert "若未发现重大风险" in value_trap_line


def test_wait_signal_is_not_a_public_signal():
    skill = SKILL_PATH.read_text(encoding="utf-8")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "`WAIT`" not in skill
    assert "WAIT" not in template


def test_skill_requires_placeholder_cleanup_scan():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "placeholder check" in skill
    assert "[Ticker]" in skill
    assert "[金额]" in skill
    assert "最近完整财年" in skill
    assert "前4个完整财年" in skill
    assert_compact_contains(skill, "Normal Markdown links are allowed")


def test_watchlist_requires_completion_gate():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "`WATCHLIST` requires the Completion Gate to be satisfied" in skill
    assert "not `WATCHLIST`" in skill


def test_skill_requires_publication_cleanup_scan():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "publication cleanup scan" in skill
    assert "fetch_.*\\\\.py" in skill
    assert "screen_.*" not in skill
    assert "underlying data providers or official venues" in skill


def test_skill_uses_controlled_structured_taxonomy():
    skill = SKILL_PATH.read_text(encoding="utf-8")
    taxonomy = TAXONOMY_PATH.read_text(encoding="utf-8")

    assert "references/taxonomy.md" in skill
    assert "tags.market" in skill
    assert "tags.sector" in skill
    assert "tags.industry" in skill
    assert "tags.theme" in skill

    for heading in ("## market", "## sector", "## industry", "## theme"):
        assert heading in taxonomy

    for tag in (
        "hong-kong",
        "us",
        "adr",
        "communication-services",
        "consumer-discretionary",
        "ecommerce",
        "online-travel",
        "social-platform",
        "ip-content",
        "platform",
        "ai-cloud",
    ):
        assert f"- {tag}" in taxonomy
