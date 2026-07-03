#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fetch_risk_free_rate import fetch_risk_free_rate  # noqa: E402


LOGGER = logging.getLogger("stock_screen")
EASTMONEY_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_DATA_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
EASTMONEY_HK_DATA_URL = "https://emh5.eastmoney.com/api/GangGu/CaiWu"
EASTMONEY_XUANGU_LIST_URL = "https://data.eastmoney.com/dataapi/xuangu/list"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
HKEX_SECURITIES_LIST_URL = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
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
A_SHARE_SELECTOR_FIELDS = (
    "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NEW_PRICE,CHANGE_RATE,"
    "PE9,PBNEWMRQ,TOTAL_MARKET_CAP,INDUSTRY"
)
MIN_FINANCIAL_YEARS = 5
DEFAULT_MIN_MARKET_CAP = 5_000_000_000
DEFAULT_REQUEST_DELAY_SECONDS = 0.2
DEFAULT_PROGRESS_INTERVAL = 50
DEFAULT_PAGE_SIZE = 100
DEFAULT_REPORTS_ROOT = Path("reports") / "stock-screen"
CACHE_DIR_NAME = "cache"
FINANCIAL_CACHE_DIR_NAME = "financials"
UNIVERSE_FILENAME = "universe.json"
ENRICH_FILENAME = "enrich.jsonl"
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
    market_cap_rank: int | None = None
    market_cap_percentile: float | None = None
    selected_for_financial_analysis: bool = False
    source: str = "eastmoney"


@dataclass
class ListingEntry:
    code: str
    secid: str
    market: str
    official_name: str | None = None
    listing_date: str | None = None
    board: str | None = None
    trading_currency: str | None = None
    listing_source: str | None = None


def snapshot_to_dict(snapshot: MarketSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def snapshot_from_dict(payload: dict[str, Any]) -> MarketSnapshot:
    return MarketSnapshot(
        ticker=str(payload["ticker"]),
        code=str(payload["code"]),
        name=str(payload["name"]),
        market=str(payload["market"]),
        currency=str(payload["currency"]),
        price=to_float(payload.get("price")),
        pe=to_float(payload.get("pe")),
        pb=to_float(payload.get("pb")),
        market_cap=to_float(payload.get("market_cap")),
        float_market_cap=to_float(payload.get("float_market_cap")),
        industry=payload.get("industry"),
        market_cap_rank=int(payload["market_cap_rank"]) if payload.get("market_cap_rank") is not None else None,
        market_cap_percentile=to_float(payload.get("market_cap_percentile")),
        selected_for_financial_analysis=bool(payload.get("selected_for_financial_analysis")),
        source=str(payload.get("source") or "eastmoney"),
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_run_date() -> str:
    return date.today().isoformat()


def default_run_dir(run_date: str) -> Path:
    return DEFAULT_REPORTS_ROOT / run_date


def default_cache_dir() -> Path:
    return DEFAULT_REPORTS_ROOT / CACHE_DIR_NAME / FINANCIAL_CACHE_DIR_NAME


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


def write_json_path(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(json_safe(payload), ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return rows


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


def sleep_if_needed(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def configure_progress_logger() -> logging.Logger:
    for handler in list(LOGGER.handlers):
        LOGGER.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    return LOGGER


def checkpoint_status_counts(rows: dict[str, dict[str, Any]]) -> tuple[int, int]:
    ok = sum(1 for row in rows.values() if row.get("enrich_status") == "ok")
    failed = sum(1 for row in rows.values() if row.get("enrich_status") == "failed")
    return ok, failed


def should_log_progress(processed: int, total: int, interval: int) -> bool:
    return interval > 0 and (processed % interval == 0 or processed == total)


def log_screen_progress(
    logger: logging.Logger | None,
    *,
    event: str,
    processed: int,
    total: int,
    ticker: str,
    checkpoint_rows: dict[str, dict[str, Any]],
    financial_fetch_attempts: int,
    interval: int,
    force: bool = False,
) -> None:
    if logger is None:
        return
    if not force and not should_log_progress(processed, total, interval):
        return
    ok, failed = checkpoint_status_counts(checkpoint_rows)
    pending = max(total - len(checkpoint_rows), 0)
    logger.info(
        "[stock-screen] enrich %s/%s ok=%s failed=%s pending=%s attempts=%s ticker=%s event=%s",
        processed,
        total,
        ok,
        failed,
        pending,
        financial_fetch_attempts,
        ticker,
        event,
    )


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


def normalize_currency(currency: Any, default_currency: str) -> str:
    if not currency:
        return default_currency
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


def get_with_retry(
    session: requests.sessions.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
    attempts: int = 3,
    request_delay: float = 0.0,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                sleep_if_needed(max(request_delay, 0.5 * attempt))
        finally:
            sleep_if_needed(request_delay)
    assert last_error is not None
    raise last_error


def fetch_hkex_listings(
    session: requests.sessions.Session,
    *,
    timeout: float,
    request_delay: float,
) -> list[ListingEntry]:
    from openpyxl import load_workbook

    response = get_with_retry(
        session,
        HKEX_SECURITIES_LIST_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(timeout, 60),
        request_delay=request_delay,
    )
    workbook = load_workbook(BytesIO(response.content), read_only=True, data_only=True)
    sheet = workbook.active
    sheet.reset_dimensions()
    rows = sheet.iter_rows(values_only=True)
    for _ in range(2):
        next(rows)
    headers = [str(value or "").strip() for value in next(rows)]
    index = {header: pos for pos, header in enumerate(headers)}
    listings: list[ListingEntry] = []
    for row in rows:
        code = str(row[index["Stock Code"]] or "").strip()
        category = str(row[index["Category"]] or "").strip()
        sub_category = str(row[index["Sub-Category"]] or "").strip()
        if not code or category != "Equity" or "Equity Securities" not in sub_category:
            continue
        code = code.zfill(5)
        listings.append(
            ListingEntry(
                code=code,
                secid=f"116.{code}",
                market="HK",
                official_name=row[index["Name of Securities"]],
                board=sub_category,
                trading_currency=row[index["Trading Currency"]],
                listing_source="HKEX",
            )
        )
    return listings


def chunked(items: list[ListingEntry], size: int) -> list[list[ListingEntry]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def fetch_a_share_selector_market_snapshots(
    *,
    markets: list[str],
    min_market_cap: float,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> tuple[list[MarketSnapshot], list[dict[str, Any]]]:
    requested = {market for market in markets if market in {"SH", "SZ"}}
    if not requested:
        return [], []

    snapshots: list[MarketSnapshot] = []
    errors: list[dict[str, Any]] = []
    page_number = 1
    page_size = DEFAULT_PAGE_SIZE
    while True:
        params = {
            "type": "RPTA_PCNEW_STOCKSELECT",
            "sty": A_SHARE_SELECTOR_FIELDS,
            "filter": f"(TOTAL_MARKET_CAP>={int(min_market_cap)})",
            "source": "SELECT_SECURITIES",
            "client": "WEB",
            "hyversion": "new",
            "st": "TOTAL_MARKET_CAP",
            "sr": -1,
            "p": page_number,
            "ps": page_size,
        }
        try:
            payload = get_json(session, EASTMONEY_XUANGU_LIST_URL, params=params, request_delay=request_delay, timeout=timeout)
        except Exception as exc:
            errors.append({"market": ",".join(sorted(requested)), "phase": "market_snapshot_xuangu", "error": str(exc)})
            break

        result = payload.get("result") or {}
        rows = result.get("data") or []
        for row in rows:
            try:
                snapshot = parse_a_share_selector_snapshot(row)
            except Exception as exc:
                errors.append({"market": "A", "phase": "market_snapshot_xuangu_parse", "error": str(exc)})
                continue
            if snapshot is None or snapshot.market not in requested:
                continue
            if snapshot.market_cap is None or snapshot.market_cap < min_market_cap:
                continue
            snapshots.append(snapshot)

        if not rows or result.get("nextpage") is False:
            break
        count = to_float(result.get("count"))
        if count is not None and page_number >= math.ceil(count / page_size):
            break
        page_number += 1

    snapshots.sort(key=lambda item: item.market_cap or 0, reverse=True)
    return snapshots, errors


def fetch_hk_tencent_market_snapshots(
    listings: list[ListingEntry],
    *,
    min_market_cap: float,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> tuple[list[MarketSnapshot], list[dict[str, Any]]]:
    listings_by_symbol = {f"hk{listing.code.lower()}": listing for listing in listings if listing.market == "HK"}
    snapshots: list[MarketSnapshot] = []
    errors: list[dict[str, Any]] = []
    symbols = list(listings_by_symbol)
    headers = {**DEFAULT_HEADERS, "Referer": "https://gu.qq.com/", "Accept": "*/*"}

    for index in range(0, len(symbols), DEFAULT_PAGE_SIZE):
        batch = symbols[index : index + DEFAULT_PAGE_SIZE]
        if not batch:
            continue
        try:
            response = session.get(f"{TENCENT_QUOTE_URL}{','.join(batch)}", headers=headers, timeout=timeout)
            response.raise_for_status()
            records = parse_tencent_quote_records(response.text)
        except Exception as exc:
            errors.append({"market": "HK", "phase": "market_snapshot_tencent_quote", "error": str(exc)})
            sleep_if_needed(request_delay)
            continue

        for symbol, fields in records.items():
            try:
                snapshot = parse_tencent_hk_snapshot(fields, listings_by_symbol.get(symbol))
            except Exception as exc:
                errors.append({"market": "HK", "phase": "market_snapshot_tencent_parse", "error": str(exc)})
                continue
            if snapshot is None:
                continue
            if snapshot.market_cap is None or snapshot.market_cap < min_market_cap:
                continue
            snapshots.append(snapshot)
        sleep_if_needed(request_delay)

    snapshots.sort(key=lambda item: item.market_cap or 0, reverse=True)
    return snapshots, errors


def fetch_listing_universe_market_snapshots(
    *,
    markets: list[str],
    min_market_cap: float,
    session: requests.sessions.Session,
    timeout: float,
    request_delay: float,
) -> tuple[list[MarketSnapshot], list[dict[str, Any]]]:
    snapshots: list[MarketSnapshot] = []
    errors: list[dict[str, Any]] = []
    a_markets = [market for market in markets if market in {"SH", "SZ"}]
    if a_markets:
        a_snapshots, a_errors = fetch_a_share_selector_market_snapshots(
            markets=a_markets,
            min_market_cap=min_market_cap,
            session=session,
            timeout=timeout,
            request_delay=request_delay,
        )
        snapshots.extend(a_snapshots)
        errors.extend(a_errors)

    if "HK" in markets:
        try:
            hk_listings = fetch_hkex_listings(session, timeout=timeout, request_delay=request_delay)
            hk_snapshots, hk_errors = fetch_hk_tencent_market_snapshots(
                hk_listings,
                min_market_cap=min_market_cap,
                session=session,
                timeout=timeout,
                request_delay=request_delay,
            )
            snapshots.extend(hk_snapshots)
            errors.extend(hk_errors)
        except Exception as exc:
            errors.append({"market": "HK", "phase": "listing_universe", "error": str(exc)})

    snapshots.sort(key=lambda item: item.market_cap or 0, reverse=True)
    return snapshots, errors


def limit_snapshots_per_market(
    snapshots: list[MarketSnapshot],
    *,
    markets: list[str],
    max_count: int,
) -> list[MarketSnapshot]:
    if max_count <= 0:
        return snapshots
    limited: list[MarketSnapshot] = []
    for market in markets:
        market_snapshots = [snapshot for snapshot in snapshots if snapshot.market == market]
        limited.extend(market_snapshots[:max_count])
    return limited



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
    if min_market_cap is not None and sort_by == "market_cap":
        snapshots, errors = fetch_listing_universe_market_snapshots(
            markets=markets,
            min_market_cap=min_market_cap,
            session=client,
            timeout=timeout,
            request_delay=request_delay,
        )
        return limit_snapshots_per_market(snapshots, markets=markets, max_count=max_count), errors

    snapshots: list[MarketSnapshot] = []
    errors: list[dict[str, Any]] = []
    page_size = DEFAULT_PAGE_SIZE if max_count <= 0 else min(max_count, DEFAULT_PAGE_SIZE)
    max_pages = None if max_count <= 0 else max(1, math.ceil(max_count / page_size))

    for market in markets:
        config = MARKET_CONFIGS[market]
        market_snapshots: list[MarketSnapshot] = []
        page_number = 1
        while max_pages is None or page_number <= max_pages:
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
            try:
                response = client.get(EASTMONEY_LIST_URL, params=params, timeout=timeout)
                response.raise_for_status()
                payload = parse_json_or_jsonp(response.text)
                rows = ((payload.get("data") or {}).get("diff") or [])
            except Exception as exc:
                errors.append({"market": market, "phase": "market_snapshot", "error": f"{EASTMONEY_LIST_URL}: {exc}"})
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
    try:
        company_type = fetch_a_company_type(snapshot, session, timeout, request_delay)
    except Exception:
        company_type = "4"
    statement_suffix = {"1": "S", "2": "I", "3": "B", "4": "G"}.get(company_type, "G")

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
    request_delay: float = 0.0,
    timeout: float = 20,
) -> list[dict[str, Any]]:
    client = configure_session(session or requests.Session())
    if snapshot.market in {"SH", "SZ"}:
        return fetch_a_financial_rows(snapshot, session=client, request_delay=request_delay, timeout=timeout)
    if snapshot.market == "HK":
        return fetch_hk_financial_rows(snapshot, session=client, request_delay=request_delay, timeout=timeout)
    return []


def complete_financial_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = ("net_profit", "operating_cash_flow", "free_cash_flow")
    return [row for row in rows if all(row.get(field) is not None for field in required)]


def financial_currency(rows: list[dict[str, Any]], default_currency: str) -> str:
    for row in rows:
        currency = row.get("currency")
        if currency:
            return normalize_currency(currency, default_currency)
    return default_currency


def financial_cache_path(cache_dir: Path, snapshot: MarketSnapshot) -> Path:
    return cache_dir / snapshot.market / f"{snapshot.code}.json"


def load_financial_rows_from_cache(cache_dir: Path | None, snapshot: MarketSnapshot) -> list[dict[str, Any]] | None:
    if cache_dir is None:
        return None
    path = financial_cache_path(cache_dir, snapshot)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("financial_rows")
    if not isinstance(rows, list):
        return None
    return rows


def write_financial_rows_cache(cache_dir: Path | None, snapshot: MarketSnapshot, rows: list[dict[str, Any]]) -> None:
    if cache_dir is None:
        return
    payload = {
        "ticker": snapshot.ticker,
        "code": snapshot.code,
        "market": snapshot.market,
        "fetched_at": now_iso(),
        "source": "eastmoney",
        "report_periods": [row.get("year") for row in rows if row.get("year")],
        "financial_rows": rows,
    }
    write_json_path(financial_cache_path(cache_dir, snapshot), payload)


def fetch_financial_rows_cached(
    snapshot: MarketSnapshot,
    *,
    cache_dir: Path | None,
    session: requests.sessions.Session,
    request_delay: float,
    timeout: float,
) -> tuple[list[dict[str, Any]], bool]:
    cached = load_financial_rows_from_cache(cache_dir, snapshot)
    if cached is not None:
        return cached, True
    rows = fetch_financial_rows(snapshot, session=session, request_delay=request_delay, timeout=timeout)
    write_financial_rows_cache(cache_dir, snapshot, rows)
    return rows, False


def write_universe(
    run_dir: Path,
    *,
    run_date: str,
    markets: list[str],
    snapshots: list[MarketSnapshot],
    errors: list[dict[str, Any]],
    min_market_cap: float,
) -> None:
    write_json_path(
        run_dir / UNIVERSE_FILENAME,
        {
            "run_date": run_date,
            "fetched_at": now_iso(),
            "markets": markets,
            "min_market_cap": min_market_cap,
            "snapshot_count": len(snapshots),
            "errors": errors,
            "snapshots": [snapshot_to_dict(snapshot) for snapshot in snapshots],
        },
    )


def reset_run_checkpoint(run_dir: Path | None) -> None:
    if run_dir is None:
        return
    for filename in (UNIVERSE_FILENAME, ENRICH_FILENAME, "progress.json"):
        path = run_dir / filename
        if path.exists():
            path.unlink()


def load_universe(run_dir: Path) -> tuple[list[MarketSnapshot], list[dict[str, Any]], dict[str, Any]]:
    path = run_dir / UNIVERSE_FILENAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshots = [snapshot_from_dict(item) for item in payload.get("snapshots", [])]
    errors = payload.get("errors") or []
    return snapshots, errors, payload


def latest_checkpoint_rows(run_dir: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(run_dir / ENRICH_FILENAME):
        ticker = row.get("ticker")
        if ticker:
            latest[str(ticker)] = row
    return latest


def checkpoint_result(
    run_dir: Path | None,
    *,
    run_date: str,
    snapshot: MarketSnapshot,
    enrich_status: str,
    result: dict[str, Any],
    attempt: int,
    error: str | None = None,
    from_cache: bool = False,
) -> None:
    if run_dir is None:
        return
    row = {
        "run_date": run_date,
        "fetched_at": now_iso(),
        "ticker": snapshot.ticker,
        "market": snapshot.market,
        "code": snapshot.code,
        "enrich_status": enrich_status,
        "attempt": attempt,
        "from_cache": from_cache,
        "result": result,
    }
    if error:
        row["error"] = error
    append_jsonl(run_dir / ENRICH_FILENAME, row)


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


def financial_fetch_blockers(snapshot: MarketSnapshot, min_market_cap: float) -> list[str]:
    reasons: list[str] = []
    if snapshot.price is None or snapshot.price <= 0:
        reasons.append("no_valid_price")
    if snapshot.market in {"SH", "SZ"} and (snapshot.name.startswith("ST") or snapshot.name.startswith("*ST")):
        reasons.append("st_or_special_treatment")
    if snapshot.market_cap is None or snapshot.market_cap < min_market_cap:
        reasons.append("below_market_cap_floor")
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
        "market_cap_rank": snapshot.market_cap_rank,
        "market_cap_percentile": snapshot.market_cap_percentile,
        "analyzed": bool(financial_rows),
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


def financial_fetch_failed_item(
    snapshot: MarketSnapshot,
    *,
    min_market_cap: float,
    error: str,
) -> dict[str, Any]:
    return {
        "ticker": snapshot.ticker,
        "name": snapshot.name,
        "market": snapshot.market,
        "currency": snapshot.currency,
        "financial_currency": snapshot.currency,
        "price": snapshot.price,
        "market_cap": snapshot.market_cap,
        "market_cap_rank": snapshot.market_cap_rank,
        "market_cap_percentile": snapshot.market_cap_percentile,
        "analyzed": False,
        "industry": snapshot.industry,
        "status": "INSUFFICIENT_DATA",
        "quality_score": 0,
        "valuation_score": 0,
        "screen_score": 0,
        "metrics": {"pe": snapshot.pe, "pb": snapshot.pb, "complete_financial_years": 0},
        "quality_flags": [],
        "valuation_flags": [],
        "reject_reasons": quick_reject_reasons(snapshot, min_market_cap),
        "data_gaps": ["financial_fetch_failed"],
        "error_phase": "financial_rows",
        "error": error,
        "source": snapshot.source,
    }


def screen_stocks(
    *,
    markets: list[str],
    max_count: int,
    sort_by: str,
    min_market_cap: float,
    request_delay: float = 0.0,
    session: requests.sessions.Session | None = None,
    timeout: float = 20,
    run_date: str | None = None,
    run_dir: Path | None = None,
    resume: bool = False,
    cache_dir: Path | None = None,
    progress_interval: int = 0,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    run_date = run_date or default_run_date()
    normalized_markets = [market.upper() for market in markets]
    unsupported = [market for market in normalized_markets if market not in MARKET_CONFIGS]
    supported_markets = [market for market in normalized_markets if market in MARKET_CONFIGS]
    client = configure_session(session or requests.Session())
    if run_dir is not None and not resume:
        reset_run_checkpoint(run_dir)

    if resume and run_dir is not None and (run_dir / UNIVERSE_FILENAME).exists():
        snapshots, errors, universe_payload = load_universe(run_dir)
        universe_source = "checkpoint"
        universe_fetched_at = universe_payload.get("fetched_at")
        universe_run_date = universe_payload.get("run_date")
        if universe_run_date and universe_run_date != run_date:
            return {
                "ok": False,
                "fetched_at": now_iso(),
                "markets": supported_markets,
                "unsupported_markets": unsupported,
                "source": "secondary_market_data",
                "data_limits": {
                    "secondary_source_only": True,
                    "max_count": max_count,
                    "run_date": run_date,
                    "run_dir": str(run_dir),
                    "cache_dir": str(cache_dir) if cache_dir is not None else None,
                    "resume": resume,
                    "universe_source": universe_source,
                    "universe_fetched_at": universe_fetched_at,
                    "universe_run_date": universe_run_date,
                    "snapshot_sources": sorted({snapshot.source for snapshot in snapshots if snapshot.source}),
                    "financial_analysis_scope": "all_rows_at_or_above_market_cap_floor",
                    "financial_analysis_selected_count": 0,
                    "analyzed_count": 0,
                    "financial_fetch_attempts": 0,
                    "min_market_cap": min_market_cap,
                    "request_delay_seconds": request_delay,
                    "progress_interval": progress_interval,
                    "errors": errors,
                },
                "risk_free_rates": {},
                "summary": {
                    "total": 0,
                    "candidate": 0,
                    "rejected": 0,
                    "insufficient_data": 0,
                    "industry_review_required": 0,
                },
                "phase": "resume_checkpoint",
                "error": (
                    f"Cannot resume run_date {run_date} from checkpoint run_date {universe_run_date}. "
                    "Start a new date directory or pass the checkpoint run_date explicitly."
                ),
                "results": [],
            }
    else:
        snapshots, errors = fetch_market_snapshots(
            markets=supported_markets,
            max_count=max_count,
            sort_by="market_cap",
            min_market_cap=min_market_cap,
            request_delay=request_delay,
            session=client,
            timeout=timeout,
        )
        annotate_market_cap_universe(snapshots)
        universe_source = "live"
        universe_fetched_at = now_iso()
        if run_dir is not None:
            write_universe(
                run_dir,
                run_date=run_date,
                markets=supported_markets,
                snapshots=snapshots,
                errors=errors,
                min_market_cap=min_market_cap,
            )
    for market in unsupported:
        errors.append({"market": market, "phase": "market_snapshot", "error": "unsupported market"})

    if logger is not None:
        logger.info(
            "[stock-screen] universe %s total=%s markets=%s run_date=%s",
            universe_source,
            len(snapshots),
            ",".join(supported_markets) or "-",
            run_date,
        )

    rates: dict[str, dict[str, Any]] = {}
    results_by_ticker: dict[str, dict[str, Any]] = {}
    checkpoint_rows = latest_checkpoint_rows(run_dir) if run_dir is not None else {}
    if resume:
        for ticker, row in checkpoint_rows.items():
            result = row.get("result")
            if isinstance(result, dict):
                results_by_ticker[ticker] = result
    financial_fetch_attempts = 0
    for processed_count, snapshot in enumerate(snapshots, start=1):
        previous_row = checkpoint_rows.get(snapshot.ticker)
        if resume and previous_row and previous_row.get("enrich_status") == "ok":
            log_screen_progress(
                logger,
                event="skipped",
                processed=processed_count,
                total=len(snapshots),
                ticker=snapshot.ticker,
                checkpoint_rows=checkpoint_rows,
                financial_fetch_attempts=financial_fetch_attempts,
                interval=progress_interval,
            )
            continue

        fetch_blockers = financial_fetch_blockers(snapshot, min_market_cap)
        should_analyze = not fetch_blockers and snapshot.selected_for_financial_analysis
        financial_rows: list[dict[str, Any]] = []
        from_cache = False
        attempt = int((previous_row or {}).get("attempt") or 0) + 1
        if should_analyze:
            financial_fetch_attempts += 1
            try:
                financial_rows, from_cache = fetch_financial_rows_cached(
                    snapshot,
                    cache_dir=cache_dir,
                    session=client,
                    request_delay=request_delay,
                    timeout=timeout,
                )
            except Exception as exc:
                result = financial_fetch_failed_item(snapshot, min_market_cap=min_market_cap, error=str(exc))
                results_by_ticker[snapshot.ticker] = result
                checkpoint_result(
                    run_dir,
                    run_date=run_date,
                    snapshot=snapshot,
                    enrich_status="failed",
                    result=result,
                    attempt=attempt,
                    error=str(exc),
                )
                checkpoint_rows[snapshot.ticker] = {
                    "ticker": snapshot.ticker,
                    "enrich_status": "failed",
                    "attempt": attempt,
                    "result": result,
                }
                log_screen_progress(
                    logger,
                    event="failed",
                    processed=processed_count,
                    total=len(snapshots),
                    ticker=snapshot.ticker,
                    checkpoint_rows=checkpoint_rows,
                    financial_fetch_attempts=financial_fetch_attempts,
                    interval=progress_interval,
                    force=True,
                )
                continue

        fin_currency = financial_currency(financial_rows, snapshot.currency)
        if fin_currency not in rates:
            rates[fin_currency] = fetch_risk_free_rate(fin_currency, timeout=timeout)
        result = build_result_item(
            snapshot,
            financial_rows=financial_rows,
            risk_free=rates.get(fin_currency),
            min_market_cap=min_market_cap,
        )
        results_by_ticker[snapshot.ticker] = result
        checkpoint_result(
            run_dir,
            run_date=run_date,
            snapshot=snapshot,
            enrich_status="ok",
            result=result,
            attempt=attempt,
            from_cache=from_cache,
        )
        checkpoint_rows[snapshot.ticker] = {
            "ticker": snapshot.ticker,
            "enrich_status": "ok",
            "attempt": attempt,
            "result": result,
        }
        log_screen_progress(
            logger,
            event="ok_from_cache" if from_cache else "ok",
            processed=processed_count,
            total=len(snapshots),
            ticker=snapshot.ticker,
            checkpoint_rows=checkpoint_rows,
            financial_fetch_attempts=financial_fetch_attempts,
            interval=progress_interval,
        )

    results = [results_by_ticker[snapshot.ticker] for snapshot in snapshots if snapshot.ticker in results_by_ticker]
    results = sort_results(results, sort_by)
    snapshot_sources = sorted({snapshot.source for snapshot in snapshots if snapshot.source})
    failed_markets = failed_market_snapshots(supported_markets, errors)
    no_supported_markets = bool(normalized_markets) and not supported_markets
    all_supported_markets_failed = bool(supported_markets) and not snapshots and set(supported_markets) <= failed_markets
    no_snapshots_with_errors = bool(supported_markets) and not snapshots and bool(errors)
    ok = not (no_supported_markets or all_supported_markets_failed or no_snapshots_with_errors)
    payload = {
        "ok": ok,
        "fetched_at": now_iso(),
        "markets": supported_markets,
        "unsupported_markets": unsupported,
        "source": "secondary_market_data",
        "data_limits": {
            "secondary_source_only": True,
            "max_count": max_count,
            "run_date": run_date,
            "run_dir": str(run_dir) if run_dir is not None else None,
            "cache_dir": str(cache_dir) if cache_dir is not None else None,
            "resume": resume,
            "universe_source": universe_source,
            "universe_fetched_at": universe_fetched_at,
            "snapshot_sources": snapshot_sources,
            "financial_analysis_scope": "all_rows_at_or_above_market_cap_floor",
            "financial_analysis_selected_count": sum(1 for item in snapshots if item.selected_for_financial_analysis),
            "analyzed_count": sum(1 for item in results if item.get("analyzed")),
            "financial_fetch_attempts": financial_fetch_attempts,
            "min_market_cap": min_market_cap,
            "request_delay_seconds": request_delay,
            "progress_interval": progress_interval,
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
    elif no_snapshots_with_errors:
        payload["phase"] = "market_snapshot"
        payload["error"] = "No market snapshots fetched; see data_limits.errors."
    if logger is not None:
        ok_count, failed_count = checkpoint_status_counts(checkpoint_rows)
        logger.info(
            "[stock-screen] complete total=%s ok=%s failed=%s results=%s candidates=%s run_dir=%s",
            len(snapshots),
            ok_count,
            failed_count,
            len(results),
            payload["summary"]["candidate"],
            str(run_dir) if run_dir is not None else "-",
        )
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

    base_columns = [
        "ticker",
        "name",
        "market",
        "currency",
        "financial_currency",
        "status",
        "price",
        "market_cap",
        "market_cap_rank",
        "market_cap_percentile",
        "analyzed",
        "industry",
        "quality_score",
        "valuation_score",
        "screen_score",
        "quality_flags",
        "valuation_flags",
        "reject_reasons",
        "data_gaps",
        "error_phase",
        "error",
        "source",
    ]
    metric_columns = [
        "pe",
        "pb",
        "roe_mean",
        "roe_std",
        "roe_stability",
        "roic_mean",
        "avg_net_profit_5y",
        "avg_ocf_5y",
        "avg_fcf_5y",
        "ocf_to_profit",
        "fcf_to_profit",
        "market_cap_to_avg_profit",
        "market_cap_to_avg_fcf",
        "expected_return",
        "debt_to_assets",
        "goodwill_to_equity",
        "risk_free_multiple_cap",
        "complete_financial_years",
        "negative_fcf_years",
    ]

    def row_for(item: dict[str, Any]) -> list[Any]:
        row: list[Any] = []
        metrics = item.get("metrics") or {}
        for column in base_columns:
            value = item.get(column)
            if isinstance(value, list):
                value = ", ".join(str(part) for part in value)
            row.append(value)
        for column in metric_columns:
            row.append(metrics.get(column))
        return row

    columns = base_columns + metric_columns

    all_sheet = workbook.create_sheet("All")
    all_sheet.append(columns)
    for item in payload["results"]:
        all_sheet.append(row_for(item))

    for market in payload.get("markets", []):
        sheet = workbook.create_sheet(market[:31])
        sheet.append(columns)
        for item in payload["results"]:
            if item.get("market") == market:
                sheet.append(row_for(item))

    for status in ("CANDIDATE", "REJECTED", "INSUFFICIENT_DATA", "INDUSTRY_REVIEW_REQUIRED"):
        sheet = workbook.create_sheet(status.title().replace("_", ""))
        sheet.append(columns)
        for item in payload["results"]:
            if item["status"] != status:
                continue
            sheet.append(row_for(item))

    raw_sheet = workbook.create_sheet("RawSnapshots")
    raw_sheet.append(["ticker", "metrics_json"])
    for item in payload["results"]:
        raw_sheet.append([item["ticker"], json.dumps(json_safe(item.get("metrics", {})), ensure_ascii=False)])
    workbook.save(output_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen stock candidates for quality value research.")
    parser.add_argument("--markets", nargs="+", default=["SH", "SZ", "HK"], help="Markets to screen. Default: SH SZ HK.")
    parser.add_argument(
        "--max-count",
        type=int,
        default=300,
        help="Maximum market snapshots to keep per market after sorting. Use 0 to page until --min-market-cap is crossed.",
    )
    parser.add_argument("--sort-by", choices=["screen_score", "market_cap"], default="screen_score")
    parser.add_argument("--min-market-cap", type=float, default=DEFAULT_MIN_MARKET_CAP)
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=DEFAULT_PROGRESS_INTERVAL,
        help="Print progress to stderr every N processed rows. Use 0 to disable periodic progress.",
    )
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--run-date", default=default_run_date(), help="Run date partition in YYYY-MM-DD format.")
    parser.add_argument(
        "--run-dir",
        help="Checkpoint run directory. Defaults to reports/stock-screen/<run-date> when --resume is used.",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from the run directory checkpoint files.")
    parser.add_argument(
        "--cache-dir",
        help="Financial-row cache directory. Defaults to reports/stock-screen/cache/financials when checkpointing.",
    )
    parser.add_argument("--json-out")
    parser.add_argument("--xlsx-out")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir) if args.run_dir else (default_run_dir(args.run_date) if args.resume else None)
    cache_dir = Path(args.cache_dir) if args.cache_dir else (default_cache_dir() if run_dir is not None else None)
    logger = configure_progress_logger()
    progress_interval = max(args.progress_interval, 0)

    payload = screen_stocks(
        markets=args.markets,
        max_count=args.max_count,
        sort_by=args.sort_by,
        min_market_cap=args.min_market_cap,
        request_delay=args.request_delay,
        timeout=args.timeout,
        run_date=args.run_date,
        run_dir=run_dir,
        resume=args.resume,
        cache_dir=cache_dir,
        progress_interval=progress_interval,
        logger=logger,
    )
    if args.json_out:
        write_json(args.json_out, payload)
    xlsx_out = args.xlsx_out
    if xlsx_out is None and run_dir is not None:
        xlsx_out = str(run_dir / f"stock-screen-{args.run_date}.xlsx")
    if xlsx_out:
        write_xlsx(xlsx_out, payload)

    stdout_payload = {key: value for key, value in payload.items() if key != "results"}
    stdout_payload["results"] = payload["results"][: min(50, len(payload["results"]))]
    print(json.dumps(json_safe(stdout_payload), ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
