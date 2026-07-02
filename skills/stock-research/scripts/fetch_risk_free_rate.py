#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from html.parser import HTMLParser
import io
import json
import re
from datetime import date, datetime, timezone
from typing import Any

import requests


FRED_DGS10_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
FRED_DGS10_PAGE_URL = "https://fred.stlouisfed.org/series/DGS10"
CHINABOND_CGB_YC_DEF_ID = "2c9081e50a2f9606010a3068cae70001"
CHINABOND_YC_DETAIL_URL = "https://yield.chinabond.com.cn/cbweb-mn/yc/ycDetail"
CHINABOND_YIELD_MAIN_URL = "https://yield.chinabond.com.cn/cbweb-mn/yield_main?locale=zh_CN"
MOF_JGB_CURRENT_CSV_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
MOF_JGB_INTEREST_RATE_PAGE_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/"
HKMA_HKD_BENCHMARK_XLS_URL = (
    "https://www.hkma.gov.hk/media/eng/doc/market-data-and-statistics/"
    "monthly-statistical-bulletin/T10040301.xls"
)
HKMA_HKD_BENCHMARK_PAGE_URL = (
    "https://www.hkma.gov.hk/eng/data-publications-and-research/"
    "data-and-statistics/monthly-statistical-bulletin/"
)

SOVEREIGN_SOURCES: dict[str, dict[str, str]] = {
    "USD": {
        "name": "FRED DGS10 / Federal Reserve H.15 10-Year Treasury Constant Maturity",
        "url": FRED_DGS10_PAGE_URL,
        "tenor": "10Y",
    },
    "CNY": {
        "name": "ChinaBond CGB 10Y / 中债国债收益率曲线10年期",
        "url": CHINABOND_YIELD_MAIN_URL,
        "tenor": "10Y",
    },
    "HKD": {
        "name": "HKMA Monthly Statistical Bulletin Table 10.4.3.1 HKD Government Bond Benchmark Yield",
        "url": HKMA_HKD_BENCHMARK_PAGE_URL,
        "tenor": "10Y",
    },
    "JPY": {
        "name": "Japan 10-Year Government Bond Yield",
        "url": MOF_JGB_INTEREST_RATE_PAGE_URL,
        "tenor": "10Y",
    },
}


class RiskFreeRateError(RuntimeError):
    """Raised when the rate source cannot return a usable 10Y yield."""


class SimpleTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "tr":
            self._current_row = []
        elif tag.lower() in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            cell = " ".join("".join(self._current_cell).split())
            self._current_row.append(cell)
            self._current_cell = None
        elif normalized_tag == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None


def iso_now(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def stale_days(as_of: str, now: datetime | None = None) -> int | None:
    try:
        as_of_date = date.fromisoformat(as_of)
    except ValueError:
        return None
    current = now or datetime.now(timezone.utc)
    return (current.date() - as_of_date).days


def multiple_cap(rate_percent: float, n: float, absolute_cap: float = 20.0) -> float:
    if rate_percent <= 0 or n <= 0:
        return absolute_cap
    return round(min(absolute_cap, 100 / (n * rate_percent)), 2)


def multiple_caps(rate_percent: float) -> dict[str, float]:
    return {
        "conservativeN2": multiple_cap(rate_percent, 2.0),
        "qualityN1_5": multiple_cap(rate_percent, 1.5),
        "absoluteCap": 20.0,
    }


def parse_fred_dgs10_csv(text: str) -> dict[str, Any]:
    rows = csv.DictReader(io.StringIO(text))
    latest: dict[str, Any] | None = None
    for row in rows:
        value = (row.get("DGS10") or "").strip()
        observation_date = (row.get("observation_date") or "").strip()
        if not observation_date or not value or value == ".":
            continue
        try:
            latest = {"asOf": observation_date, "ratePercent": float(value)}
        except ValueError:
            continue
    if latest is None:
        raise RiskFreeRateError("FRED DGS10 returned no usable 10Y yield observations.")
    return latest


def parse_chinabond_yc_detail_html(text: str) -> dict[str, Any]:
    parser = SimpleTableParser()
    parser.feed(text)

    curve_name = "中债国债收益率曲线(到期)"
    for row in parser.rows:
        for cell in row:
            if "中债国债收益率曲线" in cell:
                curve_name = cell
                break

    work_time_match = re.search(r"workTime=(\d{4}-\d{2}-\d{2})", text)
    as_of = work_time_match.group(1) if work_time_match else None

    for row in parser.rows:
        if len(row) < 2:
            continue
        tenor = row[0].strip().lower()
        value = row[1].strip()
        if tenor in {"10.0y", "10y", "10 y"}:
            try:
                return {"asOf": as_of, "ratePercent": float(value), "curveName": curve_name}
            except ValueError as exc:
                raise RiskFreeRateError(f"ChinaBond 10Y yield is not numeric: {value}") from exc

    raise RiskFreeRateError("ChinaBond detail page returned no 10.0y yield row.")


def parse_mof_jgb_current_csv(text: str) -> dict[str, Any]:
    rows = list(csv.reader(io.StringIO(text)))
    header_index = None
    for index, row in enumerate(rows):
        if row and row[0].strip() == "Date":
            header_index = index
            break
    if header_index is None:
        raise RiskFreeRateError("MOF JGB CSV returned no Date header row.")

    header = [cell.strip() for cell in rows[header_index]]
    try:
        date_index = header.index("Date")
        ten_year_index = header.index("10Y")
    except ValueError as exc:
        raise RiskFreeRateError("MOF JGB CSV returned no 10Y column.") from exc

    latest: dict[str, Any] | None = None
    for row in rows[header_index + 1 :]:
        if len(row) <= max(date_index, ten_year_index):
            continue
        date_text = row[date_index].strip()
        value = row[ten_year_index].strip()
        if not date_text or not value:
            continue
        try:
            as_of = datetime.strptime(date_text, "%Y/%m/%d").date().isoformat()
            latest = {"asOf": as_of, "ratePercent": float(value)}
        except ValueError:
            continue
    if latest is None:
        raise RiskFreeRateError("MOF JGB CSV returned no usable 10Y yield observations.")
    return latest


def parse_hkma_hkd_benchmark_workbook(book: Any) -> dict[str, Any]:
    try:
        sheet = next(sheet for sheet in book.sheets() if "Benchmark yields" in sheet.name)
    except StopIteration:
        sheet = book.sheet_by_index(0)

    date_column = None
    ten_year_column = None
    for row_index in range(sheet.nrows):
        row_values = [str(sheet.cell_value(row_index, column_index)).strip().lower() for column_index in range(sheet.ncols)]
        if "10-year" not in row_values:
            continue
        ten_year_column = row_values.index("10-year")
        first_tenor_column = min(
            column_index
            for column_index, value in enumerate(row_values)
            if value in {"3-year", "5-year", "7-year", "10-year", "15-year", "20-year"}
        )
        date_column = first_tenor_column - 1
        break

    if ten_year_column is None or date_column is None or date_column < 0:
        raise RiskFreeRateError("HKMA workbook returned no 10-year benchmark yield header.")

    for row_index in range(sheet.nrows - 1, -1, -1):
        date_value = sheet.cell_value(row_index, date_column)
        rate_value = sheet.cell_value(row_index, ten_year_column)
        if rate_value in ("", "-") or date_value in ("", "-"):
            continue
        try:
            rate_percent = float(rate_value)
        except (TypeError, ValueError):
            continue
        try:
            import xlrd

            as_of = xlrd.xldate_as_datetime(float(date_value), book.datemode).date().isoformat()
        except Exception as exc:
            raise RiskFreeRateError(f"HKMA 10Y yield date is not usable: {date_value}") from exc
        return {"asOf": as_of, "ratePercent": rate_percent}

    raise RiskFreeRateError("HKMA workbook returned no usable 10Y benchmark yield observations.")


def parse_hkma_hkd_benchmark_xls(content: bytes) -> dict[str, Any]:
    try:
        import xlrd
    except ImportError as exc:
        raise RiskFreeRateError("xlrd is required to parse HKMA .xls data.") from exc

    try:
        book = xlrd.open_workbook(file_contents=content)
    except Exception as exc:
        raise RiskFreeRateError(f"HKMA .xls workbook could not be opened: {exc}") from exc
    return parse_hkma_hkd_benchmark_workbook(book)


def success_payload(
    *,
    currency: str,
    rate_percent: float,
    as_of: str | None,
    source: str,
    source_url: str,
    confidence: str,
    fetched_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "currency": currency,
        "tenorYears": 10,
        "ratePercent": rate_percent,
        "asOf": as_of,
        "source": source,
        "sourceUrl": source_url,
        "confidence": confidence,
        "fetchedAt": fetched_at or iso_now(now),
        "staleDays": stale_days(as_of, now) if as_of else None,
        "multipleCaps": multiple_caps(rate_percent),
    }
    return result


def failure_payload(
    *,
    currency: str,
    error: str,
    source: str | None = None,
    source_url: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "phase": "risk_free_rate",
        "currency": currency,
        "tenorYears": 10,
        "error": error,
        "fetchedAt": iso_now(now),
    }
    if source:
        result["source"] = source
    if source_url:
        result["sourceUrl"] = source_url
    return result


def fetch_usd_rate(
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    client = session or requests.Session()
    try:
        response = client.get(FRED_DGS10_CSV_URL, timeout=timeout)
        response.raise_for_status()
        parsed = parse_fred_dgs10_csv(response.text)
    except Exception as exc:
        raise RiskFreeRateError(f"USD 10Y yield fetch failed: {exc}") from exc

    return success_payload(
        currency="USD",
        rate_percent=parsed["ratePercent"],
        as_of=parsed["asOf"],
        source=SOVEREIGN_SOURCES["USD"]["name"],
        source_url=FRED_DGS10_PAGE_URL,
        confidence="official",
        now=now,
    )


def fetch_cny_rate(
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    client = session or requests.Session()
    params = {
        "ycDefIds": CHINABOND_CGB_YC_DEF_ID,
        "zblx": "txy",
        "workTime": "",
        "dxbj": "",
        "qxlx": "",
        "yqqxN": "",
        "yqqxK": "",
        "wrjxCBFlag": "0",
        "locale": "zh_CN",
    }
    try:
        response = client.post(CHINABOND_YC_DETAIL_URL, params=params, timeout=timeout)
        response.raise_for_status()
        parsed = parse_chinabond_yc_detail_html(response.text)
    except Exception as exc:
        raise RiskFreeRateError(f"CNY 10Y yield fetch failed: {exc}") from exc

    return success_payload(
        currency="CNY",
        rate_percent=parsed["ratePercent"],
        as_of=parsed["asOf"],
        source=f"{parsed['curveName']} / ChinaBond",
        source_url=CHINABOND_YIELD_MAIN_URL,
        confidence="official-web",
        now=now,
    )


def fetch_jpy_rate(
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    client = session or requests.Session()
    try:
        response = client.get(MOF_JGB_CURRENT_CSV_URL, timeout=timeout)
        response.raise_for_status()
        parsed = parse_mof_jgb_current_csv(response.text)
    except Exception as exc:
        raise RiskFreeRateError(f"JPY 10Y yield fetch failed: {exc}") from exc

    return success_payload(
        currency="JPY",
        rate_percent=parsed["ratePercent"],
        as_of=parsed["asOf"],
        source=SOVEREIGN_SOURCES["JPY"]["name"],
        source_url=MOF_JGB_INTEREST_RATE_PAGE_URL,
        confidence="official",
        now=now,
    )


def fetch_hkd_rate(
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 30,
    now: datetime | None = None,
) -> dict[str, Any]:
    client = session or requests.Session()
    try:
        response = client.get(HKMA_HKD_BENCHMARK_XLS_URL, timeout=timeout)
        response.raise_for_status()
        parsed = parse_hkma_hkd_benchmark_xls(response.content)
    except Exception as exc:
        raise RiskFreeRateError(f"HKD 10Y yield fetch failed: {exc}") from exc

    return success_payload(
        currency="HKD",
        rate_percent=parsed["ratePercent"],
        as_of=parsed["asOf"],
        source=SOVEREIGN_SOURCES["HKD"]["name"],
        source_url=HKMA_HKD_BENCHMARK_XLS_URL,
        confidence="official",
        now=now,
    )


def fetch_risk_free_rate(
    currency: str,
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_currency = currency.upper()

    if normalized_currency == "USD":
        try:
            return fetch_usd_rate(session=session, timeout=timeout, now=now)
        except RiskFreeRateError as exc:
            return failure_payload(currency="USD", error=str(exc), now=now)

    if normalized_currency == "CNY":
        try:
            return fetch_cny_rate(session=session, timeout=timeout, now=now)
        except RiskFreeRateError as exc:
            return failure_payload(
                currency="CNY",
                error=str(exc),
                source=SOVEREIGN_SOURCES["CNY"]["name"],
                source_url=SOVEREIGN_SOURCES["CNY"]["url"],
                now=now,
            )

    if normalized_currency == "JPY":
        try:
            return fetch_jpy_rate(session=session, timeout=timeout, now=now)
        except RiskFreeRateError as exc:
            return failure_payload(
                currency="JPY",
                error=str(exc),
                source=SOVEREIGN_SOURCES["JPY"]["name"],
                source_url=SOVEREIGN_SOURCES["JPY"]["url"],
                now=now,
            )

    if normalized_currency == "HKD":
        try:
            return fetch_hkd_rate(session=session, timeout=timeout, now=now)
        except RiskFreeRateError as exc:
            return failure_payload(
                currency="HKD",
                error=str(exc),
                source=SOVEREIGN_SOURCES["HKD"]["name"],
                source_url=SOVEREIGN_SOURCES["HKD"]["url"],
                now=now,
            )

    metadata = SOVEREIGN_SOURCES.get(normalized_currency)
    if metadata is None:
        return failure_payload(
            currency=normalized_currency,
            error="Unsupported currency. Configure an official source before using this currency.",
            now=now,
        )

    return failure_payload(
        currency=normalized_currency,
        error="No official source fetcher is configured for this currency.",
        source=metadata["name"],
        source_url=metadata["url"],
        now=now,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a same-currency 10Y sovereign/risk-free yield.")
    parser.add_argument("--currency", required=True, help="Cash-flow currency, e.g. USD, CNY, HKD, JPY.")
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    result = fetch_risk_free_rate(
        args.currency,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
