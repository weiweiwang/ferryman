#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class StockDataError(RuntimeError):
    """Raised when yfinance cannot return usable stock data."""


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def numeric_value(value: Any, default: float | int | None = 0) -> float | int | None:
    value = json_safe(value)
    return value if isinstance(value, int | float) else default


def dataframe_row_value(frame: pd.DataFrame, label: str, column: Any, default: float | int | None = 0) -> float | int | None:
    if label not in frame.index or column not in frame.columns:
        return default
    return numeric_value(frame.loc[label, column], default)


def first_row_value(
    frame: pd.DataFrame,
    labels: tuple[str, ...],
    column: Any,
    default: float | int | None = None,
) -> float | int | None:
    for label in labels:
        value = dataframe_row_value(frame, label, column, default=None)
        if value is not None:
            return value
    return default


def safe_ratio(numerator: Any, denominator: Any) -> float | None:
    numerator_value = numeric_value(numerator, None)
    denominator_value = numeric_value(denominator, None)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return numerator_value / denominator_value


def price_history_rows(history: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if history.empty:
        return rows

    for index, row in history.iterrows():
        close = json_safe(row.get("Close"))
        if close is None:
            continue
        rows.append(
            {
                "date": json_safe(index),
                "open": json_safe(row.get("Open")),
                "high": json_safe(row.get("High")),
                "low": json_safe(row.get("Low")),
                "close": close,
                "volume": json_safe(row.get("Volume")) or 0,
            }
        )
    return rows


def money_value(value: Any, currency: str | None) -> dict[str, Any]:
    return {"value": json_safe(value), "currency": currency}


def fx_rate(from_currency: str | None, to_currency: str | None) -> dict[str, Any] | None:
    if not from_currency or not to_currency:
        return None
    if from_currency == to_currency:
        return {
            "value": 1.0,
            "from": from_currency,
            "to": to_currency,
            "source": "identity",
            "symbol": None,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    symbol = f"{from_currency}{to_currency}=X"
    try:
        history = yf.Ticker(symbol).history(period="5d")
    except Exception as exc:
        logger.warning("FX rate fetch failed for %s: %s", symbol, exc)
        return None
    if history.empty or history["Close"].dropna().empty:
        return None

    return {
        "value": json_safe(history["Close"].dropna().iloc[-1]),
        "from": from_currency,
        "to": to_currency,
        "source": "yfinance",
        "symbol": symbol,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def get_5y_financials(stock: yf.Ticker) -> list[dict[str, Any]]:
    """Fetch and process up to 5 years of annual financial statements."""
    try:
        financials = stock.financials
        cashflow = stock.cashflow
        balance = stock.balance_sheet
    except Exception as exc:
        raise StockDataError(f"Financial statements fetch failed: {exc}") from exc

    if financials.empty and cashflow.empty and balance.empty:
        return []

    years = list(dict.fromkeys([*financials.columns, *cashflow.columns, *balance.columns]))[:5]
    data: list[dict[str, Any]] = []
    for year in years:
        revenue = dataframe_row_value(financials, "Total Revenue", year, default=None)
        net_income = dataframe_row_value(financials, "Net Income", year, default=None)
        normalized_income = dataframe_row_value(financials, "Normalized Income", year, default=None)
        unusual_items = dataframe_row_value(financials, "Total Unusual Items", year, default=None)
        ebit = first_row_value(financials, ("EBIT", "Operating Income"), year)
        pretax_income = dataframe_row_value(financials, "Pretax Income", year, default=None)
        tax_provision = dataframe_row_value(financials, "Tax Provision", year, default=None)
        tax_rate = dataframe_row_value(financials, "Tax Rate For Calcs", year, default=None)
        equity = dataframe_row_value(balance, "Stockholders Equity", year, default=None)
        invested_capital = dataframe_row_value(balance, "Invested Capital", year, default=None)
        total_assets = dataframe_row_value(balance, "Total Assets", year, default=None)
        total_debt = dataframe_row_value(balance, "Total Debt", year, default=None)
        cash_and_investments = dataframe_row_value(
            balance,
            "Cash Cash Equivalents And Short Term Investments",
            year,
            default=None,
        )
        goodwill = dataframe_row_value(balance, "Goodwill", year, default=None)
        goodwill_and_intangibles = dataframe_row_value(balance, "Goodwill And Other Intangible Assets", year, default=None)
        accounts_receivable = first_row_value(balance, ("Accounts Receivable", "Receivables"), year)
        inventory = dataframe_row_value(balance, "Inventory", year, default=None)
        working_capital = dataframe_row_value(balance, "Working Capital", year, default=None)
        operating_cash_flow = dataframe_row_value(cashflow, "Operating Cash Flow", year, default=None)
        capital_expenditure = dataframe_row_value(cashflow, "Capital Expenditure", year, default=None)
        asset_impairment = dataframe_row_value(cashflow, "Asset Impairment Charge", year, default=None)
        if all(value is None for value in (revenue, net_income, equity, operating_cash_flow)):
            continue

        net_income_value = numeric_value(net_income, 0) or 0
        equity_value = numeric_value(equity, 0) or 0
        operating_cash_flow_value = numeric_value(operating_cash_flow, 0) or 0
        capital_expenditure_value = numeric_value(capital_expenditure, 0) or 0
        effective_tax_rate = numeric_value(tax_rate, None)
        if effective_tax_rate is None:
            effective_tax_rate = safe_ratio(tax_provision, pretax_income)
        nopat = None
        if ebit is not None:
            nopat = ebit * (1 - (effective_tax_rate or 0))
        free_cash_flow = operating_cash_flow_value + capital_expenditure_value
        data.append(
            {
                "Year": year.strftime("%Y") if hasattr(year, "strftime") else str(year),
                "Revenue": numeric_value(revenue, 0),
                "Net Income": net_income_value,
                "Normalized Income": numeric_value(normalized_income, None),
                "Total Unusual Items": numeric_value(unusual_items, None),
                "EBIT": numeric_value(ebit, None),
                "NOPAT": numeric_value(nopat, None),
                "Operating Cash Flow": operating_cash_flow_value,
                "Free Cash Flow": free_cash_flow,
                "ROE": net_income_value / equity_value if equity_value else 0,
                "ROIC": safe_ratio(nopat, invested_capital),
                "Net Margin": safe_ratio(net_income, revenue),
                "FCF Margin": safe_ratio(free_cash_flow, revenue),
                "Cash Conversion": safe_ratio(operating_cash_flow, net_income),
                "EPS": dataframe_row_value(financials, "Diluted EPS", year, default=None),
                "Invested Capital": numeric_value(invested_capital, None),
                "Stockholders Equity": numeric_value(equity, None),
                "Total Assets": numeric_value(total_assets, None),
                "Total Debt": numeric_value(total_debt, None),
                "Cash And Investments": numeric_value(cash_and_investments, None),
                "Goodwill": numeric_value(goodwill, None),
                "Goodwill And Intangibles": numeric_value(goodwill_and_intangibles, None),
                "Accounts Receivable": numeric_value(accounts_receivable, None),
                "Inventory": numeric_value(inventory, None),
                "Working Capital": numeric_value(working_capital, None),
                "Asset Impairment Charge": numeric_value(asset_impairment, None),
                "Goodwill To Equity": safe_ratio(goodwill, equity),
                "Receivables To Revenue": safe_ratio(accounts_receivable, revenue),
            }
        )
    return data


def fetch_stock_data(ticker: str) -> dict[str, Any]:
    stock = yf.Ticker(ticker)
    history = stock.history(period="1y")
    if history.empty:
        raise StockDataError(f"Ticker {ticker} not found or returned no price history.")

    info = stock.info
    if not isinstance(info, dict):
        info = {}

    price_currency = info.get("currency")
    financial_currency = info.get("financialCurrency")
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "currency": price_currency,
        "financialCurrency": financial_currency,
        "fxRate": fx_rate(financial_currency, price_currency),
        "exchange": info.get("exchange"),
        "sharesOutstanding": info.get("sharesOutstanding"),
        "marketCap": money_value(info.get("marketCap"), price_currency),
        "ttm_metrics": {
            "price": money_value(info.get("currentPrice", history["Close"].iloc[-1]), price_currency),
            "pe": info.get("trailingPE"),
            "pb": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "fcf": money_value(info.get("freeCashflow"), financial_currency),
            "eps": money_value(info.get("trailingEps"), price_currency),
            "revenue_growth": info.get("revenueGrowth"),
        },
        "historical_financials": {
            "currency": financial_currency,
            "perShareCurrency": financial_currency,
            "rows": get_5y_financials(stock),
        },
        "price_history": {
            "currency": price_currency,
            "rows": price_history_rows(history),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Fetching data for %s...", ticker)
    try:
        result = fetch_stock_data(ticker)
    except StockDataError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(json_safe(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
