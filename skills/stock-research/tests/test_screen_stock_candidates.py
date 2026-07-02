from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from openpyxl import load_workbook


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "screen_stock_candidates.py"


def load_screen_module():
    spec = importlib.util.spec_from_file_location("screen_stock_candidates_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load stock candidate screener from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_snapshot(module, **overrides):
    values = {
        "ticker": "000001.SZ",
        "code": "000001",
        "name": "Quality Co",
        "market": "SZ",
        "currency": "CNY",
        "price": 10.0,
        "pe": 10.0,
        "pb": 2.0,
        "market_cap": 1_000_000_000.0,
        "float_market_cap": 900_000_000.0,
        "industry": "软件服务",
    }
    values.update(overrides)
    return module.MarketSnapshot(**values)


def sample_financial_rows():
    return [
        {
            "year": "2025",
            "currency": "CNY",
            "net_profit": 80_000_000.0,
            "operating_cash_flow": 95_000_000.0,
            "free_cash_flow": 75_000_000.0,
            "roe": 18.0,
            "roic": 15.0,
            "total_assets": 500_000_000.0,
            "total_liabilities": 150_000_000.0,
            "goodwill": 10_000_000.0,
            "equity": 350_000_000.0,
            "payout_ratio": 0.3,
        },
        {
            "year": "2024",
            "currency": "CNY",
            "net_profit": 82_000_000.0,
            "operating_cash_flow": 94_000_000.0,
            "free_cash_flow": 76_000_000.0,
            "roe": 19.0,
            "roic": 15.5,
            "total_assets": 480_000_000.0,
            "total_liabilities": 150_000_000.0,
            "goodwill": 10_000_000.0,
            "equity": 330_000_000.0,
        },
        {
            "year": "2023",
            "currency": "CNY",
            "net_profit": 78_000_000.0,
            "operating_cash_flow": 90_000_000.0,
            "free_cash_flow": 73_000_000.0,
            "roe": 17.0,
            "roic": 14.0,
            "total_assets": 460_000_000.0,
            "total_liabilities": 140_000_000.0,
            "goodwill": 8_000_000.0,
            "equity": 320_000_000.0,
        },
        {
            "year": "2022",
            "currency": "CNY",
            "net_profit": 79_000_000.0,
            "operating_cash_flow": 93_000_000.0,
            "free_cash_flow": 74_000_000.0,
            "roe": 18.0,
            "roic": 14.5,
            "total_assets": 440_000_000.0,
            "total_liabilities": 130_000_000.0,
            "goodwill": 8_000_000.0,
            "equity": 310_000_000.0,
        },
        {
            "year": "2021",
            "currency": "CNY",
            "net_profit": 81_000_000.0,
            "operating_cash_flow": 92_000_000.0,
            "free_cash_flow": 75_000_000.0,
            "roe": 20.0,
            "roic": 16.0,
            "total_assets": 420_000_000.0,
            "total_liabilities": 125_000_000.0,
            "goodwill": 8_000_000.0,
            "equity": 295_000_000.0,
        },
    ]


def risk_free_payload():
    return {"ok": True, "multipleCaps": {"conservativeN2": 15.58}}


def walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_keys(item)


class FakeListResponse:
    def __init__(self, payload):
        self.payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FailThenSuccessListSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append((url, params, timeout))
        if len(self.calls) == 1:
            raise RuntimeError("primary host failed")
        return FakeListResponse({"data": {"diff": [{"f12": "601398", "f14": "工商银行", "f20": 1000}]}})


class AlwaysFailListSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, params, timeout):
        raise RuntimeError("requests host failed")


def test_screener_does_not_import_django_or_radar_runtime():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    for forbidden in ("django", "celery", "mysql", "radar.models", "insights."):
        assert forbidden not in source


def test_market_snapshot_fetcher_falls_back_to_secondary_eastmoney_host():
    module = load_screen_module()
    session = FailThenSuccessListSession()

    snapshots, errors = module.fetch_market_snapshots(
        markets=["SH"],
        max_count=1,
        sort_by="market_cap",
        session=session,
    )

    assert errors == []
    assert len(session.calls) == 2
    _, params, _ = session.calls[0]
    assert params["ut"] == module.EASTMONEY_QUOTE_UT
    assert params["fltt"] == 1
    assert params["dect"] == 1
    assert params["wbp2u"] == module.EASTMONEY_WBP2U
    assert snapshots[0].ticker == "601398.SH"


def test_market_snapshot_fetcher_uses_curl_fallback_when_requests_hosts_fail(monkeypatch):
    module = load_screen_module()

    class Completed:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"data": {"diff": [{"f12": "601398", "f14": "工商银行", "f20": 1000}]}})

    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: Completed())

    snapshots, errors = module.fetch_market_snapshots(
        markets=["SH"],
        max_count=1,
        sort_by="market_cap",
        session=AlwaysFailListSession(),
    )

    assert errors == []
    assert snapshots[0].ticker == "601398.SH"


def test_screen_stocks_returns_stable_failure_when_all_market_snapshots_fail(monkeypatch):
    module = load_screen_module()

    monkeypatch.setattr(module, "curl_get_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("empty reply")))

    payload = module.screen_stocks(
        markets=["HK"],
        max_count=1,
        enrich_limit=1,
        sort_by="market_cap",
        min_market_cap=100_000_000,
        session=AlwaysFailListSession(),
    )

    assert payload["ok"] is False
    assert payload["phase"] == "market_snapshot"
    assert payload["error"] == "No market snapshots fetched from Eastmoney for requested markets."
    assert payload["summary"]["total"] == 0
    assert payload["results"] == []
    assert payload["data_limits"]["errors"][0]["market"] == "HK"


def test_cli_returns_nonzero_when_market_snapshot_fetch_fails(monkeypatch, capsys):
    module = load_screen_module()

    monkeypatch.setattr(
        module,
        "fetch_market_snapshots",
        lambda **kwargs: ([], [{"market": "HK", "phase": "market_snapshot", "error": "empty reply"}]),
    )

    exit_code = module.main(["--markets", "HK", "--max-count", "1", "--enrich-limit", "1"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["phase"] == "market_snapshot"


def test_parse_json_or_jsonp_accepts_passivemoney_callback_shape():
    module = load_screen_module()

    payload = module.parse_json_or_jsonp('jQuery112404724607974107744_1610264100930({"data":{"diff":[]}});')

    assert payload == {"data": {"diff": []}}


def test_parse_market_snapshot_maps_eastmoney_fields_to_snake_case_contract():
    module = load_screen_module()

    snapshot = module.parse_market_snapshot(
        {"f12": "000001", "f14": "Ping An", "f2": 12.3, "f115": 9.8, "f23": 1.1, "f20": 1000, "f21": 800, "f100": "银行"},
        "SZ",
    )

    assert snapshot.ticker == "000001.SZ"
    assert snapshot.currency == "CNY"
    assert snapshot.pe == 9.8
    assert snapshot.pb == 1.1
    assert snapshot.market_cap == 1000


def test_parse_market_snapshot_scales_official_eastmoney_quote_values():
    module = load_screen_module()

    a_snapshot = module.parse_market_snapshot(
        {
            "f1": 2,
            "f2": 705,
            "f12": "601398",
            "f14": "工商银行",
            "f20": 2_512_664_112_477,
            "f23": 65,
            "f115": 677,
            "f152": 2,
        },
        "SH",
    )
    hk_snapshot = module.parse_market_snapshot(
        {
            "f1": 3,
            "f2": 430200,
            "f12": "00700",
            "f14": "腾讯控股",
            "f20": 3_911_479_428_598,
            "f23": 307,
            "f115": 1488,
            "f152": 2,
        },
        "HK",
    )

    assert a_snapshot.price == 7.05
    assert a_snapshot.pe == 6.77
    assert a_snapshot.pb == 0.65
    assert hk_snapshot.price == 430.2
    assert hk_snapshot.pe == 14.88
    assert hk_snapshot.pb == 3.07


def test_parse_market_snapshot_detects_hk_secondary_quote_currencies():
    module = load_screen_module()

    rmb_counter = module.parse_market_snapshot({"f12": "80700", "f14": "腾讯控股-R"}, "HK")
    usd_counter = module.parse_market_snapshot({"f12": "90700", "f14": "腾讯控股-U"}, "HK")

    assert rmb_counter.ticker == "80700.HK"
    assert rmb_counter.currency == "CNY"
    assert usd_counter.currency == "USD"


def test_parses_eastmoney_hk_currency_and_chinese_amount_units():
    module = load_screen_module()

    assert module.normalize_currency("人民币", "HKD") == "CNY"
    assert module.normalize_currency("港元", "CNY") == "HKD"
    assert module.to_float("2248.42亿") == 224_842_000_000.0
    assert module.to_float("39.13%") == 39.13


def test_build_result_item_marks_quality_value_candidate_with_readable_flags():
    module = load_screen_module()

    item = module.build_result_item(
        sample_snapshot(module),
        financial_rows=sample_financial_rows(),
        risk_free=risk_free_payload(),
        min_market_cap=100_000_000,
    )

    assert item["status"] == "CANDIDATE"
    assert set(item["quality_flags"]) >= {"stable_roe", "high_roic", "strong_cash_conversion", "positive_fcf_5y"}
    assert set(item["valuation_flags"]) >= {"cheap_pe", "cheap_profit", "cheap_fcf", "reasonable_pb"}
    assert "high_expected_return" not in item["valuation_flags"]
    assert "cheap_pb" not in item["valuation_flags"]
    assert item["metrics"]["pe"] == 10.0
    assert item["metrics"]["expected_return"] is not None


def test_build_result_item_uses_reject_reasons_for_obvious_rejects():
    module = load_screen_module()

    item = module.build_result_item(
        sample_snapshot(module, name="*ST Bad Co", price=0, pe=-3),
        financial_rows=[],
        risk_free=risk_free_payload(),
        min_market_cap=100_000_000,
    )

    assert item["status"] == "REJECTED"
    assert set(item["reject_reasons"]) >= {"no_valid_price", "st_or_special_treatment", "non_positive_pe"}
    assert item["quality_flags"] == []
    assert item["valuation_flags"] == []


def test_build_result_item_uses_data_gaps_for_missing_financial_history():
    module = load_screen_module()

    item = module.build_result_item(
        sample_snapshot(module),
        financial_rows=sample_financial_rows()[:3],
        risk_free=risk_free_payload(),
        min_market_cap=100_000_000,
    )

    assert item["status"] == "INSUFFICIENT_DATA"
    assert "missing_5y_financial_rows" in item["data_gaps"]
    assert item["reject_reasons"] == []


def test_industry_review_required_takes_precedence_over_generic_financial_rules():
    module = load_screen_module()
    weak_bank_rows = [row | {"free_cash_flow": -1.0} for row in sample_financial_rows()]

    item = module.build_result_item(
        sample_snapshot(module, industry="银行"),
        financial_rows=weak_bank_rows,
        risk_free=risk_free_payload(),
        min_market_cap=100_000_000,
    )

    assert item["status"] == "INDUSTRY_REVIEW_REQUIRED"
    assert "industry_review_required" in item["data_gaps"]
    assert item["reject_reasons"] == []


def test_result_payload_uses_snake_case_without_legacy_camel_case():
    module = load_screen_module()

    item = module.build_result_item(
        sample_snapshot(module),
        financial_rows=sample_financial_rows(),
        risk_free=risk_free_payload(),
        min_market_cap=100_000_000,
    )

    forbidden = {
        "metricSnapshot",
        "peTtm",
        "roeMean",
        "roeStd",
        "qualityFlags",
        "valuationFlags",
        "rejectReasons",
        "nextResearchChecks",
    }
    assert forbidden.isdisjoint(set(walk_keys(item)))


def test_cli_writes_json_and_xlsx_outputs(monkeypatch, tmp_path, capsys):
    module = load_screen_module()
    snapshot = sample_snapshot(module)

    monkeypatch.setattr(module, "fetch_market_snapshots", lambda **kwargs: ([snapshot], []))
    monkeypatch.setattr(module, "fetch_financial_rows", lambda *args, **kwargs: sample_financial_rows())
    monkeypatch.setattr(module, "fetch_risk_free_rate", lambda *args, **kwargs: risk_free_payload() | {"ok": True})

    json_out = tmp_path / "screen.json"
    xlsx_out = tmp_path / "screen.xlsx"
    exit_code = module.main(
        [
            "--markets",
            "SH",
            "SZ",
            "HK",
            "--max-count",
            "1",
            "--enrich-limit",
            "1",
            "--min-market-cap",
            "100000000",
            "--json-out",
            str(json_out),
            "--xlsx-out",
            str(xlsx_out),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["summary"]["candidate"] == 1
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["results"][0]["ticker"] == "000001.SZ"
    workbook = load_workbook(xlsx_out)
    assert workbook["Candidate"].max_row == 2
