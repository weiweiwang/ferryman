from __future__ import annotations

import re
from typing import Any

from screen_stock_common import (
    ListingEntry,
    MARKET_CONFIGS,
    MarketSnapshot,
    eastmoney_price,
    eastmoney_ratio,
    normalize_currency,
    ticker_for_market,
    to_float,
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
    return MarketSnapshot(
        ticker=ticker_for_market(code, market),
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


def market_from_secucode(secucode: Any) -> str | None:
    suffix = str(secucode or "").strip().upper().split(".")[-1]
    return {"SH": "SH", "SZ": "SZ"}.get(suffix)


def parse_a_share_selector_snapshot(row: dict[str, Any]) -> MarketSnapshot | None:
    market = market_from_secucode(row.get("SECUCODE"))
    if market is None:
        return None
    code = str(row.get("SECURITY_CODE") or "").strip()
    if not code:
        return None
    return MarketSnapshot(
        ticker=ticker_for_market(code, market),
        code=code,
        name=str(row.get("SECURITY_NAME_ABBR") or code),
        market=market,
        currency=MARKET_CONFIGS[market]["currency"],
        price=to_float(row.get("NEW_PRICE")),
        pe=to_float(row.get("PE9")),
        pb=to_float(row.get("PBNEWMRQ")),
        market_cap=to_float(row.get("TOTAL_MARKET_CAP")),
        float_market_cap=None,
        industry=str(row.get("INDUSTRY") or "") or None,
        source="eastmoney_xuangu",
    )


def tencent_quote_field(fields: list[str], index: int) -> str | None:
    if len(fields) <= index:
        return None
    value = fields[index].strip()
    if value in {"", "-", "--"}:
        return None
    return value


def tencent_quote_number(fields: list[str], index: int, *, multiplier: float = 1.0) -> float | None:
    value = to_float(tencent_quote_field(fields, index))
    if value is None:
        return None
    return value * multiplier


def parse_tencent_quote_records(text: str) -> dict[str, list[str]]:
    records: dict[str, list[str]] = {}
    for match in re.finditer(r'v_([a-z]{2}\d+)="(.*?)";', text, flags=re.IGNORECASE | re.DOTALL):
        records[match.group(1).lower()] = match.group(2).split("~")
    return records


def parse_tencent_hk_snapshot(fields: list[str], listing: ListingEntry | None = None) -> MarketSnapshot | None:
    code = (tencent_quote_field(fields, 2) or (listing.code if listing else "")).zfill(5)
    if not code or not code.strip("0"):
        return None
    market_cap_100m = tencent_quote_number(fields, 44)
    if market_cap_100m is None:
        return None
    currency = normalize_currency(tencent_quote_field(fields, 75), MARKET_CONFIGS["HK"]["currency"])
    return MarketSnapshot(
        ticker=ticker_for_market(code, "HK"),
        code=code,
        name=tencent_quote_field(fields, 1) or str((listing.official_name if listing else None) or code),
        market="HK",
        currency=currency,
        price=tencent_quote_number(fields, 3),
        pe=tencent_quote_number(fields, 39),
        pb=tencent_quote_number(fields, 58),
        market_cap=market_cap_100m * 100_000_000,
        float_market_cap=tencent_quote_number(fields, 45, multiplier=100_000_000),
        industry=None,
        source="tencent_quote",
    )
