from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_risk_free_rate.py"


def load_rate_module():
    spec = importlib.util.spec_from_file_location("fetch_risk_free_rate_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load risk-free rate fetcher from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, text: str, status_error: Exception | None = None, content: bytes | None = None):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = []

    def get(self, url: str, timeout: float):
        self.calls.append(("get", url, timeout))
        return self.response

    def post(self, url: str, params: dict[str, str], timeout: float):
        self.calls.append(("post", url, params, timeout))
        return self.response


class FakeSheet:
    name = "T10.4.3.1 (Benchmark yields)"

    rows = [
        ["", "", "", "3-year", "5-year", "7-year", "10-year", "15-year", "20-year"],
        ["", "", 46168.0, 2.71, 2.75, 2.86, 3.191, 3.45, 3.98],
        ["", "", 46169.0, 2.72, 2.76, 2.87, "-", 3.46, 3.99],
        ["", "", 46171.0, 2.735, 2.758, 2.884, 3.21, 3.498, 3.926],
    ]

    @property
    def nrows(self):
        return len(self.rows)

    @property
    def ncols(self):
        return max(len(row) for row in self.rows)

    def cell_value(self, row: int, column: int):
        try:
            return self.rows[row][column]
        except IndexError:
            return ""


class FakeWorkbook:
    datemode = 0

    def sheets(self):
        return [FakeSheet()]

    def sheet_by_index(self, index: int):
        return self.sheets()[index]


CHINABOND_SAMPLE_HTML = """
<html><body>
<table><tr><td><span>中债国债收益率曲线(到期)</span></td>
<td><a href="/cbweb-mn/yc/downBzqxDetail?workTime=2026-06-30">标准期限信息下载(excel)</a></td></tr></table>
<table>
  <tr><td>标准期限</td><td>收益率(%)</td></tr>
  <tr><td>7.0y</td><td>1.5667</td></tr>
  <tr><td>10.0y</td><td>1.733</td></tr>
  <tr><td>30.0y</td><td>2.236</td></tr>
</table>
</body></html>
"""

MOF_JGB_SAMPLE_CSV = """Interest Rate (June 2026),,,,,,,,,,,,,,,(Unit : %)
Date,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y,20Y,25Y,30Y,40Y
2026/6/29,1.173,1.411,1.547,1.753,1.916,2.053,2.201,2.367,2.513,2.644,3.204,3.54,3.791,3.785,3.715
2026/6/30,1.165,1.382,1.531,1.755,1.937,2.075,2.231,2.398,2.553,2.69,3.271,3.625,3.883,3.873,3.792
"""

HKMA_SAMPLE_XLS_BYTES = b"hkma-xls"


def test_risk_free_fetcher_keeps_runtime_dependencies_lightweight():
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "import requests" in source
    for heavy_import in ("pandas", "yfinance", "openpyxl", "bs4", "lxml"):
        assert heavy_import not in source


def test_parse_fred_dgs10_csv_uses_latest_non_empty_observation():
    module = load_rate_module()

    parsed = module.parse_fred_dgs10_csv(
        "observation_date,DGS10\n"
        "2026-06-26,4.25\n"
        "2026-06-29,.\n"
        "2026-06-30,4.38\n"
    )

    assert parsed == {"asOf": "2026-06-30", "ratePercent": 4.38}


def test_fetch_usd_rate_from_fred_session():
    module = load_rate_module()
    session = FakeSession(FakeResponse("observation_date,DGS10\n2026-06-30,4.38\n"))
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    result = module.fetch_usd_rate(session=session, timeout=3, now=now)

    assert result["ok"] is True
    assert result["currency"] == "USD"
    assert result["ratePercent"] == 4.38
    assert result["asOf"] == "2026-06-30"
    assert result["confidence"] == "official"
    assert result["staleDays"] == 1
    assert result["multipleCaps"]["conservativeN2"] == 11.42
    assert session.calls == [("get", module.FRED_DGS10_CSV_URL, 3)]


def test_parse_chinabond_detail_html_extracts_cny_10y_yield():
    module = load_rate_module()

    parsed = module.parse_chinabond_yc_detail_html(CHINABOND_SAMPLE_HTML)

    assert parsed == {
        "asOf": "2026-06-30",
        "ratePercent": 1.733,
        "curveName": "中债国债收益率曲线(到期)",
    }


def test_fetch_cny_rate_from_chinabond_session():
    module = load_rate_module()
    session = FakeSession(FakeResponse(CHINABOND_SAMPLE_HTML))
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    result = module.fetch_cny_rate(session=session, timeout=5, now=now)

    assert result["ok"] is True
    assert result["currency"] == "CNY"
    assert result["ratePercent"] == 1.733
    assert result["asOf"] == "2026-06-30"
    assert result["confidence"] == "official-web"
    assert result["multipleCaps"]["conservativeN2"] == 20.0
    assert session.calls[0][0] == "post"
    assert session.calls[0][1] == module.CHINABOND_YC_DETAIL_URL
    assert session.calls[0][2]["ycDefIds"] == module.CHINABOND_CGB_YC_DEF_ID


def test_parse_mof_jgb_current_csv_extracts_jpy_10y_yield():
    module = load_rate_module()

    parsed = module.parse_mof_jgb_current_csv(MOF_JGB_SAMPLE_CSV)

    assert parsed == {"asOf": "2026-06-30", "ratePercent": 2.69}


def test_parse_hkma_hkd_benchmark_workbook_extracts_latest_10y_yield():
    module = load_rate_module()

    parsed = module.parse_hkma_hkd_benchmark_workbook(FakeWorkbook())

    assert parsed == {"asOf": "2026-05-29", "ratePercent": 3.21}


def test_fetch_jpy_rate_from_mof_session():
    module = load_rate_module()
    session = FakeSession(FakeResponse(MOF_JGB_SAMPLE_CSV))
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    result = module.fetch_jpy_rate(session=session, timeout=7, now=now)

    assert result["ok"] is True
    assert result["currency"] == "JPY"
    assert result["ratePercent"] == 2.69
    assert result["asOf"] == "2026-06-30"
    assert result["confidence"] == "official"
    assert result["multipleCaps"]["conservativeN2"] == 18.59
    assert session.calls == [("get", module.MOF_JGB_CURRENT_CSV_URL, 7)]


def test_fetch_hkd_rate_from_hkma_session(monkeypatch):
    module = load_rate_module()
    session = FakeSession(FakeResponse("", content=HKMA_SAMPLE_XLS_BYTES))
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(
        module,
        "parse_hkma_hkd_benchmark_xls",
        lambda content: {"asOf": "2026-05-29", "ratePercent": 3.21},
    )
    result = module.fetch_hkd_rate(session=session, timeout=9, now=now)

    assert result["ok"] is True
    assert result["currency"] == "HKD"
    assert result["ratePercent"] == 3.21
    assert result["asOf"] == "2026-05-29"
    assert result["confidence"] == "official"
    assert result["multipleCaps"]["conservativeN2"] == 15.58
    assert session.calls == [("get", module.HKMA_HKD_BENCHMARK_XLS_URL, 9)]


def test_cny_failure_is_stable_when_chinabond_html_has_no_10y_row():
    module = load_rate_module()
    session = FakeSession(FakeResponse("<html><table><tr><td>7.0y</td><td>1.5</td></tr></table></html>"))

    result = module.fetch_risk_free_rate("CNY", session=session)

    assert result["ok"] is False
    assert result["phase"] == "risk_free_rate"
    assert result["currency"] == "CNY"
    assert result["tenorYears"] == 10
    assert "no 10.0y yield row" in result["error"]
    assert result["sourceUrl"] == module.CHINABOND_YIELD_MAIN_URL


def test_hkd_failure_is_stable_when_hkma_xls_cannot_be_parsed(monkeypatch):
    module = load_rate_module()
    session = FakeSession(FakeResponse("", content=b"not-a-workbook"))

    monkeypatch.setattr(
        module,
        "parse_hkma_hkd_benchmark_xls",
        lambda content: (_ for _ in ()).throw(module.RiskFreeRateError("bad HKMA workbook")),
    )
    rejected = module.fetch_risk_free_rate("HKD", session=session)

    assert rejected["ok"] is False
    assert rejected["phase"] == "risk_free_rate"
    assert rejected["currency"] == "HKD"
    assert "bad HKMA workbook" in rejected["error"]
    assert rejected["sourceUrl"] == module.HKMA_HKD_BENCHMARK_PAGE_URL
    assert session.calls == [("get", module.HKMA_HKD_BENCHMARK_XLS_URL, 20)]


def test_multiple_cap_formula():
    module = load_rate_module()

    assert module.multiple_cap(4.38, 2.0) == 11.42
    assert module.multiple_cap(4.38, 1.5) == 15.22
    assert module.multiple_cap(1.0, 2.0) == 20.0


def test_main_can_write_explicit_json_out(monkeypatch, tmp_path, capsys):
    module = load_rate_module()
    output_path = tmp_path / "rate.json"
    payload = {"ok": True, "currency": "CNY", "ratePercent": 1.733}

    monkeypatch.setattr(module, "fetch_risk_free_rate", lambda *args, **kwargs: payload)

    exit_code = module.main(["--currency", "CNY", "--json-out", str(output_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out) == payload
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_fetch_usd_rate_from_fred_live():
    if os.environ.get("STOCK_RESEARCH_RUN_LIVE_TESTS") != "1":
        pytest.skip("Set STOCK_RESEARCH_RUN_LIVE_TESTS=1 to run live source tests.")
    module = load_rate_module()

    result = module.fetch_risk_free_rate("USD", timeout=20)

    assert result["ok"] is True, result
    assert result["currency"] == "USD"
    assert 0 < result["ratePercent"] < 20
    assert result["asOf"]
    assert result["confidence"] == "official"


def test_fetch_cny_rate_from_chinabond_live():
    if os.environ.get("STOCK_RESEARCH_RUN_LIVE_TESTS") != "1":
        pytest.skip("Set STOCK_RESEARCH_RUN_LIVE_TESTS=1 to run live source tests.")
    module = load_rate_module()

    result = module.fetch_risk_free_rate("CNY", timeout=20)

    assert result["ok"] is True, result
    assert result["currency"] == "CNY"
    assert 0 < result["ratePercent"] < 10
    assert result["asOf"]
    assert result["confidence"] == "official-web"
    assert "ChinaBond" in result["source"]


def test_fetch_jpy_rate_from_mof_live():
    if os.environ.get("STOCK_RESEARCH_RUN_LIVE_TESTS") != "1":
        pytest.skip("Set STOCK_RESEARCH_RUN_LIVE_TESTS=1 to run live source tests.")
    module = load_rate_module()

    result = module.fetch_risk_free_rate("JPY", timeout=45)

    assert result["ok"] is True, result
    assert result["currency"] == "JPY"
    assert 0 < result["ratePercent"] < 20
    assert result["asOf"]
    assert result["confidence"] == "official"


def test_fetch_hkd_rate_from_hkma_live():
    if os.environ.get("STOCK_RESEARCH_RUN_LIVE_TESTS") != "1":
        pytest.skip("Set STOCK_RESEARCH_RUN_LIVE_TESTS=1 to run live source tests.")
    module = load_rate_module()

    result = module.fetch_risk_free_rate("HKD", timeout=45)

    assert result["ok"] is True, result
    assert result["currency"] == "HKD"
    assert 0 < result["ratePercent"] < 20
    assert result["asOf"]
    assert result["confidence"] == "official"
    assert "HKMA" in result["source"]
