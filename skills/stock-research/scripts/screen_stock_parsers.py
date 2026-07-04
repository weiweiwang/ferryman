from __future__ import annotations

from typing import Any

from screen_stock_common import (
    MARKET_CONFIGS,
    MarketSnapshot,
    eastmoney_price,
    eastmoney_ratio,
    ticker_for_market,
    to_float,
    us_ticker_for_eastmoney_market,
)


def parse_market_snapshot(raw: dict[str, Any], market: str) -> MarketSnapshot:
    config = MARKET_CONFIGS[market]
    code = str(raw.get("f12") or "").strip()
    name = str(raw.get("f14") or code)
    currency = config["currency"]
    if market == "HK":
        if code.startswith("8") or name.endswith("-R"):
            currency = "CNY"
        elif code.startswith("9") or name.endswith("-U"):
            currency = "USD"
    ticker = us_ticker_for_eastmoney_market(code, raw.get("f13")) if market == "US" else ticker_for_market(code, market)
    return MarketSnapshot(
        ticker=ticker,
        code=code,
        name=name,
        market=market,
        currency=currency,
        price=eastmoney_price(raw.get("f2"), raw),
        pe=eastmoney_ratio(raw.get("f115") if raw.get("f115") not in (None, "-", "--") else raw.get("f9"), raw),
        pb=eastmoney_ratio(raw.get("f23"), raw),
        market_cap=to_float(raw.get("f20")),
        float_market_cap=to_float(raw.get("f21")),
        industry=str(raw.get("f100") or "") or None,
    )
