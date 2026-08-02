#!/usr/bin/env python3
"""Render clean ai-product-scout article Markdown into formatted HTML."""

from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token


H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$")
FORBIDDEN_SOURCE_PATTERNS = (
    re.compile(r"operations publishing zone", re.I),
    re.compile(r"^\s*#{2,6}\s+article strategy\s*$", re.I | re.M),
    re.compile(r"^\s*#{2,6}\s+title candidates\s*$", re.I | re.M),
    re.compile(r"^\s*#{2,6}\s+fact check notes(?:\s*/\s*source notes)?\s*$", re.I | re.M),
    re.compile(r"^\s*\*\*(?:date|publication / channel|brand name)\*\*\s*:", re.I | re.M),
)
MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


ARTICLE_STYLE = (
    "max-width:660px;margin:0 auto;padding:0 12px 34px;"
    "box-sizing:border-box;color:#2c3e50;font-family:Optima-Regular,Optima,"
    "PingFangSC-light,PingFangTC-light,'PingFang SC','Microsoft YaHei',"
    "'微软雅黑','Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
    "font-size:16px;line-height:1.8;letter-spacing:0;word-break:break-word;"
    "word-wrap:break-word;text-align:left;"
)
TITLE_STYLE = (
    "margin:6px 0 24px;padding:0 0 14px;border-bottom:2px solid #07c160;"
    "color:#1a1a1a;font-size:26px;line-height:1.42;font-weight:700;"
    "letter-spacing:0;text-align:center;text-wrap:balance;"
)
LEAD_STYLE = (
    "margin:8px 0 18px;color:#2c3e50;font-size:16px;line-height:1.86;"
    "font-weight:500;letter-spacing:0;"
)
P_STYLE = "margin:8px 0;color:#34495e;font-size:16px;line-height:1.8;letter-spacing:0;"
H2_STYLE = (
    "margin:30px 0 14px;padding:0 0 0 12px;border-left:4px solid #07c160;"
    "color:#2c3e50;font-size:22px;line-height:1.45;font-weight:600;letter-spacing:0;"
)
H2_NUMBER_STYLE = (
    "display:inline-block;margin:0 8px 0 0;color:#07c160;font-size:18px;"
    "line-height:1;font-weight:700;letter-spacing:0;vertical-align:1px;"
)
H3_STYLE = (
    "margin:24px 0 12px;padding:0 0 0 10px;border-left:3px solid #07c160;"
    "color:#34495e;font-size:19px;line-height:1.5;font-weight:600;letter-spacing:0;"
)
QUOTE_STYLE = (
    "margin:20px 0;padding:16px 20px;border:0;border-left:4px solid #07c160;"
    "background:#f6f8fa;color:#475569;font-size:15px;line-height:1.8;"
    "letter-spacing:0;border-radius:2px;"
)
LIST_STYLE = "margin:8px 0 18px;padding-left:24px;color:#34495e;font-size:16px;line-height:1.8;"
LI_STYLE = "margin:8px 0;padding-left:4px;color:#34495e;font-size:16px;line-height:1.8;"
HR_STYLE = "height:1px;margin:28px 0;border:0;background:#e2e8f0;"
STRONG_STYLE = "font-weight:600;color:#07c160;"
EM_STYLE = "font-style:italic;color:#07c160;font-weight:500;"
CODE_STYLE = (
    "margin:0 3px;padding:3px 6px;border:1px solid #bbf7d0;border-radius:3px;"
    "background:#f0fdf4;color:#059669;font-family:'SF Mono',Monaco,"
    "'Cascadia Code','Roboto Mono',Consolas,monospace;font-size:14px;"
)
A_STYLE = "color:#07c160;text-decoration:none;border-bottom:1px solid #07c160;font-weight:500;"
TABLE_WRAP_STYLE = "margin:16px 0 22px;overflow-x:auto;-webkit-overflow-scrolling:touch;"
TABLE_STYLE = (
    "width:100%;border-collapse:collapse;color:#34495e;font-size:14px;"
    "line-height:1.65;letter-spacing:0;"
)
TH_STYLE = (
    "padding:9px 10px;border:1px solid #dbe7ef;background:#f6f8fa;"
    "color:#2c3e50;font-weight:600;text-align:left;vertical-align:top;"
)
TD_STYLE = "padding:9px 10px;border:1px solid #dbe7ef;text-align:left;vertical-align:top;"
FIGURE_STYLE = "margin:10px 0 18px;padding:0;text-align:center;"
IMG_STYLE = (
    "display:block;width:100%;max-width:100%;height:auto;margin:0 auto;"
    "border-radius:4px;border:0;"
)
VIDEO_STYLE = (
    "display:block;width:100%;max-width:100%;height:auto;margin:0 auto;"
    "border-radius:4px;border:0;background:#0f172a;"
)
VIDEO_SOURCE_RE = re.compile(r"\.(?:mp4|webm|mov|m4v)(?:[?#].*)?$", re.I)


@dataclass(frozen=True)
class Article:
    title: str
    body: str


def slug_output_path(input_path: Path) -> Path:
    return input_path.with_suffix(".html")


def extract_article(markdown_text: str) -> Article:
    _validate_clean_source(markdown_text)

    lines = markdown_text.splitlines()
    title = ""
    body_lines: list[str] = []
    consumed_title = False

    for line in lines:
        match = H1_RE.match(line)
        if match and not consumed_title:
            title = normalize_chinese_spacing(_strip_inline_markdown(match.group(1))).strip()
            consumed_title = True
            continue
        body_lines.append(line)

    if not title:
        raise ValueError("Article Markdown must start with exactly one H1 title, e.g. '# 最终标题'.")

    body = "\n".join(body_lines).strip()
    if not body:
        raise ValueError("Article Markdown must include body text after the H1 title.")
    return Article(title=title, body=body)


def _validate_clean_source(markdown_text: str) -> None:
    for pattern in FORBIDDEN_SOURCE_PATTERNS:
        if pattern.search(markdown_text):
            raise ValueError(
                "Article Markdown must contain only '# final title' and final body. "
                "Move strategy, metadata, title candidates, fact-check notes, and publishing-zone markers to the research brief."
            )

    h1_count = sum(1 for line in markdown_text.splitlines() if H1_RE.match(line))
    if h1_count != 1:
        raise ValueError("Article Markdown must contain exactly one H1 final title.")

    lines = markdown_text.splitlines()
    first_nonempty = next((line for line in lines if line.strip()), "")
    if not H1_RE.match(first_nonempty):
        raise ValueError("Article Markdown must start with exactly one H1 final title.")

    h1_index = next(index for index, line in enumerate(lines) if H1_RE.match(line))
    body_lines = lines[h1_index + 1 :]
    nonempty_body = [line.strip() for line in body_lines if line.strip()]
    if not nonempty_body:
        return


def _strip_inline_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^>\s*", "", text)
    text = re.sub(r"^[*-]\s+", "", text)
    text = re.sub(r"[*_`]+", "", text)
    return text.strip()


def render_body_html(markdown_body: str) -> str:
    tokens = MARKDOWN.parse(markdown_body)
    rendered: list[str] = []
    lead_used = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "paragraph_open":
            inline = _next_inline(tokens, index)
            if inline:
                video = _video_link_from_inline(inline)
                if video:
                    rendered.append(_render_video_paragraph(*video))
                    index += 3
                    continue
                if _is_image_only_inline(inline):
                    rendered.append(_render_image_paragraph(inline))
                    index += 3
                    continue
                is_lead = not lead_used
                style = LEAD_STYLE if is_lead else P_STYLE
                rendered.append(f'<p style="{style}">{render_inline_tokens(inline.children or [])}</p>')
                lead_used = True
            index += 3
            continue

        if token.type == "heading_open":
            inline = _next_inline(tokens, index)
            if inline:
                rendered.append(_render_heading_token(token, inline))
            index += 3
            continue

        if token.type == "blockquote_open":
            block_html, index = _render_blockquote(tokens, index)
            rendered.append(block_html)
            continue

        if token.type in {"bullet_list_open", "ordered_list_open"}:
            list_html, index = _render_list(tokens, index)
            rendered.append(list_html)
            continue

        if token.type == "table_open":
            table_html, index = _render_table(tokens, index)
            rendered.append(table_html)
            continue

        if token.type == "hr":
            rendered.append(f'<hr style="{HR_STYLE}">')

        index += 1
    return "\n".join(item for item in rendered if item)


def _next_inline(tokens: list[Token], index: int) -> Token | None:
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1]
    return None


def _is_image_only_inline(inline_token: Token) -> bool:
    children = inline_token.children or []
    meaningful = [token for token in children if token.type not in {"softbreak", "hardbreak"}]
    return (
        len(meaningful) == 1
        and meaningful[0].type == "image"
        and not is_video_source(str(meaningful[0].attrGet("src") or ""))
    )


def _render_image_paragraph(inline_token: Token) -> str:
    image = next(token for token in inline_token.children or [] if token.type == "image")
    return f'<figure style="{FIGURE_STYLE}">{render_image_token(image)}</figure>'


def _video_link_from_inline(inline_token: Token) -> tuple[str, str] | None:
    children = inline_token.children or []
    meaningful = [
        token for token in children
        if not (token.type == "text" and not token.content.strip())
        and token.type not in {"softbreak", "hardbreak"}
    ]
    if len(meaningful) == 1 and meaningful[0].type == "image":
        src = str(meaningful[0].attrGet("src") or "")
        if is_video_source(src):
            return src, meaningful[0].content or "Product demo video"
    if len(meaningful) < 2 or meaningful[0].type != "link_open" or meaningful[-1].type != "link_close":
        return None
    href = str(meaningful[0].attrGet("href") or "")
    if not is_video_source(href):
        return None
    label = normalize_chinese_spacing(_plain_inline_text(meaningful[1:-1])).strip() or "Product demo video"
    return href, label


def _render_video_paragraph(src: str, label: str) -> str:
    return f'<figure style="{FIGURE_STYLE}">{render_video(src, label)}</figure>'


def _render_heading_token(open_token: Token, inline_token: Token) -> str:
    level = int(open_token.tag[1]) if open_token.tag.startswith("h") else 3
    if level == 2:
        return f'<h2 style="{H2_STYLE}">{render_heading_tokens(inline_token.children or [])}</h2>'
    return f'<h3 style="{H3_STYLE}">{render_inline_tokens(inline_token.children or [])}</h3>'


def _render_blockquote(tokens: list[Token], start: int) -> tuple[str, int]:
    quote_parts: list[str] = []
    index = start + 1
    while index < len(tokens) and tokens[index].type != "blockquote_close":
        if tokens[index].type == "paragraph_open":
            inline = _next_inline(tokens, index)
            if inline:
                quote_parts.append(
                    f'<p style="margin:0 0 8px;color:#475569;font-size:15px;line-height:1.8;">'
                    f"{render_inline_tokens(inline.children or [])}</p>"
                )
            index += 3
            continue
        index += 1
    return f'<blockquote style="{QUOTE_STYLE}">{"".join(quote_parts)}</blockquote>', index + 1


def _render_list(tokens: list[Token], start: int) -> tuple[str, int]:
    list_type = "ul" if tokens[start].type == "bullet_list_open" else "ol"
    close_type = "bullet_list_close" if list_type == "ul" else "ordered_list_close"
    items: list[str] = []
    index = start + 1
    while index < len(tokens) and tokens[index].type != close_type:
        if tokens[index].type == "list_item_open":
            item_html, index = _render_list_item(tokens, index)
            items.append(item_html)
            continue
        index += 1
    return f'<{list_type} style="{LIST_STYLE}">{"".join(items)}</{list_type}>', index + 1


def _render_list_item(tokens: list[Token], start: int) -> tuple[str, int]:
    parts: list[str] = []
    index = start + 1
    while index < len(tokens) and tokens[index].type != "list_item_close":
        if tokens[index].type == "paragraph_open":
            inline = _next_inline(tokens, index)
            if inline:
                parts.append(render_inline_tokens(inline.children or []))
            index += 3
            continue
        index += 1
    return f'<li style="{LI_STYLE}">{" ".join(parts)}</li>', index + 1


def _render_table(tokens: list[Token], start: int) -> tuple[str, int]:
    parts: list[str] = [f'<div style="{TABLE_WRAP_STYLE}">']
    index = start
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_open":
            parts.append(f'<table style="{TABLE_STYLE}">')
        elif token.type == "table_close":
            parts.append("</table></div>")
            return "".join(parts), index + 1
        elif token.type == "thead_open":
            parts.append("<thead>")
        elif token.type == "thead_close":
            parts.append("</thead>")
        elif token.type == "tbody_open":
            parts.append("<tbody>")
        elif token.type == "tbody_close":
            parts.append("</tbody>")
        elif token.type == "tr_open":
            parts.append("<tr>")
        elif token.type == "tr_close":
            parts.append("</tr>")
        elif token.type in {"th_open", "td_open"}:
            inline = _next_inline(tokens, index)
            content = render_inline_tokens(inline.children or []) if inline else ""
            tag = "th" if token.type == "th_open" else "td"
            style = _table_cell_style(token, TH_STYLE if tag == "th" else TD_STYLE)
            parts.append(f'<{tag} style="{style}">{content}</{tag}>')
            index += 3
            continue
        index += 1
    return "".join(parts), index


def _table_cell_style(token: Token, base_style: str) -> str:
    align_style = token.attrGet("style") or ""
    if "text-align" not in align_style:
        return base_style
    return f"{base_style}{align_style}"


def render_inline(markdown_text: str) -> str:
    markdown_text = normalize_chinese_spacing(markdown_text)
    inline_tokens = MARKDOWN.parseInline(markdown_text, {})
    if not inline_tokens:
        return ""
    return render_inline_tokens(inline_tokens[0].children or [])


def render_inline_tokens(tokens: list[Token]) -> str:
    rendered: list[str] = []
    for token in tokens:
        if token.type == "text":
            rendered.append(html.escape(normalize_chinese_spacing(token.content), quote=True))
        elif token.type == "code_inline":
            rendered.append(f'<code style="{CODE_STYLE}">{html.escape(token.content, quote=True)}</code>')
        elif token.type == "strong_open":
            rendered.append(f'<strong style="{STRONG_STYLE}">')
        elif token.type == "strong_close":
            rendered.append("</strong>")
        elif token.type == "em_open":
            rendered.append(f'<em style="{EM_STYLE}">')
        elif token.type == "em_close":
            rendered.append("</em>")
        elif token.type == "link_open":
            href = html.escape(str(token.attrGet("href") or ""), quote=True)
            rendered.append(f'<a href="{href}" style="{A_STYLE}">')
        elif token.type == "link_close":
            rendered.append("</a>")
        elif token.type == "image":
            rendered.append(render_image_token(token))
        elif token.type == "softbreak":
            rendered.append(" ")
        elif token.type == "hardbreak":
            rendered.append("<br>")
        else:
            rendered.append(html.escape(token.content, quote=True))
    return "".join(rendered)


def render_image_token(token: Token) -> str:
    src = html.escape(str(token.attrGet("src") or ""), quote=True)
    alt = html.escape(normalize_chinese_spacing(token.content or ""), quote=True)
    title = html.escape(str(token.attrGet("title") or ""), quote=True)
    title_attr = f' title="{title}"' if title else ""
    return f'<img src="{src}" alt="{alt}"{title_attr} style="{IMG_STYLE}">'


def is_video_source(value: str) -> bool:
    return bool(VIDEO_SOURCE_RE.search(value))


def render_video(src: str, label: str) -> str:
    safe_src = html.escape(src, quote=True)
    safe_label = html.escape(normalize_chinese_spacing(label), quote=True)
    return (
        f'<video src="{safe_src}" controls preload="metadata" '
        f'aria-label="{safe_label}" style="{VIDEO_STYLE}">'
        f'<a href="{safe_src}" style="{A_STYLE}">{safe_label}</a>'
        "</video>"
    )


def render_heading_tokens(tokens: list[Token]) -> str:
    plain_text = _plain_inline_text(tokens).strip()
    match = re.match(r"^(\d{2})\s+(.+)$", plain_text)
    if not match:
        return render_inline_tokens(tokens)
    number, text = match.groups()
    normalized_text = normalize_chinese_spacing(text).strip()
    return f'<span style="{H2_NUMBER_STYLE}">{html.escape(number)}</span>{html.escape(normalized_text)}'


def _plain_inline_text(tokens: list[Token]) -> str:
    parts: list[str] = []
    for token in tokens:
        if token.type in {"text", "code_inline"}:
            parts.append(token.content)
        elif token.children:
            parts.append(_plain_inline_text(token.children))
    return "".join(parts)


def normalize_chinese_spacing(text: str) -> str:
    """Remove non-essential spaces between CJK and adjacent ASCII tokens."""
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[A-Za-z0-9$])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9%$])\s+(?=[\u3400-\u9fff])", "", text)
    return text


def render_full_html(article: Article) -> str:
    title_html = html.escape(article.title)
    body_html = render_body_html(article.body)
    plain_title = html.escape(article.title, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_html}</title>
  <style>
    body {{ margin: 0; background: #eef2f7; color: #111827; }}
    .toolbar {{ max-width: 660px; margin: 0 auto; padding: 14px 18px 10px; box-sizing: border-box; font-family: -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',Arial,sans-serif; }}
    .toolbar input {{ width: 100%; box-sizing: border-box; border: 1px solid #d3dbe8; border-radius: 6px; padding: 9px 11px; font-size: 13px; color: #111827; background: #fff; }}
    .toolbar p {{ margin: 7px 0 0; color: #64748b; font-size: 12px; line-height: 1.6; }}
    .preview {{ background: #fff; padding: 34px 0 42px; box-shadow: 0 1px 0 rgba(15,23,42,0.04); }}
  </style>
</head>
<body>
  <div class="toolbar">
    <input aria-label="文章标题" readonly value="{plain_title}">
    <p>上方可单独复制标题；下方白色区域包含格式化标题和正文，选中后可复制到目标编辑器。</p>
  </div>
  <main class="preview">
    <section id="formatted-article" style="{ARTICLE_STYLE}">
      <h1 style="{TITLE_STYLE}">{title_html}</h1>
      {body_html}
    </section>
  </main>
</body>
</html>
"""


def render_file(input_path: Path, output_path: Path | None = None) -> dict[str, object]:
    markdown_text = input_path.read_text(encoding="utf-8")
    article = extract_article(markdown_text)
    destination = output_path or slug_output_path(input_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_full_html(article), encoding="utf-8")
    return {
        "ok": True,
        "title": article.title,
        "input": str(input_path),
        "output": str(destination),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to the ai-product-scout article Markdown file.")
    parser.add_argument("-o", "--output", help="Optional HTML output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = render_file(Path(args.input).expanduser(), Path(args.output).expanduser() if args.output else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
