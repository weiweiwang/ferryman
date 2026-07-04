#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from screen_stock_common import (  # noqa: E402
    EASTMONEY_LIST_FIELDS,
    EASTMONEY_QUOTE_UT,
    EASTMONEY_WBP2U,
    MARKET_CONFIGS,
    MIN_FINANCIAL_YEARS,
    US_MARKET_CODE_BY_SUFFIX,
    configure_session,
    eastmoney_price,
    json_safe,
    normalize_currency,
    safe_ratio,
    to_float,
    us_ticker_for_eastmoney_market,
)
from screen_stock_parsers import parse_market_snapshot  # noqa: E402
from screen_stock_providers import fetch_financial_rows, get_json  # noqa: E402


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


EASTMONEY_ULIST_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_WEBGUEST_ULIST_URL = "https://push2.eastmoney.com/webguest/api/qt/ulist.np/get"
EASTMONEY_STOCK_GET_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EASTMONEY_QUOTE_FIELDS = f"{EASTMONEY_LIST_FIELDS},f84,f85,f116,f117"
EASTMONEY_FX_SECIDS = {
    ("USD", "CNY"): ("133.USDCNH", False),
    ("CNY", "USD"): ("133.USDCNH", True),
    ("HKD", "CNY"): ("133.HKDCNH", False),
    ("CNY", "HKD"): ("133.HKDCNH", True),
}


class StockDataError(RuntimeError):
    """Raised when Eastmoney cannot return usable stock data."""

    def __init__(
        self,
        message: str,
        phase: str = "stock_data",
        *,
        error_code: str = "stock_data_failed",
        source: str = "eastmoney",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.error_code = error_code
        self.source = source
        self.details = details or {}

    def payload(self, ticker: str) -> dict[str, Any]:
        result = {
            "ok": False,
            "phase": self.phase,
            "ticker": ticker,
            "error_code": self.error_code,
            "source": self.source,
            "error": str(self),
        }
        if self.details:
            result["details"] = json_safe(self.details)
        return result


@dataclass(frozen=True)
class SecidCandidate:
    secid: str
    market: str
    code: str


def money_value(value: Any, currency: str | None) -> dict[str, Any]:
    return {"value": json_safe(value), "currency": currency}


def normalized_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def secid_candidates_for_ticker(ticker: str) -> list[SecidCandidate]:
    normalized = normalized_ticker(ticker)
    if not normalized:
        return []

    if normalized.endswith(".SH"):
        code = normalized.removesuffix(".SH")
        return [SecidCandidate(f"{MARKET_CONFIGS['SH']['secid_prefix']}.{code}", "SH", code)]
    if normalized.endswith(".SZ"):
        code = normalized.removesuffix(".SZ")
        return [SecidCandidate(f"{MARKET_CONFIGS['SZ']['secid_prefix']}.{code}", "SZ", code)]
    if normalized.endswith(".HK"):
        code = normalized.removesuffix(".HK").zfill(5)
        return [SecidCandidate(f"{MARKET_CONFIGS['HK']['secid_prefix']}.{code}", "HK", code)]

    if "." in normalized:
        code, suffix = normalized.rsplit(".", 1)
        market_code = US_MARKET_CODE_BY_SUFFIX.get(suffix)
        if market_code:
            return [SecidCandidate(f"{market_code}.{code}", "US", code)]

    if normalized.isdigit() and len(normalized) == 6:
        market = "SH" if normalized.startswith(("5", "6", "9")) else "SZ"
        return [SecidCandidate(f"{MARKET_CONFIGS[market]['secid_prefix']}.{normalized}", market, normalized)]
    if normalized.isdigit() and len(normalized) <= 5:
        code = normalized.zfill(5)
        return [SecidCandidate(f"{MARKET_CONFIGS['HK']['secid_prefix']}.{code}", "HK", code)]

    code = normalized.split(".", 1)[0]
    return [SecidCandidate(f"{market_code}.{code}", "US", code) for market_code in ("105", "106", "107")]


def fetch_quote_row(
    ticker: str,
    *,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> tuple[SecidCandidate, dict[str, Any]]:
    candidates = secid_candidates_for_ticker(ticker)
    if not candidates:
        raise StockDataError(
            f"Ticker {ticker} is empty or invalid.",
            phase="price_quote",
            error_code="invalid_ticker",
        )

    request_errors: list[dict[str, Any]] = []
    empty_secids: list[str] = []
    for candidate in candidates:
        params = {
            "secids": candidate.secid,
            "fields": EASTMONEY_QUOTE_FIELDS,
            "fltt": 1,
            "invt": 2,
            "ut": EASTMONEY_QUOTE_UT,
            "wbp2u": EASTMONEY_WBP2U,
            "timil": 1,
            "cb": "jQuery1124",
        }
        try:
            payload = get_json(
                session,
                EASTMONEY_WEBGUEST_ULIST_URL,
                params=params,
                request_delay=request_delay,
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug("Eastmoney quote failed for %s: %s", candidate.secid, exc)
            request_errors.append(
                {
                    "secid": candidate.secid,
                    "market": candidate.market,
                    "endpoint": EASTMONEY_WEBGUEST_ULIST_URL,
                    "error": str(exc),
                }
            )
            continue
        rows = ((payload.get("data") or {}).get("diff") or [])
        if rows:
            return candidate, rows[0]
        empty_secids.append(candidate.secid)

        stock_params = {
            "secid": candidate.secid,
            "fields": EASTMONEY_QUOTE_FIELDS,
            "fltt": 1,
            "invt": 2,
            "ut": EASTMONEY_QUOTE_UT,
            "wbp2u": EASTMONEY_WBP2U,
        }
        try:
            payload = get_json(
                session,
                EASTMONEY_STOCK_GET_URL,
                params=stock_params,
                request_delay=request_delay,
                timeout=timeout,
            )
        except Exception as exc:
            logger.debug("Eastmoney stock/get failed for %s: %s", candidate.secid, exc)
            request_errors.append(
                {
                    "secid": candidate.secid,
                    "market": candidate.market,
                    "endpoint": EASTMONEY_STOCK_GET_URL,
                    "error": str(exc),
                }
            )
            continue
        row = payload.get("data") or {}
        if row:
            return candidate, row
    if request_errors:
        raise StockDataError(
            f"Eastmoney quote provider request failed for {ticker}; cannot determine whether the ticker exists.",
            phase="price_quote",
            error_code="provider_request_failed",
            details={
                "candidates": [candidate.secid for candidate in candidates],
                "empty_secids": empty_secids,
                "request_errors": request_errors,
            },
        )
    raise StockDataError(
        f"Ticker {ticker} not found in Eastmoney quote API.",
        phase="price_quote",
        error_code="quote_not_found",
        details={
            "candidates": [candidate.secid for candidate in candidates],
            "empty_secids": empty_secids,
        },
    )


def fetch_quote_snapshot(
    ticker: str,
    *,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
):
    candidate, row = fetch_quote_row(ticker, session=session, timeout=timeout, request_delay=request_delay)
    try:
        snapshot = parse_market_snapshot(row, candidate.market)
    except Exception as exc:
        raise StockDataError(
            f"Quote parse failed for {ticker}: {exc}",
            phase="price_quote",
            error_code="quote_parse_failed",
            details={"secid": candidate.secid, "market": candidate.market},
        ) from exc
    if snapshot.market == "US" and "." not in snapshot.ticker:
        snapshot.ticker = us_ticker_for_eastmoney_market(snapshot.code, row.get("f13"))
    snapshot.source = "eastmoney_quote"
    if snapshot.price is None or snapshot.price <= 0:
        raise StockDataError(
            f"Ticker {ticker} returned no usable current price.",
            phase="price_quote",
            error_code="quote_price_unavailable",
            details={"secid": candidate.secid, "market": candidate.market},
        )
    return snapshot, row


def quote_implied_shares(market_cap: Any, price: Any) -> float | None:
    market_cap_value = to_float(market_cap)
    price_value = to_float(price)
    if market_cap_value is None or price_value in (None, 0):
        return None
    return market_cap_value / price_value


def percent_to_ratio(value: Any) -> float | None:
    result = to_float(value)
    if result is None:
        return None
    return result / 100 if abs(result) > 1 else result


def sum_optional(*values: Any) -> float | None:
    present = [to_float(value) for value in values if to_float(value) is not None]
    return sum(present) if present else None


def financial_row_to_output(row: dict[str, Any]) -> dict[str, Any]:
    revenue = to_float(row.get("revenue"))
    net_income = to_float(row.get("net_profit"))
    operating_cash_flow = to_float(row.get("operating_cash_flow"))
    capex = to_float(row.get("capex"))
    free_cash_flow = to_float(row.get("free_cash_flow"))
    equity = to_float(row.get("equity"))
    total_assets = to_float(row.get("total_assets"))
    total_liabilities = to_float(row.get("total_liabilities"))
    total_debt = to_float(row.get("total_debt"))
    if total_debt is None:
        total_debt = sum_optional(row.get("short_debt"), row.get("long_debt"))
    return {
        "Year": str(row.get("year") or ""),
        "Revenue": revenue,
        "Net Income": net_income,
        "Normalized Income": to_float(row.get("normalized_income")),
        "Total Unusual Items": to_float(row.get("unusual_items")),
        "EBIT": to_float(row.get("ebit")),
        "NOPAT": to_float(row.get("nopat")),
        "Operating Cash Flow": operating_cash_flow,
        "Capex": capex,
        "Capital Expenditure": -capex if capex is not None else None,
        "Free Cash Flow": free_cash_flow,
        "ROE": percent_to_ratio(row.get("roe")),
        "ROIC": percent_to_ratio(row.get("roic")),
        "Net Margin": safe_ratio(net_income, revenue),
        "FCF Margin": safe_ratio(free_cash_flow, revenue),
        "OCF / Net Income": safe_ratio(operating_cash_flow, net_income),
        "FCF / Net Income": safe_ratio(free_cash_flow, net_income),
        "EPS": to_float(row.get("eps")),
        "Invested Capital": to_float(row.get("invested_capital")),
        "Stockholders Equity": equity,
        "Total Assets": total_assets,
        "Total Debt": total_debt,
        "Total Liabilities": total_liabilities,
        "Cash And Equivalents": to_float(row.get("cash_and_equivalents")),
        "Current Financial Assets": to_float(row.get("current_financial_assets")),
        "Noncurrent Financial Assets": to_float(row.get("noncurrent_financial_assets")),
        "Goodwill": to_float(row.get("goodwill")),
        "Goodwill And Intangibles": to_float(row.get("goodwill_and_intangibles")),
        "Accounts Receivable": to_float(row.get("accounts_receivable")),
        "Inventory": to_float(row.get("inventory")),
        "Working Capital": to_float(row.get("working_capital")),
        "Asset Impairment Charge": to_float(row.get("asset_impairment")),
        "Goodwill To Equity": safe_ratio(row.get("goodwill"), equity),
        "Receivables To Revenue": safe_ratio(row.get("accounts_receivable"), revenue),
    }


def convert_financial_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [financial_row_to_output(row) for row in rows if row.get("year")]


def financial_data_limits(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing_fields_by_year: dict[str, list[str]] = {}
    required_fields = (
        "Revenue",
        "Net Income",
        "Operating Cash Flow",
        "Capex",
        "Free Cash Flow",
        "Cash And Equivalents",
        "Total Debt",
    )
    complete_fcf_years = [
        row.get("Year")
        for row in rows
        if all(row.get(field) is not None for field in required_fields)
    ]
    for row in rows:
        missing = [field for field in required_fields if row.get(field) is None]
        if missing:
            missing_fields_by_year[str(row.get("Year"))] = missing

    has_five_years = len(complete_fcf_years) >= MIN_FINANCIAL_YEARS
    return {
        "provider": "eastmoney",
        "annualRowsReturned": len(rows),
        "annualYearsReturned": [row.get("Year") for row in rows],
        "completeFcfYearCount": len(complete_fcf_years),
        "completeFcfYearsReturned": complete_fcf_years,
        "minimumCompleteFcfYearsForFormalReport": MIN_FINANCIAL_YEARS,
        "meetsFiveYearFcfRequirement": has_five_years,
        "needsPrimarySourceForFiveYearNormalization": not has_five_years,
        "missingFieldsByYear": missing_fields_by_year,
    }


def eastmoney_fx_rate(
    from_currency: str,
    to_currency: str,
    *,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> dict[str, Any] | None:
    pair = EASTMONEY_FX_SECIDS.get((from_currency, to_currency))
    if pair is None:
        return None
    secid, invert = pair
    params = {
        "secids": secid,
        "fields": "f1,f12,f13,f14,f2,f152",
        "fltt": 1,
        "invt": 2,
        "ut": EASTMONEY_QUOTE_UT,
        "wbp2u": EASTMONEY_WBP2U,
        "timil": 1,
        "cb": "jQuery1124",
    }
    try:
        payload = get_json(
            session,
            EASTMONEY_WEBGUEST_ULIST_URL,
            params=params,
            request_delay=request_delay,
            timeout=timeout,
        )
    except Exception as exc:
        raise StockDataError(
            f"Eastmoney FX rate request failed for {from_currency}->{to_currency} ({secid}): {exc}",
            phase="fx_rate",
            error_code="fx_rate_request_failed",
            details={
                "from": from_currency,
                "to": to_currency,
                "symbol": secid,
                "endpoint": EASTMONEY_WEBGUEST_ULIST_URL,
                "error": str(exc),
            },
        ) from exc
    rows = ((payload.get("data") or {}).get("diff") or [])
    if not rows:
        raise StockDataError(
            f"Eastmoney FX rate returned no rows for {from_currency}->{to_currency} ({secid}).",
            phase="fx_rate",
            error_code="fx_rate_not_found",
            details={"from": from_currency, "to": to_currency, "symbol": secid},
        )
    value = eastmoney_price(rows[0].get("f2"), rows[0])
    if value is None or value == 0:
        raise StockDataError(
            f"Eastmoney FX rate returned no usable quote for {from_currency}->{to_currency} ({secid}).",
            phase="fx_rate",
            error_code="fx_rate_quote_unusable",
            details={"from": from_currency, "to": to_currency, "symbol": secid, "raw": rows[0]},
        )
    if invert:
        value = 1 / value
    return {
        "value": value,
        "from": from_currency,
        "to": to_currency,
        "source": "eastmoney",
        "symbol": secid,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def fx_rate(
    from_currency: str | None,
    to_currency: str | None,
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
    request_delay: float = 0.0,
) -> dict[str, Any] | None:
    if not from_currency or not to_currency:
        return None
    from_code = normalize_currency(from_currency, from_currency)
    to_code = normalize_currency(to_currency, to_currency)
    if from_code == to_code:
        return {
            "value": 1.0,
            "from": from_code,
            "to": to_code,
            "source": "identity",
            "symbol": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    client = configure_session(session or requests.Session())
    direct_rate = eastmoney_fx_rate(from_code, to_code, session=client, timeout=timeout, request_delay=request_delay)
    if direct_rate is not None:
        return direct_rate

    bridge_currency = "CNY"
    if from_code == bridge_currency or to_code == bridge_currency:
        return None

    first_leg = eastmoney_fx_rate(
        from_code,
        bridge_currency,
        session=client,
        timeout=timeout,
        request_delay=request_delay,
    )
    second_leg = eastmoney_fx_rate(
        bridge_currency,
        to_code,
        session=client,
        timeout=timeout,
        request_delay=request_delay,
    )
    if first_leg is None or second_leg is None:
        return None
    return {
        "value": first_leg["value"] * second_leg["value"],
        "from": from_code,
        "to": to_code,
        "source": "eastmoney_cross",
        "symbol": f"{first_leg['symbol']}->{second_leg['symbol']}",
        "bridge": bridge_currency,
        "legs": [first_leg, second_leg],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def latest_metric(rows: list[dict[str, Any]], field: str) -> Any:
    for row in rows:
        value = row.get(field)
        if value is not None:
            return value
    return None


def fetch_stock_data(
    ticker: str,
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
    request_delay: float = 0.0,
) -> dict[str, Any]:
    client = configure_session(session or requests.Session())
    snapshot, _raw_quote = fetch_quote_snapshot(ticker, session=client, timeout=timeout, request_delay=request_delay)
    try:
        provider_rows = fetch_financial_rows(snapshot, session=client, request_delay=request_delay, timeout=timeout)
    except Exception as exc:
        raise StockDataError(f"Financial statements fetch failed: {exc}", phase="financial_statements") from exc

    financial_rows = convert_financial_rows(provider_rows)
    price_currency = snapshot.currency
    financial_currency = None
    for row in provider_rows:
        if row.get("currency"):
            financial_currency = normalize_currency(row.get("currency"), price_currency)
            break
    financial_currency = financial_currency or price_currency
    shares_outstanding = quote_implied_shares(snapshot.market_cap, snapshot.price)
    current_fx_rate = fx_rate(
        financial_currency,
        price_currency,
        session=client,
        timeout=timeout,
        request_delay=request_delay,
    )
    if financial_currency != price_currency and current_fx_rate is None:
        raise StockDataError(
            f"FX rate is required but unsupported for {financial_currency}->{price_currency}.",
            phase="fx_rate",
            error_code="fx_rate_unsupported",
            details={"from": financial_currency, "to": price_currency},
        )

    return {
        "ticker": snapshot.ticker,
        "requestedTicker": normalized_ticker(ticker),
        "name": snapshot.name or snapshot.ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "currency": price_currency,
        "financialCurrency": financial_currency,
        "fxRate": current_fx_rate,
        "exchange": snapshot.market,
        "sharesOutstanding": shares_outstanding,
        "marketCap": money_value(snapshot.market_cap, price_currency),
        "metrics": {
            "price": money_value(snapshot.price, price_currency),
            "pe": snapshot.pe,
            "pb": snapshot.pb,
            "roe": latest_metric(financial_rows, "ROE"),
            "fcf": money_value(latest_metric(financial_rows, "Free Cash Flow"), financial_currency),
            "eps": money_value(latest_metric(financial_rows, "EPS"), financial_currency),
            "revenue_growth": None,
        },
        "historical_financials": {
            "currency": financial_currency,
            "rows": financial_rows,
        },
        "price_history": {
            "currency": price_currency,
            "rows": [],
            "dataLimits": {"provider": "eastmoney", "historyRowsReturned": 0},
        },
        "dataLimits": financial_data_limits(financial_rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--json-out", help="Optional path to write the stdout JSON payload.")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--request-delay", type=float, default=0.0)
    args = parser.parse_args(argv)

    ticker = normalized_ticker(args.ticker)

    logger.info("Fetching data for %s...", ticker)
    try:
        result = fetch_stock_data(ticker, timeout=args.timeout, request_delay=args.request_delay)
    except StockDataError as exc:
        print(json.dumps(exc.payload(ticker), ensure_ascii=False))
        return 1

    payload = json.dumps(json_safe(result), ensure_ascii=False, indent=2)
    if args.json_out:
        output_path = Path(args.json_out).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
