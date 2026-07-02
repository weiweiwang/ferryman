#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fetch_risk_free_rate import fetch_risk_free_rate  # noqa: E402


EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_LIST_URLS = (
    EASTMONEY_LIST_URL,
    "https://push2.eastmoney.com/webguest/api/qt/clist/get?timil=1",
    "https://80.push2.eastmoney.com/api/qt/clist/get",
)
EASTMONEY_DATA_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
EASTMONEY_HK_DATA_URL = "https://emh5.eastmoney.com/api/GangGu/CaiWu"
EASTMONEY_QUOTE_UT = "fa5fd1943c7b386f172d6893dbfba10b"
EASTMONEY_WBP2U = "|0|0|0|web"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://quote.eastmoney.com/center/gridlist.html",
}

MARKET_CONFIGS: dict[str, dict[str, Any]] = {
    "SH": {"name": "Shanghai A-share", "fs": "m:1+t:2+f:!2,m:1+t:23+f:!2", "currency": "CNY", "secid_prefix": "1"},
    "SZ": {"name": "Shenzhen A-share", "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2", "currency": "CNY", "secid_prefix": "0"},
    "HK": {
        "name": "Hong Kong",
        "fs": "m:116+t:3,m:116+t:4,m:116+t:1,m:116+t:2",
        "currency": "HKD",
        "secid_prefix": "116",
    },
}

SORT_FIELDS = {"market_cap": "f20", "change_pct": "f3"}
EASTMONEY_LIST_FIELDS = (
    "f1,f2,f3,f5,f6,f8,f9,f10,f12,f13,f14,f20,f21,f23,f24,"
    "f25,f62,f100,f115,f152"
)
MIN_FINANCIAL_YEARS = 5
DEFAULT_MIN_MARKET_CAP = 5_000_000_000
INDUSTRY_REVIEW_KEYWORDS = (
    "银行",
    "保险",
    "证券",
    "地产",
    "房地产",
    "生物",
    "医药",
    "煤炭",
    "钢铁",
    "有色",
)
CURRENCY_ALIASES = {
    "人民币": "CNY",
    "人民幣": "CNY",
    "rmb": "CNY",
    "cny": "CNY",
    "港元": "HKD",
    "港币": "HKD",
    "港幣": "HKD",
    "hkd": "HKD",
    "美元": "USD",
    "usd": "USD",
    "日元": "JPY",
    "日圆": "JPY",
    "日圓": "JPY",
    "jpy": "JPY",
}


@dataclass
class MarketSnapshot:
    ticker: str
    code: str
    name: str
    market: str
    currency: str
    price: float | None
    pe: float | None
    pb: float | None
    market_cap: float | None
    float_market_cap: float | None
    industry: str | None
    source: str = "eastmoney"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def configure_session(session: requests.sessions.Session) -> requests.sessions.Session:
    session.headers.update(DEFAULT_HEADERS)
    if hasattr(session, "trust_env"):
        session.trust_env = False
    return session


def parse_json_or_jsonp(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty response")
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)

    open_paren = stripped.find("(")
    close_paren = stripped.rfind(")")
    if open_paren > 0 and close_paren > open_paren:
        return json.loads(stripped[open_paren + 1 : close_paren])
    raise ValueError("response is not JSON or JSONP")


def to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    multiplier = 1.0
    if isinstance(value, str):
        value = value.replace(",", "").replace("%", "").strip()
        if value in ("", "-", "--"):
            return None
        for unit, unit_multiplier in (
            ("万亿", 1_000_000_000_000),
            ("億", 100_000_000),
            ("亿", 100_000_000),
            ("萬", 10_000),
            ("万", 10_000),
        ):
            if unit in value:
                value = value.replace(unit, "")
                multiplier = unit_multiplier
                break
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number * multiplier


def to_scaled_float(value: Any, precision: Any) -> float | None:
    number = to_float(value)
    scale = to_float(precision)
    if number is None:
        return None
    if scale is None:
        return number
    if isinstance(value, int | float) and float(value).is_integer():
        return number / (10 ** int(scale))
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return number / (10 ** int(scale))
    return number


def eastmoney_price(value: Any, raw: dict[str, Any]) -> float | None:
    return to_scaled_float(value, raw.get("f1"))


def eastmoney_ratio(value: Any, raw: dict[str, Any]) -> float | None:
    return to_scaled_float(value, raw.get("f152") or 2)


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return statistics.fmean(clean)


def stdev(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if len(clean) < 2:
        return 0.0 if clean else None
    return statistics.stdev(clean)


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def is_industry_review_required(industry: str | None) -> bool:
    if not industry:
        return False
    return any(keyword in industry for keyword in INDUSTRY_REVIEW_KEYWORDS)


def ticker_for_market(code: str, market: str) -> str:
    if market == "HK":
        return f"{code.zfill(4)}.HK"
    if market in {"SH", "SZ"}:
        return f"{code}.{market}"
    return code


def normalize_currency(currency: Any, fallback: str) -> str:
    if not currency:
        return fallback
    normalized = str(currency).strip()
    return CURRENCY_ALIASES.get(normalized.lower(), CURRENCY_ALIASES.get(normalized, normalized.upper()))


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


def fetch_market_snapshots(
    *,
    markets: list[str],
    max_count: int,
    sort_by: str,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
) -> tuple[list[MarketSnapshot], list[dict[str, Any]]]:
    if max_count <= 0:
        return [], []
    client = configure_session(session or requests.Session())
    snapshots: list[MarketSnapshot] = []
    errors: list[dict[str, Any]] = []
    page_size = min(max_count, 100)
    max_pages = max(1, math.ceil(max_count / page_size))

    for market in markets:
        config = MARKET_CONFIGS[market]
        for page_number in range(1, max_pages + 1):
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
            request_errors: list[str] = []
            for url in EASTMONEY_LIST_URLS:
                try:
                    response = client.get(url, params=params, timeout=timeout)
                    response.raise_for_status()
                    payload = parse_json_or_jsonp(response.text)
                    rows = ((payload.get("data") or {}).get("diff") or [])
                    break
                except Exception as exc:
                    request_errors.append(f"{url}: {exc}")
            else:
                curl_errors: list[str] = []
                for url in EASTMONEY_LIST_URLS:
                    try:
                        payload = curl_get_json(url, params=params, timeout=timeout)
                        rows = ((payload.get("data") or {}).get("diff") or [])
                        break
                    except Exception as exc:
                        curl_errors.append(f"{url}: {exc}")
                else:
                    errors.append(
                        {
                            "market": market,
                            "phase": "market_snapshot",
                            "error": "; ".join(request_errors + curl_errors),
                        }
                    )
                    break

            for row in rows:
                try:
                    snapshots.append(parse_market_snapshot(row, market))
                except Exception as exc:
                    errors.append({"market": market, "phase": "market_snapshot_parse", "error": str(exc)})
            if len(rows) < page_size:
                break

    snapshots.sort(key=lambda item: item.market_cap or 0, reverse=True)
    return snapshots[:max_count], errors


def get_json(
    session: requests.sessions.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    if data is None:
        response = session.get(url, params=params, timeout=timeout)
    else:
        response = session.post(url, data=data, timeout=timeout)
    response.raise_for_status()
    try:
        return parse_json_or_jsonp(response.content.decode("utf-8"))
    except UnicodeDecodeError:
        return parse_json_or_jsonp(response.text)


def curl_get_json(url: str, *, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    query = urlencode(params)
    separator = "&" if "?" in url else "?"
    full_url = f"{url}{separator}{query}"
    command = [
        "curl",
        "-sS",
        "--compressed",
        "--max-time",
        str(max(1, int(timeout))),
        "-H",
        f"User-Agent: {DEFAULT_HEADERS['User-Agent']}",
        "-H",
        f"Accept: {DEFAULT_HEADERS['Accept']}",
        "-H",
        f"Accept-Language: {DEFAULT_HEADERS['Accept-Language']}",
        full_url,
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"curl exited with {completed.returncode}")
    return parse_json_or_jsonp(completed.stdout)


def fetch_a_company_type(snapshot: MarketSnapshot, session: requests.sessions.Session, timeout: float) -> str:
    params = {
        "filter": f'(SECUCODE="{snapshot.code}.{snapshot.market}")',
        "client": "APP",
        "source": "HSF10",
        "type": "RPT_F10_PUBLIC_COMPANYTPYE",
        "sty": "ALL",
    }
    payload = get_json(session, EASTMONEY_DATA_URL, params=params, timeout=timeout)
    return str(payload["result"]["data"][0]["COMPANY_TYPE"])


def fetch_a_statement_rows(
    snapshot: MarketSnapshot,
    *,
    statement_type: str,
    style: str,
    session: requests.sessions.Session,
    timeout: float,
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
    payload = get_json(session, EASTMONEY_DATA_URL, params=params, timeout=timeout)
    return (payload.get("result") or {}).get("data") or []


def fetch_a_financial_rows(
    snapshot: MarketSnapshot,
    *,
    session: requests.sessions.Session,
    timeout: float,
) -> list[dict[str, Any]]:
    try:
        company_type = fetch_a_company_type(snapshot, session, timeout)
    except Exception:
        company_type = "4"
    statement_suffix = {"1": "S", "2": "I", "3": "B", "4": "G"}.get(company_type, "G")

    income_rows = fetch_a_statement_rows(
        snapshot,
        statement_type="RPT_F10_FINANCE_MAINFINADATA",
        style="APP_F10_MAINFINADATA",
        session=session,
        timeout=timeout,
    )
    cash_rows = fetch_a_statement_rows(
        snapshot,
        statement_type=f"RPT_F10_FINANCE_{statement_suffix}CASHFLOW",
        style=f"APP_F10_{statement_suffix}CASHFLOW",
        session=session,
        timeout=timeout,
    )
    balance_rows = fetch_a_statement_rows(
        snapshot,
        statement_type=f"RPT_F10_FINANCE_{statement_suffix}BALANCE",
        style=f"F10_FINANCE_{statement_suffix}BALANCE",
        session=session,
        timeout=timeout,
    )

    by_year: dict[str, dict[str, Any]] = {}
    for row in income_rows:
        year = str(row.get("REPORT_DATE") or "")[:4]
        if not year:
            continue
        by_year.setdefault(year, {"year": year, "currency": "CNY"})
        by_year[year].update(
            {
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
        goodwill = to_float(row.get("GOODWILL")) or 0.0
        equity = total_assets - total_liabilities if total_assets is not None and total_liabilities is not None else None
        by_year.setdefault(year, {"year": year, "currency": "CNY"})
        by_year[year].update(
            {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "goodwill": goodwill,
                "equity": equity,
            }
        )
    return [by_year[year] for year in sorted(by_year.keys(), reverse=True)]


def fetch_hk_company_type(snapshot: MarketSnapshot, session: requests.sessions.Session, timeout: float) -> str:
    payload = get_json(
        session,
        f"{EASTMONEY_HK_DATA_URL}/GetCompanyType",
        data={"fc": snapshot.code.zfill(5), "color": "w"},
        timeout=timeout,
    )
    return str(payload["Result"]["CompanyType"])


def fetch_hk_financial_rows(
    snapshot: MarketSnapshot,
    *,
    session: requests.sessions.Session,
    timeout: float,
) -> list[dict[str, Any]]:
    corp_type = fetch_hk_company_type(snapshot, session, timeout)
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
    main_payload = get_json(session, f"{EASTMONEY_HK_DATA_URL}/GetZhuYaoZhiBiaoList", data=post_data, timeout=timeout)
    cash_payload = get_json(session, f"{EASTMONEY_HK_DATA_URL}/GetXianJinLiuLiangList", data=post_data, timeout=timeout)
    balance_payload = get_json(session, f"{EASTMONEY_HK_DATA_URL}/GetZiChanFuZhaiList", data=post_data, timeout=timeout)

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
        goodwill = to_float(row.get("BS004001005")) or 0.0
        equity = total_assets - total_liabilities if total_assets is not None and total_liabilities is not None else None
        by_year.setdefault(year, {"year": year, "currency": normalize_currency(row.get("CURRENCY"), snapshot.currency)})
        by_year[year].update(
            {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "goodwill": goodwill,
                "equity": equity,
            }
        )
    return [by_year[year] for year in sorted(by_year.keys(), reverse=True)]


def fetch_financial_rows(
    snapshot: MarketSnapshot,
    *,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
) -> list[dict[str, Any]]:
    client = configure_session(session or requests.Session())
    if snapshot.market in {"SH", "SZ"}:
        return fetch_a_financial_rows(snapshot, session=client, timeout=timeout)
    if snapshot.market == "HK":
        return fetch_hk_financial_rows(snapshot, session=client, timeout=timeout)
    return []


def complete_financial_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = ("net_profit", "operating_cash_flow", "free_cash_flow")
    return [row for row in rows if all(row.get(field) is not None for field in required)]


def financial_currency(rows: list[dict[str, Any]], fallback: str) -> str:
    for row in rows:
        currency = row.get("currency")
        if currency:
            return normalize_currency(currency, fallback)
    return fallback


def compute_metrics(
    snapshot: MarketSnapshot,
    financial_rows: list[dict[str, Any]],
    risk_free: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    data_gaps: list[str] = []
    rows = financial_rows[:MIN_FINANCIAL_YEARS]
    complete_rows = complete_financial_rows(rows)
    if len(complete_rows) < MIN_FINANCIAL_YEARS:
        data_gaps.append("missing_5y_financial_rows")

    net_profits = [to_float(row.get("net_profit")) for row in complete_rows]
    operating_cash_flows = [to_float(row.get("operating_cash_flow")) for row in complete_rows]
    free_cash_flows = [to_float(row.get("free_cash_flow")) for row in complete_rows]
    roe_values = [to_float(row.get("roe")) for row in rows]
    roic_values = [to_float(row.get("roic")) for row in rows]
    latest = rows[0] if rows else {}

    avg_net_profit = mean(net_profits)
    avg_ocf = mean(operating_cash_flows)
    avg_fcf = mean(free_cash_flows)
    roe_mean = mean(roe_values)
    roe_std = stdev(roe_values)
    roic_mean = mean(roic_values)
    equity = to_float(latest.get("equity"))
    goodwill = to_float(latest.get("goodwill"))
    total_assets = to_float(latest.get("total_assets"))
    total_liabilities = to_float(latest.get("total_liabilities"))
    debt_to_assets = safe_ratio(total_liabilities, total_assets)
    goodwill_to_equity = safe_ratio(goodwill, equity)
    payout_ratio = to_float(latest.get("payout_ratio"))
    if payout_ratio is not None and payout_ratio > 1:
        payout_ratio = payout_ratio / 100
    if payout_ratio is None:
        payout_ratio = 0.0

    market_cap_to_avg_profit = safe_ratio(snapshot.market_cap, avg_net_profit)
    market_cap_to_avg_fcf = safe_ratio(snapshot.market_cap, avg_fcf)
    risk_free_multiple_cap = None
    if risk_free and risk_free.get("ok"):
        risk_free_multiple_cap = (risk_free.get("multipleCaps") or {}).get("conservativeN2")
    else:
        data_gaps.append("risk_free_rate_unavailable")

    expected_return = None
    if snapshot.pe and snapshot.pe > 0 and roe_mean is not None:
        expected_return = 100 * (payout_ratio / snapshot.pe + (roe_mean / 100) * (1 - payout_ratio))

    metrics = {
        "pe": round_or_none(snapshot.pe, 4),
        "pb": round_or_none(snapshot.pb, 4),
        "roe_mean": round_or_none(roe_mean, 4),
        "roe_std": round_or_none(roe_std, 4),
        "roe_stability": round_or_none(safe_ratio(roe_mean, roe_std), 4),
        "roic_mean": round_or_none(roic_mean, 4),
        "avg_net_profit_5y": round_or_none(avg_net_profit, 2),
        "avg_ocf_5y": round_or_none(avg_ocf, 2),
        "avg_fcf_5y": round_or_none(avg_fcf, 2),
        "ocf_to_profit": round_or_none(safe_ratio(avg_ocf, avg_net_profit), 4),
        "fcf_to_profit": round_or_none(safe_ratio(avg_fcf, avg_net_profit), 4),
        "market_cap_to_avg_profit": round_or_none(market_cap_to_avg_profit, 4),
        "market_cap_to_avg_fcf": round_or_none(market_cap_to_avg_fcf, 4),
        "expected_return": round_or_none(expected_return, 4),
        "debt_to_assets": round_or_none(debt_to_assets, 4),
        "goodwill_to_equity": round_or_none(goodwill_to_equity, 4),
        "risk_free_multiple_cap": round_or_none(risk_free_multiple_cap, 4),
        "complete_financial_years": len(complete_rows),
        "negative_fcf_years": sum(1 for value in free_cash_flows if value is not None and value < 0),
    }
    return metrics, data_gaps


def quick_reject_reasons(snapshot: MarketSnapshot, min_market_cap: float) -> list[str]:
    reasons: list[str] = []
    if snapshot.price is None or snapshot.price <= 0:
        reasons.append("no_valid_price")
    if snapshot.market in {"SH", "SZ"} and (snapshot.name.startswith("ST") or snapshot.name.startswith("*ST")):
        reasons.append("st_or_special_treatment")
    if snapshot.market_cap is None or snapshot.market_cap < min_market_cap:
        reasons.append("below_market_cap_floor")
    if snapshot.pe is None or snapshot.pe <= 0:
        reasons.append("non_positive_pe")
    return reasons


def quality_flags(metrics: dict[str, Any], negative_fcf_years: int) -> list[str]:
    flags: list[str] = []
    if (metrics.get("roe_mean") or 0) >= 12 and (metrics.get("roe_stability") or 0) >= 2:
        flags.append("stable_roe")
    if (metrics.get("roic_mean") or 0) >= 10:
        flags.append("high_roic")
    if (metrics.get("ocf_to_profit") or 0) >= 0.9 and (metrics.get("fcf_to_profit") or 0) >= 0.7:
        flags.append("strong_cash_conversion")
    if (metrics.get("avg_fcf_5y") or 0) > 0 and negative_fcf_years <= 1:
        flags.append("positive_fcf_5y")
    if metrics.get("debt_to_assets") is not None and metrics["debt_to_assets"] <= 0.5:
        flags.append("low_debt")
    if metrics.get("goodwill_to_equity") is not None and metrics["goodwill_to_equity"] <= 0.2:
        flags.append("low_goodwill")
    return flags


def valuation_flags(metrics: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    cap = metrics.get("risk_free_multiple_cap")
    if cap is not None:
        if metrics.get("pe") is not None and 0 < metrics["pe"] <= cap:
            flags.append("cheap_pe")
        if metrics.get("market_cap_to_avg_profit") is not None and metrics["market_cap_to_avg_profit"] <= cap:
            flags.append("cheap_profit")
        if metrics.get("market_cap_to_avg_fcf") is not None and metrics["market_cap_to_avg_fcf"] <= cap:
            flags.append("cheap_fcf")
    if metrics.get("pb") is not None and 0 < metrics["pb"] <= 3:
        flags.append("reasonable_pb")
    return flags


def score_flags(flags: list[str], weights: dict[str, int]) -> int:
    return min(100, sum(weights.get(flag, 0) for flag in flags))


def classify_candidate(
    snapshot: MarketSnapshot,
    metrics: dict[str, Any],
    data_gaps: list[str],
    initial_reject_reasons: list[str],
) -> tuple[str, list[str], list[str], list[str], int, int, int]:
    reject_reasons = list(initial_reject_reasons)
    if reject_reasons:
        return "REJECTED", [], [], sorted(set(reject_reasons)), 0, 0, 0

    if is_industry_review_required(snapshot.industry):
        data_gaps.append("industry_review_required")
        return "INDUSTRY_REVIEW_REQUIRED", [], [], [], 0, 0, 0

    if metrics.get("avg_net_profit_5y") is not None and metrics["avg_net_profit_5y"] <= 0:
        reject_reasons.append("non_positive_profit")
    if metrics.get("avg_fcf_5y") is not None and metrics["avg_fcf_5y"] <= 0:
        reject_reasons.append("non_positive_fcf")
    if metrics.get("ocf_to_profit") is not None and metrics["ocf_to_profit"] < 0.6:
        reject_reasons.append("weak_ocf_conversion")
    if metrics.get("fcf_to_profit") is not None and metrics["fcf_to_profit"] < 0.4:
        reject_reasons.append("weak_fcf_conversion")
    if metrics.get("debt_to_assets") is not None and metrics["debt_to_assets"] > 0.7:
        reject_reasons.append("high_debt")
    if metrics.get("goodwill_to_equity") is not None and metrics["goodwill_to_equity"] > 0.5:
        reject_reasons.append("high_goodwill")

    if reject_reasons:
        return "REJECTED", [], [], sorted(set(reject_reasons)), 0, 0, 0

    complete_years = metrics.get("complete_financial_years") or 0
    if complete_years < MIN_FINANCIAL_YEARS:
        return "INSUFFICIENT_DATA", [], [], [], 0, 0, 0

    negative_fcf_years = metrics.get("negative_fcf_years") or 0
    q_flags = quality_flags(metrics, negative_fcf_years)
    v_flags = valuation_flags(metrics)
    q_score = score_flags(
        q_flags,
        {
            "stable_roe": 25,
            "high_roic": 15,
            "strong_cash_conversion": 25,
            "positive_fcf_5y": 15,
            "low_debt": 10,
            "low_goodwill": 10,
        },
    )
    v_score = score_flags(
        v_flags,
        {"cheap_pe": 25, "cheap_profit": 30, "cheap_fcf": 35, "reasonable_pb": 10},
    )
    screen_score = round(q_score * 0.6 + v_score * 0.4)
    if len(q_flags) >= 3 and len(set(v_flags) & {"cheap_pe", "cheap_profit", "cheap_fcf"}) >= 1:
        return "CANDIDATE", q_flags, v_flags, [], q_score, v_score, screen_score
    return "REJECTED", q_flags, v_flags, ["not_enough_quality_or_valuation_signals"], q_score, v_score, screen_score


def build_result_item(
    snapshot: MarketSnapshot,
    *,
    financial_rows: list[dict[str, Any]],
    risk_free: dict[str, Any] | None,
    min_market_cap: float,
) -> dict[str, Any]:
    reject_reasons = quick_reject_reasons(snapshot, min_market_cap)
    fin_currency = financial_currency(financial_rows, snapshot.currency)
    metrics, data_gaps = compute_metrics(snapshot, financial_rows, risk_free)
    if fin_currency != snapshot.currency:
        metrics["market_cap_to_avg_profit"] = None
        metrics["market_cap_to_avg_fcf"] = None
        data_gaps.append("fx_conversion_required")
    status, q_flags, v_flags, final_reject_reasons, q_score, v_score, screen_score = classify_candidate(
        snapshot,
        metrics,
        data_gaps,
        reject_reasons,
    )

    return {
        "ticker": snapshot.ticker,
        "name": snapshot.name,
        "market": snapshot.market,
        "currency": snapshot.currency,
        "financial_currency": fin_currency,
        "price": snapshot.price,
        "market_cap": snapshot.market_cap,
        "industry": snapshot.industry,
        "status": status,
        "quality_score": q_score,
        "valuation_score": v_score,
        "screen_score": screen_score,
        "metrics": metrics,
        "quality_flags": q_flags,
        "valuation_flags": v_flags,
        "reject_reasons": final_reject_reasons,
        "data_gaps": sorted(set(data_gaps)),
        "source": snapshot.source,
    }


def sort_results(results: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    if sort_by == "market_cap":
        return sorted(results, key=lambda item: item.get("market_cap") or 0, reverse=True)
    return sorted(results, key=lambda item: item.get("screen_score") or 0, reverse=True)


def failed_market_snapshots(markets: list[str], errors: list[dict[str, Any]]) -> set[str]:
    requested = set(markets)
    return {
        str(error.get("market"))
        for error in errors
        if error.get("phase") == "market_snapshot" and error.get("market") in requested
    }


def screen_stocks(
    *,
    markets: list[str],
    max_count: int,
    enrich_limit: int,
    sort_by: str,
    min_market_cap: float,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
) -> dict[str, Any]:
    normalized_markets = [market.upper() for market in markets]
    unsupported = [market for market in normalized_markets if market not in MARKET_CONFIGS]
    supported_markets = [market for market in normalized_markets if market in MARKET_CONFIGS]
    client = configure_session(session or requests.Session())
    snapshots, errors = fetch_market_snapshots(
        markets=supported_markets,
        max_count=max_count,
        sort_by="market_cap",
        session=client,
        timeout=timeout,
    )
    for market in unsupported:
        errors.append({"market": market, "phase": "market_snapshot", "error": "unsupported market"})

    rates: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    enriched = 0
    for snapshot in snapshots:
        initial_rejects = quick_reject_reasons(snapshot, min_market_cap)
        should_enrich = not initial_rejects and enriched < enrich_limit
        financial_rows: list[dict[str, Any]] = []
        if should_enrich:
            try:
                financial_rows = fetch_financial_rows(snapshot, session=client, timeout=timeout)
                enriched += 1
            except Exception as exc:
                results.append(
                    {
                        "ticker": snapshot.ticker,
                        "name": snapshot.name,
                        "market": snapshot.market,
                        "currency": snapshot.currency,
                        "financial_currency": snapshot.currency,
                        "price": snapshot.price,
                        "market_cap": snapshot.market_cap,
                        "industry": snapshot.industry,
                        "status": "INSUFFICIENT_DATA",
                        "quality_score": 0,
                        "valuation_score": 0,
                        "screen_score": 0,
                        "metrics": {"pe": snapshot.pe, "pb": snapshot.pb, "complete_financial_years": 0},
                        "quality_flags": [],
                        "valuation_flags": [],
                        "reject_reasons": [],
                        "data_gaps": ["financial_fetch_failed", str(exc)],
                        "source": snapshot.source,
                    }
                )
                continue
        elif not initial_rejects:
            results.append(
                {
                    "ticker": snapshot.ticker,
                    "name": snapshot.name,
                    "market": snapshot.market,
                    "currency": snapshot.currency,
                    "financial_currency": snapshot.currency,
                    "price": snapshot.price,
                    "market_cap": snapshot.market_cap,
                    "industry": snapshot.industry,
                    "status": "INSUFFICIENT_DATA",
                    "quality_score": 0,
                    "valuation_score": 0,
                    "screen_score": 0,
                    "metrics": {"pe": snapshot.pe, "pb": snapshot.pb, "complete_financial_years": 0},
                    "quality_flags": [],
                    "valuation_flags": [],
                    "reject_reasons": [],
                    "data_gaps": ["not_enriched"],
                    "source": snapshot.source,
                }
            )
            continue

        fin_currency = financial_currency(financial_rows, snapshot.currency)
        if fin_currency not in rates:
            rates[fin_currency] = fetch_risk_free_rate(fin_currency, timeout=timeout)
        results.append(
            build_result_item(
                snapshot,
                financial_rows=financial_rows,
                risk_free=rates.get(fin_currency),
                min_market_cap=min_market_cap,
            )
        )

    results = sort_results(results, sort_by)
    failed_markets = failed_market_snapshots(supported_markets, errors)
    no_supported_markets = bool(normalized_markets) and not supported_markets
    all_supported_markets_failed = bool(supported_markets) and not snapshots and set(supported_markets) <= failed_markets
    ok = not (no_supported_markets or all_supported_markets_failed)
    payload = {
        "ok": ok,
        "fetched_at": now_iso(),
        "markets": supported_markets,
        "unsupported_markets": unsupported,
        "source": "eastmoney",
        "data_limits": {
            "secondary_source_only": True,
            "max_count": max_count,
            "enrich_limit": enrich_limit,
            "min_market_cap": min_market_cap,
            "errors": errors,
        },
        "risk_free_rates": rates,
        "summary": {
            "total": len(results),
            "candidate": sum(1 for item in results if item["status"] == "CANDIDATE"),
            "rejected": sum(1 for item in results if item["status"] == "REJECTED"),
            "insufficient_data": sum(1 for item in results if item["status"] == "INSUFFICIENT_DATA"),
            "industry_review_required": sum(1 for item in results if item["status"] == "INDUSTRY_REVIEW_REQUIRED"),
        },
        "results": results,
    }
    if no_supported_markets:
        payload["phase"] = "market_snapshot"
        payload["error"] = "No supported markets requested."
    elif all_supported_markets_failed:
        payload["phase"] = "market_snapshot"
        payload["error"] = "No market snapshots fetched from Eastmoney for requested markets."
    return payload


def write_json(path: str, payload: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def write_xlsx(path: str, payload: dict[str, Any]) -> None:
    from openpyxl import Workbook

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    columns = [
        "ticker",
        "name",
        "market",
        "status",
        "price",
        "market_cap",
        "industry",
        "quality_score",
        "valuation_score",
        "screen_score",
        "quality_flags",
        "valuation_flags",
        "reject_reasons",
        "data_gaps",
    ]
    for status in ("CANDIDATE", "REJECTED", "INSUFFICIENT_DATA", "INDUSTRY_REVIEW_REQUIRED"):
        sheet = workbook.create_sheet(status.title().replace("_", ""))
        sheet.append(columns)
        for item in payload["results"]:
            if item["status"] != status:
                continue
            row = []
            for column in columns:
                value = item.get(column)
                if isinstance(value, list):
                    value = ", ".join(str(part) for part in value)
                row.append(value)
            sheet.append(row)

    raw_sheet = workbook.create_sheet("RawSnapshots")
    raw_sheet.append(["ticker", "metrics_json"])
    for item in payload["results"]:
        raw_sheet.append([item["ticker"], json.dumps(json_safe(item.get("metrics", {})), ensure_ascii=False)])
    workbook.save(output_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen stock candidates for quality value research.")
    parser.add_argument("--markets", nargs="+", default=["SH", "SZ", "HK"], help="Markets to screen. Default: SH SZ HK.")
    parser.add_argument("--max-count", type=int, default=300, help="Maximum market snapshots to keep after sorting.")
    parser.add_argument("--enrich-limit", type=int, default=100, help="Maximum non-rejected snapshots to enrich.")
    parser.add_argument("--sort-by", choices=["screen_score", "market_cap"], default="screen_score")
    parser.add_argument("--min-market-cap", type=float, default=DEFAULT_MIN_MARKET_CAP)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--json-out")
    parser.add_argument("--xlsx-out")
    args = parser.parse_args(argv)

    payload = screen_stocks(
        markets=args.markets,
        max_count=args.max_count,
        enrich_limit=args.enrich_limit,
        sort_by=args.sort_by,
        min_market_cap=args.min_market_cap,
        timeout=args.timeout,
    )
    if args.json_out:
        write_json(args.json_out, payload)
    if args.xlsx_out:
        write_xlsx(args.xlsx_out, payload)

    stdout_payload = {key: value for key, value in payload.items() if key != "results"}
    stdout_payload["results"] = payload["results"][: min(50, len(payload["results"]))]
    print(json.dumps(json_safe(stdout_payload), ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
