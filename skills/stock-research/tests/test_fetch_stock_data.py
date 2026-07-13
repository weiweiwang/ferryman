from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_stock_data.py"
REQUIRED_ANNUAL_FIELDS = (
    "Revenue",
    "Net Income",
    "Operating Cash Flow",
    "Capex",
    "Free Cash Flow",
    "Cash And Equivalents",
    "Total Debt",
)
LIVE_FETCH_TICKERS = ("AAPL.O", "600809.SH", "00700.HK", "00992.HK")
LIVE_TEST = pytest.mark.skipif(
    os.environ.get("STOCK_RESEARCH_RUN_LIVE_TESTS") != "1",
    reason="Set STOCK_RESEARCH_RUN_LIVE_TESTS=1 to run live source tests.",
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.text = json.dumps(payload)
        self.content = self.text.encode("utf-8")

    def raise_for_status(self):
        return None


class FailingSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        raise RuntimeError(f"dns failed for {url}")


class EmptyQuoteSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        if str(url).endswith("/stock/get"):
            return FakeResponse({"data": None})
        return FakeResponse({"data": {"diff": []}})


def fake_fx_leg(value: float, from_currency: str, to_currency: str, symbol: str) -> dict:
    return {
        "value": value,
        "from": from_currency,
        "to": to_currency,
        "source": "eastmoney",
        "symbol": symbol,
        "fetched_at": "2026-07-04T00:00:00+00:00",
    }


def load_fetch_module():
    spec = importlib.util.spec_from_file_location("fetch_stock_data_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load stock fetcher from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_complete_stock_data_contract(result: dict, expected_ticker: str, expected_exchange: str) -> None:
    assert result["ticker"] == expected_ticker
    assert result["exchange"] == expected_exchange
    assert result["name"]
    assert result["currency"]
    assert result["financialCurrency"]
    if result["financialCurrency"] != result["currency"]:
        assert result["fxRate"]["from"] == result["financialCurrency"]
        assert result["fxRate"]["to"] == result["currency"]
        assert result["fxRate"]["value"] > 0
    assert "ttm_metrics" not in result
    assert result["metrics"]["price"]["value"] > 0
    assert result["metrics"]["price"]["currency"] == result["currency"]
    assert result["marketCap"]["value"] > 0
    assert result["marketCap"]["currency"] == result["currency"]
    assert result["sharesOutstanding"] > 0

    rows = result["historical_financials"]["rows"]
    assert result["historical_financials"]["currency"] == result["financialCurrency"]
    assert len(rows) >= 5
    rows_by_year = {row["Year"]: row for row in rows}
    complete_years = result["dataLimits"]["completeFcfYearsReturned"][:5]
    assert len(complete_years) >= 5
    for year in complete_years:
        row = rows_by_year[year]
        assert row["Year"]
        for field in REQUIRED_ANNUAL_FIELDS:
            assert row[field] is not None, f"{expected_ticker} {row['Year']} missing {field}"
        assert "Cash And Investments" not in row
        assert "Current Financial Assets" in row
        assert "Noncurrent Financial Assets" in row

    limits = result["dataLimits"]
    assert limits["provider"] == "eastmoney"
    assert limits["annualRowsReturned"] >= 5
    assert limits["completeFcfYearCount"] >= 5
    assert limits["minimumCompleteFcfYearsForFormalReport"] == 5
    assert limits["meetsFiveYearFcfRequirement"] is True
    assert limits["needsPrimarySourceForFiveYearNormalization"] is False
    required_years = set(limits["completeFcfYearsReturned"][:5])
    assert not required_years.intersection(limits["missingFieldsByYear"])


def test_stock_fetcher_does_not_depend_on_yahoo_or_heavy_dataframe_runtime():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "y" + "finance" not in source
    assert "import " + "pandas" not in source
    assert "=" + "X" not in source
    assert "--json-out" in source
    assert "--output-dir" not in source
    for heavy_import in ("openpyxl", "plotly", "kaleido"):
        assert heavy_import not in source


def test_stock_fetcher_only_supports_fx_pairs_with_matching_rate_workflow():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "133.USDCNH" in source
    assert "133.HKDCNH" in source
    for unsupported_symbol in ("133.EURCNH", "133.AUDCNH", "133.GBPCNH"):
        assert unsupported_symbol not in source


def test_ticker_to_eastmoney_secid_candidates():
    module = load_fetch_module()

    assert module.secid_candidates_for_ticker("600809.SH")[0].secid == "1.600809"
    assert module.secid_candidates_for_ticker("000568.SZ")[0].secid == "0.000568"
    assert module.secid_candidates_for_ticker("700.HK")[0].secid == "116.00700"
    assert module.secid_candidates_for_ticker("AAPL.O")[0].secid == "105.AAPL"
    assert [item.secid for item in module.secid_candidates_for_ticker("AAPL")] == [
        "105.AAPL",
        "106.AAPL",
        "107.AAPL",
    ]


def test_quote_provider_request_failure_is_not_reported_as_not_found():
    module = load_fetch_module()

    with pytest.raises(module.StockDataError) as exc_info:
        module.fetch_quote_row("AAPL.O", session=FailingSession(), timeout=1, request_delay=0)

    error = exc_info.value
    assert error.phase == "price_quote"
    assert error.error_code == "provider_request_failed"
    assert "cannot determine whether the ticker exists" in str(error)
    assert error.details["candidates"] == ["105.AAPL"]
    assert error.details["request_errors"][0]["secid"] == "105.AAPL"
    assert "dns failed" in error.details["request_errors"][0]["error"]


def test_quote_empty_result_is_reported_as_quote_not_found():
    module = load_fetch_module()

    with pytest.raises(module.StockDataError) as exc_info:
        module.fetch_quote_row("NO_SUCH_TICKER_999999.O", session=EmptyQuoteSession(), timeout=1, request_delay=0)

    error = exc_info.value
    assert error.phase == "price_quote"
    assert error.error_code == "quote_not_found"
    assert "not found in Eastmoney quote API" in str(error)
    assert error.details["candidates"] == ["105.NO_SUCH_TICKER_999999"]
    assert error.details["empty_secids"] == ["105.NO_SUCH_TICKER_999999"]


def test_financial_row_conversion_keeps_capex_cash_debt_and_ratios():
    module = load_fetch_module()

    rows = module.convert_financial_rows(
        [
            {
                "year": "2025",
                "currency": "USD",
                "revenue": 1000,
                "net_profit": 200,
                "operating_cash_flow": 260,
                "capex": 60,
                "free_cash_flow": 200,
                "roe": 40,
                "roic": 25,
                "equity": 500,
                "total_assets": 1500,
                "total_liabilities": 900,
                "cash_and_equivalents": 100,
                "current_financial_assets": 50,
                "noncurrent_financial_assets": 25,
                "long_debt": 300,
                "short_debt": 20,
                "goodwill": 25,
            }
        ]
    )

    row = rows[0]
    assert row["Year"] == "2025"
    assert row["Revenue"] == 1000
    assert row["Net Income"] == 200
    assert row["Operating Cash Flow"] == 260
    assert row["Capex"] == 60
    assert row["Capital Expenditure"] == -60
    assert row["Free Cash Flow"] == 200
    assert row["ROE"] == 0.4
    assert row["ROIC"] == 0.25
    assert row["FCF Margin"] == 0.2
    assert row["OCF / Net Income"] == 1.3
    assert row["FCF / Net Income"] == 1.0
    assert row["Cash And Equivalents"] == 100
    assert row["Current Financial Assets"] == 50
    assert row["Noncurrent Financial Assets"] == 25
    assert "Cash And Investments" not in row
    assert row["Total Debt"] == 320
    assert row["Goodwill To Equity"] == 0.05


def test_financial_data_limits_require_five_complete_fcf_years_and_required_fields():
    module = load_fetch_module()
    rows = [
        {
            "Year": "2025",
            "Revenue": 1000,
            "Net Income": 200,
            "Operating Cash Flow": 260,
            "Capex": 60,
            "Free Cash Flow": 200,
            "Cash And Equivalents": 100,
            "Current Financial Assets": 50,
            "Noncurrent Financial Assets": 25,
            "Total Debt": 320,
        },
        {
            "Year": "2024",
            "Revenue": None,
            "Net Income": 180,
            "Operating Cash Flow": 240,
            "Capex": None,
            "Free Cash Flow": None,
            "Cash And Equivalents": None,
            "Current Financial Assets": None,
            "Noncurrent Financial Assets": None,
            "Total Debt": None,
        },
    ]

    limits = module.financial_data_limits(rows)

    assert limits["provider"] == "eastmoney"
    assert limits["annualRowsReturned"] == 2
    assert limits["completeFcfYearCount"] == 1
    assert limits["minimumCompleteFcfYearsForFormalReport"] == 5
    assert limits["needsPrimarySourceForFiveYearNormalization"] is True
    assert "minimumCompleteFcfYearsFor90Confidence" not in limits
    assert "confidenceCapIfNotSupplemented" not in limits
    assert limits["missingFieldsByYear"] == {
        "2024": ["Revenue", "Capex", "Free Cash Flow", "Cash And Equivalents", "Total Debt"],
    }


@LIVE_TEST
@pytest.mark.parametrize("ticker", LIVE_FETCH_TICKERS)
def test_fetch_stock_data_returns_complete_data_for_us_a_hk_from_real_api(ticker):
    module = load_fetch_module()

    result = module.fetch_stock_data(ticker, timeout=20, request_delay=0.1)

    expected_exchange = {"AAPL.O": "US", "600809.SH": "SH", "00700.HK": "HK", "00992.HK": "HK"}[ticker]
    assert_complete_stock_data_contract(result, ticker, expected_exchange)


def test_fx_rate_uses_identity_for_matching_currencies():
    module = load_fetch_module()

    rate = module.fx_rate("HKD", "HKD")

    assert rate["value"] == 1.0
    assert rate["from"] == "HKD"
    assert rate["to"] == "HKD"
    assert rate["source"] == "identity"
    assert rate["symbol"] is None


@LIVE_TEST
def test_fx_rate_supports_cny_hkd_via_real_eastmoney_api():
    module = load_fetch_module()

    rate = module.fx_rate("CNY", "HKD", timeout=20, request_delay=0.1)

    assert rate["from"] == "CNY"
    assert rate["to"] == "HKD"
    assert 1.0 < rate["value"] < 1.5
    assert rate["source"] == "eastmoney"
    assert rate["symbol"] == "133.HKDCNH"


@LIVE_TEST
def test_fx_rate_supports_usd_hkd_cross_via_real_eastmoney_api():
    module = load_fetch_module()

    rate = module.fx_rate("USD", "HKD", timeout=20, request_delay=0.1)

    assert rate["from"] == "USD"
    assert rate["to"] == "HKD"
    assert 7.0 < rate["value"] < 9.0
    assert rate["source"] == "eastmoney_cross"
    assert rate["bridge"] == "CNY"
    assert rate["symbol"] == "133.USDCNH->133.HKDCNH"


def test_fx_rate_crosses_via_cny_for_usd_hkd(monkeypatch):
    module = load_fetch_module()
    calls = []

    def fake_eastmoney_fx_rate(from_currency, to_currency, **kwargs):
        calls.append((from_currency, to_currency))
        if (from_currency, to_currency) == ("USD", "HKD"):
            return None
        if (from_currency, to_currency) == ("USD", "CNY"):
            return fake_fx_leg(7.2, "USD", "CNY", "133.USDCNH")
        if (from_currency, to_currency) == ("CNY", "HKD"):
            return fake_fx_leg(1.08, "CNY", "HKD", "133.HKDCNH")
        raise AssertionError(f"unexpected pair {from_currency}->{to_currency}")

    monkeypatch.setattr(module, "eastmoney_fx_rate", fake_eastmoney_fx_rate)

    rate = module.fx_rate("USD", "HKD", timeout=1, request_delay=0)

    assert calls == [("USD", "HKD"), ("USD", "CNY"), ("CNY", "HKD")]
    assert rate["value"] == pytest.approx(7.776)
    assert rate["from"] == "USD"
    assert rate["to"] == "HKD"
    assert rate["source"] == "eastmoney_cross"
    assert rate["bridge"] == "CNY"
    assert rate["symbol"] == "133.USDCNH->133.HKDCNH"
    assert [leg["symbol"] for leg in rate["legs"]] == ["133.USDCNH", "133.HKDCNH"]


def test_fx_rate_does_not_support_non_rate_currency_crosses(monkeypatch):
    module = load_fetch_module()
    calls = []

    def fake_eastmoney_fx_rate(from_currency, to_currency, **kwargs):
        calls.append((from_currency, to_currency))
        direct = {
            ("CNY", "HKD"): fake_fx_leg(1.08, "CNY", "HKD", "133.HKDCNH"),
        }
        return direct.get((from_currency, to_currency))

    monkeypatch.setattr(module, "eastmoney_fx_rate", fake_eastmoney_fx_rate)

    eur_hkd = module.fx_rate("EUR", "HKD", timeout=1, request_delay=0)
    aud_hkd = module.fx_rate("AUD", "HKD", timeout=1, request_delay=0)
    gbp_hkd = module.fx_rate("GBP", "HKD", timeout=1, request_delay=0)

    assert eur_hkd is None
    assert aud_hkd is None
    assert gbp_hkd is None
    assert ("EUR", "CNY") in calls
    assert ("AUD", "CNY") in calls
    assert ("GBP", "CNY") in calls


def test_fx_rate_request_failure_returns_specific_error():
    module = load_fetch_module()

    with pytest.raises(module.StockDataError) as exc_info:
        module.fx_rate("CNY", "HKD", session=FailingSession(), timeout=1, request_delay=0)

    error = exc_info.value
    assert error.phase == "fx_rate"
    assert error.error_code == "fx_rate_request_failed"
    assert error.details["from"] == "CNY"
    assert error.details["to"] == "HKD"
    assert error.details["symbol"] == "133.HKDCNH"
    assert "dns failed" in error.details["error"]


def test_fetch_stock_data_fails_when_required_fx_rate_is_missing(monkeypatch):
    module = load_fetch_module()

    class Snapshot:
        ticker = "TEST.HK"
        name = "Test Co"
        currency = "HKD"
        market = "HK"
        price = 10.0
        market_cap = 1000.0
        pe = 10.0
        pb = 1.0

    monkeypatch.setattr(module, "fetch_quote_snapshot", lambda *args, **kwargs: (Snapshot(), {}))
    monkeypatch.setattr(
        module,
        "fetch_financial_rows",
        lambda *args, **kwargs: [
            {
                "year": "2025",
                "currency": "CNY",
                "revenue": 100,
                "net_profit": 20,
                "operating_cash_flow": 25,
                "capex": 5,
                "free_cash_flow": 20,
            }
        ],
    )
    monkeypatch.setattr(module, "fx_rate", lambda *args, **kwargs: None)

    with pytest.raises(module.StockDataError) as exc_info:
        module.fetch_stock_data("TEST.HK", timeout=1, request_delay=0)

    error = exc_info.value
    assert error.phase == "fx_rate"
    assert error.error_code == "fx_rate_unsupported"
    assert error.details == {"from": "CNY", "to": "HKD"}


def test_fetch_stock_data_labels_statement_eps_with_financial_currency(monkeypatch):
    module = load_fetch_module()

    class Snapshot:
        ticker = "TEST.HK"
        name = "Test Co"
        currency = "HKD"
        market = "HK"
        price = 10.0
        market_cap = 1000.0
        pe = 10.0
        pb = 1.0

    monkeypatch.setattr(module, "fetch_quote_snapshot", lambda *args, **kwargs: (Snapshot(), {}))
    monkeypatch.setattr(
        module,
        "fetch_financial_rows",
        lambda *args, **kwargs: [
            {
                "year": "2025",
                "currency": "USD",
                "revenue": 100,
                "net_profit": 20,
                "operating_cash_flow": 25,
                "capex": 5,
                "free_cash_flow": 20,
                "cash_and_equivalents": 10,
                "total_debt": 1,
                "eps": 0.42,
            }
        ],
    )
    monkeypatch.setattr(
        module,
        "fx_rate",
        lambda from_currency, to_currency, **kwargs: {
            "value": 7.8,
            "from": from_currency,
            "to": to_currency,
            "source": "test",
            "symbol": "USDHKD",
        },
    )

    result = module.fetch_stock_data("TEST.HK", timeout=1, request_delay=0)

    assert result["currency"] == "HKD"
    assert result["financialCurrency"] == "USD"
    assert result["metrics"]["eps"] == {"value": 0.42, "currency": "USD"}


def test_main_serializes_error_code_source_and_details(monkeypatch, capsys):
    module = load_fetch_module()

    def fail_fetch(*args, **kwargs):
        raise module.StockDataError(
            "FX provider failed",
            phase="fx_rate",
            error_code="fx_rate_request_failed",
            details={"symbol": "133.HKDCNH"},
        )

    monkeypatch.setattr(module, "fetch_stock_data", fail_fetch)

    assert module.main(["--ticker", "00700.HK", "--timeout", "1"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "phase": "fx_rate",
        "ticker": "00700.HK",
        "error_code": "fx_rate_request_failed",
        "source": "eastmoney",
        "error": "FX provider failed",
        "details": {"symbol": "133.HKDCNH"},
    }


@LIVE_TEST
def test_main_can_write_explicit_json_out_from_real_api(tmp_path, capsys):
    module = load_fetch_module()
    output_path = tmp_path / "stock-data.json"

    assert module.main(["--ticker", "AAPL.O", "--json-out", str(output_path), "--timeout", "20"]) == 0

    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert file_payload == stdout_payload
    assert_complete_stock_data_contract(stdout_payload, "AAPL.O", "US")


@LIVE_TEST
def test_main_returns_stable_error_payload_from_real_api(capsys):
    module = load_fetch_module()

    assert module.main(["--ticker", "NO_SUCH_TICKER_999999.O", "--timeout", "20"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["phase"] == "price_quote"
    assert payload["ticker"] == "NO_SUCH_TICKER_999999.O"
    assert payload["source"] == "eastmoney"
    assert payload["error_code"] in {"quote_not_found", "provider_request_failed"}
    if payload["error_code"] == "quote_not_found":
        assert "not found in Eastmoney quote API" in payload["error"]
    else:
        assert "cannot determine whether the ticker exists" in payload["error"]
        assert payload["details"]["request_errors"]
