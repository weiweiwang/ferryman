from __future__ import annotations

from typing import Any

from screen_stock_common import (
    MIN_FINANCIAL_YEARS,
    MarketSnapshot,
    is_industry_review_required,
    mean,
    normalize_currency,
    round_or_none,
    safe_ratio,
    stdev,
    to_float,
)


def complete_financial_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    required = ("net_profit", "operating_cash_flow", "free_cash_flow")
    return [row for row in rows if all(row.get(field) is not None for field in required)]


def financial_currency(rows: list[dict[str, Any]], default_currency: str) -> str:
    for row in rows:
        currency = row.get("currency")
        if currency:
            return normalize_currency(currency, default_currency)
    return default_currency


def compute_metrics(
    snapshot: MarketSnapshot,
    financial_rows: list[dict[str, Any]],
    risk_free: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    data_gaps: list[str] = []
    rows = financial_rows
    complete_rows = complete_financial_rows(rows)[:MIN_FINANCIAL_YEARS]
    if len(complete_rows) < MIN_FINANCIAL_YEARS:
        data_gaps.append("missing_5y_financial_rows")

    net_profits = [to_float(row.get("net_profit")) for row in complete_rows]
    operating_cash_flows = [to_float(row.get("operating_cash_flow")) for row in complete_rows]
    free_cash_flows = [to_float(row.get("free_cash_flow")) for row in complete_rows]
    roe_values = [to_float(row.get("roe")) for row in complete_rows]
    roic_values = [to_float(row.get("roic")) for row in complete_rows]
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


def classify_candidate(
    snapshot: MarketSnapshot,
    metrics: dict[str, Any],
    data_gaps: list[str],
    initial_reject_reasons: list[str],
) -> tuple[str, list[str]]:
    reject_reasons = list(initial_reject_reasons)
    if reject_reasons:
        return "REJECTED", sorted(set(reject_reasons))

    if is_industry_review_required(snapshot.industry):
        data_gaps.append("industry_review_required")
        return "INDUSTRY_REVIEW_REQUIRED", []

    complete_years = metrics.get("complete_financial_years") or 0
    if complete_years < MIN_FINANCIAL_YEARS:
        return "INSUFFICIENT_DATA", []

    if metrics.get("avg_net_profit_5y") is not None and metrics["avg_net_profit_5y"] <= 0:
        reject_reasons.append("non_positive_profit")
    if metrics.get("avg_fcf_5y") is not None and metrics["avg_fcf_5y"] <= 0:
        reject_reasons.append("non_positive_fcf")
    if metrics.get("ocf_to_profit") is not None and metrics["ocf_to_profit"] < 0.5:
        reject_reasons.append("weak_ocf_conversion")
    if metrics.get("goodwill_to_equity") is not None and metrics["goodwill_to_equity"] > 0.5:
        reject_reasons.append("high_goodwill")

    if reject_reasons:
        return "REJECTED", sorted(set(reject_reasons))

    return "CANDIDATE", []


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
    if not snapshot.industry:
        data_gaps.append("industry_unavailable")
    if fin_currency != snapshot.currency:
        metrics["market_cap_to_avg_profit"] = None
        metrics["market_cap_to_avg_fcf"] = None
        data_gaps.append("fx_conversion_required")
    status, final_reject_reasons = classify_candidate(
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
        "metrics": metrics,
        "reject_reasons": final_reject_reasons,
        "data_gaps": sorted(set(data_gaps)),
        "source": snapshot.source,
    }


def refresh_result_item_contract(item: dict[str, Any], *, min_market_cap: float) -> dict[str, Any]:
    """Reclassify checkpointed rows with the current screener contract."""
    metrics = dict(item.get("metrics") or {})
    market_cap_rank = to_float(item.get("market_cap_rank"))
    snapshot = MarketSnapshot(
        ticker=str(item.get("ticker") or ""),
        code=str(item.get("ticker") or "").split(".")[0],
        name=str(item.get("name") or ""),
        market=str(item.get("market") or ""),
        currency=str(item.get("currency") or ""),
        price=to_float(item.get("price")),
        pe=to_float(metrics.get("pe")),
        pb=to_float(metrics.get("pb")),
        market_cap=to_float(item.get("market_cap")),
        float_market_cap=None,
        industry=item.get("industry"),
        market_cap_rank=int(market_cap_rank) if market_cap_rank is not None else None,
        market_cap_percentile=to_float(item.get("market_cap_percentile")),
        source=str(item.get("source") or "eastmoney"),
    )
    data_gaps = list(item.get("data_gaps") or [])
    reject_reasons = quick_reject_reasons(snapshot, min_market_cap)
    status, final_reject_reasons = classify_candidate(snapshot, metrics, data_gaps, reject_reasons)
    removed_fields = {
        "quality_score",
        "valuation_score",
        "screen_score",
        "quality_flags",
        "valuation_flags",
    }
    refreshed = {key: value for key, value in item.items() if key not in removed_fields}
    refreshed["status"] = status
    refreshed["metrics"] = metrics
    refreshed["reject_reasons"] = final_reject_reasons
    refreshed["data_gaps"] = sorted(set(data_gaps))
    return refreshed


def sort_results(results: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    if sort_by == "expected_return":
        return sorted(
            results,
            key=lambda item: (
                (item.get("metrics") or {}).get("expected_return") is not None,
                (item.get("metrics") or {}).get("expected_return") or 0,
            ),
            reverse=True,
        )
    return sorted(results, key=lambda item: item.get("market_cap") or 0, reverse=True)


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
        "metrics": {"pe": snapshot.pe, "pb": snapshot.pb, "complete_financial_years": 0},
        "reject_reasons": quick_reject_reasons(snapshot, min_market_cap),
        "data_gaps": ["financial_fetch_failed"],
        "error_phase": "financial_rows",
        "error": error,
        "source": snapshot.source,
    }
