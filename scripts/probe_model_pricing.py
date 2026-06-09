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
    return price_values_in_text(window, currency)


def price_values_in_text(text: str, currency: str = "$") -> list[float]:
    escaped = re.escape(currency)
    return [float(value) for value in re.findall(rf"{escaped}\s*(\d+(?:\.\d+)?)", text)]


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
    results: list[PriceProbeResult] = []
    lines = text.splitlines()
    for model, index in gemini_model_anchors(lines):
        window = gemini_standard_price_window(lines[index : index + 100])
        input_price = first_price_after_label(window, "Input price")
        output_price = first_price_after_label(window, "Output price")
        if input_price is None or output_price is None:
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
    if not results:
        results.append(PriceProbeResult("gemini", "*", url, False, error="prices not found"))
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
    lines = text.splitlines()
    models = deepseek_model_names(text)
    if not models:
        return [PriceProbeResult("deepseek", "*", url, False, error="model names not found")]
    cache_hit_prices = deepseek_prices_for_row(lines, "CACHE HIT", len(models))
    cache_miss_prices = deepseek_prices_for_row(lines, "CACHE MISS", len(models))
    output_prices = deepseek_prices_for_row(lines, "OUTPUT TOKENS", len(models))
    if cache_hit_prices is None or cache_miss_prices is None or output_prices is None:
        return [PriceProbeResult("deepseek", "*", url, False, error="prices not found")]
    return [
        PriceProbeResult(
            provider="deepseek",
            model=model,
            source_url=url,
            ok=True,
            currency="USD",
            input_per_million=cache_miss_prices[index],
            output_per_million=output_prices[index],
            cache_hit_input_per_million=cache_hit_prices[index],
            note="cache miss input price is used as default input price",
        )
        for index, model in enumerate(models)
    ]


def gemini_model_anchors(lines: list[str]) -> list[tuple[str, int]]:
    anchors: list[tuple[str, int]] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        for model in re.findall(r"\bgemini-[a-z0-9][a-z0-9.-]*\b", line, re.I):
            model = model.lower()
            if model in seen:
                continue
            seen.add(model)
            anchors.append((model, index))
    return anchors


def gemini_standard_price_window(lines: list[str]) -> list[str]:
    start = next((index for index, line in enumerate(lines) if line == "Standard"), 0)
    stop = next(
        (
            index
            for index, line in enumerate(lines[start + 1 :], start + 1)
            if line in {"Batch", "Flex", "Priority"}
        ),
        len(lines),
    )
    return lines[start:stop]


def deepseek_model_names(text: str) -> list[str]:
    start = text.find("MODEL")
    stop = text.find("BASE URL", start)
    if start < 0:
        start = 0
    if stop < 0:
        stop = text.find("PRICING", start)
    window = text[start:stop] if stop >= 0 else text[start : start + 1000]
    seen: set[str] = set()
    models: list[str] = []
    for model in re.findall(r"\bdeepseek-v[0-9][a-z0-9.-]*\b", window, re.I):
        model = model.lower()
        if model in seen:
            continue
        seen.add(model)
        models.append(model)
    return models


def deepseek_prices_for_row(lines: list[str], label: str, expected_count: int) -> list[float] | None:
    try:
        pricing_index = next(index for index, line in enumerate(lines) if "PRICING" in line)
    except StopIteration:
        pricing_index = 0
    for index, line in enumerate(lines[pricing_index : pricing_index + 40], pricing_index):
        if label not in line:
            continue
        values = price_values_in_text(" ".join(lines[index : index + expected_count + 2]), "$")
        if len(values) >= expected_count:
            return values[:expected_count]
    return None


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
