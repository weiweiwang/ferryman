from __future__ import annotations

from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = SKILL_DIR / "assets" / "report-template.md"
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
