from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import requests

from screen_stock_common import (
    DEFAULT_PAGE_SIZE,
    EASTMONEY_LIST_FIELDS,
    EASTMONEY_QUOTE_UT,
    EASTMONEY_WBP2U,
    MARKET_CONFIGS,
    MARKET_SNAPSHOT_ENDPOINT,
    MIN_FINANCIAL_YEARS,
    SORT_FIELDS,
    US_MARKET_CODE_BY_SUFFIX,
    MarketSnapshot,
    configure_session,
    normalize_currency,
    parse_json_or_jsonp,
    sleep_if_needed,
    to_float,
    us_ticker_for_eastmoney_market,
)
from screen_stock_parsers import (
    parse_market_snapshot,
)


# Market snapshot fetching must stay single-source: Eastmoney webguest clist for
# SH/SZ/HK/US. Financial statement endpoints below may differ by market, but
# the screening universe must not mix HKEX, Tencent, xuangu, or alternate hosts.
EASTMONEY_WEBGUEST_LIST_URL = MARKET_SNAPSHOT_ENDPOINT
EASTMONEY_DATA_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
EASTMONEY_DATA_V1_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
EASTMONEY_HK_DATA_URL = "https://emh5.eastmoney.com/api/GangGu/CaiWu"

US_INCOME_ITEM_CODES = {
    "revenue": "004001999",
    "net_profit": ("004015999", "004013999", "004013003"),
}
US_CASHFLOW_ITEM_CODES = {
    "operating_cash_flow": "003999",
    "capex": "005002",
}
US_BALANCE_ITEM_CODES = {
    "cash_and_equivalents": "004001001",
    "current_financial_assets": "004001016",
    "noncurrent_financial_assets": "004003015",
    "total_assets": "004005999",
    "short_debt": "004007007",
    "long_debt": "004009005",
    "total_liabilities": "004011999",
    "equity": "004017999",
}
US_REPORT_LOOKBACK_YEARS = MIN_FINANCIAL_YEARS + 5


def sum_present_values(*values: Any) -> float | None:
    present = [to_float(value) for value in values if to_float(value) is not None]
    return sum(present) if present else None


def sum_present_fields(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    return sum_present_values(*(row.get(key) for key in keys))


def eastmoney_list_url_for_market(market: str) -> str:
    # Keep one endpoint for every supported market; tests enforce this boundary.
    return EASTMONEY_WEBGUEST_LIST_URL


def fetch_eastmoney_list_market_snapshots(
    *,
    markets: list[str],
    max_count: int,
    sort_by: str,
    min_market_cap: float | None = None,
    request_delay: float = 0.0,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
) -> tuple[list[MarketSnapshot], list[dict[str, Any]]]:
    client = configure_session(session or requests.Session())
    snapshots: list[MarketSnapshot] = []
    errors: list[dict[str, Any]] = []
    page_size = DEFAULT_PAGE_SIZE if max_count <= 0 else min(max_count, DEFAULT_PAGE_SIZE)
    max_pages = None if max_count <= 0 else max(1, math.ceil(max_count / page_size))

    for market in markets:
        config = MARKET_CONFIGS[market]
        market_snapshots: list[MarketSnapshot] = []
        page_number = 1
        while max_pages is None or page_number <= max_pages:
            list_url = eastmoney_list_url_for_market(market)
            params = {
                "pn": page_number,
                "pz": page_size,
                "po": 1,
                "np": 1,
                "ut": EASTMONEY_QUOTE_UT,
                "fltt": 1,
                "invt": 2,
                "fid": SORT_FIELDS.get(sort_by, "f20"),
                "fs": config["fs"],
                "fields": EASTMONEY_LIST_FIELDS,
                "dect": 1,
                "wbp2u": EASTMONEY_WBP2U,
                "_": int(datetime.now(timezone.utc).timestamp() * 1000),
            }
            params["timil"] = 1
            params["cb"] = "jQuery1124"
            try:
                response = client.get(list_url, params=params, timeout=timeout)
                response.raise_for_status()
                payload = parse_json_or_jsonp(response.text)
                rows = ((payload.get("data") or {}).get("diff") or [])
            except Exception as exc:
                errors.append({"market": market, "phase": "market_snapshot", "error": f"{list_url}: {exc}"})
                break

            reached_market_cap_floor = False
            for row in rows:
                try:
                    snapshot = parse_market_snapshot(row, market)
                except Exception as exc:
                    errors.append({"market": market, "phase": "market_snapshot_parse", "error": str(exc)})
                    continue
                if (
                    sort_by == "market_cap"
                    and min_market_cap is not None
                    and snapshot.market_cap is not None
                    and snapshot.market_cap < min_market_cap
                ):
                    reached_market_cap_floor = True
                    continue
                market_snapshots.append(snapshot)
            if len(rows) < page_size:
                break
            if reached_market_cap_floor:
                break
            if max_count > 0 and len(market_snapshots) >= max_count:
                break
            page_number += 1
            sleep_if_needed(request_delay)
        market_snapshots.sort(key=lambda item: item.market_cap or 0, reverse=True)
        snapshots.extend(market_snapshots if max_count <= 0 else market_snapshots[:max_count])

    return snapshots, errors


def fetch_market_snapshots(
    *,
    markets: list[str],
    max_count: int,
    sort_by: str,
    min_market_cap: float | None = None,
    request_delay: float = 0.0,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
) -> tuple[list[MarketSnapshot], list[dict[str, Any]]]:
    client = configure_session(session or requests.Session())
    return fetch_eastmoney_list_market_snapshots(
        markets=markets,
        max_count=max_count,
        sort_by=sort_by,
        min_market_cap=min_market_cap,
        request_delay=request_delay,
        session=client,
        timeout=timeout,
    )


def annotate_market_cap_universe(snapshots: list[MarketSnapshot]) -> None:
    by_market: dict[str, list[MarketSnapshot]] = {}
    for snapshot in snapshots:
        by_market.setdefault(snapshot.market, []).append(snapshot)

    for market_snapshots in by_market.values():
        ordered = sorted(market_snapshots, key=lambda item: item.market_cap or 0, reverse=True)
        total = len(ordered)
        if total == 0:
            continue
        for index, snapshot in enumerate(ordered, start=1):
            snapshot.market_cap_rank = index
            snapshot.market_cap_percentile = round(100 * index / total, 4)
            snapshot.selected_for_financial_analysis = True


def get_json(
    session: requests.sessions.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    request_delay: float = 0.0,
    timeout: float = 20,
) -> dict[str, Any]:
    try:
        if data is None:
            response = session.get(url, params=params, timeout=timeout)
        else:
            response = session.post(url, data=data, timeout=timeout)
        response.raise_for_status()
        try:
            return parse_json_or_jsonp(response.content.decode("utf-8"))
        except UnicodeDecodeError:
            return parse_json_or_jsonp(response.text)
    finally:
        sleep_if_needed(request_delay)


def fetch_a_company_type(
    snapshot: MarketSnapshot,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> str:
    params = {
        "filter": f'(SECUCODE="{snapshot.code}.{snapshot.market}")',
        "client": "APP",
        "source": "HSF10",
        "type": "RPT_F10_PUBLIC_COMPANYTPYE",
        "sty": "ALL",
    }
    payload = get_json(session, EASTMONEY_DATA_URL, params=params, request_delay=request_delay, timeout=timeout)
    return str(payload["result"]["data"][0]["COMPANY_TYPE"])


def fetch_a_statement_rows(
    snapshot: MarketSnapshot,
    *,
    statement_type: str,
    style: str,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> list[dict[str, Any]]:
    params = {
        "filter": f'(SECUCODE="{snapshot.code}.{snapshot.market}")(REPORT_TYPE="年报")',
        "client": "APP",
        "source": "HSF10",
        "type": statement_type,
        "sty": style,
        "ps": MIN_FINANCIAL_YEARS + 1,
        "sr": -1,
        "st": "REPORT_DATE",
    }
    payload = get_json(session, EASTMONEY_DATA_URL, params=params, request_delay=request_delay, timeout=timeout)
    return (payload.get("result") or {}).get("data") or []


def fetch_a_financial_rows(
    snapshot: MarketSnapshot,
    *,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float = 0.0,
) -> list[dict[str, Any]]:
    company_type = fetch_a_company_type(snapshot, session, timeout, request_delay)
    statement_suffixes = {"1": "S", "2": "I", "3": "B", "4": "G"}
    if company_type not in statement_suffixes:
        raise RuntimeError(f"Unsupported A-share company type for {snapshot.ticker}: {company_type}")
    statement_suffix = statement_suffixes[company_type]

    income_rows = fetch_a_statement_rows(
        snapshot,
        statement_type="RPT_F10_FINANCE_MAINFINADATA",
        style="APP_F10_MAINFINADATA",
        session=session,
        timeout=timeout,
        request_delay=request_delay,
    )
    cash_rows = fetch_a_statement_rows(
        snapshot,
        statement_type=f"RPT_F10_FINANCE_{statement_suffix}CASHFLOW",
        style=f"APP_F10_{statement_suffix}CASHFLOW",
        session=session,
        timeout=timeout,
        request_delay=request_delay,
    )
    balance_rows = fetch_a_statement_rows(
        snapshot,
        statement_type=f"RPT_F10_FINANCE_{statement_suffix}BALANCE",
        style=f"F10_FINANCE_{statement_suffix}BALANCE",
        session=session,
        timeout=timeout,
        request_delay=request_delay,
    )

    by_year: dict[str, dict[str, Any]] = {}
    for row in income_rows:
        year = str(row.get("REPORT_DATE") or "")[:4]
        if not year:
            continue
        by_year.setdefault(year, {"year": year, "currency": "CNY"})
        by_year[year].update(
            {
                "revenue": to_float(row.get("TOTALOPERATEREVE") or row.get("OPERATEINCOME") or row.get("OPERATE_INCOME")),
                "net_profit": to_float(row.get("PARENTNETPROFIT")),
                "roe": to_float(row.get("ROEJQ")),
                "roic": to_float(row.get("ROIC")),
                "debt_to_assets_percent": to_float(row.get("ZCFZL")),
                "payout_ratio": None,
            }
        )
    for row in cash_rows:
        year = str(row.get("REPORT_DATE") or "")[:4]
        if not year:
            continue
        operating_cash_flow = to_float(row.get("NETCASH_OPERATE"))
        capex = to_float(row.get("CONSTRUCT_LONG_ASSET"))
        by_year.setdefault(year, {"year": year, "currency": "CNY"})
        by_year[year].update(
            {
                "operating_cash_flow": operating_cash_flow,
                "capex": capex,
                "free_cash_flow": operating_cash_flow - capex
                if operating_cash_flow is not None and capex is not None
                else None,
            }
        )
    for row in balance_rows:
        year = str(row.get("REPORT_DATE") or "")[:4]
        if not year:
            continue
        total_assets = to_float(row.get("TOTAL_ASSETS"))
        total_liabilities = to_float(row.get("TOTAL_LIABILITIES"))
        short_debt = sum_present_fields(
            row,
            (
                "SHORT_LOAN",
                "SHORT_BOND_PAYABLE",
                "SHORT_FIN_PAYABLE",
                "NONCURRENT_LIAB_1YEAR",
            ),
        )
        long_debt = sum_present_fields(
            row,
            (
                "LONG_LOAN",
                "BOND_PAYABLE",
                "LEASE_LIAB",
                "LONG_PAYABLE",
            ),
        )
        total_debt = sum_present_values(short_debt, long_debt)
        goodwill = to_float(row.get("GOODWILL")) or 0.0
        equity = total_assets - total_liabilities if total_assets is not None and total_liabilities is not None else None
        by_year.setdefault(year, {"year": year, "currency": "CNY"})
        by_year[year].update(
            {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "cash_and_equivalents": to_float(row.get("MONETARYFUNDS")),
                "current_financial_assets": sum_present_fields(
                    row,
                    (
                        "TRADE_FINASSET",
                        "FVTPL_FINASSET",
                        "DERIVE_FINASSET",
                        "OTHER_CURRENT_ASSET",
                    ),
                ),
                "noncurrent_financial_assets": sum_present_fields(
                    row,
                    (
                        "FVTOCI_FINASSET",
                        "FVTOCI_NCFINASSET",
                        "OTHER_EQUITY_INVEST",
                        "OTHER_NONCURRENT_FINASSET",
                        "OTHER_CREDITOR_INVEST",
                    ),
                ),
                "short_debt": short_debt,
                "long_debt": long_debt,
                "total_debt": total_debt,
                "goodwill": goodwill,
                "equity": equity,
            }
        )
    return [by_year[year] for year in sorted(by_year.keys(), reverse=True)]


def fetch_hk_company_type(
    snapshot: MarketSnapshot,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> str:
    payload = get_json(
        session,
        f"{EASTMONEY_HK_DATA_URL}/GetCompanyType",
        data={"fc": snapshot.code.zfill(5), "color": "w"},
        request_delay=request_delay,
        timeout=timeout,
    )
    return str(payload["Result"]["CompanyType"])


def fetch_hk_financial_rows(
    snapshot: MarketSnapshot,
    *,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float = 0.0,
) -> list[dict[str, Any]]:
    corp_type = fetch_hk_company_type(snapshot, session, timeout, request_delay)
    if corp_type != "4":
        return []

    post_data = {
        "fc": snapshot.code.zfill(5),
        "color": "w",
        "corpType": corp_type,
        "reportDateType": 6,
        "endDate": "",
        "latestCount": MIN_FINANCIAL_YEARS + 1,
        "reportTimeTypeCode": "",
    }
    main_payload = get_json(
        session,
        f"{EASTMONEY_HK_DATA_URL}/GetZhuYaoZhiBiaoList",
        data=post_data,
        request_delay=request_delay,
        timeout=timeout,
    )
    cash_payload = get_json(
        session,
        f"{EASTMONEY_HK_DATA_URL}/GetXianJinLiuLiangList",
        data=post_data,
        request_delay=request_delay,
        timeout=timeout,
    )
    balance_payload = get_json(
        session,
        f"{EASTMONEY_HK_DATA_URL}/GetZiChanFuZhaiList",
        data=post_data,
        request_delay=request_delay,
        timeout=timeout,
    )

    by_year: dict[str, dict[str, Any]] = {}
    for row in ((main_payload.get("Result") or {}).get("ZhuYaoZhiBiaoList_QiYe") or []):
        year = str(row.get("Reportdate") or "")[:4]
        if not year:
            continue
        currency = normalize_currency(row.get("Currency"), snapshot.currency)
        roe = to_float(row.get("Roe"))
        roic = to_float(row.get("Roic"))
        debt_to_assets = to_float(row.get("Debttoassets"))
        if debt_to_assets is not None and abs(debt_to_assets) < 1:
            debt_to_assets *= 100
        by_year.setdefault(year, {"year": year, "currency": currency})
        by_year[year].update(
            {
                "revenue": to_float(row.get("Revenue")),
                "net_profit": to_float(row.get("Parentnetprofit")),
                "roe": roe * 100 if roe is not None and abs(roe) < 1 else roe,
                "roic": roic * 100 if roic is not None and abs(roic) < 1 else roic,
                "debt_to_assets_percent": debt_to_assets,
                "payout_ratio": to_float(row.get("Diviratio")),
            }
        )
    for row in ((cash_payload.get("Result") or {}).get("DataList") or []):
        year = str(row.get("REPORTDATE") or "")[:4]
        if not year:
            continue
        operating_cash_flow = to_float(row.get("CS003999") or row.get("CS002999"))
        buy_capex = sum(to_float(row.get(key)) or 0 for key in ("CS005005", "CS005007"))
        sell_capex = sum(to_float(row.get(key)) or 0 for key in ("CS005004", "CS005006"))
        capex = buy_capex - sell_capex
        by_year.setdefault(year, {"year": year, "currency": normalize_currency(row.get("CURRENCY"), snapshot.currency)})
        by_year[year].update(
            {
                "operating_cash_flow": operating_cash_flow,
                "capex": capex,
                "free_cash_flow": operating_cash_flow - capex if operating_cash_flow is not None else None,
            }
        )
    for row in ((balance_payload.get("Result") or {}).get("DataList") or []):
        year = str(row.get("REPORTDATE") or "")[:4]
        if not year:
            continue
        total_assets = to_float(row.get("BS004009999"))
        total_liabilities = to_float(row.get("BS004025999"))
        short_debt = sum_present_fields(
            row,
            (
                "BS004011006",  # current lease liabilities
                "BS004011010",  # current borrowings
                "BS004011023",  # other current financial liabilities
            ),
        )
        long_debt = sum_present_fields(
            row,
            (
                "BS004020001",  # non-current borrowings
                "BS004020005",  # non-current lease liabilities
                "BS004020018",  # non-current notes payable
                "BS004020019",  # other non-current financial liabilities
            ),
        )
        total_debt = sum_present_values(short_debt, long_debt)
        goodwill = to_float(row.get("BS004001005")) or 0.0
        equity = total_assets - total_liabilities if total_assets is not None and total_liabilities is not None else None
        by_year.setdefault(year, {"year": year, "currency": normalize_currency(row.get("CURRENCY"), snapshot.currency)})
        by_year[year].update(
            {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "cash_and_equivalents": sum_present_fields(
                    row,
                    (
                        "BS004002009",  # restricted cash
                        "BS004002010",  # cash and cash equivalents
                    ),
                ),
                "current_financial_assets": sum_present_fields(
                    row,
                    (
                        "BS004002011",  # current term deposits
                        "BS004002013",  # current FV financial assets
                        "BS004002022",  # other current financial assets
                    ),
                ),
                "noncurrent_financial_assets": sum_present_fields(
                    row,
                    (
                        "BS004001022",  # non-current FV financial assets
                        "BS004001030",  # non-current term deposits
                        "BS004001031",  # other non-current financial assets
                    ),
                ),
                "short_debt": short_debt,
                "long_debt": long_debt,
                "total_debt": total_debt,
                "goodwill": goodwill,
                "equity": equity,
            }
        )
    return [by_year[year] for year in sorted(by_year.keys(), reverse=True)]


def percent_or_none(value: Any) -> float | None:
    result = to_float(value)
    if result is not None and abs(result) < 1:
        return result * 100
    return result


def us_secucode_candidates(snapshot: MarketSnapshot) -> list[str]:
    for value in (snapshot.ticker, snapshot.code):
        candidate = str(value or "").strip().upper()
        if "." in candidate and candidate.rsplit(".", 1)[-1] in US_MARKET_CODE_BY_SUFFIX:
            return [candidate]

    code = str(snapshot.code or snapshot.ticker or "").strip().upper().split(".", 1)[0]
    if not code:
        return []
    return [us_ticker_for_eastmoney_market(code, market_code) for market_code in ("105", "106", "107")]


def fetch_eastmoney_v1_rows(
    session: requests.sessions.Session,
    *,
    report_name: str,
    columns: str,
    filter_clause: str,
    timeout: float,
    request_delay: float,
    distinct: str | None = None,
    page_size: int = 1000,
    sort_columns: str = "REPORT_DATE,STD_ITEM_CODE",
    sort_types: str = "-1,1",
) -> list[dict[str, Any]]:
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_clause,
        "pageNumber": 1,
        "pageSize": page_size,
        "sortTypes": sort_types,
        "sortColumns": sort_columns,
        "source": "SECURITIES",
        "client": "PC",
    }
    if distinct:
        params["distinct"] = distinct
    payload = get_json(session, EASTMONEY_DATA_V1_URL, params=params, request_delay=request_delay, timeout=timeout)
    return (payload.get("result") or {}).get("data") or []


def is_us_annual_report(row: dict[str, Any]) -> bool:
    report = str(row.get("REPORT") or "").strip().upper()
    date_type = str(row.get("DATE_TYPE_CODE") or "").strip()
    report_type = str(row.get("REPORT_TYPE") or "").strip()
    return report.endswith("/FY") or date_type == "001" or report_type == "年报"


def us_report_year(row: dict[str, Any]) -> str:
    report_date = str(row.get("REPORT_DATE") or row.get("FINANCIAL_DATE") or "").strip()
    if len(report_date) >= 4:
        return report_date[:4]
    report = str(row.get("REPORT") or "").strip()
    return report.split("/", 1)[0] if "/" in report else report[:4]


def fetch_us_report_rows(
    secucode: str,
    *,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> list[dict[str, Any]]:
    rows = fetch_eastmoney_v1_rows(
        session,
        report_name="RPT_USSK_FN_CASHFLOW",
        columns=(
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT,REPORT_DATE,FISCAL_YEAR,"
            "CURRENCY,ACCOUNT_STANDARD,DATE_TYPE_CODE,REPORT_TYPE"
        ),
        filter_clause=f'(SECUCODE="{secucode}")(DATE_TYPE_CODE="001")',
        timeout=timeout,
        request_delay=request_delay,
        distinct="REPORT_DATE,DATE_TYPE_CODE",
        page_size=US_REPORT_LOOKBACK_YEARS,
        sort_columns="REPORT_DATE,DATE_TYPE_CODE",
        sort_types="-1,1",
    )
    annual_rows: list[dict[str, Any]] = []
    seen_reports: set[str] = set()
    for row in rows:
        report = str(row.get("REPORT") or "").strip()
        if not report or report in seen_reports or not is_us_annual_report(row):
            continue
        annual_rows.append(row)
        seen_reports.add(report)
        if len(annual_rows) >= US_REPORT_LOOKBACK_YEARS:
            break
    return annual_rows


def fetch_us_statement_rows(
    secucode: str,
    *,
    reports: list[str],
    report_name: str,
    columns: str,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> list[dict[str, Any]]:
    report_filter = ",".join(f'"{report}"' for report in reports)
    return fetch_eastmoney_v1_rows(
        session,
        report_name=report_name,
        columns=columns,
        filter_clause=f'(SECUCODE="{secucode}")(REPORT in ({report_filter}))',
        timeout=timeout,
        request_delay=request_delay,
        page_size=1000,
    )


def amount_rows_by_report_and_item(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    mapped: dict[str, dict[str, float]] = {}
    for row in rows:
        report = str(row.get("REPORT") or "").strip()
        item_code = str(row.get("STD_ITEM_CODE") or "").strip()
        amount = to_float(row.get("AMOUNT"))
        if not report or not item_code or amount is None:
            continue
        mapped.setdefault(report, {})[item_code] = amount
    return mapped


def first_amount(items: dict[str, float], codes: tuple[str, ...] | str) -> float | None:
    for code in (codes if isinstance(codes, tuple) else (codes,)):
        if code in items:
            return items[code]
    return None


def fetch_us_financial_rows(
    snapshot: MarketSnapshot,
    *,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float = 0.0,
) -> list[dict[str, Any]]:
    report_rows: list[dict[str, Any]] = []
    secucode = ""
    for candidate in us_secucode_candidates(snapshot):
        report_rows = fetch_us_report_rows(candidate, session=session, timeout=timeout, request_delay=request_delay)
        if report_rows:
            secucode = candidate
            break
    if not report_rows or not secucode:
        return []

    reports = [str(row["REPORT"]) for row in report_rows]
    statement_columns = "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT,REPORT_DATE,STD_ITEM_CODE,ITEM_NAME,AMOUNT,CURRENCY"
    income_rows = fetch_us_statement_rows(
        secucode,
        reports=reports,
        report_name="RPT_USF10_FN_INCOME",
        columns=statement_columns,
        session=session,
        timeout=timeout,
        request_delay=request_delay,
    )
    cash_rows = fetch_us_statement_rows(
        secucode,
        reports=reports,
        report_name="RPT_USSK_FN_CASHFLOW",
        columns=statement_columns,
        session=session,
        timeout=timeout,
        request_delay=request_delay,
    )
    balance_rows = fetch_us_statement_rows(
        secucode,
        reports=reports,
        report_name="RPT_USF10_FN_BALANCE",
        columns=statement_columns,
        session=session,
        timeout=timeout,
        request_delay=request_delay,
    )
    indicator_rows = fetch_eastmoney_v1_rows(
        session,
        report_name="RPT_USF10_FN_GMAININDICATOR",
        columns=(
            "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,FINANCIAL_DATE,CURRENCY,"
            "DATE_TYPE_CODE,REPORT_TYPE,OPERATE_INCOME,PARENT_HOLDER_NETPROFIT,ROE_AVG,ROA,DEBT_ASSET_RATIO"
        ),
        filter_clause=f'(SECUCODE="{secucode}")(DATE_TYPE_CODE="001")',
        timeout=timeout,
        request_delay=request_delay,
        page_size=MIN_FINANCIAL_YEARS + 5,
        sort_columns="REPORT_DATE",
        sort_types="-1",
    )

    income_by_report = amount_rows_by_report_and_item(income_rows)
    cash_by_report = amount_rows_by_report_and_item(cash_rows)
    balance_by_report = amount_rows_by_report_and_item(balance_rows)
    by_year: dict[str, dict[str, Any]] = {}
    year_by_report: dict[str, str] = {}
    for report_row in report_rows:
        report = str(report_row.get("REPORT") or "")
        year = us_report_year(report_row)
        if not report or not year:
            continue
        year_by_report[report] = year
        by_year.setdefault(
            year,
            {
                "year": year,
                "currency": normalize_currency(report_row.get("CURRENCY"), snapshot.currency),
            },
        )

    for report in reports:
        year = year_by_report.get(report)
        if not year:
            continue
        income_items = income_by_report.get(report) or {}
        cash_items = cash_by_report.get(report) or {}
        balance_items = balance_by_report.get(report) or {}

        operating_cash_flow = first_amount(cash_items, US_CASHFLOW_ITEM_CODES["operating_cash_flow"])
        capex_amount = first_amount(cash_items, US_CASHFLOW_ITEM_CODES["capex"])
        capex = abs(capex_amount) if capex_amount is not None else None
        total_assets = first_amount(balance_items, US_BALANCE_ITEM_CODES["total_assets"])
        total_liabilities = first_amount(balance_items, US_BALANCE_ITEM_CODES["total_liabilities"])
        equity = first_amount(balance_items, US_BALANCE_ITEM_CODES["equity"])
        if equity is None and total_assets is not None and total_liabilities is not None:
            equity = total_assets - total_liabilities
        short_debt = first_amount(balance_items, US_BALANCE_ITEM_CODES["short_debt"])
        long_debt = first_amount(balance_items, US_BALANCE_ITEM_CODES["long_debt"])
        total_debt = sum_present_values(short_debt, long_debt)

        by_year[year].update(
            {
                "revenue": first_amount(income_items, US_INCOME_ITEM_CODES["revenue"]),
                "net_profit": first_amount(income_items, US_INCOME_ITEM_CODES["net_profit"]),
                "operating_cash_flow": operating_cash_flow,
                "capex": capex,
                "free_cash_flow": operating_cash_flow - capex
                if operating_cash_flow is not None and capex is not None
                else None,
                "cash_and_equivalents": first_amount(balance_items, US_BALANCE_ITEM_CODES["cash_and_equivalents"]),
                "current_financial_assets": first_amount(balance_items, US_BALANCE_ITEM_CODES["current_financial_assets"]),
                "noncurrent_financial_assets": first_amount(
                    balance_items, US_BALANCE_ITEM_CODES["noncurrent_financial_assets"]
                ),
                "short_debt": short_debt,
                "long_debt": long_debt,
                "total_debt": total_debt,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "goodwill": 0.0,
                "equity": equity,
                "payout_ratio": None,
            }
        )

    for row in indicator_rows:
        if not is_us_annual_report(row):
            continue
        year = us_report_year(row)
        if year not in by_year:
            continue
        by_year[year].update(
            {
                "roe": percent_or_none(row.get("ROE_AVG")),
                "debt_to_assets_percent": percent_or_none(row.get("DEBT_ASSET_RATIO")),
            }
        )
        if by_year[year].get("net_profit") is None:
            by_year[year]["net_profit"] = to_float(row.get("PARENT_HOLDER_NETPROFIT"))
        if by_year[year].get("revenue") is None:
            by_year[year]["revenue"] = to_float(row.get("OPERATE_INCOME"))

    return [by_year[year] for year in sorted(by_year.keys(), reverse=True)]


def fetch_financial_rows(
    snapshot: MarketSnapshot,
    *,
    session: requests.sessions.Session | None = None,
    request_delay: float = 0.0,
    timeout: float = 20,
) -> list[dict[str, Any]]:
    client = configure_session(session or requests.Session())
    if snapshot.market in {"SH", "SZ"}:
        return fetch_a_financial_rows(snapshot, session=client, request_delay=request_delay, timeout=timeout)
    if snapshot.market == "HK":
        return fetch_hk_financial_rows(snapshot, session=client, request_delay=request_delay, timeout=timeout)
    if snapshot.market == "US":
        return fetch_us_financial_rows(snapshot, session=client, request_delay=request_delay, timeout=timeout)
    return []
