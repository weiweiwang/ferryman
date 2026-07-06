#!/usr/bin/env python3
"""Fetch Reddit RSS/Atom search results as structured JSON."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
DEFAULT_USER_AGENT = "product-opportunity-miner/0.1 (local research)"


def strip_html(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<(br|p|div|li|tr|td|/p|/div|/li|/tr|/td)\b[^>]*>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def entry_text(entry: ET.Element, name: str) -> str:
    node = entry.find(f"atom:{name}", ATOM_NS)
    return node.text.strip() if node is not None and node.text else ""


def entry_link(entry: ET.Element) -> str:
    node = entry.find("atom:link", ATOM_NS)
    return node.attrib.get("href", "") if node is not None else ""


def entry_author(entry: ET.Element) -> str:
    node = entry.find("atom:author/atom:name", ATOM_NS)
    return node.text.strip() if node is not None and node.text else ""


def entry_subreddit(entry: ET.Element, link: str) -> str:
    category = entry.find("atom:category", ATOM_NS)
    if category is not None:
        label = category.attrib.get("label") or category.attrib.get("term") or ""
        match = re.search(r"r/([^/\s]+)", label)
        if match:
            return match.group(1)
    match = re.search(r"/r/([^/]+)/", link)
    return match.group(1) if match else ""


def build_url(query: str, subreddit: str | None, sort: str, time_filter: str | None) -> str:
    params = {"q": query, "sort": sort}
    if time_filter:
        params["t"] = time_filter
    encoded = urllib.parse.urlencode(params)
    if subreddit:
        return f"https://www.reddit.com/r/{urllib.parse.quote(subreddit)}/search.rss?{encoded}&restrict_sr=on"
    return f"https://www.reddit.com/search.rss?{encoded}"


def build_old_url(query: str, subreddit: str | None, sort: str, time_filter: str | None) -> str:
    params = {"q": query, "sort": sort}
    if time_filter:
        params["t"] = time_filter
    encoded = urllib.parse.urlencode(params)
    if subreddit:
        return f"https://old.reddit.com/r/{urllib.parse.quote(subreddit)}/search?{encoded}&restrict_sr=on"
    return f"https://old.reddit.com/search?{encoded}"


def fetch(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_feed(raw: bytes, source_url: str, limit: int, include_communities: bool) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    results = []
    seen = set()
    for entry in root.findall("atom:entry", ATOM_NS):
        link = entry_link(entry)
        if not link or link in seen:
            continue
        item_id = entry_text(entry, "id")
        if not include_communities and not item_id.startswith("t3_"):
            continue
        seen.add(link)
        content = strip_html(entry_text(entry, "content"))
        item = {
            "title": entry_text(entry, "title"),
            "url": link,
            "id": item_id,
            "subreddit": entry_subreddit(entry, link),
            "author": entry_author(entry),
            "published": entry_text(entry, "published") or entry_text(entry, "updated"),
            "updated": entry_text(entry, "updated"),
            "snippet": content,
            "source_type": "reddit_rss",
            "source_url": source_url,
        }
        results.append(item)
        if len(results) >= limit:
            break
    return results


def first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    return strip_html(match.group(1)) if match else ""


def parse_old_reddit(raw: bytes, source_url: str, limit: int, include_communities: bool) -> list[dict[str, str]]:
    page = raw.decode("utf-8", errors="replace")
    blocks = re.split(r'<div class=" search-result ', page)
    results = []
    seen = set()
    for block in blocks:
        if 'data-fullname="' not in block:
            continue
        item_id = first_match(r'data-fullname="([^"]+)"', block)
        if not include_communities and not item_id.startswith("t3_"):
            continue
        link_match = re.search(r'<a href="([^"]+)" class="search-title[^"]*"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not link_match:
            continue
        link = html.unescape(link_match.group(1))
        if link in seen:
            continue
        seen.add(link)
        item = {
            "title": strip_html(link_match.group(2)),
            "url": link.replace("https://old.reddit.com", "https://www.reddit.com"),
            "id": item_id,
            "subreddit": first_match(r'to&#32;<a href="https://old\.reddit\.com/r/([^/]+)/"', block),
            "author": first_match(r'class="author[^"]*"[^>]*>(.*?)</a>', block),
            "published": first_match(r'datetime="([^"]+)"', block),
            "updated": "",
            "snippet": first_match(r'<div class="search-result-body">(.*?)</div>\s*(?:<div|</div>)', block),
            "score": first_match(r'<span class="search-score">(.*?)</span>', block),
            "comments": first_match(r'class="search-comments[^"]*"[^>]*>(.*?)</a>', block),
            "source_type": "old_reddit_html",
            "source_url": source_url,
        }
        results.append(item)
        if len(results) >= limit:
            break
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Search Reddit RSS/Atom and emit JSON results.")
    parser.add_argument("query", help="Reddit search query")
    parser.add_argument("--subreddit", help="Restrict search to one subreddit")
    parser.add_argument("--limit", type=int, default=10, help="Maximum number of results")
    parser.add_argument("--sort", default="relevance", choices=["relevance", "hot", "top", "new", "comments"])
    parser.add_argument("--time", choices=["hour", "day", "week", "month", "year", "all"], help="Time filter")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout in seconds")
    parser.add_argument("--include-communities", action="store_true", help="Include subreddit/community results")
    parser.add_argument("--source", default="auto", choices=["auto", "rss", "old"], help="Fetch source")
    args = parser.parse_args()

    url = build_url(args.query, args.subreddit, args.sort, args.time)
    old_url = build_old_url(args.query, args.subreddit, args.sort, args.time)
    fallback_reason = ""
    try:
        if args.source == "old":
            raw = fetch(old_url, args.timeout)
            results = parse_old_reddit(raw, old_url, args.limit, args.include_communities)
            source_url = old_url
            source_type = "old_reddit_html"
        else:
            raw = fetch(url, args.timeout)
            results = parse_feed(raw, url, args.limit, args.include_communities)
            source_url = url
            source_type = "reddit_rss"
    except urllib.error.HTTPError as exc:
        if args.source == "rss":
            error = {"error": f"rss_http_{exc.code}", "source_url": url}
            print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
            return 1
        fallback_reason = f"rss_http_{exc.code}"
        try:
            raw = fetch(old_url, args.timeout)
            results = parse_old_reddit(raw, old_url, args.limit, args.include_communities)
            source_url = old_url
            source_type = "old_reddit_html"
        except Exception as fallback_exc:  # noqa: BLE001
            error = {"error": str(fallback_exc), "rss_error": fallback_reason, "source_url": old_url}
            print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
            return 1
    except Exception as exc:  # noqa: BLE001 - CLI should return a concise error.
        if args.source in {"rss", "old"}:
            source_url = url if args.source == "rss" else old_url
            print(json.dumps({"error": str(exc), "source_url": source_url}, ensure_ascii=False), file=sys.stderr)
            return 1
        fallback_reason = f"rss_error:{exc}"
        try:
            raw = fetch(old_url, args.timeout)
            results = parse_old_reddit(raw, old_url, args.limit, args.include_communities)
            source_url = old_url
            source_type = "old_reddit_html"
        except Exception as fallback_exc:  # noqa: BLE001
            error = {"error": str(fallback_exc), "rss_error": fallback_reason, "source_url": old_url}
            print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
            return 1

    payload = {"query": args.query, "source_type": source_type, "source_url": source_url, "results": results}
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
