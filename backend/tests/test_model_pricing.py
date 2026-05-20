import json
from types import SimpleNamespace

import pytest

from app.core.model_pricing import (
    CNY_USD_FX_URL,
    CLAUDE_PRICING_URL,
    DEEPSEEK_PRICING_URL,
    GEMINI_PRICING_URL,
    KIMI_K25_PRICING_URL,
    KIMI_K26_PRICING_URL,
    QWEN_PRICING_URL,
    ModelPricingService,
    PricingCatalog,
    ModelPrice,
    parse_claude_prices,
    parse_deepseek_prices,
    parse_gemini_prices,
    parse_kimi_prices,
    parse_qwen_prices,
)
from app.core.toolkits.pricing import PricingToolkit


def test_pricing_parsers_extract_supported_model_prices():
    gemini_prices = parse_gemini_prices("""
    gemini-3.1-flash-lite
    Input price
    Free of charge
    $0.25 (text / image / video)
    Output price (including thinking tokens)
    Free of charge
    $1.50
    gemini-3-flash-preview
    Input price
    Free of charge
    $0.50 (text / image / video)
    Output price (including thinking tokens)
    Free of charge
    $3.00
    gemini-3.1-pro-preview
    Input price
    Not available
    $2.00, prompts
    $4.00, prompts > 200k tokens
    Output price (including thinking tokens)
    Not available
    $12.00, prompts
    """)
    assert {price.model_id: price.input_per_million for price in gemini_prices} == {
        "gemini:gemini-3.1-flash-lite": 0.25,
        "gemini:gemini-3-flash-preview": 0.5,
        "gemini:gemini-3.1-pro-preview": 2.0,
    }
    assert gemini_prices[0].output_per_million == 1.5

    claude_prices = parse_claude_prices("""
    Claude Opus 4.6  | $5 / MTok  | $6.25 / MTok  | $10 / MTok  | $0.50 / MTok  | $25 / MTok
    Claude Sonnet 4.6  | $3 / MTok  | $3.75 / MTok  | $6 / MTok  | $0.30 / MTok  | $15 / MTok
    Claude Haiku 4.5  | $1 / MTok  | $1.25 / MTok  | $2 / MTok  | $0.10 / MTok  | $5 / MTok
    """)
    assert {price.model_id: price.output_per_million for price in claude_prices} == {
        "anthropic:claude-opus-4.6": 25.0,
        "anthropic:claude-sonnet-4.6": 15.0,
        "anthropic:claude-haiku-4.5": 5.0,
    }

    kimi_prices = parse_kimi_prices("""
    rows: [["kimi-k2.6", "1M tokens", "¥1.10", "¥6.50", "¥27.00", "262,144 tokens"]]
    rows: [["kimi-k2.5", "1M tokens", "¥0.70", "¥4.00", "¥21.00", "262,144 tokens"]]
    """)
    assert kimi_prices[0].model_id == "kimi:kimi-k2.6"
    assert kimi_prices[0].currency == "CNY"
    assert kimi_prices[0].cache_hit_input_per_million == 1.1
    assert kimi_prices[0].input_per_million == 6.5
    assert kimi_prices[0].output_per_million == 27.0

    deepseek_prices = parse_deepseek_prices("""
    PRICING
    1M INPUT TOKENS (CACHE HIT)
    $0.0028
    $0.003625 (75% off)
    $0.0145
    1M INPUT TOKENS (CACHE MISS)
    $0.14
    $0.435 (75% off)
    $1.74
    1M OUTPUT TOKENS
    $0.28
    $0.87 (75% off)
    $3.48
    """)
    assert deepseek_prices[0].model_id == "deepseek:deepseek-v4-flash"
    assert deepseek_prices[0].input_per_million == 0.14
    assert deepseek_prices[1].model_id == "deepseek:deepseek-v4-pro"
    assert deepseek_prices[1].output_per_million == 0.87

    qwen_prices = parse_qwen_prices("""
    qwen3.6-plus
    0<Token≤256K
    2
    元
    12
    元
    12
    元
    qwen-plus
    0<Token≤128K
    0.8
    元
    2
    元
    8
    元
    qwen-max
    无阶梯计价
    2.4
    元
    9.6
    元
    """)
    assert {price.model_id: price.output_per_million for price in qwen_prices} == {
        "qwen:qwen3.6-plus": 12.0,
        "qwen:qwen-plus": 2.0,
        "qwen:qwen-max": 9.6,
    }


def test_refresh_converts_qwen_cny_prices_to_usd():
    pages = {
        CNY_USD_FX_URL: json.dumps({"date": "2026-05-13", "rates": {"USD": 0.14}}),
        GEMINI_PRICING_URL: """
        gemini-3.1-flash-lite
        Input price
        $0.25
        Output price
        $1.50
        gemini-3-flash-preview
        Input price
        $0.50
        Output price
        $3.00
        gemini-3.1-pro-preview
        Input price
        $2.00
        Output price
        $12.00
        """,
        CLAUDE_PRICING_URL: "Claude Sonnet 4.6 | $3 / MTok | $3.75 / MTok | $6 / MTok | $0.30 / MTok | $15 / MTok",
        KIMI_K26_PRICING_URL: 'rows: [["kimi-k2.6", "1M tokens", "¥1.10", "¥6.50", "¥27.00", "262,144 tokens"]]',
        KIMI_K25_PRICING_URL: 'rows: [["kimi-k2.5", "1M tokens", "¥0.70", "¥4.00", "¥21.00", "262,144 tokens"]]',
        DEEPSEEK_PRICING_URL: "PRICING $0.0028 $0.003625 $0.0145 $0.14 $0.435 $1.74 $0.28 $0.87 $3.48",
        QWEN_PRICING_URL: "qwen3.6-plus\n2\n元\n12\n元\nqwen-plus\n0.8\n元\n2\n元\nqwen-max\n2.4\n元\n9.6\n元",
    }
    service = ModelPricingService(fetch_text=lambda url: pages[url])

    catalog = service._refresh_sync()

    qwen_price = catalog.models["qwen:qwen3.6-plus"]
    assert qwen_price.currency == "USD"
    assert qwen_price.source_currency == "CNY"
    assert qwen_price.input_per_million == 0.28
    assert qwen_price.output_per_million == 1.68
    assert qwen_price.fx_rate == 0.14

    kimi_price = catalog.models["kimi:kimi-k2.6"]
    assert kimi_price.currency == "USD"
    assert kimi_price.source_currency == "CNY"
    assert kimi_price.input_per_million == 0.91
    assert kimi_price.output_per_million == 3.78
    assert kimi_price.source_url == KIMI_K26_PRICING_URL


def test_calculate_cost_marks_missing_pricing_incomplete():
    service = ModelPricingService(enabled=False)
    service._catalog = PricingCatalog(
        status="ready",
        refreshed_at="2026-05-13T10:00:00Z",
        models={
            "gemini:gemini-3-flash-preview": ModelPrice(
                currency="USD",
                input_per_million=0.5,
                output_per_million=3.0,
                source_currency="USD",
                source_input_per_million=0.5,
                source_output_per_million=3.0,
                source_url="https://example.test/gemini",
            )
        },
    )
    usage = {
        "version": 1,
        "request": {
            "total": {"input_tokens": 3000, "output_tokens": 1000, "total_tokens": 4000},
            "by_model": {
                "gemini:gemini-3-flash-preview": {
                    "input_tokens": 2000,
                    "output_tokens": 500,
                    "total_tokens": 2500,
                    "request_count": 2,
                },
                "custom:unknown": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "total_tokens": 1500,
                    "request_count": 1,
                },
            },
        },
        "classifier": {
            "model": "gemini:gemini-3-flash-preview",
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
            "request_count": 1,
        },
    }

    cost = service.calculate_cost(usage)

    assert cost["complete"] is False
    assert cost["missing_pricing"] == ["custom:unknown"]
    assert cost["request"]["by_model"]["gemini:gemini-3-flash-preview"]["total_cost"] == 0.0025
    assert cost["classifier"]["total_cost"] == 0.0008
    assert cost["total"]["total_cost"] == 0.0033


@pytest.mark.asyncio
async def test_start_waits_for_initial_refresh_before_returning():
    pages = {
        CNY_USD_FX_URL: json.dumps({"date": "2026-05-13", "rates": {"USD": 0.14}}),
        GEMINI_PRICING_URL: """
        gemini-3.1-flash-lite
        Input price
        $0.25
        Output price
        $1.50
        gemini-3-flash-preview
        Input price
        $0.50
        Output price
        $3.00
        gemini-3.1-pro-preview
        Input price
        $2.00
        Output price
        $12.00
        """,
        CLAUDE_PRICING_URL: "",
        KIMI_K26_PRICING_URL: "",
        KIMI_K25_PRICING_URL: "",
        DEEPSEEK_PRICING_URL: "",
        QWEN_PRICING_URL: "",
    }
    fetched_urls: list[str] = []

    def fetch_text(url: str) -> str:
        fetched_urls.append(url)
        return pages[url]

    service = ModelPricingService(
        fetch_text=fetch_text,
        refresh_interval_seconds=60 * 60,
    )

    await service.start()
    try:
        assert service.catalog.status == "ready"
        assert "gemini:gemini-3-flash-preview" in service.catalog.models
        assert GEMINI_PRICING_URL in fetched_urls
    finally:
        await service.shutdown()


@pytest.mark.asyncio
async def test_pricing_tool_returns_cached_model_price():
    service = ModelPricingService(enabled=False)
    service._catalog = PricingCatalog(
        status="ready",
        refreshed_at="2026-05-13T10:00:00Z",
        models={
            "gemini:gemini-3-flash-preview": ModelPrice(
                currency="USD",
                input_per_million=0.5,
                output_per_million=3.0,
                source_currency="USD",
                source_input_per_million=0.5,
                source_output_per_million=3.0,
                source_url="https://ai.google.dev/gemini-api/docs/pricing",
            )
        },
    )
    ctx = SimpleNamespace(deps=SimpleNamespace(model_pricing_service=service))

    result = await PricingToolkit.get_model_pricing(ctx, "gemini:gemini-3-flash-preview")

    assert result["found"] is True
    assert result["model_id"] == "gemini:gemini-3-flash-preview"
    assert result["price"]["input_per_million"] == 0.5


@pytest.mark.asyncio
async def test_pricing_tool_lists_available_models_for_missing_model():
    service = ModelPricingService(enabled=False)
    service._catalog = PricingCatalog(
        status="ready",
        refreshed_at="2026-05-13T10:00:00Z",
        models={
            "qwen:qwen3.6-plus": ModelPrice(
                currency="USD",
                input_per_million=0.29446,
                output_per_million=1.76676,
                source_currency="CNY",
                source_input_per_million=2.0,
                source_output_per_million=12.0,
                fx_rate=0.14723,
                source_url="https://help.aliyun.com/zh/model-studio/model-pricing",
            )
        },
    )
    ctx = SimpleNamespace(deps=SimpleNamespace(model_pricing_service=service))

    result = await PricingToolkit.get_model_pricing(ctx, "unknown:model")

    assert result["found"] is False
    assert result["available_models"] == ["qwen:qwen3.6-plus"]
