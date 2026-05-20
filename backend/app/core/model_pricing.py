from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)

MILLION_TOKENS = 1_000_000
REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
HTTP_TIMEOUT_SECONDS = 20

GEMINI_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"
CLAUDE_PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
KIMI_K26_PRICING_URL = "https://platform.kimi.com/docs/pricing/chat-k26"
KIMI_K25_PRICING_URL = "https://platform.kimi.com/docs/pricing/chat-k25"
KIMI_PRICING_URL = KIMI_K26_PRICING_URL
DEEPSEEK_PRICING_URL = "https://api-docs.deepseek.com/quick_start/pricing/"
QWEN_PRICING_URL = "https://help.aliyun.com/zh/model-studio/model-pricing"
CNY_USD_FX_URL = "https://api.frankfurter.dev/v1/latest?base=CNY&symbols=USD"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )
}


@dataclass(frozen=True)
class FxRate:
    rate: float
    source: str
    source_url: str
    date: str
    fetched_at: str
    stale: bool = False

    def snapshot(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ModelPrice:
    currency: str
    input_per_million: float
    output_per_million: float
    source_currency: str
    source_input_per_million: float
    source_output_per_million: float
    source_url: str
    cache_hit_input_per_million: float | None = None
    fx_rate: float | None = None
    pricing_note: str | None = None

    def snapshot(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class PricingCatalog:
    version: int = 1
    status: str = "empty"
    refreshed_at: str | None = None
    expires_at: str | None = None
    fx: dict[str, FxRate] = field(default_factory=dict)
    models: dict[str, ModelPrice] = field(default_factory=dict)
    refresh_errors: list[dict[str, object]] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        return {
            "version": self.version,
            "status": self.status,
            "refreshed_at": self.refreshed_at,
            "expires_at": self.expires_at,
            "fx": {key: rate.snapshot() for key, rate in self.fx.items()},
            "models": {key: price.snapshot() for key, price in self.models.items()},
            "refresh_errors": self.refresh_errors,
        }


@dataclass(frozen=True)
class RawPrice:
    model_id: str
    input_per_million: float
    output_per_million: float
    currency: str
    source_url: str
    cache_hit_input_per_million: float | None = None
    pricing_note: str | None = None


class ModelPricingService:
    """Maintain an in-memory model pricing catalog and estimate run costs."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        refresh_interval_seconds: int = REFRESH_INTERVAL_SECONDS,
        fetch_text: Callable[[str], str] | None = None,
    ) -> None:
        self._enabled = enabled
        self._refresh_interval_seconds = refresh_interval_seconds
        self._fetch_text = fetch_text or self._fetch_text_with_requests
        self._catalog = PricingCatalog()
        self._refresh_task: asyncio.Task[None] | None = None

    @property
    def catalog(self) -> PricingCatalog:
        return self._catalog

    async def start(self) -> None:
        if not self._enabled or self._refresh_task is not None:
            return
        await self._refresh_once()
        self._refresh_task = asyncio.create_task(self._refresh_loop(), name="model-pricing-refresh")

    async def shutdown(self) -> None:
        if self._refresh_task is None:
            return
        self._refresh_task.cancel()
        try:
            await self._refresh_task
        except asyncio.CancelledError:
            pass
        self._refresh_task = None

    async def refresh(self) -> PricingCatalog:
        catalog = await asyncio.to_thread(self._refresh_sync)
        self._catalog = catalog
        return catalog

    def calculate_cost(self, usage: dict[str, object] | None) -> dict[str, object] | None:
        if not isinstance(usage, dict):
            return None

        computed_at = _utc_now_text()
        catalog = self._catalog
        request_cost = self._calculate_request_cost(usage)
        classifier_cost = self._calculate_classifier_cost(usage)
        missing_pricing = sorted(set(request_cost["missing_pricing"] + classifier_cost["missing_pricing"]))

        total_input_cost = _round_cost(request_cost["total"]["input_cost"] + classifier_cost["input_cost"])
        total_output_cost = _round_cost(request_cost["total"]["output_cost"] + classifier_cost["output_cost"])
        cost: dict[str, object] = {
            "version": 1,
            "currency": "USD",
            "complete": not missing_pricing,
            "estimated": True,
            "computed_at": computed_at,
            "pricing_refreshed_at": catalog.refreshed_at,
            "total": {
                "input_cost": total_input_cost,
                "output_cost": total_output_cost,
                "total_cost": _round_cost(total_input_cost + total_output_cost),
            },
            "request": {
                "total": request_cost["total"],
                "by_model": request_cost["by_model"],
            },
            "missing_pricing": missing_pricing,
        }
        if classifier_cost["included"]:
            cost["classifier"] = classifier_cost["payload"]
        if catalog.fx:
            cost["fx"] = {
                key: {
                    "rate": value.rate,
                    "date": value.date,
                    "source": value.source,
                    "stale": value.stale,
                }
                for key, value in catalog.fx.items()
            }
        return cost

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(self._refresh_interval_seconds)
            await self._refresh_once()

    async def _refresh_once(self) -> None:
        try:
            logger.info({"message": {"event": "model_pricing_refresh_started"}})
            catalog = await self.refresh()
            logger.info({
                "message": {
                    "event": "model_pricing_refresh_finished",
                    "status": catalog.status,
                    "model_count": len(catalog.models),
                    "error_count": len(catalog.refresh_errors),
                    "refreshed_at": catalog.refreshed_at,
                }
            })
        except Exception as exc:
            logger.warning({
                "message": {
                    "event": "model_pricing_refresh_failed",
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                }
            })

    def _refresh_sync(self) -> PricingCatalog:
        refreshed_at = datetime.now(timezone.utc)
        expires_at = refreshed_at + timedelta(seconds=self._refresh_interval_seconds)
        errors: list[dict[str, object]] = []

        fx: dict[str, FxRate] = {}
        cny_usd = self._fetch_cny_usd_fx(previous=self._catalog.fx.get("CNY_USD"), errors=errors)
        if cny_usd is not None:
            fx["CNY_USD"] = cny_usd

        raw_prices: list[RawPrice] = []
        parser_specs: list[tuple[str, str, Callable[[str], list[RawPrice]]]] = [
            ("gemini", GEMINI_PRICING_URL, parse_gemini_prices),
            ("claude", CLAUDE_PRICING_URL, parse_claude_prices),
            ("kimi", KIMI_K26_PRICING_URL, parse_kimi_prices),
            ("kimi", KIMI_K25_PRICING_URL, parse_kimi_prices),
            ("deepseek", DEEPSEEK_PRICING_URL, parse_deepseek_prices),
            ("qwen", QWEN_PRICING_URL, parse_qwen_prices),
        ]
        for provider, url, parser in parser_specs:
            try:
                raw_prices.extend(parser(self._fetch_text(url)))
            except Exception as exc:
                errors.append({
                    "provider": provider,
                    "source_url": url,
                    "error": str(exc),
                    "error_type": exc.__class__.__name__,
                })

        models: dict[str, ModelPrice] = {}
        for raw_price in raw_prices:
            price = self._normalize_raw_price(raw_price, cny_usd)
            if price is None:
                errors.append({
                    "provider": raw_price.model_id.split(":", 1)[0],
                    "model": raw_price.model_id,
                    "source_url": raw_price.source_url,
                    "error": f"missing FX for {raw_price.currency}",
                })
                continue
            models[raw_price.model_id] = price

        status = "ready" if models else "empty"
        return PricingCatalog(
            status=status,
            refreshed_at=_utc_text(refreshed_at),
            expires_at=_utc_text(expires_at),
            fx=fx,
            models=models,
            refresh_errors=errors,
        )

    def _fetch_cny_usd_fx(self, *, previous: FxRate | None, errors: list[dict[str, object]]) -> FxRate | None:
        try:
            payload = json.loads(self._fetch_text(CNY_USD_FX_URL))
            rate = float(payload["rates"]["USD"])
            return FxRate(
                rate=rate,
                source="frankfurter",
                source_url=CNY_USD_FX_URL,
                date=str(payload.get("date") or ""),
                fetched_at=_utc_now_text(),
            )
        except Exception as exc:
            errors.append({
                "provider": "fx",
                "source_url": CNY_USD_FX_URL,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
            })
            if previous is None:
                return None
            return FxRate(
                rate=previous.rate,
                source=previous.source,
                source_url=previous.source_url,
                date=previous.date,
                fetched_at=previous.fetched_at,
                stale=True,
            )

    @staticmethod
    def _fetch_text_with_requests(url: str) -> str:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _normalize_raw_price(raw_price: RawPrice, cny_usd: FxRate | None) -> ModelPrice | None:
        if raw_price.currency == "USD":
            fx_rate = None
            input_per_million = raw_price.input_per_million
            output_per_million = raw_price.output_per_million
            cache_hit_input = raw_price.cache_hit_input_per_million
        elif raw_price.currency == "CNY":
            if cny_usd is None:
                return None
            fx_rate = cny_usd.rate
            input_per_million = raw_price.input_per_million * fx_rate
            output_per_million = raw_price.output_per_million * fx_rate
            cache_hit_input = (
                raw_price.cache_hit_input_per_million * fx_rate
                if raw_price.cache_hit_input_per_million is not None
                else None
            )
        else:
            return None

        return ModelPrice(
            currency="USD",
            input_per_million=_round_price(input_per_million),
            output_per_million=_round_price(output_per_million),
            cache_hit_input_per_million=_round_price(cache_hit_input) if cache_hit_input is not None else None,
            source_currency=raw_price.currency,
            source_input_per_million=raw_price.input_per_million,
            source_output_per_million=raw_price.output_per_million,
            fx_rate=fx_rate,
            source_url=raw_price.source_url,
            pricing_note=raw_price.pricing_note,
        )

    def _calculate_request_cost(self, usage: dict[str, object]) -> dict[str, Any]:
        request = usage.get("request")
        by_model = request.get("by_model") if isinstance(request, dict) else None
        output_by_model: dict[str, object] = {}
        missing_pricing: list[str] = []
        input_cost_total = 0.0
        output_cost_total = 0.0

        if isinstance(by_model, dict):
            for model_id, model_usage in by_model.items():
                if not isinstance(model_id, str) or not isinstance(model_usage, dict):
                    continue
                price = self._catalog.models.get(model_id)
                if price is None:
                    missing_pricing.append(model_id)
                    continue
                payload = _calculate_model_cost_payload(
                    usage=model_usage,
                    price=price,
                    model_id=model_id,
                )
                output_by_model[model_id] = payload
                input_cost_total += float(payload["input_cost"])
                output_cost_total += float(payload["output_cost"])

        input_cost_total = _round_cost(input_cost_total)
        output_cost_total = _round_cost(output_cost_total)
        return {
            "total": {
                "input_cost": input_cost_total,
                "output_cost": output_cost_total,
                "total_cost": _round_cost(input_cost_total + output_cost_total),
            },
            "by_model": output_by_model,
            "missing_pricing": missing_pricing,
        }

    def _calculate_classifier_cost(self, usage: dict[str, object]) -> dict[str, Any]:
        classifier = usage.get("classifier")
        if not isinstance(classifier, dict):
            return {
                "included": False,
                "input_cost": 0.0,
                "output_cost": 0.0,
                "payload": None,
                "missing_pricing": [],
            }

        model_id = classifier.get("model")
        if not isinstance(model_id, str) or not model_id:
            return {
                "included": False,
                "input_cost": 0.0,
                "output_cost": 0.0,
                "payload": None,
                "missing_pricing": [],
            }

        price = self._catalog.models.get(model_id)
        if price is None:
            return {
                "included": False,
                "input_cost": 0.0,
                "output_cost": 0.0,
                "payload": None,
                "missing_pricing": [model_id],
            }

        payload = _calculate_model_cost_payload(usage=classifier, price=price, model_id=model_id)
        payload["model"] = model_id
        return {
            "included": True,
            "input_cost": float(payload["input_cost"]),
            "output_cost": float(payload["output_cost"]),
            "payload": payload,
            "missing_pricing": [],
        }


def parse_gemini_prices(raw_html: str) -> list[RawPrice]:
    text = _html_to_text(raw_html)
    lines = text.splitlines()
    results: list[RawPrice] = []
    for model_name in [
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
    ]:
        window = _window_after_exact_line(lines, model_name, 80)
        input_price = _first_price_after_label(window, "Input price", "$")
        output_price = _first_price_after_label(window, "Output price", "$")
        if input_price is None or output_price is None:
            raise ValueError(f"Could not parse Gemini pricing for {model_name}")
        results.append(
            RawPrice(
                model_id=f"gemini:{model_name}",
                input_per_million=input_price,
                output_per_million=output_price,
                currency="USD",
                source_url=GEMINI_PRICING_URL,
                pricing_note="standard text tier; pro uses the first <=200k tier",
            )
        )
    return results


def parse_claude_prices(raw_html: str) -> list[RawPrice]:
    text = _html_to_text(raw_html)
    lines = text.splitlines()
    targets = {
        "claude-opus-4.6": "Claude Opus 4.6",
        "claude-sonnet-4.6": "Claude Sonnet 4.6",
        "claude-haiku-4.5": "Claude Haiku 4.5",
        "claude-3-5-sonnet-latest": "Claude Sonnet 3.5",
    }
    results: list[RawPrice] = []
    for model_id, label in targets.items():
        try:
            index = next(i for i, line in enumerate(lines) if line.startswith(label))
        except StopIteration:
            continue
        row = lines[index]
        if len(re.findall(r"\$(\d+(?:\.\d+)?)\s*/\s*MTok", row)) < 2:
            row = " ".join(lines[index : index + 8])
        prices = [float(value) for value in re.findall(r"\$(\d+(?:\.\d+)?)\s*/\s*MTok", row)]
        if len(prices) < 2:
            continue
        output_price = prices[4] if len(prices) >= 5 else prices[-1]
        results.append(
            RawPrice(
                model_id=f"anthropic:{model_id}",
                input_per_million=prices[0],
                output_per_million=output_price,
                currency="USD",
                source_url=CLAUDE_PRICING_URL,
                pricing_note="Claude API 1P global pricing",
            )
        )
    if not results:
        raise ValueError("Could not parse any Claude pricing rows")
    return results


def parse_kimi_prices(raw_html: str) -> list[RawPrice]:
    results: list[RawPrice] = []
    source_urls = {
        "kimi-k2.6": KIMI_K26_PRICING_URL,
        "kimi-k2.5": KIMI_K25_PRICING_URL,
    }
    for model_name, source_url in source_urls.items():
        prices = _kimi_cny_prices_for_model(raw_html, model_name)
        if prices is None:
            continue
        cache_hit, input_price, output_price = prices
        results.append(
            RawPrice(
                model_id=f"kimi:{model_name}",
                input_per_million=input_price,
                output_per_million=output_price,
                cache_hit_input_per_million=cache_hit,
                currency="CNY",
                source_url=source_url,
                pricing_note="official Kimi model page; prices are per 1M tokens",
            )
        )
    if not results:
        raise ValueError("Could not parse any Kimi pricing rows")
    return results


def parse_deepseek_prices(raw_html: str) -> list[RawPrice]:
    text = _html_to_text(raw_html)
    amounts = _prices_after("PRICING", text, "$")
    if len(amounts) < 9:
        raise ValueError("Could not parse DeepSeek pricing table")
    return [
        RawPrice(
            model_id="deepseek:deepseek-v4-flash",
            input_per_million=amounts[3],
            output_per_million=amounts[6],
            cache_hit_input_per_million=amounts[0],
            currency="USD",
            source_url=DEEPSEEK_PRICING_URL,
            pricing_note="cache miss input price is used as default input price",
        ),
        RawPrice(
            model_id="deepseek:deepseek-v4-pro",
            input_per_million=amounts[4],
            output_per_million=amounts[7],
            cache_hit_input_per_million=amounts[1],
            currency="USD",
            source_url=DEEPSEEK_PRICING_URL,
            pricing_note="discounted official price if present on page",
        ),
    ]


def parse_qwen_prices(raw_html: str) -> list[RawPrice]:
    text = _html_to_text(raw_html)
    lines = text.splitlines()
    results: list[RawPrice] = []
    for model_name in ["qwen3.6-plus", "qwen-plus", "qwen-max"]:
        window = _window_after_exact_line(lines, model_name, 80)
        values = _cny_price_values_from_lines(window)
        if len(values) < 2:
            raise ValueError(f"Could not parse Qwen pricing for {model_name}")
        results.append(
            RawPrice(
                model_id=f"qwen:{model_name}",
                input_per_million=values[0],
                output_per_million=values[1],
                currency="CNY",
                source_url=QWEN_PRICING_URL,
                pricing_note="China mainland lowest context tier; non-thinking output price",
            )
        )
    return results


def _calculate_model_cost_payload(*, usage: dict[str, object], price: ModelPrice, model_id: str) -> dict[str, object]:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    input_cost = _round_cost(input_tokens / MILLION_TOKENS * price.input_per_million)
    output_cost = _round_cost(output_tokens / MILLION_TOKENS * price.output_per_million)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "request_count": int(usage.get("request_count") or 0),
        "input_per_million": price.input_per_million,
        "output_per_million": price.output_per_million,
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": _round_cost(input_cost + output_cost),
        "pricing_source": price.source_url,
    }


def _html_to_text(raw_html: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw_html)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = html.unescape(text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _window_after_exact_line(lines: list[str], label: str, count: int) -> list[str]:
    try:
        index = next(i for i, line in enumerate(lines) if line == label)
    except StopIteration as exc:
        raise ValueError(f"Could not find pricing row for {label}") from exc
    return lines[index : index + count]


def _first_price_after_label(lines: list[str], label: str, currency: str) -> float | None:
    try:
        index = next(i for i, line in enumerate(lines) if line.startswith(label))
    except StopIteration:
        return None
    for line in lines[index : index + 6]:
        match = re.search(rf"{re.escape(currency)}\s*(\d+(?:\.\d+)?)", line)
        if match:
            return float(match.group(1))
    return None


def _prices_after(label: str, text: str, currency: str) -> list[float]:
    index = text.find(label)
    if index < 0:
        return []
    window = text[index : index + 5000]
    return [float(value) for value in re.findall(rf"{re.escape(currency)}\s*(\d+(?:\.\d+)?)", window)]


def _kimi_cny_prices_for_model(raw_html: str, model_name: str) -> tuple[float, float, float] | None:
    for match in re.finditer(re.escape(model_name), raw_html, re.I):
        window = raw_html[match.start() : match.start() + 3000]
        values = [
            float(value)
            for value in re.findall(r"(?:[¥￥]|\\u00a5)\s*(\d+(?:\.\d+)?)", window)
        ]
        if len(values) >= 3:
            return values[0], values[1], values[2]
    return None


def _cny_price_values_from_lines(lines: list[str]) -> list[float]:
    values: list[float] = []
    for index, line in enumerate(lines[:-1]):
        if lines[index + 1] != "元":
            continue
        match = re.fullmatch(r"(\d+(?:\.\d+)?)", line)
        if match:
            values.append(float(match.group(1)))
    return values


def _round_price(value: float) -> float:
    return round(value, 10)


def _round_cost(value: float) -> float:
    return round(value, 10)


def _utc_now_text() -> str:
    return _utc_text(datetime.now(timezone.utc))


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
