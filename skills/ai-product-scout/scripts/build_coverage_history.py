#!/usr/bin/env python3
"""Build an ai-product-scout coverage history from local reports."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BRIEF_RE = re.compile(r"^ai-product-scout-(?P<slug>.+)\.md$")
ARTICLE_RE = re.compile(r"^ai-product-case-article-(?P<slug>.+)\.md$")
URL_RE = re.compile(r"https?://[^\s)>'\"]+")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
GENERIC_SLUG_RE = re.compile(r"(?:candidate|candidates|dark-horse|research|vertical-dark|report|daily|roundup)", re.I)
FIELD_PATTERNS = {
    "productName": [
        re.compile(r"^- \*\*(?:Product Name|Top Case|产品名|公司名|主案例)\*\*[:：]\s*(.+?)\s*$", re.M),
        re.compile(r"^\*\*(?:Product Name|Top Case|产品名|公司名|主案例)[:：]\*\*\s*(.+?)\s*$", re.M),
        re.compile(r"^\|\s*\*\*(?:产品|产品名|公司名|主案例)\*\*\s*\|\s*(.+?)\s*\|\s*$", re.M),
        re.compile(r"^###\s+\d+\.\s+(.+?)\s*$", re.M),
    ],
    "url": [
        re.compile(r"^- \*\*(?:URL|Homepage|Website|官网|产品官网)\*\*[:：]\s*(.+?)\s*$", re.M),
        re.compile(r"^\*\*(?:URL|Homepage|Website|官网|产品官网)[:：]\*\*\s*(.+?)\s*$", re.M),
        re.compile(r"^\|\s*\*\*(?:URL|Homepage|Website|官网|产品官网)\*\*\s*\|\s*(.+?)\s*\|\s*$", re.M),
    ],
}


def normalize_value(value: str) -> str:
    return value.strip().strip("[]()。.,，")


def strip_markdown(value: str) -> str:
    value = MARKDOWN_LINK_RE.sub(r"\1", value)
    value = re.sub(r"[*_`]+", "", value)
    return normalize_value(value)


def clean_product_name(value: str) -> str:
    value = strip_markdown(value)
    value = re.sub(r"^#+\s*", "", value)
    value = re.sub(r"^\d+[.)、]\s*", "", value)
    value = value.replace("⭐", " ").strip()
    value = re.split(r"\s+[—–-]\s+|｜|\|", value, maxsplit=1)[0].strip()
    value = re.sub(r"[（(](?:入选主案例|主案例|候选|推荐|.*?案例).*?[）)]", "", value).strip()
    value = re.sub(r"\s+", " ", value)
    if not value or DATE_RE.match(value) or GENERIC_SLUG_RE.search(value):
        return ""
    return value


def first_match(text: str, patterns: list[re.Pattern[str]]) -> str:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return normalize_value(match.group(1))
    return ""


def extract_url(value: str) -> str:
    markdown_link = MARKDOWN_LINK_RE.search(value)
    if markdown_link:
        return normalize_value(markdown_link.group(2))
    match = URL_RE.search(value)
    return normalize_value(match.group(0)) if match else ""


def first_url(text: str) -> str:
    field_url = first_match(text, FIELD_PATTERNS["url"])
    if field_url:
        found = extract_url(field_url)
        if found:
            return found
    return extract_url(text)


def canonical_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path or "")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", "", ""))


def url_aliases(value: str) -> set[str]:
    aliases: set[str] = set()
    if not value:
        return aliases
    raw = value.strip()
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return aliases
    host = parsed.netloc.lower()
    domain = host.removeprefix("www.")
    path = re.sub(r"/+$", "", parsed.path or "")
    aliases.add(raw.rstrip("/").lower())
    aliases.add(urlunparse((parsed.scheme.lower(), host, path, "", "", "")))
    aliases.add(urlunparse((parsed.scheme.lower(), domain, path, "", "", "")))
    aliases.add(domain)
    if path:
        aliases.add(f"{domain}{path}".lower())
    return {alias for alias in aliases if alias}


def product_from_title(title: str, slug: str) -> str:
    title = strip_markdown(title)
    if not title:
        return product_from_slug(slug)
    prefix = re.split(r"[:：]", title, maxsplit=1)[0].strip()
    if 1 < len(prefix) <= 40 and re.search(r"[A-Za-z]", prefix) and not prefix.startswith("公众号"):
        return clean_product_name(prefix)
    match = re.search(r"\b[A-Z][A-Za-z0-9][A-Za-z0-9 .+-]{1,38}\b", title)
    if match:
        return clean_product_name(match.group(0))
    return product_from_slug(slug)


def product_from_slug(slug: str) -> str:
    if not slug or DATE_RE.match(slug) or GENERIC_SLUG_RE.search(slug):
        return ""
    parts = [part for part in slug.split("-") if part not in {"ai", "case", "article"}]
    if not parts:
        return ""
    return " ".join(part.upper() if len(part) <= 3 else part.capitalize() for part in parts[:3])


def article_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return strip_markdown(line[2:])
    except UnicodeDecodeError:
        return ""
    return ""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def case_date(path: Path) -> str:
    return path.parent.name if DATE_RE.match(path.parent.name) else ""


def collect_related_files(reports_root: Path, date: str, slug: str) -> dict[str, Any]:
    directory = reports_root / date if date else reports_root
    files: dict[str, Any] = {}
    brief = directory / f"ai-product-scout-{slug}.md"
    article = directory / f"ai-product-case-article-{slug}.md"
    html = directory / f"ai-product-case-article-{slug}.html"
    if brief.exists():
        files["brief"] = str(brief)
    if article.exists():
        files["article"] = str(article)
    if html.exists():
        files["html"] = str(html)
    covers = sorted(directory.glob(f"ai-product-cover-{slug}.*"))
    visuals = sorted(directory.glob(f"ai-product-visual-{slug}.*"))
    media = sorted(directory.glob(f"ai-product-media-{slug}.*"))
    if covers:
        files["covers"] = [str(path) for path in covers]
    if visuals:
        files["visuals"] = [str(path) for path in visuals]
    if media:
        files["media"] = [str(path) for path in media]
    return files


def source_paths(item: dict[str, Any], reports_root: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    files = item.get("files", {})
    if isinstance(files, dict):
        for value in files.values():
            if isinstance(value, str):
                paths.append(Path(value))
            elif isinstance(value, list):
                paths.extend(Path(path) for path in value if isinstance(path, str))
    root_value = item.get("sourceRoot") or (str(reports_root) if reports_root else "")
    slug = item.get("slug", "")
    date = item.get("date", "")
    if root_value and slug:
        root = Path(root_value)
        directory = root / date if date else root
        paths.extend([
            directory / f"ai-product-scout-{slug}.md",
            directory / f"ai-product-case-article-{slug}.md",
        ])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen and path.exists():
            seen.add(key)
            unique.append(path)
    return unique


def enrich_item(item: dict[str, Any], reports_root: Path | None = None) -> dict[str, Any]:
    enriched = dict(item)
    slug = str(enriched.get("slug", ""))
    texts: list[tuple[Path, str]] = [(path, read_text(path)) for path in source_paths(enriched, reports_root)]
    texts = [(path, text) for path, text in texts if text]

    product = clean_product_name(str(enriched.get("productName", "")))
    url = first_url(str(enriched.get("url", "")))
    title = strip_markdown(str(enriched.get("articleTitle", "")))

    for path, text in texts:
        if not product:
            product = clean_product_name(first_match(text, FIELD_PATTERNS["productName"]))
        if not url:
            url = first_url(text)
        if not title and ARTICLE_RE.match(path.name):
            title = article_title(path)

    if not product:
        product = product_from_title(title, slug)

    enriched["productName"] = product
    enriched["url"] = canonical_url(url) or url
    enriched["articleTitle"] = title
    return enriched


def build_aliases(cases: list[dict[str, Any]]) -> dict[str, list[str]]:
    aliases = defaultdict(list)
    for item in cases:
        slug = str(item.get("slug", ""))
        if item.get("productName"):
            aliases[str(item["productName"]).lower()].append(slug)
        if item.get("articleTitle"):
            aliases[str(item["articleTitle"]).lower()].append(slug)
        if item.get("url"):
            for alias in url_aliases(str(item["url"])):
                aliases[alias].append(slug)
        if slug:
            aliases[slug.lower()].append(slug)
    return {key: sorted(set(value)) for key, value in sorted(aliases.items())}


def finalize_history(cases: list[dict[str, Any]], reports_root: Path, imported_roots: list[str] | None = None) -> dict[str, Any]:
    cases = sorted(cases, key=lambda item: (str(item.get("date", "")), str(item.get("slug", "")), str(item.get("sourceName", ""))))
    return {
        "schema": "ai-product-scout-history.v1",
        "generatedAt": "",
        "reportsRoot": str(reports_root),
        "importedReportsRoots": sorted(set(imported_roots or [])),
        "caseCount": len(cases),
        "cases": cases,
        "aliases": build_aliases(cases),
    }


def semantic_history(history: dict[str, Any]) -> dict[str, Any]:
    comparable = dict(history)
    comparable.pop("generatedAt", None)
    return comparable


def with_generated_at(history: dict[str, Any], generated_at: str) -> dict[str, Any]:
    stamped = dict(history)
    stamped["generatedAt"] = generated_at
    return stamped


def write_history_if_changed(history: dict[str, Any], output: Path) -> tuple[dict[str, Any], bool]:
    existing = load_existing_history(output)
    if existing and semantic_history(existing) == semantic_history(history):
        return existing, False

    now = datetime.now(timezone.utc)
    stamped = with_generated_at(history, now.isoformat())
    output.write_text(json.dumps(stamped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.utime(output, (now.timestamp(), now.timestamp()))
    return stamped, True


def build_history(reports_root: Path) -> dict[str, Any]:
    reports_root = reports_root.expanduser().resolve()
    by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for path in sorted(reports_root.glob("**/*.md")):
        brief_match = BRIEF_RE.match(path.name)
        article_match = ARTICLE_RE.match(path.name)
        if not brief_match and not article_match:
            continue
        slug = (brief_match or article_match).group("slug")  # type: ignore[union-attr]
        date = case_date(path)
        key = (date, slug)
        item = by_key.setdefault(
            key,
            {
                "date": date,
                "slug": slug,
                "productName": "",
                "url": "",
                "articleTitle": "",
                "sourceRoot": str(reports_root),
                "sourceName": "current",
                "files": {},
            },
        )
        text = read_text(path)
        if brief_match:
            product = clean_product_name(first_match(text, FIELD_PATTERNS["productName"]))
            if product and not item["productName"]:
                item["productName"] = product
            url = first_url(text)
            if url and not item["url"]:
                item["url"] = url
        if article_match:
            title = article_title(path)
            if title:
                item["articleTitle"] = title
        item["files"] = collect_related_files(reports_root, date, slug)

    cases = [enrich_item(item, reports_root) for item in by_key.values()]
    return finalize_history(cases, reports_root)


def load_existing_history(output_path: Path) -> dict[str, Any] | None:
    if not output_path.exists():
        return None
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def merge_existing_history(current_history: dict[str, Any], existing_history: dict[str, Any] | None, reports_root: Path) -> dict[str, Any]:
    reports_root = reports_root.expanduser().resolve()
    current_cases = [enrich_item(dict(item), reports_root) for item in current_history.get("cases", [])]
    current_root = str(reports_root)
    preserved_cases: list[dict[str, Any]] = []
    imported_roots = set(current_history.get("importedReportsRoots") or [])

    if existing_history:
        imported_roots.update(existing_history.get("importedReportsRoots") or [])
        for item in existing_history.get("cases", []):
            if not isinstance(item, dict):
                continue
            source_root = str(item.get("sourceRoot") or existing_history.get("reportsRoot") or "")
            if source_root == current_root or item.get("sourceName") == "current":
                continue
            preserved = enrich_item(item)
            preserved_cases.append(preserved)
            if source_root:
                imported_roots.add(source_root)

    combined: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in preserved_cases + current_cases:
        key = (str(item.get("sourceRoot", "")), str(item.get("date", "")), str(item.get("slug", "")))
        combined[key] = item
    imported_roots.discard(current_root)
    return finalize_history(list(combined.values()), reports_root, sorted(imported_roots))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports_root", nargs="?", default="reports", help="Reports directory to scan.")
    parser.add_argument("--output", help="Output JSON path. Defaults to <reports_root>/ai-product-scout-history.json.")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the output with only the scanned reports root instead of merging existing imported history.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports_root = Path(args.reports_root).expanduser().resolve()
    output = Path(args.output).expanduser() if args.output else reports_root / "ai-product-scout-history.json"
    current_history = build_history(reports_root)
    existing_history = None if args.replace else load_existing_history(output)
    history = merge_existing_history(current_history, existing_history, reports_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    history, changed = write_history_if_changed(history, output)
    print(json.dumps({"ok": True, "output": str(output), "caseCount": history["caseCount"], "changed": changed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
