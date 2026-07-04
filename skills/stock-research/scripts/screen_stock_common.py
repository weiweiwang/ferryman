from __future__ import annotations

import json
import logging
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests


LOGGER = logging.getLogger("stock_screen")

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
    "US": {
        "name": "United States",
        "fs": "m:105,m:106,m:107",
        "currency": "USD",
        "secid_prefix": "",
    },
}

EASTMONEY_QUOTE_UT = "fa5fd1943c7b386f172d6893dbfba10b"
EASTMONEY_WBP2U = "|0|0|0|web"
# Market snapshot universe is intentionally locked to one Eastmoney webguest
# clist endpoint across SH/SZ/HK/US. Do not add mixed market snapshot providers
# or alternate list hosts without explicit user review.
MARKET_SNAPSHOT_PROVIDER = "eastmoney_webguest_clist"
MARKET_SNAPSHOT_ENDPOINT = "https://push2.eastmoney.com/webguest/api/qt/clist/get"
SORT_FIELDS = {"market_cap": "f20", "change_pct": "f3"}
EASTMONEY_LIST_FIELDS = (
    "f1,f2,f3,f5,f6,f8,f9,f10,f12,f13,f14,f20,f21,f23,f24,"
    "f25,f62,f100,f115,f152"
)
MIN_FINANCIAL_YEARS = 5
DEFAULT_MIN_MARKET_CAP = 5_000_000_000
DEFAULT_REQUEST_DELAY_SECONDS = 0.2
DEFAULT_PROGRESS_INTERVAL = 50
DEFAULT_FINANCIAL_CACHE_MAX_AGE_DAYS = 7
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
    "欧元": "EUR",
    "歐元": "EUR",
    "eur": "EUR",
    "澳大利亚元": "AUD",
    "澳大利亞元": "AUD",
    "澳元": "AUD",
    "澳幣": "AUD",
    "aud": "AUD",
    "英镑": "GBP",
    "英鎊": "GBP",
    "gbp": "GBP",
}
US_MARKET_SUFFIX_BY_F13 = {"105": "O", "106": "N", "107": "A"}
US_MARKET_CODE_BY_SUFFIX = {"O": "105", "N": "106", "A": "107"}


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
    if isinstance(value, (list, tuple)):
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
    if isinstance(value, (int, float)) and float(value).is_integer():
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


def us_ticker_for_eastmoney_market(code: str, eastmoney_market_code: Any = None) -> str:
    normalized_code = str(code or "").strip().upper()
    if "." in normalized_code:
        return normalized_code
    suffix = US_MARKET_SUFFIX_BY_F13.get(str(eastmoney_market_code or "").strip())
    return f"{normalized_code}.{suffix}" if suffix else normalized_code


def normalize_currency(currency: Any, default_currency: str) -> str:
    if not currency:
        return default_currency
    normalized = str(currency).strip()
    return CURRENCY_ALIASES.get(normalized.lower(), CURRENCY_ALIASES.get(normalized, normalized.upper()))
