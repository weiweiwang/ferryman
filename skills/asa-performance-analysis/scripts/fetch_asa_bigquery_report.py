#!/usr/bin/env python3
"""Fetch ASA keyword performance from BigQuery and write a dated CSV report.

Credentials are resolved in this order:
1. --credentials-file
2. ASA_BIGQUERY_SERVICE_ACCOUNT_JSON
3. GOOGLE_APPLICATION_CREDENTIALS
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yfinance as yf


SERVICE_ACCOUNT_ENV_VARS = ("ASA_BIGQUERY_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS")

QUERY = """
WITH
  first_opens AS (
    SELECT
      DATE(timestamp, "UTC") AS first_open_date,
      JSON_VALUE(json_payload.message.token) AS token,
      JSON_VALUE(json_payload.message.payload.params.keyword_id) AS keyword_id
    FROM `{attribution_table}`
    WHERE
      JSON_VALUE(json_payload.message.payload.name) = "client_first_open"
      AND JSON_VALUE(json_payload.message.payload.params.pkg) = @bundle_id
      AND JSON_VALUE(json_payload.message.payload.params.channel) = "ASA"
      AND JSON_VALUE(json_payload.message.payload.params.keyword_id) IS NOT NULL
      AND timestamp >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")
  ),

  purchases AS (
    SELECT
      DATE(TIMESTAMP(JSON_VALUE(json_payload.message.payload.events[0].params.original_purchase_date)), "UTC") AS original_purchase_date,
      CAST(JSON_VALUE(json_payload.message.payload.events[0].params.product_price) AS FLOAT64) / 1000 AS income,
      JSON_VALUE(json_payload.message.payload.events[0].params.product_currency) AS currency,
      JSON_VALUE(json_payload.message.payload.user_id) AS token
    FROM `{iap_table}`
    WHERE
      resource.type = "k8s_container"
      AND JSON_VALUE(json_payload.message.event_name) = "firebase"
      AND JSON_VALUE(json_payload.message.payload.events[0].name) = "server_purchase"
      AND JSON_VALUE(json_payload.message.payload.events[0].params.bundle_id) = @bundle_id
      AND JSON_VALUE(json_payload.message.payload.events[0].params.environment) = "production"
      AND timestamp >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")
  ),

  renew_cycles AS (
    SELECT
      DATE(TIMESTAMP(JSON_VALUE(json_payload.message.payload.events[0].params.original_purchase_date)), "UTC") AS original_purchase_date,
      CAST(JSON_VALUE(json_payload.message.payload.events[0].params.renewal_count) AS INT64) AS renewal_cycle,
      JSON_VALUE(json_payload.message.payload.user_id) AS token,
      CAST(JSON_VALUE(json_payload.message.payload.events[0].params.product_price) AS FLOAT64) / 1000 AS income,
      JSON_VALUE(json_payload.message.payload.events[0].params.product_currency) AS currency
    FROM `{iap_table}`
    WHERE
      resource.type = "k8s_container"
      AND JSON_VALUE(json_payload.message.payload.events[0].name) = "server_renew"
      AND JSON_VALUE(json_payload.message.payload.events[0].params.bundle_id) = @bundle_id
      AND JSON_VALUE(json_payload.message.payload.events[0].params.environment) = "production"
      AND timestamp >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")
  ),

  unsubscribes_15m AS (
    SELECT
      DATE(TIMESTAMP(JSON_VALUE(json_payload.message.payload.events[0].params.original_purchase_date)), "UTC") AS original_purchase_date,
      JSON_VALUE(json_payload.message.payload.user_id) AS token
    FROM `{iap_table}`
    WHERE
      resource.type = "k8s_container"
      AND JSON_VALUE(json_payload.message.payload.events[0].name) = "server_unsubscribe"
      AND JSON_VALUE(json_payload.message.payload.events[0].params.bundle_id) = @bundle_id
      AND JSON_VALUE(json_payload.message.payload.events[0].params.environment) = "production"
      AND CAST(JSON_VALUE(json_payload.message.payload.events[0].params.unsubscribe_delay) AS INT64) <= 15
      AND timestamp >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")
  ),

  unsubscribes AS (
    SELECT
      DATE(TIMESTAMP(JSON_VALUE(json_payload.message.payload.events[0].params.original_purchase_date)), "UTC") AS original_purchase_date,
      JSON_VALUE(json_payload.message.payload.user_id) AS token
    FROM `{iap_table}`
    WHERE
      resource.type = "k8s_container"
      AND JSON_VALUE(json_payload.message.payload.events[0].name) = "server_unsubscribe"
      AND JSON_VALUE(json_payload.message.payload.events[0].params.bundle_id) = @bundle_id
      AND JSON_VALUE(json_payload.message.payload.events[0].params.environment) = "production"
      AND timestamp >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")
  ),

  keyword_attributions AS (
    SELECT
      f.first_open_date,
      f.keyword_id,
      SUM({purchase_income_case}) AS purchase_income,
      COUNT(DISTINCT f.token) AS active_users,
      COUNT(DISTINCT p.token) AS purchase_users,
      COUNT(DISTINCT p.token) - COUNT(DISTINCT u15m.token) AS RU15m,
      COUNT(DISTINCT p.token) - COUNT(DISTINCT u.token) AS RU,
      COUNT(DISTINCT CASE WHEN r.renewal_cycle = 1 THEN r.token END) AS RUC1,
      COUNT(DISTINCT CASE WHEN r.renewal_cycle = 2 THEN r.token END) AS RUC2,
      COUNT(DISTINCT CASE WHEN r.renewal_cycle = 3 THEN r.token END) AS RUC3,
      COUNT(DISTINCT CASE WHEN r.renewal_cycle = 4 THEN r.token END) AS RUC4,
      COUNT(DISTINCT CASE WHEN r.renewal_cycle = 5 THEN r.token END) AS RUC5
    FROM first_opens AS f
    LEFT JOIN purchases p ON f.token = p.token
    LEFT JOIN renew_cycles r ON f.token = r.token
    LEFT JOIN unsubscribes_15m u15m ON f.token = u15m.token
    LEFT JOIN unsubscribes u ON f.token = u.token
    GROUP BY f.first_open_date, f.keyword_id
  ),

  keyword_latest_status AS (
    SELECT
      JSON_VALUE(json_payload.message.payload.params.keyword_id) AS keyword_id,
      JSON_VALUE(json_payload.message.payload.params.keyword_status) AS keyword_status
    FROM `{attribution_table}`
    WHERE
      JSON_VALUE(json_payload.message.payload.name) = "keyword_report"
      AND JSON_VALUE(json_payload.message.payload.params.version) = "v1"
      AND JSON_VALUE(json_payload.message.payload.params.granularity) = "HOURLY"
      AND JSON_VALUE(json_payload.message.payload.params.bundle_id) = @bundle_id
      AND JSON_VALUE(json_payload.message.payload.params.environment) = "production"
    QUALIFY
      ROW_NUMBER() OVER (
        PARTITION BY JSON_VALUE(json_payload.message.payload.params.keyword_id)
        ORDER BY timestamp DESC
      ) = 1
  ),

  base_keyword_costs AS (
    SELECT
      JSON_VALUE(json_payload.message.payload.report_date) AS report_date,
      JSON_VALUE(json_payload.message.payload.params.ad_group.name) AS ad_group,
      JSON_VALUE(json_payload.message.payload.params.ad_group.id) AS ad_group_id,
      JSON_VALUE(json_payload.message.payload.params.campaign_id) AS campaign_id,
      JSON_VALUE(json_payload.message.payload.params.keyword) AS keyword,
      JSON_VALUE(json_payload.message.payload.params.keyword_id) AS keyword_id,
      JSON_VALUE(json_payload.message.payload.params.match_type) AS match_type,
      JSON_VALUE(json_payload.message.payload.params.currency) AS currency,
      SAFE_CAST(JSON_VALUE(json_payload.message.payload.params.spend) AS FLOAT64) AS spend,
      SAFE_CAST(JSON_VALUE(json_payload.message.payload.params.impressions) AS INT64) AS impressions,
      SAFE_CAST(JSON_VALUE(json_payload.message.payload.params.taps) AS INT64) AS taps,
      SAFE_CAST(JSON_VALUE(json_payload.message.payload.params.total_installs) AS INT64) AS total_installs
    FROM `{attribution_table}`
    WHERE
      JSON_VALUE(json_payload.message.payload.name) = "keyword_report"
      AND JSON_VALUE(json_payload.message.payload.params.version) = "v1"
      AND JSON_VALUE(json_payload.message.payload.params.granularity) = "HOURLY"
      AND JSON_VALUE(json_payload.message.payload.params.bundle_id) = @bundle_id
      AND JSON_VALUE(json_payload.message.payload.params.environment) = "production"
      AND timestamp >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")
    QUALIFY
      ROW_NUMBER() OVER (
        PARTITION BY
          JSON_VALUE(json_payload.message.payload.report_date),
          JSON_VALUE(json_payload.message.payload.params.keyword_id)
        ORDER BY timestamp DESC
      ) = 1
  ),

  keyword_costs AS (
    SELECT
      DATE(TIMESTAMP(bc.report_date), "UTC") AS report_date,
      bc.campaign_id,
      bc.ad_group,
      bc.ad_group_id,
      bc.keyword,
      bc.keyword_id,
      ks.keyword_status,
      bc.match_type,
      ROUND(SUM({spend_case}), 2) AS spend,
      SUM(bc.impressions) AS impressions,
      SUM(bc.taps) AS clicks,
      SUM(bc.total_installs) AS installs
    FROM base_keyword_costs bc
    LEFT JOIN keyword_latest_status ks ON bc.keyword_id = ks.keyword_id
    GROUP BY
      report_date,
      bc.campaign_id,
      bc.ad_group,
      bc.ad_group_id,
      bc.keyword,
      bc.keyword_id,
      ks.keyword_status,
      bc.match_type
  )

SELECT
  kc.report_date,
  kc.campaign_id,
  kc.ad_group_id,
  kc.ad_group,
  kc.keyword,
  kc.keyword_id,
  kc.keyword_status,
  kc.match_type,
  kc.spend,
  kc.impressions,
  kc.clicks,
  kc.installs,
  COALESCE(ka.purchase_income, 0.0) AS purchase_income,
  COALESCE(ka.active_users, 0) AS active_users,
  COALESCE(ka.purchase_users, 0) AS purchase_users,
  COALESCE(ka.RU15m, 0) AS RU15m,
  COALESCE(ka.RU, 0) AS RU,
  COALESCE(ka.RUC1, 0) AS RUC1,
  COALESCE(ka.RUC2, 0) AS RUC2,
  COALESCE(ka.RUC3, 0) AS RUC3,
  COALESCE(ka.RUC4, 0) AS RUC4,
  COALESCE(ka.RUC5, 0) AS RUC5
FROM keyword_costs kc
LEFT JOIN keyword_attributions ka
  ON kc.report_date = ka.first_open_date
  AND kc.keyword_id = ka.keyword_id
ORDER BY
  kc.report_date DESC,
  kc.spend DESC
"""

CURRENCY_QUERY = """
SELECT DISTINCT
  CASE
    WHEN JSON_VALUE(json_payload.message.payload.params.currency) = "RMB" THEN "CNY"
    ELSE JSON_VALUE(json_payload.message.payload.params.currency)
    END AS currency
FROM `{attribution_table}`
WHERE
  JSON_VALUE(json_payload.message.payload.name) = "keyword_report"
  AND JSON_VALUE(json_payload.message.payload.params.version) = "v1"
  AND JSON_VALUE(json_payload.message.payload.params.granularity) = "HOURLY"
  AND JSON_VALUE(json_payload.message.payload.params.bundle_id) = @bundle_id
  AND JSON_VALUE(json_payload.message.payload.params.environment) = "production"
  AND timestamp
    >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")
"""

COLUMNS = [
    "ad_group_id", "ad_group", "match_type", "keyword", "keyword_status", "days",
    "purchase_users", "RUC1", "RUC2", "RUC3", "RUC4", "RUC5", "spend", "daily_spend", "CPS", "CPR1",
    "RRC1", "RRC2", "RRC3", "RRC4", "RRC5", "impressions", "clicks", "installs", "CTR", "CIR", "CVR", "CPC", "CPI",
    "purchase_income", "active_users", "RU15m", "RU", "ASR15m", "ASR",
    "RUC1_mature_purchases", "RUC2_mature_purchases", "RUC3_mature_purchases",
    "RUC4_mature_purchases", "RUC5_mature_purchases",
    "payback_days", "LTV_per_purchase_user", "expected_revenue", "payback_ratio", "Target_CPI",
    "required_CPS_reduction"
]

DAILY_COLUMNS = [
    "report_date", "campaign_id", "ad_group_id", "ad_group", "keyword", "keyword_id",
    "keyword_status", "match_type", "spend", "impressions", "clicks", "installs",
    "purchase_income", "active_users", "purchase_users", "RU15m", "RU", "RUC1", "RUC2", "RUC3",
    "RUC4", "RUC5"
]

COHORT_COLUMNS = [
    "ad_group_id", "ad_group", "match_type", "keyword", "keyword_status",
    "spend", "impressions", "clicks", "installs", "purchases", "renewals", "RRC"
]


class AsaPerformanceError(RuntimeError):
    pass


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": {"type": "AsaPerformanceError", "message": message}}, ensure_ascii=False))
    return 1


def default_start_date(today: date | None = None) -> date:
    return (today or datetime.now(timezone.utc).date()) - timedelta(days=60)


def parse_date_arg(value: str | None) -> date | None:
    if not value:
        return default_start_date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AsaPerformanceError(f"--start-date必须使用YYYY-MM-DD格式: {value}") from exc


def credentials_path(value: str | None) -> Path:
    raw = value or next((os.environ.get(name) for name in SERVICE_ACCOUNT_ENV_VARS if os.environ.get(name)), None)
    if not raw:
        raise AsaPerformanceError("缺少service account JSON，请提供--credentials-file或设置ASA_BIGQUERY_SERVICE_ACCOUNT_JSON")
    path = Path(raw).expanduser()
    if not path.is_file():
        raise AsaPerformanceError(f"service account JSON不存在: {path}")
    return path


def client(key_file: Path) -> Any:
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ModuleNotFoundError as exc:
        raise AsaPerformanceError("缺少依赖google-cloud-bigquery") from exc
    creds = service_account.Credentials.from_service_account_file(str(key_file))
    return bigquery.Client(project=creds.project_id, credentials=creds)


def query_config(bundle_id: str, start_date: date | None, args: argparse.Namespace) -> Any:
    from google.cloud import bigquery
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("bundle_id", "STRING", bundle_id),
            bigquery.ScalarQueryParameter("start_date", "DATE", start_date.isoformat() if start_date else None),
        ]
    )


def run(client_: Any, sql: str, config: Any, timeout: int) -> list[dict[str, Any]]:
    try:
        return [dict(row.items()) for row in client_.query(sql, job_config=config, timeout=timeout).result(timeout=timeout)]
    except Exception as exc:
        raise AsaPerformanceError(f"BigQuery查询失败: {exc}") from exc


def fx_rate(currency: str, target: str) -> tuple[float, str]:
    c = "CNY" if currency == "RMB" else currency
    t = "CNY" if target == "RMB" else target
    if c == t:
        return 1.0, "identity"
    symbol = f"{c}{t}=X"

    import time
    history = None
    for attempt in range(3):
        try:
            history = yf.Ticker(symbol).history(period="5d")
            if not (history.empty or history["Close"].dropna().empty):
                break
        except Exception as exc:
            if attempt == 2:
                raise AsaPerformanceError(f"无法获取汇率: {symbol} (连接失败: {exc})") from exc
        if attempt < 2:
            time.sleep(1)

    if history is None or history.empty or history["Close"].dropna().empty:
        raise AsaPerformanceError(f"无法获取汇率: {symbol}")
    rate = float(history["Close"].dropna().iloc[-1])
    if rate <= 0 or not math.isfinite(rate):
        raise AsaPerformanceError(f"非法汇率: {symbol}={rate}")
    return rate, f"yfinance:{symbol}"


def resolve_rates(client_: Any, args: argparse.Namespace, config: Any, attribution_table: str) -> tuple[dict[str, float], dict[str, str]]:
    target = args.target_currency.upper()
    rates = {target: 1.0}
    sources = {target: "identity"}
    if target == "CNY":
        rates["RMB"] = 1.0
        sources["RMB"] = "identity"
    elif target == "RMB":
        rates["CNY"] = 1.0
        sources["CNY"] = "identity"

    rows = run(client_, CURRENCY_QUERY.format(attribution_table=attribution_table), config, args.job_timeout_seconds)
    for row in rows:
        currency = (row.get("currency") or target).upper()
        if currency == "RMB":
            currency = "CNY"
        if currency not in rates:
            rates[currency], sources[currency] = fx_rate(currency, target)
    return rates, sources


def make_currency_case(rates: dict[str, float], currency_col: str, value_col: str) -> str:
    lines = ["CASE"]
    for currency, rate in sorted(rates.items()):
        lines.append(f'        WHEN {currency_col} = "{currency}" THEN {value_col} * {rate:.10f}')
    if "CNY" in rates:
        lines.append(f'        WHEN {currency_col} = "RMB" THEN {value_col} * {rates["CNY"]:.10f}')
    lines.append("        ELSE 0")
    lines.append("        END")
    return "\n".join(lines)


def calculate_ltv(
    first_purchase_gross: float,
    regular_period_gross: float,
    trial_days: int,
    billing_period_days: int,
    payback_days: int,
    apple_fee: float,
    rrc1: float | None,
    rrc2: float | None,
    rrc3: float | None,
    rrc4: float | None = None,
    rrc5: float | None = None
) -> float:
    """Calculate lifetime value per purchase user within the target payback window."""
    net_first = first_purchase_gross * (1.0 - apple_fee)
    net_regular = regular_period_gross * (1.0 - apple_fee)

    r_curve = []
    
    # Cycle 1 (index 0): first payment / conversion rate
    c1 = rrc1 if rrc1 is not None else 0.40
    r_curve.append(c1)
    
    # Cycle 2 (index 1): second payment
    if rrc2 is not None:
        c2 = rrc2
    else:
        c2 = r_curve[0] * 0.75
    r_curve.append(c2)
    
    # Cycle 3 (index 2): third payment
    if rrc3 is not None:
        c3 = rrc3
    else:
        c3 = r_curve[1] * 0.85
    r_curve.append(c3)

    # Cycle 4 (index 3): fourth payment
    if rrc4 is not None:
        c4 = rrc4
    else:
        c4 = r_curve[2] * 0.90
    r_curve.append(c4)

    # Cycle 5 (index 4): fifth payment
    if rrc5 is not None:
        c5 = rrc5
    else:
        c5 = r_curve[3] * 0.92
    r_curve.append(c5)
    
    # Extrapolate higher cycles (6 to 52) using marginal renewal rates
    for i in range(5, 52):
        if i == 5:
            m = 0.95
        else:
            m = 0.96
        r_curve.append(r_curve[-1] * m)

    if trial_days > 0:
        if trial_days >= payback_days:
            return 0.0
        ltv = net_first * r_curve[0]
        k_max = math.floor((payback_days - trial_days) / billing_period_days)
        for k in range(1, k_max + 1):
            if k < len(r_curve):
                ltv += net_regular * r_curve[k]
        return round(ltv, 2)
    else:
        ltv = net_first
        k_max = math.floor(payback_days / billing_period_days)
        for k in range(0, k_max):
            if k < len(r_curve):
                ltv += net_regular * r_curve[k]
        return round(ltv, 2)


def renewal_cutoff_date(
    today_dt: date,
    trial_days: int,
    billing_period_days: int,
    renewal_cycle: int
) -> date:
    if renewal_cycle < 1:
        raise AsaPerformanceError("renewal_cycle必须大于等于1")
    if trial_days > 0:
        mature_days = trial_days + (renewal_cycle - 1) * billing_period_days + 1
    else:
        mature_days = renewal_cycle * billing_period_days + 1
    return today_dt - timedelta(days=mature_days)


def aggregate_daily_metrics(
    rows: list[dict[str, Any]],
    trial_days: int,
    billing_period_days: int,
    today_dt: date,
    first_purchase_gross: float = 0.0,
    regular_period_gross: float = 0.0,
    apple_fee: float = 0.15,
    payback_days: int = 180
) -> list[dict[str, Any]]:
    ruc1_cutoff = renewal_cutoff_date(today_dt, trial_days, billing_period_days, 1)
    ruc2_cutoff = renewal_cutoff_date(today_dt, trial_days, billing_period_days, 2)
    ruc3_cutoff = renewal_cutoff_date(today_dt, trial_days, billing_period_days, 3)
    ruc4_cutoff = renewal_cutoff_date(today_dt, trial_days, billing_period_days, 4)
    ruc5_cutoff = renewal_cutoff_date(today_dt, trial_days, billing_period_days, 5)

    def to_date(val: Any) -> date:
        if isinstance(val, date):
            return val
        if isinstance(val, datetime):
            return val.date()
        return date.fromisoformat(str(val))

    # 1. 先按日期切片过滤出各阶段的成熟期子集
    ruc1_rows = [r for r in rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc1_cutoff]
    ruc2_rows = [r for r in rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc2_cutoff]
    ruc3_rows = [r for r in rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc3_cutoff]
    ruc4_rows = [r for r in rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc4_cutoff]
    ruc5_rows = [r for r in rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc5_cutoff]

    # 辅助函数：将行列表按关键词分组
    def group_by_keyword(subset: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for r in subset:
            key = (str(r.get("ad_group_id") or ""), str(r.get("keyword") or ""))
            grouped.setdefault(key, []).append(r)
        return grouped

    # 2. 分别对全量数据和各时期子集进行关键词分组
    overall_grouped = group_by_keyword(rows)
    ruc1_grouped = group_by_keyword(ruc1_rows)
    ruc2_grouped = group_by_keyword(ruc2_rows)
    ruc3_grouped = group_by_keyword(ruc3_rows)
    ruc4_grouped = group_by_keyword(ruc4_rows)
    ruc5_grouped = group_by_keyword(ruc5_rows)

    out_rows = []
    for key, all_rows in overall_grouped.items():
        ad_group_id, keyword = key
        first_row = all_rows[0]

        spend = sum(float(row.get("spend") or 0) for row in all_rows)
        impressions = sum(int(row.get("impressions") or 0) for row in all_rows)
        clicks = sum(int(row.get("clicks") or 0) for row in all_rows)
        installs = sum(int(row.get("installs") or 0) for row in all_rows)
        purchase_income = sum(float(row.get("purchase_income") or 0) for row in all_rows)
        active_users = sum(int(row.get("active_users") or 0) for row in all_rows)
        purchase_users = sum(int(row.get("purchase_users") or 0) for row in all_rows)

        RU15m = sum(int(row.get("RU15m") or 0) for row in all_rows)
        RU = sum(int(row.get("RU") or 0) for row in all_rows)
        RUC1 = sum(int(row.get("RUC1") or 0) for row in all_rows)
        RUC2 = sum(int(row.get("RUC2") or 0) for row in all_rows)
        RUC3 = sum(int(row.get("RUC3") or 0) for row in all_rows)
        RUC4 = sum(int(row.get("RUC4") or 0) for row in all_rows)
        RUC5 = sum(int(row.get("RUC5") or 0) for row in all_rows)

        report_dates = set()
        for row in all_rows:
            report_date_str = row.get("report_date")
            if report_date_str:
                report_dates.add(to_date(report_date_str))
        days = len(report_dates)
        days = days if days > 0 else 1

        # 从RUC1子集分组中提取成熟指标
        ruc1_sub = ruc1_grouped.get(key, [])
        ruc1_purchases = sum(int(r.get("purchase_users") or 0) for r in ruc1_sub)
        ruc1_renewals = sum(int(r.get("RUC1") or 0) for r in ruc1_sub)

        # 从RUC2子集分组中提取成熟指标
        ruc2_sub = ruc2_grouped.get(key, [])
        ruc2_purchases = sum(int(r.get("purchase_users") or 0) for r in ruc2_sub)
        ruc2_renewals = sum(int(r.get("RUC2") or 0) for r in ruc2_sub)

        # 从RUC3子集分组中提取成熟指标
        ruc3_sub = ruc3_grouped.get(key, [])
        ruc3_purchases = sum(int(r.get("purchase_users") or 0) for r in ruc3_sub)
        ruc3_renewals = sum(int(r.get("RUC3") or 0) for r in ruc3_sub)

        # 从RUC4子集分组中提取成熟指标
        ruc4_sub = ruc4_grouped.get(key, [])
        ruc4_purchases = sum(int(r.get("purchase_users") or 0) for r in ruc4_sub)
        ruc4_renewals = sum(int(r.get("RUC4") or 0) for r in ruc4_sub)

        # 从RUC5子集分组中提取成熟指标
        ruc5_sub = ruc5_grouped.get(key, [])
        ruc5_purchases = sum(int(r.get("purchase_users") or 0) for r in ruc5_sub)
        ruc5_renewals = sum(int(r.get("RUC5") or 0) for r in ruc5_sub)

        def safe_div(n: float, d: float, round_digits: int = 2) -> float | None:
            if not d:
                return None
            return round(n / d, round_digits)

        rrc1 = safe_div(ruc1_renewals, ruc1_purchases, 4)
        rrc2 = safe_div(ruc2_renewals, ruc2_purchases, 4)
        rrc3 = safe_div(ruc3_renewals, ruc3_purchases, 4)
        rrc4 = safe_div(ruc4_renewals, ruc4_purchases, 4)
        rrc5 = safe_div(ruc5_renewals, ruc5_purchases, 4)

        if purchase_users > 0:
            ltv = calculate_ltv(
                first_purchase_gross=first_purchase_gross,
                regular_period_gross=regular_period_gross,
                trial_days=trial_days,
                billing_period_days=billing_period_days,
                payback_days=payback_days,
                apple_fee=apple_fee,
                rrc1=rrc1,
                rrc2=rrc2,
                rrc3=rrc3,
                rrc4=rrc4,
                rrc5=rrc5
            )
            expected_rev = round(ltv * purchase_users, 2)
            payback_ratio = round(expected_rev / spend, 4) if spend > 0 else 0.0
            required_reduction = round(max(0.0, 1.0 - payback_ratio), 4)
        else:
            ltv = 0.0
            expected_rev = 0.0
            payback_ratio = 0.0
            required_reduction = 0.0

        target_cpi = safe_div(ltv * purchase_users, installs, 2) if purchase_users > 0 and installs > 0 and ltv > 0 else None

        g = {
            "ad_group_id": ad_group_id,
            "ad_group": first_row.get("ad_group"),
            "match_type": first_row.get("match_type"),
            "keyword": keyword,
            "keyword_status": first_row.get("keyword_status"),
            "days": days,
            "purchase_users": purchase_users,
            "RUC1": RUC1,
            "RUC2": RUC2,
            "RUC3": RUC3,
            "RUC4": RUC4,
            "RUC5": RUC5,
            "spend": round(spend, 2),
            "daily_spend": safe_div(spend, days),
            "CPS": safe_div(spend, purchase_users),
            "CPR1": safe_div(spend, RUC1),
            "RRC1": rrc1,
            "RRC2": rrc2,
            "RRC3": rrc3,
            "RRC4": rrc4,
            "RRC5": rrc5,
            "impressions": impressions,
            "clicks": clicks,
            "installs": installs,
            "CTR": safe_div(clicks, impressions, 4),
            "CIR": safe_div(installs, clicks, 4),
            "CVR": safe_div(purchase_users, clicks, 4),
            "CPC": safe_div(spend, clicks),
            "CPI": safe_div(spend, installs),
            "purchase_income": round(purchase_income, 2),
            "active_users": active_users,
            "RU15m": RU15m,
            "RU": RU,
            "ASR15m": safe_div(RU15m, purchase_users, 4),
            "ASR": safe_div(RU, purchase_users, 4),
            "RUC1_mature_purchases": ruc1_purchases,
            "RUC2_mature_purchases": ruc2_purchases,
            "RUC3_mature_purchases": ruc3_purchases,
            "RUC4_mature_purchases": ruc4_purchases,
            "RUC5_mature_purchases": ruc5_purchases,
            "payback_days": payback_days,
            "LTV_per_purchase_user": ltv,
            "expected_revenue": expected_rev,
            "payback_ratio": payback_ratio,
            "Target_CPI": target_cpi,
            "required_CPS_reduction": required_reduction,
        }
        out_rows.append(g)

    out_rows.sort(key=lambda x: x["spend"], reverse=True)
    return out_rows


def aggregate_cohort_slice(
    subset_rows: list[dict[str, Any]],
    renewal_field: str
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in subset_rows:
        key = (str(r.get("ad_group_id") or ""), str(r.get("keyword") or ""))
        grouped.setdefault(key, []).append(r)

    out = []
    for key, all_rows in grouped.items():
        ad_group_id, keyword = key
        first_row = all_rows[0]
        spend = sum(float(r.get("spend") or 0) for r in all_rows)
        impressions = sum(int(r.get("impressions") or 0) for r in all_rows)
        clicks = sum(int(r.get("clicks") or 0) for r in all_rows)
        installs = sum(int(r.get("installs") or 0) for r in all_rows)
        purchases = sum(int(r.get("purchase_users") or 0) for r in all_rows)
        renewals = sum(int(r.get(renewal_field) or 0) for r in all_rows)
        
        rrc = round(renewals / purchases, 4) if purchases else None
        
        out.append({
            "ad_group_id": ad_group_id,
            "ad_group": first_row.get("ad_group"),
            "match_type": first_row.get("match_type"),
            "keyword": keyword,
            "keyword_status": first_row.get("keyword_status"),
            "spend": round(spend, 2),
            "impressions": impressions,
            "clicks": clicks,
            "installs": installs,
            "purchases": purchases,
            "renewals": renewals,
            "RRC": rrc,
        })
    out.sort(key=lambda x: x["spend"], reverse=True)
    return out


def write_generic_csv(rows: list[dict[str, Any]], columns: list[str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_csv(rows: list[dict[str, Any]], path: Path) -> Path:
    return write_generic_csv(rows, COLUMNS, path)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fetch ASA keyword performance from BigQuery")
    p.add_argument("--bundle-id", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--start-date")
    p.add_argument("--credentials-file")
    p.add_argument("--target-currency", default="CNY")
    p.add_argument("--job-timeout-seconds", type=int, default=120)
    p.add_argument("--trial-days", type=int, default=7)
    p.add_argument("--billing-period-days", type=int, default=30)
    p.add_argument("--first-purchase-gross", type=float, default=0.0)
    p.add_argument("--regular-period-gross", type=float, default=0.0)
    p.add_argument("--apple-fee", type=float, default=0.15)
    p.add_argument("--payback-days", type=int, default=180)
    p.add_argument("--attribution-table")
    p.add_argument("--iap-table")
    return p


def main() -> int:
    try:
        args = parser().parse_args()
        if args.payback_days <= 0:
            raise AsaPerformanceError("--payback-days必须大于0")
        start_date = parse_date_arg(args.start_date)
        bq = client(credentials_path(args.credentials_file))
        
        attribution_table = args.attribution_table or f"{bq.project}.attribution_log_dataset._AllLogs"
        iap_table = args.iap_table or f"{bq.project}.iap_log_dataset._AllLogs"
        
        config = query_config(args.bundle_id, start_date, args)
        rates, rate_sources = resolve_rates(bq, args, config, attribution_table)
        
        sql = QUERY.format(
            attribution_table=attribution_table,
            iap_table=iap_table,
            spend_case=make_currency_case(rates, "bc.currency", "bc.spend"),
            purchase_income_case=make_currency_case(rates, "p.currency", "p.income"),
        )
        
        daily_rows = run(bq, sql, config, args.job_timeout_seconds)
        
        today_dt = datetime.now(timezone.utc).date()
        agg_rows = aggregate_daily_metrics(
            daily_rows,
            args.trial_days,
            args.billing_period_days,
            today_dt,
            first_purchase_gross=args.first_purchase_gross,
            regular_period_gross=args.regular_period_gross,
            apple_fee=args.apple_fee,
            payback_days=args.payback_days
        )
        
        output_path = Path(args.output).expanduser()
        csv_path = write_csv(agg_rows, output_path)
        
        # 准备分表路径
        parent = output_path.parent
        stem = output_path.stem
        suffix = output_path.suffix
        
        daily_path = parent / f"{stem}_daily{suffix}"
        ruc1_path = parent / f"{stem}_ruc1{suffix}"
        ruc2_path = parent / f"{stem}_ruc2{suffix}"
        ruc3_path = parent / f"{stem}_ruc3{suffix}"
        ruc4_path = parent / f"{stem}_ruc4{suffix}"
        ruc5_path = parent / f"{stem}_ruc5{suffix}"
        
        # 准备切片条件与数据
        ruc1_cutoff = renewal_cutoff_date(today_dt, args.trial_days, args.billing_period_days, 1)
        ruc2_cutoff = renewal_cutoff_date(today_dt, args.trial_days, args.billing_period_days, 2)
        ruc3_cutoff = renewal_cutoff_date(today_dt, args.trial_days, args.billing_period_days, 3)
        ruc4_cutoff = renewal_cutoff_date(today_dt, args.trial_days, args.billing_period_days, 4)
        ruc5_cutoff = renewal_cutoff_date(today_dt, args.trial_days, args.billing_period_days, 5)
        
        def to_date(val: Any) -> date:
            if isinstance(val, date):
                return val
            if isinstance(val, datetime):
                return val.date()
            return date.fromisoformat(str(val))
            
        ruc1_rows = [r for r in daily_rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc1_cutoff]
        ruc2_rows = [r for r in daily_rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc2_cutoff]
        ruc3_rows = [r for r in daily_rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc3_cutoff]
        ruc4_rows = [r for r in daily_rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc4_cutoff]
        ruc5_rows = [r for r in daily_rows if r.get("report_date") and to_date(r.get("report_date")) <= ruc5_cutoff]
        
        # 生成分表数据
        ruc1_report = aggregate_cohort_slice(ruc1_rows, "RUC1")
        ruc2_report = aggregate_cohort_slice(ruc2_rows, "RUC2")
        ruc3_report = aggregate_cohort_slice(ruc3_rows, "RUC3")
        ruc4_report = aggregate_cohort_slice(ruc4_rows, "RUC4")
        ruc5_report = aggregate_cohort_slice(ruc5_rows, "RUC5")
        
        # 按 report_date 降序，spend 降序排序日表数据
        sorted_daily_rows = sorted(
            daily_rows,
            key=lambda x: (
                str(x.get("report_date") or ""),
                float(x.get("spend") or 0.0)
            ),
            reverse=True
        )
        
        # 写入分表
        write_generic_csv(sorted_daily_rows, DAILY_COLUMNS, daily_path)
        write_generic_csv(ruc1_report, COHORT_COLUMNS, ruc1_path)
        write_generic_csv(ruc2_report, COHORT_COLUMNS, ruc2_path)
        write_generic_csv(ruc3_report, COHORT_COLUMNS, ruc3_path)
        write_generic_csv(ruc4_report, COHORT_COLUMNS, ruc4_path)
        write_generic_csv(ruc5_report, COHORT_COLUMNS, ruc5_path)
        
        print(json.dumps({
            "ok": True,
            "csv_output": str(csv_path),
            "split_outputs": {
                "daily": str(daily_path),
                "ruc1": str(ruc1_path),
                "ruc2": str(ruc2_path),
                "ruc3": str(ruc3_path),
                "ruc4": str(ruc4_path),
                "ruc5": str(ruc5_path)
            },
            "row_count": len(agg_rows),
            "payback_days": args.payback_days
        }, ensure_ascii=False))
        return 0
    except Exception as exc:
        return fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
