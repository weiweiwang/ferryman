#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATHS = (
    SKILL_DIR / "assets" / "report-template.md",
    SKILL_DIR / "assets" / "blocked-data-template.md",
)
TAXONOMY_PATH = SKILL_DIR / "references" / "taxonomy.md"
ALLOWED_SIGNALS = {"STRONG_BUY", "BUY", "WATCHLIST", "AVOID"}
ALLOWED_EVIDENCE_CLASSES = {"required", "material", "non_critical"}
ALLOWED_EVIDENCE_STATES = {"verified", "verified_adverse", "not_applicable", "unresolved"}
ALLOWED_REPORT_LANGUAGES = {"zh", "en"}
ALLOWED_ANCHOR_FAMILIES = {
    "normalized_fcf",
    "normalized_eps",
    "reverse_dcf",
    "segment_sotp",
    "net_assets",
}
TAG_GROUPS = ("market", "sector", "industry", "theme")
COMPLETION_CHECK_IDS = {
    "current_price",
    "share_count",
    "financial_currency",
    "quote_currency",
    "five_year_revenue",
    "five_year_net_profit",
    "five_year_ocf",
    "five_year_capex",
    "five_year_fcf",
    "five_year_cash",
    "five_year_debt",
    "risk_free_rate",
    "required_citations",
}
MANAGEMENT_CHECK_IDS = {
    "shareholder_alignment",
    "capital_allocation",
    "incentives_dilution",
    "accounting_quality",
    "governance_related_parties",
}
THESIS_CHECK_IDS = {
    "abnormal_normalization",
    "repeatable_fcf",
    "shareholder_return",
    "hidden_liabilities",
    "receivables_inventory_goodwill",
    "segment_economics",
    "management_outlook",
    "financial_asset_composition",
    "mispricing_explanation",
    "normalized_fcf_anchor",
    "non_fcf_cross_check",
    "avoid_failure",
}
MANDATORY_CHECK_IDS = COMPLETION_CHECK_IDS | MANAGEMENT_CHECK_IDS | THESIS_CHECK_IDS
RELATIVE_YEAR_LABELS = (
    "最近完整财年",
    "前1个完整财年",
    "前2个完整财年",
    "前3个完整财年",
    "前4个完整财年",
)
INTERNAL_TERM_PATTERN = re.compile(
    r"stock-research|Stock Research|股票研究|数据脚本|fetch_.*\.py|POST|"
    r"hisAnnouncement/query|orgId|secCode|gssz|gssh|dataLimits|fxRate"
)
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


def template_placeholders() -> set[str]:
    text = "\n".join(path.read_text(encoding="utf-8") for path in TEMPLATE_PATHS)
    return set(re.findall(r"\[[^\]\n]+\]", text))


def taxonomy() -> dict[str, set[str]]:
    result = {group: set() for group in TAG_GROUPS}
    current: str | None = None
    for line in TAXONOMY_PATH.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(market|sector|industry|theme)\s*$", line)
        if heading:
            current = heading.group(1)
            continue
        if current and line.startswith("- "):
            result[current].add(line[2:].strip())
    return result


def split_frontmatter(markdown: str) -> tuple[dict[str, Any] | None, str]:
    if not markdown.startswith("---\n"):
        return None, markdown
    end = markdown.find("\n---", 4)
    if end < 0:
        raise ValueError("frontmatter is not closed")
    data = yaml.safe_load(markdown[4:end])
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a YAML mapping")
    return data, markdown[end + 4 :].lstrip("\n")


def positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def nested(data: dict[str, Any], parent: str, child: str) -> Any:
    value = data.get(parent)
    return value.get(child) if isinstance(value, dict) else None


def common_text_errors(markdown: str) -> list[str]:
    errors: list[str] = []
    leaked = sorted(placeholder for placeholder in template_placeholders() if placeholder in markdown)
    if leaked:
        errors.append(f"unreplaced template placeholders: {', '.join(leaked)}")
    relative_years = [label for label in RELATIVE_YEAR_LABELS if label in markdown]
    if relative_years:
        errors.append(f"relative fiscal-year labels remain: {', '.join(relative_years)}")
    internal = INTERNAL_TERM_PATTERN.search(markdown)
    if internal:
        errors.append(f"internal implementation term leaked: {internal.group(0)}")
    return errors


def validate_tags(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tags = data.get("tags")
    if not isinstance(tags, dict):
        return ["tags must be a mapping with market, sector, industry, and theme arrays"]
    allowed = taxonomy()
    for group in TAG_GROUPS:
        values = tags.get(group)
        if not isinstance(values, list):
            errors.append(f"tags.{group} must be an array")
            continue
        unknown = [str(value) for value in values if str(value) not in allowed[group]]
        if unknown:
            errors.append(f"tags.{group} contains unknown values: {', '.join(unknown)}")
    extra = sorted(set(tags) - set(TAG_GROUPS))
    if extra:
        errors.append(f"tags contains unsupported groups: {', '.join(extra)}")
    return errors


def evidence_note_path(report_path: Path) -> Path:
    name = report_path.name
    if name.startswith("stock-audit-") and name.endswith(".md"):
        name = f"evidence-{name[len('stock-audit-'):-3]}.yaml"
    else:
        name = f"{report_path.stem}.evidence.yaml"
    return report_path.with_name(name)


def load_evidence_note(report_path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    path = evidence_note_path(report_path)
    if not path.exists():
        return None, [f"missing evidence sidecar: {path.name}"]
    try:
        note = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, [f"invalid evidence sidecar YAML: {exc}"]
    if not isinstance(note, dict):
        return None, ["evidence sidecar must be a YAML mapping"]
    return note, []


def valid_source_urls(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(url, str) and URL_PATTERN.match(url) for url in value
    )


def validate_check(check_id: str, check: Any) -> list[str]:
    prefix = f"evidence check {check_id}"
    if not isinstance(check, dict):
        return [f"{prefix} must be a mapping"]
    errors: list[str] = []
    evidence_class = check.get("class")
    state = check.get("state")
    if evidence_class not in ALLOWED_EVIDENCE_CLASSES:
        errors.append(f"{prefix}.class must be one of: {', '.join(sorted(ALLOWED_EVIDENCE_CLASSES))}")
    if state not in ALLOWED_EVIDENCE_STATES:
        errors.append(f"{prefix}.state must be one of: {', '.join(sorted(ALLOWED_EVIDENCE_STATES))}")
    if state in {"verified", "verified_adverse"} and not valid_source_urls(check.get("source_urls")):
        errors.append(f"{prefix} in state {state} requires at least one http(s) source URL")
    if state == "not_applicable" and not str(check.get("rationale") or "").strip():
        errors.append(f"{prefix} in state not_applicable requires a rationale")
    if state == "unresolved" and not str(check.get("gap") or "").strip():
        errors.append(f"{prefix} in state unresolved requires a gap description")
    return errors


def expected_publication_gate(checks: dict[str, Any]) -> bool:
    if not MANDATORY_CHECK_IDS.issubset(checks):
        return False
    if any(
        not isinstance(checks.get(check_id), dict) or checks[check_id].get("state") != "verified"
        for check_id in COMPLETION_CHECK_IDS
    ):
        return False
    if any(
        not isinstance(checks.get(check_id), dict)
        or checks[check_id].get("state") not in {"verified", "verified_adverse"}
        for check_id in MANAGEMENT_CHECK_IDS
    ):
        return False
    for check in checks.values():
        if not isinstance(check, dict):
            return False
        if check.get("class") in {"required", "material"} and check.get("state") == "unresolved":
            return False
    return True


def check_is_verified(checks: dict[str, Any], check_id: str) -> bool:
    check = checks.get(check_id)
    return isinstance(check, dict) and check.get("state") == "verified"


def has_unresolved_non_critical(checks: dict[str, Any]) -> bool:
    return any(
        isinstance(check, dict)
        and check.get("class") == "non_critical"
        and check.get("state") == "unresolved"
        for check in checks.values()
    )


def validate_valuation_anchors(note: dict[str, Any]) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    anchors = note.get("valuation_anchors")
    if not isinstance(anchors, list) or not anchors:
        return ["evidence sidecar requires at least one valuation anchor"], set()
    supporting_families: set[str] = set()
    for index, anchor in enumerate(anchors):
        prefix = f"valuation_anchors[{index}]"
        if not isinstance(anchor, dict):
            errors.append(f"{prefix} must be a mapping")
            continue
        family = str(anchor.get("family") or "").strip()
        if family not in ALLOWED_ANCHOR_FAMILIES:
            errors.append(f"{prefix}.family must be one of: {', '.join(sorted(ALLOWED_ANCHOR_FAMILIES))}")
        if not isinstance(anchor.get("supports_2x"), bool):
            errors.append(f"{prefix}.supports_2x must be boolean")
        if not valid_source_urls(anchor.get("source_urls")):
            errors.append(f"{prefix} requires at least one http(s) source URL")
        if family and anchor.get("supports_2x") is True:
            supporting_families.add(family)
    return errors, supporting_families


def signal_from_contract(
    signal: Any,
    quality_score: Any,
    current_price: Any,
    fair_values: dict[str, float],
    gates: dict[str, Any],
    checks: dict[str, Any],
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    if not positive_number(quality_score) or not positive_number(current_price):
        return None, errors
    if not {"base", "conservative"}.issubset(fair_values):
        return None, errors
    base_ratio = float(current_price) / fair_values["base"]
    conservative_ratio = float(current_price) / fair_values["conservative"]
    avoid_failure = checks.get("avoid_failure")
    has_avoid_failure = isinstance(avoid_failure, dict) and avoid_failure.get("state") == "verified_adverse"
    strong = (
        quality_score >= 80
        and base_ratio <= 0.50
        and conservative_ratio <= 0.85
        and gates.get("strong_buy_evidence") is True
        and not has_avoid_failure
    )
    buy = (
        quality_score >= 75
        and base_ratio <= 0.70
        and conservative_ratio <= 1.00
        and gates.get("buy_evidence") is True
        and not has_avoid_failure
    )
    if strong:
        expected = "STRONG_BUY"
    elif buy:
        expected = "BUY"
    elif quality_score < 65 or has_avoid_failure:
        expected = "AVOID"
    else:
        expected = "WATCHLIST"
    if signal != expected:
        errors.append(f"signal {signal} violates the decision table; expected {expected}")
    return expected, errors


def validate_evidence_note(
    note: dict[str, Any],
    data: dict[str, Any],
    body: str,
    current_price: Any,
    fair_values: dict[str, float],
) -> list[str]:
    errors: list[str] = []
    if note.get("version") != 1:
        errors.append("evidence sidecar version must be 1")
    language = note.get("report_language")
    if language not in ALLOWED_REPORT_LANGUAGES:
        errors.append("evidence sidecar report_language must be zh or en")
    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = title_match.group(1) if title_match else ""
    if language == "en" and "Investment Quality Review" not in title:
        errors.append("English evidence sidecar requires an English Investment Quality Review title")
    if language == "zh" and "投资质量评估" not in title:
        errors.append("Chinese evidence sidecar requires a Chinese 投资质量评估 title")
    if str(note.get("ticker")) != str(data.get("ticker")):
        errors.append("evidence sidecar ticker must match report ticker")
    if str(note.get("report_date")) != str(data.get("report_date")):
        errors.append("evidence sidecar report_date must match report report_date")

    checks = note.get("checks")
    if not isinstance(checks, dict):
        return errors + ["evidence sidecar checks must be a mapping"]
    missing = sorted(MANDATORY_CHECK_IDS - set(checks))
    if missing:
        errors.append(f"evidence sidecar missing mandatory checks: {', '.join(missing)}")
    for check_id, check in checks.items():
        errors.extend(validate_check(str(check_id), check))
    wrong_completion_classes = sorted(
        check_id
        for check_id in COMPLETION_CHECK_IDS
        if isinstance(checks.get(check_id), dict) and checks[check_id].get("class") != "required"
    )
    if wrong_completion_classes:
        errors.append(f"completion checks must use class required: {', '.join(wrong_completion_classes)}")
    wrong_management_classes = sorted(
        check_id
        for check_id in MANAGEMENT_CHECK_IDS
        if isinstance(checks.get(check_id), dict) and checks[check_id].get("class") != "material"
    )
    if wrong_management_classes:
        errors.append(f"management/accounting checks must use class material: {', '.join(wrong_management_classes)}")

    gates = note.get("gates")
    if not isinstance(gates, dict):
        return errors + ["evidence sidecar gates must be a mapping"]
    for gate in ("publication", "buy_evidence", "strong_buy_evidence"):
        if not isinstance(gates.get(gate), bool):
            errors.append(f"evidence sidecar gates.{gate} must be boolean")

    publication = expected_publication_gate(checks)
    if gates.get("publication") is not publication:
        errors.append(f"gates.publication must be {str(publication).lower()} from evidence states")
    if not publication:
        errors.append("a stock-audit report requires a true Publication Gate; output blocked-data instead")

    expected_buy_gate = (
        publication
        and not has_unresolved_non_critical(checks)
        and check_is_verified(checks, "mispricing_explanation")
        and check_is_verified(checks, "normalized_fcf_anchor")
        and check_is_verified(checks, "non_fcf_cross_check")
        and not (
            isinstance(checks.get("avoid_failure"), dict)
            and checks["avoid_failure"].get("state") == "verified_adverse"
        )
    )
    if gates.get("buy_evidence") is not expected_buy_gate:
        errors.append(f"gates.buy_evidence must be {str(expected_buy_gate).lower()} from evidence states")

    anchor_errors, supporting_families = validate_valuation_anchors(note)
    errors.extend(anchor_errors)
    management_verified = all(check_is_verified(checks, check_id) for check_id in MANAGEMENT_CHECK_IDS)
    material_adverse = any(
        isinstance(check, dict)
        and check.get("class") == "material"
        and check.get("state") == "verified_adverse"
        for check in checks.values()
    )
    expected_strong_gate = (
        expected_buy_gate
        and management_verified
        and "normalized_fcf" in supporting_families
        and len(supporting_families) >= 2
        and not material_adverse
    )
    if gates.get("strong_buy_evidence") is not expected_strong_gate:
        errors.append(f"gates.strong_buy_evidence must be {str(expected_strong_gate).lower()} from evidence states")

    expected_signal, signal_errors = signal_from_contract(
        data.get("signal"),
        data.get("quality_score"),
        current_price,
        fair_values,
        gates,
        checks,
    )
    errors.extend(signal_errors)
    decision = note.get("signal_decision")
    if not isinstance(decision, dict):
        errors.append("evidence sidecar signal_decision must be a mapping")
    else:
        if decision.get("selected") != data.get("signal") or decision.get("selected") != expected_signal:
            errors.append("signal_decision.selected must match the report and computed decision-table signal")
        reasons = decision.get("reasons")
        if not isinstance(reasons, list) or not reasons or not all(str(reason).strip() for reason in reasons):
            errors.append("signal_decision.reasons must contain at least one non-empty reason")

    if language == "en":
        cjk_count = len(re.findall(r"[\u3400-\u9fff]", body))
        body_chars = max(1, len(re.sub(r"\s+", "", body)))
        if cjk_count > max(20, int(body_chars * 0.02)):
            errors.append(f"English report contains excessive Chinese text: {cjk_count} CJK characters")
    return errors


def validate_stock_audit(
    data: dict[str, Any],
    body: str,
    markdown: str,
    report_path: Path,
) -> list[str]:
    errors = common_text_errors(markdown)
    for key in ("ticker", "exchange", "report_date", "fetched_at", "signal", "summary"):
        if data.get(key) in (None, "", "N/A"):
            errors.append(f"missing required frontmatter field: {key}")

    company = data.get("company")
    if not isinstance(company, dict) or not any(company.get(key) for key in ("zh", "en")):
        errors.append("company must contain at least one of company.zh or company.en")

    quality_score = data.get("quality_score")
    if not positive_number(quality_score) or quality_score > 100:
        errors.append("quality_score must be an unquoted number greater than 0 and at most 100")

    current_price = nested(data, "current_price", "value")
    if not positive_number(current_price):
        errors.append("current_price.value must be a positive unquoted number")
    if not nested(data, "current_price", "currency"):
        errors.append("current_price.currency is required")

    fair_values: dict[str, float] = {}
    for scenario in ("conservative", "base", "optimistic"):
        value = nested(data, "fair_value", scenario)
        if not positive_number(value):
            errors.append(f"fair_value.{scenario} must be a positive unquoted number")
        else:
            fair_values[scenario] = float(value)
    if not nested(data, "fair_value", "currency"):
        errors.append("fair_value.currency is required")

    signal = data.get("signal")
    if signal not in ALLOWED_SIGNALS:
        errors.append(f"signal must be one of: {', '.join(sorted(ALLOWED_SIGNALS))}")
    errors.extend(validate_tags(data))
    if len(re.findall(r"^##\s+", body, re.MULTILINE)) < 6:
        errors.append("stock-audit report must contain at least six level-two sections")
    if not re.search(r"https?://", body):
        errors.append("stock-audit report must contain at least one citation URL")
    if "不是个性化投资建议" not in body and "not personalized investment advice" not in body.lower():
        errors.append("research-only, not-personalized-investment-advice disclaimer is required")

    note, note_errors = load_evidence_note(report_path)
    errors.extend(note_errors)
    if note is not None:
        errors.extend(validate_evidence_note(note, data, body, current_price, fair_values))
    return errors


def section_text(body: str, headings: tuple[str, ...]) -> str | None:
    alternatives = "|".join(re.escape(heading) for heading in headings)
    match = re.search(rf"^##\s+(?:{alternatives})\s*$\n(.*?)(?=^##\s+|\Z)", body, re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else None


def table_data_rows(section: str) -> list[list[str]]:
    table_lines = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 3:
        return []
    rows: list[list[str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if any(cell and cell not in {"-", "—"} for cell in cells):
            rows.append(cells)
    return rows


def has_concrete_gap_row(section: str) -> bool:
    return any(sum(bool(cell and cell not in {"-", "—"}) for cell in row) >= 2 for row in table_data_rows(section))


def has_source_row_with_url(section: str) -> bool:
    return any(
        any(URL_PATTERN.match(cell) for cell in row)
        and any(cell and not URL_PATTERN.match(cell) and cell not in {"-", "—"} for cell in row)
        for row in table_data_rows(section)
    )


def labeled_value(body: str, labels: tuple[str, ...]) -> str | None:
    alternatives = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"^\*\*(?:{alternatives})\*\*[:：]\s*(.+)$", body, re.MULTILINE)
    return match.group(1).strip() if match else None


def validate_blocked_data(body: str, markdown: str) -> list[str]:
    errors = common_text_errors(markdown)
    if not re.search(r"^#\s+(?:数据缺口清单|Data Gap Checklist)\s*[（(].+?[）)]\s*$", body, re.MULTILINE):
        errors.append("blocked-data checklist requires a localized title with ticker")
    for labels, field in (
        (("公司", "Company"), "company"),
        (("数据时间", "Data time"), "data time"),
        (("阻塞原因", "Blocking reason"), "blocking reason"),
    ):
        value = labeled_value(body, labels)
        if not value:
            errors.append(f"blocked-data checklist requires a non-empty {field}")

    missing_section = section_text(body, ("缺失项", "Missing Items"))
    sources_section = section_text(body, ("已查来源", "Sources Checked"))
    next_section = section_text(body, ("下一步", "Next Steps"))
    if missing_section is None:
        errors.append("blocked-data checklist requires a Missing Items section")
    elif not has_concrete_gap_row(missing_section):
        errors.append("Missing Items must contain a table with at least one concrete gap row")
    if sources_section is None:
        errors.append("blocked-data checklist requires a Sources Checked section")
    else:
        if not table_data_rows(sources_section):
            errors.append("Sources Checked must contain a table with at least one source row")
        if not has_source_row_with_url(sources_section):
            errors.append("Sources Checked must contain at least one concrete source row with a URL")
    if next_section is None or not re.search(r"^[-*]\s+\S", next_section, re.MULTILINE):
        errors.append("blocked-data checklist requires at least one concrete next-step bullet")

    forbidden_patterns = {
        "signal": r"(?:^|\n)\s*signal\s*:|\*\*(?:最终信号|Current signal)\*\*",
        "quality score": r"(?:^|\n)\s*quality_score\s*:|\*\*(?:质量评分|Quality score)\*\*",
        "fair value": r"(?:^|\n)\s*fair_value\s*:|\*\*(?:公允价值|Fair value)\*\*",
        "valuation ratio": r"\*\*(?:估值位置|Valuation position)\*\*|现价/基准FV",
        "action price": r"\*\*(?:行动价格|Action price)\*\*",
    }
    leaked = [label for label, pattern in forbidden_patterns.items() if re.search(pattern, body, re.IGNORECASE)]
    if leaked:
        errors.append(f"blocked-data checklist contains report-only fields: {', '.join(leaked)}")
    return errors


def validate_path(path: Path) -> list[str]:
    markdown = path.read_text(encoding="utf-8")
    try:
        data, body = split_frontmatter(markdown)
    except (ValueError, yaml.YAMLError) as exc:
        return [str(exc)]
    if data is None:
        return validate_blocked_data(body, markdown)
    return validate_stock_audit(data, body, markdown, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a stock-research report before publication.")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    failed = False
    for path in args.paths:
        errors = validate_path(path)
        if errors:
            failed = True
            for error in errors:
                print(f"{path}: {error}")
        else:
            print(f"OK {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
