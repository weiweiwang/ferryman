from pathlib import Path
import importlib.util
import sys
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_article_html.py"
SPEC = importlib.util.spec_from_file_location("render_article_html", SCRIPT_PATH)
render_article_html = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = render_article_html
SPEC.loader.exec_module(render_article_html)


def test_extracts_clean_article_title_and_body():
    article = render_article_html.extract_article(
        """# GitHub Copilot 从$29到$750：AI补贴时代，终结了

一个Reddit帖子，昨天炸穿了TechCrunch的评论区。
"""
    )

    assert article.title == "GitHub Copilot从$29到$750：AI补贴时代，终结了"
    assert article.body == "一个Reddit帖子，昨天炸穿了TechCrunch的评论区。"


def test_rejects_publishing_zone_and_article_metadata():
    with pytest.raises(ValueError, match="only '# final title' and final body"):
        render_article_html.extract_article(
            """# Draft

## Article Strategy

====================
OPERATIONS PUBLISHING ZONE START
====================
"""
        )

    with pytest.raises(ValueError, match="only '# final title' and final body"):
        render_article_html.extract_article(
            """# Draft

**Date**: 2026-05-31

Body
"""
        )

    with pytest.raises(ValueError, match="Remove publication metadata"):
        render_article_html.extract_article(
            """# Draft

**信噪比 AI | 2026-05-31**

Body
"""
        )

    with pytest.raises(ValueError, match="Remove brand footer metadata"):
        render_article_html.extract_article(
            """# Draft

Body

*信噪比 AI | 每日一份数据驱动的 AI 深度解读*
"""
        )


def test_rejects_missing_or_multiple_h1_titles():
    with pytest.raises(ValueError, match="exactly one H1"):
        render_article_html.extract_article("Body only")

    with pytest.raises(ValueError, match="exactly one H1"):
        render_article_html.extract_article("# One\n\n# Two\n\nBody")

    with pytest.raises(ValueError, match="must start"):
        render_article_html.extract_article("前置废话\n\n# 标题\n\n正文")


def test_renders_inline_styles_for_formatted_copy():
    html = render_article_html.render_full_html(
        render_article_html.Article(
            title="标题",
            body="## 01 小标题\n\n正文有**重点**和`token`。\n\n> 引用内容",
        )
    )

    assert 'id="formatted-article"' in html
    assert "<style>" in html
    assert '<h2 style="' in html
    assert '<strong style="' in html
    assert '<code style="' in html
    assert '<blockquote style="' in html
    assert "每日一份数据驱动" not in html
    assert "信噪比AI" not in html
    assert "font-family:Optima-Regular" in html
    assert "border-bottom:2px solid #07c160" in html
    assert "border-left:4px solid #07c160" in html
    assert "color:#07c160" in html
    assert ">01</span>小标题" in html
    assert "AI行业" in render_article_html.render_inline("AI 行业")
    assert "GitHub Copilot从" in render_article_html.render_inline("GitHub Copilot 从")


def test_markdown_it_handles_links_and_code_literals():
    rendered = render_article_html.render_inline("[链接](https://example.com/?a=1&b=2)")
    assert 'href="https://example.com/?a=1&amp;b=2"' in rendered
    assert "amp;amp" not in rendered

    code = render_article_html.render_inline("字面量 `**bold**` 和 `a*b`")
    assert "<strong" not in code
    assert "**bold**" in code
    assert "a*b" in code


def test_render_file_uses_article_html_filename(tmp_path):
    source = tmp_path / "ai-hotspot-article-demo.md"
    source.write_text("# 标题\n\n正文", encoding="utf-8")

    result = render_article_html.render_file(source)

    output = Path(result["output"])
    assert output.name == "ai-hotspot-article-demo.html"
    assert output.exists()
