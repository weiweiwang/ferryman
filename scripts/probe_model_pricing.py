from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}


@dataclass
class PriceProbeResult:
    provider: str
    model: str
    source_url: str
    ok: bool
    currency: str | None = None
    input_per_million: float | None = None
    output_per_million: float | None = None
    cache_hit_input_per_million: float | None = None
    note: str | None = None
    error: str | None = None


def fetch_text(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", response.text)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = html.unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def fetch_raw(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    return response.text


def prices_after(label: str, text: str, currency: str = "$") -> list[float]:
    index = text.find(label)
    if index < 0:
        return []
    window = text[index : index + 5000]
    escaped = re.escape(currency)
    return [float(value) for value in re.findall(rf"{escaped}\s*(\d+(?:\.\d+)?)", window)]


def price_on_line(line: str, currency: str = "$") -> float | None:
    match = re.search(rf"{re.escape(currency)}\s*(\d+(?:\.\d+)?)", line)
    return float(match.group(1)) if match else None


def first_price_after_label(lines: list[str], label: str, currency: str = "$") -> float | None:
    try:
        index = next(i for i, line in enumerate(lines) if line.startswith(label))
    except StopIteration:
        return None
    for line in lines[index : index + 6]:
        price = price_on_line(line, currency)
        if price is not None:
            return price
    return None


def parse_gemini(text: str) -> list[PriceProbeResult]:
    url = "https://ai.google.dev/gemini-api/docs/pricing"
    targets = [
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
    ]
    results: list[PriceProbeResult] = []
    lines = text.splitlines()
    for model in targets:
        try:
            index = next(i for i, line in enumerate(lines) if line == model)
        except StopIteration:
            results.append(PriceProbeResult("gemini", model, url, False, error="model or prices not found"))
            continue
        window = lines[index : index + 80]
        input_price = first_price_after_label(window, "Input price")
        output_price = first_price_after_label(window, "Output price")
        if input_price is None or output_price is None:
            results.append(PriceProbeResult("gemini", model, url, False, error="prices not found"))
            continue
        results.append(
            PriceProbeResult(
                provider="gemini",
                model=model,
                source_url=url,
                ok=True,
                currency="USD",
                input_per_million=input_price,
                output_per_million=output_price,
                note="standard text tier; pro uses the first <=200k tier",
            )
        )
    return results


def parse_claude(text: str) -> list[PriceProbeResult]:
    url = "https://platform.claude.com/docs/en/about-claude/pricing"
    lines = text.splitlines()
    targets = {
        "claude-opus-4.6": "Claude Opus 4.6",
        "claude-sonnet-4.6": "Claude Sonnet 4.6",
        "claude-haiku-4.5": "Claude Haiku 4.5",
    }
    results: list[PriceProbeResult] = []
    for model, label in targets.items():
        row = next((line for line in lines if line.startswith(label)), "")
        if len(re.findall(r"\$(\d+(?:\.\d+)?)\s*/\s*MTok", row)) < 2:
            index = next((i for i, line in enumerate(lines) if line.startswith(label)), -1)
            row = " ".join(lines[index : index + 8]) if index >= 0 else row
        prices = [float(value) for value in re.findall(r"\$(\d+(?:\.\d+)?)\s*/\s*MTok", row)]
        if len(prices) < 2:
            results.append(PriceProbeResult("claude", model, url, False, error="prices not found"))
            continue
        output_price = prices[4] if len(prices) >= 5 else prices[-1]
        results.append(
            PriceProbeResult(
                provider="claude",
                model=model,
                source_url=url,
                ok=True,
                currency="USD",
                input_per_million=prices[0],
                output_per_million=output_price,
            )
        )
    return results


def parse_kimi(text: str) -> list[PriceProbeResult]:
    results: list[PriceProbeResult] = []
    source_urls = {
        "kimi-k2.6": "https://platform.kimi.com/docs/pricing/chat-k26",
        "kimi-k2.5": "https://platform.kimi.com/docs/pricing/chat-k25",
    }
    for model, url in source_urls.items():
        prices = None
        for match in re.finditer(re.escape(model), text, re.I):
            window = text[match.start() : match.start() + 3000]
            values = [
                float(value)
                for value in re.findall(r"(?:[¥￥]|\\u00a5)\s*(\d+(?:\.\d+)?)", window)
            ]
            if len(values) >= 3:
                prices = values[0], values[1], values[2]
                break
        if prices is None:
            results.append(PriceProbeResult("kimi", model, url, False, error="prices not found"))
            continue
        cache_hit, input_price, output_price = prices
        results.append(
            PriceProbeResult(
                provider="kimi",
                model=model,
                source_url=url,
                ok=True,
                currency="CNY",
                input_per_million=input_price,
                output_per_million=output_price,
                cache_hit_input_per_million=cache_hit,
            )
        )
    return results


def parse_deepseek(text: str) -> list[PriceProbeResult]:
    url = "https://api-docs.deepseek.com/quick_start/pricing/"
    amounts = prices_after("PRICING", text, "$")
    if len(amounts) < 9:
        return [
            PriceProbeResult("deepseek", "deepseek-v4-flash", url, False, error="prices not found"),
            PriceProbeResult("deepseek", "deepseek-v4-pro", url, False, error="prices not found"),
        ]
    return [
        PriceProbeResult(
            provider="deepseek",
            model="deepseek-v4-flash",
            source_url=url,
            ok=True,
            currency="USD",
            input_per_million=amounts[3],
            output_per_million=amounts[6],
            cache_hit_input_per_million=amounts[0],
            note="cache miss input price is used as default input price",
        ),
        PriceProbeResult(
            provider="deepseek",
            model="deepseek-v4-pro",
            source_url=url,
            ok=True,
            currency="USD",
            input_per_million=amounts[4],
            output_per_million=amounts[7],
            cache_hit_input_per_million=amounts[1],
            note="discounted official price if present on page",
        ),
    ]


def price_values_from_lines(lines: list[str]) -> list[float]:
    values: list[float] = []
    for index, line in enumerate(lines[:-1]):
        if lines[index + 1] != "元":
            continue
        match = re.fullmatch(r"(\d+(?:\.\d+)?)", line)
        if match:
            values.append(float(match.group(1)))
    return values


def parse_qwen(text: str) -> list[PriceProbeResult]:
    url = "https://help.aliyun.com/zh/model-studio/model-pricing"
    lines = text.splitlines()
    targets = ["qwen3.6-plus", "qwen-plus", "qwen-max"]
    results: list[PriceProbeResult] = []
    for model in targets:
        try:
            index = next(i for i, line in enumerate(lines) if line == model)
        except StopIteration:
            results.append(PriceProbeResult("qwen", model, url, False, error="model not found"))
            continue
        values = price_values_from_lines(lines[index : index + 40])
        if len(values) < 2:
            results.append(PriceProbeResult("qwen", model, url, False, error="prices not found"))
            continue
        results.append(
            PriceProbeResult(
                provider="qwen",
                model=model,
                source_url=url,
                ok=True,
                currency="CNY",
                input_per_million=values[0],
                output_per_million=values[1],
                note="first matching official mainland tier; qwen-plus may have separate thinking output price",
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe official LLM pricing pages with requests.")
    parser.add_argument("--provider", choices=["all", "gemini", "claude", "kimi", "deepseek", "qwen"], default="all")
    args = parser.parse_args()

    sources: dict[str, tuple[str, Any]] = {
        "gemini": ("https://ai.google.dev/gemini-api/docs/pricing", parse_gemini),
        "claude": ("https://platform.claude.com/docs/en/about-claude/pricing", parse_claude),
        "kimi": ("https://platform.kimi.com/docs/pricing/chat-k26", parse_kimi),
        "deepseek": ("https://api-docs.deepseek.com/quick_start/pricing/", parse_deepseek),
        "qwen": ("https://help.aliyun.com/zh/model-studio/model-pricing", parse_qwen),
    }
    selected = sources if args.provider == "all" else {args.provider: sources[args.provider]}

    results: list[PriceProbeResult] = []
    for provider, (url, parser_fn) in selected.items():
        try:
            if provider == "kimi":
                kimi_pages = [
                    fetch_raw("https://platform.kimi.com/docs/pricing/chat-k26"),
                    fetch_raw("https://platform.kimi.com/docs/pricing/chat-k25"),
                ]
                results.extend(parser_fn("\n".join(kimi_pages)))
            else:
                results.extend(parser_fn(fetch_text(url)))
        except Exception as exc:
            results.append(
                PriceProbeResult(
                    provider=provider,
                    model="*",
                    source_url=url,
                    ok=False,
                    error=f"{exc.__class__.__name__}: {exc}",
                )
            )

    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
