from __future__ import annotations

from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = SKILL_DIR / "assets" / "report-template.md"
BLOCKED_TEMPLATE_PATH = SKILL_DIR / "assets" / "blocked-data-template.md"
SKILL_PATH = SKILL_DIR / "SKILL.md"
TAXONOMY_PATH = SKILL_DIR / "references" / "taxonomy.md"


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
    ]

    for term in forbidden:
        assert term not in template

    assert "tags:\n  market: []\n  sector: []\n  industry: []\n  theme: []" in template
    assert "市场/行业/主题标签" not in template


def test_report_template_uses_base_fair_value_two_x_signal_wording():
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "现价/基准FV<=0.50" in template
    assert "现价/基准FV<=0.50是否成立" in template
    assert "高把握信号证据" in template
    assert "保守公允价值 >= 当前价格 2x" not in template
    assert "是否支持 2x" not in template


def test_skill_centralizes_signal_gate_contract():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "## Signal Gate Contract" in skill
    assert "Use the Signal Gate Contract below" in skill
    assert "Internal evidence caps:" in skill
    assert "Chinese report spacing:" in skill
    assert "### Report Writing Style" not in skill
    assert "Safety Margin Confidence" not in skill
    assert "confidence_pct" not in skill


def test_skill_keeps_candidate_screening_contract():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "## Candidate Screening" in skill
    assert "scripts/screen_stock_candidates.py --markets SH SZ HK" in skill
    assert "references/screener.md" in skill
    assert "must not create `BUY`, `STRONG_BUY`, fair value" in skill
    assert "always re-check" in skill


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
    assert "Normal Markdown links are allowed" in skill


def test_watchlist_requires_completion_gate():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "`WATCHLIST` requires the Completion Gate to be satisfied" in skill
    assert "not `WATCHLIST`" in skill


def test_skill_requires_publication_cleanup_scan():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "publication cleanup scan" in skill
    assert "fetch_.*\\\\.py" in skill
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
