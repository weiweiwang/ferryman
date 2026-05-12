from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_stock_data.py"


def load_fetch_module():
    spec = importlib.util.spec_from_file_location("fetch_stock_data_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load stock fetcher from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stock_fetcher_keeps_runtime_dependencies_lightweight():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "import yfinance" in source
    assert "import pandas" in source
    for heavy_import in ("openpyxl", "plotly", "kaleido"):
        assert heavy_import not in source


def test_price_history_rows_and_financials_from_yfinance_frames():
    module = load_fetch_module()
    pd = module.pd

    history = pd.DataFrame(
        [{"Open": 120.0, "High": 125.0, "Low": 119.0, "Close": 123.45, "Volume": 1000}],
        index=[pd.Timestamp("2026-01-01", tz="UTC")],
    )
    assert module.price_history_rows(history) == [
        {
            "date": "2026-01-01",
            "open": 120.0,
            "high": 125.0,
            "low": 119.0,
            "close": 123.45,
            "volume": 1000,
        }
    ]

    year = pd.Timestamp("2025-09-30")

    class FakeStock:
        financials = pd.DataFrame(
            {
                year: {
                    "Total Revenue": 1000,
                    "Net Income": 200,
                    "Normalized Income": 190,
                    "Total Unusual Items": 10,
                    "EBIT": 260,
                    "Pretax Income": 250,
                    "Tax Provision": 50,
                    "Diluted EPS": 2.5,
                }
            }
        )
        cashflow = pd.DataFrame(
            {
                year: {
                    "Operating Cash Flow": 250,
                    "Capital Expenditure": -70,
                    "Asset Impairment Charge": 5,
                }
            }
        )
        balance_sheet = pd.DataFrame(
            {
                year: {
                    "Stockholders Equity": 500,
                    "Invested Capital": 1000,
                    "Total Assets": 1500,
                    "Total Debt": 100,
                    "Cash Cash Equivalents And Short Term Investments": 300,
                    "Goodwill": 50,
                    "Accounts Receivable": 80,
                    "Inventory": 20,
                    "Working Capital": 400,
                }
            }
        )

    financials = module.get_5y_financials(FakeStock())
    assert len(financials) == 1
    row = financials[0]
    assert row["Year"] == "2025"
    assert row["Revenue"] == 1000
    assert row["Net Income"] == 200
    assert row["Operating Cash Flow"] == 250
    assert row["Free Cash Flow"] == 180
    assert row["ROE"] == 0.4
    assert row["ROIC"] == 0.208
    assert row["FCF Margin"] == 0.18
    assert row["Cash Conversion"] == 1.25
    assert row["Goodwill To Equity"] == 0.1
    assert row["Receivables To Revenue"] == 0.08
    assert row["EPS"] == 2.5
