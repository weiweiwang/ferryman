import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT_DIR = SKILL_DIR / "scripts"
FETCH_SCRIPT = SCRIPT_DIR / "fetch_asa_bigquery_report.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_asa_bigquery_report", FETCH_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_start_date_uses_current_date_minus_60_days():
    module = load_module()

    start_date = module.default_start_date(today=date(2026, 5, 22))

    assert start_date == date(2026, 3, 23)


def test_credentials_resolution_prefers_cli_over_env(tmp_path, monkeypatch):
    module = load_module()
    cli_path = tmp_path / "cli.json"
    env_path = tmp_path / "env.json"
    cli_path.write_text("{}", encoding="utf-8")
    env_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ASA_BIGQUERY_SERVICE_ACCOUNT_JSON", str(env_path))

    assert module.credentials_path(str(cli_path)) == cli_path


def test_credentials_resolution_reads_environment(tmp_path, monkeypatch):
    module = load_module()
    env_path = tmp_path / "env.json"
    env_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ASA_BIGQUERY_SERVICE_ACCOUNT_JSON", str(env_path))

    assert module.credentials_path(None) == env_path


def test_main_query_is_single_cte_template_without_rule_engine():
    module = load_module()

    query = module.QUERY.format(
        attribution_table="singular-silo-438306-v6.attribution_log_dataset._AllLogs",
        iap_table="singular-silo-438306-v6.iap_log_dataset._AllLogs",
        spend_case=module.make_currency_case({"CNY": 1.0}, "bc.currency", "bc.spend"),
        purchase_income_case=module.make_currency_case({"CNY": 1.0}, "p.currency", "p.income"),
    )

    assert len(re.findall(r"^WITH$", query, flags=re.MULTILINE)) == 1
    assert "first_opens AS" in query
    assert "keyword_attributions AS" in query
    assert "keyword_costs AS" in query
    assert "suggestion" not in query


def test_hourly_costs_are_aggregated_before_daily_attribution_join():
    module = load_module()

    query = module.QUERY.format(
        attribution_table="singular-silo-438306-v6.attribution_log_dataset._AllLogs",
        iap_table="singular-silo-438306-v6.iap_log_dataset._AllLogs",
        spend_case=module.make_currency_case({"CNY": 1.0}, "bc.currency", "bc.spend"),
        purchase_income_case=module.make_currency_case({"CNY": 1.0}, "p.currency", "p.income"),
    )

    assert "FROM keyword_costs kc\nLEFT JOIN keyword_attributions ka" in query
    assert "SUM(bc.impressions) AS impressions" in query


def test_date_window_uses_only_final_report_date_start_filter():
    module = load_module()

    query = module.QUERY.format(
        attribution_table="singular-silo-438306-v6.attribution_log_dataset._AllLogs",
        iap_table="singular-silo-438306-v6.iap_log_dataset._AllLogs",
        spend_case=module.make_currency_case({"CNY": 1.0}, "bc.currency", "bc.spend"),
        purchase_income_case=module.make_currency_case({"CNY": 1.0}, "p.currency", "p.income"),
    )

    assert "@end_date" not in query
    assert "@end_timestamp" not in query
    assert "@start_timestamp" not in query
    assert 'timestamp >= TIMESTAMP(COALESCE(@start_date, DATE_SUB(CURRENT_DATE("UTC"), INTERVAL 60 DAY)), "UTC")' in query


def test_make_currency_case_generation():
    module = load_module()

    case_sql = module.make_currency_case({"CNY": 1.0, "USD": 7.2, "EUR": 7.8}, "bc.currency", "bc.spend")

    assert 'WHEN bc.currency = "USD" THEN bc.spend * 7.2000000000' in case_sql
    assert 'WHEN bc.currency = "EUR" THEN bc.spend * 7.8000000000' in case_sql
    assert 'WHEN bc.currency = "CNY" THEN bc.spend * 1.0000000000' in case_sql


def test_parser_exposes_only_business_inputs():
    module = load_module()
    help_text = module.parser().format_help()

    assert "--bundle-id" in help_text
    assert "--output" in help_text
    assert "--start-date" in help_text
    assert "--credentials-file" in help_text
    assert "--trial-days" in help_text
    assert "--billing-period-days" in help_text
    assert "--payback-days" in help_text
    assert "--target-cps" not in help_text
    assert "--csv-output" not in help_text
    assert "--project-id" not in help_text
    assert "--attribution-table" in help_text
    assert "--iap-table" in help_text
    assert "--currency-rate" not in help_text
    assert "--exchange-rate-source" not in help_text
    assert "--target-cpr1" not in help_text
    assert "--format" not in help_text
    assert "--include-all-rows" not in help_text


def test_output_argument_is_required():
    module = load_module()

    args = module.parser().parse_args(["--bundle-id", "app.blynkai.todo", "--output", "reports/out.csv"])

    assert args.bundle_id == "app.blynkai.todo"
    assert args.output == "reports/out.csv"

    try:
        module.parser().parse_args(["--bundle-id", "app.blynkai.todo"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("Expected --output to be required")


def test_auto_exchange_rates_use_yfinance(monkeypatch):
    module = load_module()
    calls = []

    class FakeHistory:
        empty = False

        def __getitem__(self, key):
            assert key == "Close"
            return self

        def dropna(self):
            return self

        @property
        def iloc(self):
            return [7.1234]

    class FakeTicker:
        def __init__(self, symbol):
            calls.append(symbol)

        def history(self, period):
            assert period == "5d"
            return FakeHistory()

    monkeypatch.setattr(module.yf, "Ticker", FakeTicker)

    rate, source = module.fx_rate("USD", "CNY")

    assert calls == ["USDCNY=X"]
    assert rate == 7.1234
    assert source == "yfinance:USDCNY=X"


def test_main_query_locks_environment_to_production():
    module = load_module()

    query = module.QUERY.format(
        attribution_table="singular-silo-438306-v6.attribution_log_dataset._AllLogs",
        iap_table="singular-silo-438306-v6.iap_log_dataset._AllLogs",
        spend_case=module.make_currency_case({"CNY": 1.0, "USD": 7.2}, "bc.currency", "bc.spend"),
        purchase_income_case=module.make_currency_case({"CNY": 1.0, "USD": 7.2}, "p.currency", "p.income"),
    )

    assert 'params.environment) = "production"' in query
    assert "@environment" not in query


def test_cli_errors_are_structured_json_without_credentials(monkeypatch):
    env = os.environ.copy()
    env.pop("ASA_BIGQUERY_SERVICE_ACCOUNT_JSON", None)
    env.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    result = subprocess.run(
        [
            sys.executable,
            str(FETCH_SCRIPT),
            "--bundle-id",
            "app.blynkai.todo",
            "--output",
            "reports/test.csv",
            "--start-date",
            "2026-04-22",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "AsaPerformanceError"
    assert "service account JSON" in payload["error"]["message"]


def test_resolve_rates_initializes_with_target_currency_usd(monkeypatch):
    module = load_module()

    # Mock the database run function
    def mock_run(client_, sql, config, timeout):
        return [{"currency": "CNY"}, {"currency": "EUR"}, {"currency": "USD"}]

    # Mock the fx_rate function
    fx_calls = []
    def mock_fx_rate(currency, target):
        fx_calls.append((currency, target))
        if currency == "CNY":
            return 0.14, "mock:CNYUSD"
        if currency == "EUR":
            return 1.08, "mock:EURUSD"
        return 1.0, "mock:identity"

    monkeypatch.setattr(module, "run", mock_run)
    monkeypatch.setattr(module, "fx_rate", mock_fx_rate)

    class FakeArgs:
        target_currency = "USD"
        job_timeout_seconds = 10

    rates, sources = module.resolve_rates(None, FakeArgs(), None, "fake_table")

    # USD is target, CNY and EUR should be fetched.
    # USD should be target, so USD is not fetched since target in rates is initialized to 1.0.
    assert rates == {"USD": 1.0, "CNY": 0.14, "EUR": 1.08}
    assert sources == {"USD": "identity", "CNY": "mock:CNYUSD", "EUR": "mock:EURUSD"}
    assert ("CNY", "USD") in fx_calls
    assert ("EUR", "USD") in fx_calls
    assert ("USD", "USD") not in fx_calls


def test_resolve_rates_initializes_with_target_currency_cny(monkeypatch):
    module = load_module()

    # Mock database run to return CNY and RMB
    def mock_run(client_, sql, config, timeout):
        return [{"currency": "CNY"}, {"currency": "RMB"}]

    fx_calls = []
    def mock_fx_rate(currency, target):
        fx_calls.append((currency, target))
        return 1.0, "mock"

    monkeypatch.setattr(module, "run", mock_run)
    monkeypatch.setattr(module, "fx_rate", mock_fx_rate)

    class FakeArgs:
        target_currency = "CNY"
        job_timeout_seconds = 10

    rates, sources = module.resolve_rates(None, FakeArgs(), None, "fake_table")

    # For CNY target, CNY and RMB are pre-populated as 1.0, so no fx_rate calls should happen.
    assert rates == {"CNY": 1.0, "RMB": 1.0}
    assert sources == {"CNY": "identity", "RMB": "identity"}
    assert len(fx_calls) == 0


def test_make_currency_case_generation_removes_dead_code():
    module = load_module()

    # Case 1: Target currency is USD, so rates contains USD, CNY (with some rate), and RMB fallback.
    case_sql = module.make_currency_case({"USD": 1.0, "CNY": 0.14}, "bc.currency", "bc.spend")
    assert 'WHEN bc.currency = "USD" THEN bc.spend * 1.0000000000' in case_sql
    assert 'WHEN bc.currency = "CNY" THEN bc.spend * 0.1400000000' in case_sql
    # RMB fallback should map to the CNY rate
    assert 'WHEN bc.currency = "RMB" THEN bc.spend * 0.1400000000' in case_sql

    # Case 2: Target currency is CNY
    case_sql_cny = module.make_currency_case({"CNY": 1.0, "RMB": 1.0}, "bc.currency", "bc.spend")
    assert 'WHEN bc.currency = "CNY" THEN bc.spend * 1.0000000000' in case_sql_cny
    assert 'WHEN bc.currency = "RMB" THEN bc.spend * 1.0000000000' in case_sql_cny


def test_fx_rate_normalization(monkeypatch):
    module = load_module()

    symbol_calls = []
    class FakeHistory:
        empty = False
        def __getitem__(self, key):
            assert key == "Close"
            return self
        def dropna(self):
            return self
        @property
        def iloc(self):
            return [0.14]

    class FakeTicker:
        def __init__(self, symbol):
            symbol_calls.append(symbol)
        def history(self, period):
            return FakeHistory()

    monkeypatch.setattr(module.yf, "Ticker", FakeTicker)

    # 1. RMB target and CNY currency -> 1.0, identity
    rate, source = module.fx_rate("CNY", "RMB")
    assert rate == 1.0
    assert source == "identity"
    assert len(symbol_calls) == 0

    # 2. RMB currency and USD target -> fetches CNYUSD=X
    rate, source = module.fx_rate("RMB", "USD")
    assert rate == 0.14
    assert source == "yfinance:CNYUSD=X"
    assert symbol_calls == ["CNYUSD=X"]


def test_fx_rate_retries_on_failure(monkeypatch):
    module = load_module()

    attempt = 0
    class FakeHistory:
        empty = False
        def __getitem__(self, key):
            return self
        def dropna(self):
            return self
        @property
        def iloc(self):
            return [0.14]

    class FakeTicker:
        def __init__(self, symbol):
            pass
        def history(self, period):
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise ConnectionError("Network timeout")
            return FakeHistory()

    import time
    monkeypatch.setattr(module.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(time, "sleep", lambda x: None)

    rate, source = module.fx_rate("CNY", "USD")
    assert rate == 0.14
    assert attempt == 3

    attempt = 0
    class FakeTickerFailed:
        def __init__(self, symbol):
            pass
        def history(self, period):
            nonlocal attempt
            attempt += 1
            raise ConnectionError("Persistent network failure")

    monkeypatch.setattr(module.yf, "Ticker", FakeTickerFailed)
    try:
        module.fx_rate("CNY", "USD")
    except module.AsaPerformanceError as exc:
        assert "连接失败" in str(exc)
        assert attempt == 3
    else:
        raise AssertionError("Expected AsaPerformanceError but none raised")


def test_aggregate_daily_metrics():
    module = load_module()

    # Today is 2026-05-22.
    # Trial days = 7, billing period = 30.
    # Cutoff RUC1 = today - 7 - 1 = today - 8 days = 2026-05-14.
    # Cutoff RUC2 = today - 7 - 30 - 1 = today - 38 days = 2026-04-14.
    # Cutoff RUC3 = today - 7 - 60 - 1 = today - 68 days = 2026-03-15.
    # Cutoff RUC4 = today - 7 - 90 - 1 = today - 98 days = 2026-02-13.
    # Cutoff RUC5 = today - 7 - 120 - 1 = today - 128 days = 2026-01-14.
    today_dt = date(2026, 5, 22)

    rows = [
        # Keyword 1: mature cohort for RUC1 only (report_date = 2026-04-10 <= 2026-04-14)
        {
            "report_date": "2026-04-10",
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ENABLED",
            "spend": 100.0,
            "impressions": 1000,
            "clicks": 100,
            "installs": 50,
            "purchase_income": 500.0,
            "active_users": 10,
            "purchase_users": 5,
            "RU15m": 4,
            "RU": 3,
            "RUC1": 3,
            "RUC2": 1,  # early renewal or noise
            "RUC3": 0,
            "RUC4": 0,
            "RUC5": 0,
        },
        # Keyword 1: mature cohort for RUC1 and RUC2 (report_date = 2026-03-10 <= 2026-03-15)
        {
            "report_date": "2026-03-10",
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ENABLED",
            "spend": 80.0,
            "impressions": 800,
            "clicks": 80,
            "installs": 40,
            "purchase_income": 800.0,
            "active_users": 15,
            "purchase_users": 10,
            "RU15m": 9,
            "RU": 8,
            "RUC1": 8,
            "RUC2": 6,
            "RUC3": 1,
            "RUC4": 0,
            "RUC5": 0,
        },
        # Keyword 1: mature cohort for RUC1, RUC2, and RUC3 (report_date = 2026-02-10 <= 2026-02-13)
        {
            "report_date": "2026-02-10",
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ENABLED",
            "spend": 150.0,
            "impressions": 1500,
            "clicks": 150,
            "installs": 80,
            "purchase_income": 1600.0,
            "active_users": 30,
            "purchase_users": 20,
            "RU15m": 19,
            "RU": 18,
            "RUC1": 18,
            "RUC2": 14,
            "RUC3": 10,
            "RUC4": 4,
            "RUC5": 0,
        },
        # Keyword 1: immature cohort (report_date = 2026-05-20 > 2026-04-14)
        {
            "report_date": "2026-05-20",
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ENABLED",
            "spend": 50.0,
            "impressions": 500,
            "clicks": 50,
            "installs": 20,
            "purchase_income": 200.0,
            "active_users": 5,
            "purchase_users": 2,
            "RU15m": 2,
            "RU": 2,
            "RUC1": 0,
            "RUC2": 0,
            "RUC3": 0,
            "RUC4": 0,
            "RUC5": 0,
        },
        # Keyword 2: completely immature cohort (report_date = 2026-05-20 > 2026-05-14)
        {
            "report_date": "2026-05-20",
            "ad_group_id": "222",
            "ad_group": "Group2",
            "match_type": "BROAD",
            "keyword": "kw2",
            "keyword_status": "ENABLED",
            "spend": 30.0,
            "impressions": 300,
            "clicks": 30,
            "installs": 10,
            "purchase_income": 0.0,
            "active_users": 2,
            "purchase_users": 1,
            "RU15m": 1,
            "RU": 1,
            "RUC1": 0,
            "RUC2": 0,
            "RUC3": 0,
            "RUC4": 0,
            "RUC5": 0,
        }
    ]

    agg = module.aggregate_daily_metrics(rows, trial_days=7, billing_period_days=30, today_dt=today_dt)

    assert len(agg) == 2

    kw1 = agg[0]
    assert kw1["keyword"] == "kw1"
    assert kw1["spend"] == 380.0
    assert kw1["impressions"] == 3800
    assert kw1["clicks"] == 380
    assert kw1["installs"] == 190
    assert kw1["purchase_income"] == 3100.0
    assert kw1["active_users"] == 60
    assert kw1["purchase_users"] == 37
    assert kw1["RU15m"] == 34
    assert kw1["RU"] == 31
    assert kw1["RUC1"] == 29
    assert kw1["RUC2"] == 21
    assert kw1["RUC3"] == 11
    assert kw1["RUC4"] == 4
    assert kw1["RUC5"] == 0
    assert kw1["days"] == 4

    # Cohort mature denominators
    assert kw1["RUC1_mature_purchases"] == 5 + 10 + 20
    assert kw1["RUC2_mature_purchases"] == 5 + 10 + 20
    assert kw1["RUC3_mature_purchases"] == 10 + 20
    assert kw1["RUC4_mature_purchases"] == 20
    assert kw1["RUC5_mature_purchases"] == 0

    # RRC calculations (using mature_only / mature_purchases)
    # RRC1 = (3 + 8 + 18) / 35 = 29 / 35 = 0.8286
    assert kw1["RRC1"] == 0.8286
    # RRC2 = (1 + 6 + 14) / 35 = 21 / 35 = 0.6000
    assert kw1["RRC2"] == 0.6
    # RRC3 = (1 + 10) / 30 = 11 / 30 = 0.3667
    assert kw1["RRC3"] == 0.3667
    # RRC4 = 4 / 20 = 0.2000
    assert kw1["RRC4"] == 0.2
    assert kw1["RRC5"] is None
    assert kw1["effective_RRC1"] == 0.8286
    assert kw1["effective_RRC2"] == 0.6
    assert kw1["effective_RRC3"] == 0.3667
    assert kw1["effective_RRC4"] == 0.2
    assert kw1["effective_RRC5"] is None

    # Keyword 2
    kw2 = agg[1]
    assert kw2["keyword"] == "kw2"
    assert kw2["RUC1_mature_purchases"] == 0
    assert kw2["RRC1"] is None
    assert kw2["RRC2"] is None
    assert kw2["RRC3"] is None
    assert kw2["RRC4"] is None
    assert kw2["RRC5"] is None
    assert kw2["effective_RRC1"] is None
    assert kw2["effective_RRC2"] is None
    assert kw2["effective_RRC3"] is None
    assert kw2["effective_RRC4"] is None
    assert kw2["effective_RRC5"] is None


def test_mature_purchase_denominators_respect_cutoff_boundaries():
    module = load_module()
    today_dt = date(2026, 5, 24)

    # trial_days=3, billing_period_days=30:
    # RUC1 cutoff = 2026-05-20
    # RUC2 cutoff = 2026-04-20
    # RUC3 cutoff = 2026-03-21
    # RUC4 cutoff = 2026-02-19
    # RUC5 cutoff = 2026-01-20
    def row(
        report_date: str,
        purchases: int,
        ruc1: int,
        ruc2: int,
        ruc3: int,
        ruc4: int,
        ruc5: int
    ) -> dict:
        return {
            "report_date": report_date,
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ACTIVE",
            "spend": 10.0,
            "impressions": 100,
            "clicks": 10,
            "installs": 5,
            "purchase_income": 0.0,
            "active_users": 0,
            "purchase_users": purchases,
            "RU15m": 0,
            "RU": 0,
            "RUC1": ruc1,
            "RUC2": ruc2,
            "RUC3": ruc3,
            "RUC4": ruc4,
            "RUC5": ruc5,
        }

    rows = [
        row("2026-05-21", 100, 99, 99, 99, 99, 99),  # after RUC1 cutoff, excluded from all mature denominators
        row("2026-05-20", 10, 4, 9, 9, 9, 9),        # exactly RUC1 cutoff, included only in RUC1
        row("2026-04-21", 100, 99, 99, 99, 99, 99),  # after RUC2 cutoff, included in RUC1 only
        row("2026-04-20", 20, 10, 8, 19, 19, 19),    # exactly RUC2 cutoff, included in RUC1 and RUC2
        row("2026-03-22", 100, 99, 99, 99, 99, 99),  # after RUC3 cutoff, included in RUC1 and RUC2
        row("2026-03-21", 30, 15, 12, 9, 29, 29),    # exactly RUC3 cutoff, included through RUC3
        row("2026-02-20", 100, 99, 99, 99, 99, 99),  # after RUC4 cutoff, included through RUC3
        row("2026-02-19", 40, 20, 16, 12, 8, 39),    # exactly RUC4 cutoff, included through RUC4
        row("2026-01-21", 100, 99, 99, 99, 99, 99),  # after RUC5 cutoff, included through RUC4
        row("2026-01-20", 50, 25, 20, 15, 10, 5),    # exactly RUC5 cutoff, included in all mature denominators
    ]

    agg = module.aggregate_daily_metrics(
        rows,
        trial_days=3,
        billing_period_days=30,
        today_dt=today_dt,
        first_purchase_gross=48.0,
        regular_period_gross=48.0,
        apple_fee=0.15,
    )

    kw1 = agg[0]
    assert kw1["purchase_users"] == 650
    assert kw1["RUC1"] == 569
    assert kw1["RUC2"] == 560
    assert kw1["RUC3"] == 559
    assert kw1["RUC4"] == 570
    assert kw1["RUC5"] == 596

    assert kw1["RUC1_mature_purchases"] == 10 + 100 + 20 + 100 + 30 + 100 + 40 + 100 + 50
    assert kw1["RUC2_mature_purchases"] == 20 + 100 + 30 + 100 + 40 + 100 + 50
    assert kw1["RUC3_mature_purchases"] == 30 + 100 + 40 + 100 + 50
    assert kw1["RUC4_mature_purchases"] == 40 + 100 + 50
    assert kw1["RUC5_mature_purchases"] == 50

    assert kw1["RRC1"] == round((4 + 99 + 10 + 99 + 15 + 99 + 20 + 99 + 25) / 550, 4)
    assert kw1["RRC2"] == round((8 + 99 + 12 + 99 + 16 + 99 + 20) / 440, 4)
    assert kw1["RRC3"] == round((9 + 99 + 12 + 99 + 15) / 320, 4)
    assert kw1["RRC4"] == round((8 + 99 + 10) / 190, 4)
    assert kw1["RRC5"] == round(5 / 50, 4)


def test_renewal_cutoff_dates_for_trial_and_no_trial():
    module = load_module()
    today_dt = date(2026, 5, 24)

    assert module.renewal_cutoff_date(today_dt, 3, 30, 1) == date(2026, 5, 20)
    assert module.renewal_cutoff_date(today_dt, 3, 30, 2) == date(2026, 4, 20)
    assert module.renewal_cutoff_date(today_dt, 3, 30, 3) == date(2026, 3, 21)
    assert module.renewal_cutoff_date(today_dt, 3, 30, 4) == date(2026, 2, 19)
    assert module.renewal_cutoff_date(today_dt, 3, 30, 5) == date(2026, 1, 20)

    assert module.renewal_cutoff_date(today_dt, 0, 30, 1) == date(2026, 4, 23)
    assert module.renewal_cutoff_date(today_dt, 0, 30, 2) == date(2026, 3, 24)
    assert module.renewal_cutoff_date(today_dt, 0, 30, 3) == date(2026, 2, 22)
    assert module.renewal_cutoff_date(today_dt, 0, 30, 4) == date(2026, 1, 23)
    assert module.renewal_cutoff_date(today_dt, 0, 30, 5) == date(2025, 12, 24)


def test_aggregate_cohort_slice():
    module = load_module()
    rows = [
        {
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ENABLED",
            "spend": 100.0,
            "impressions": 1000,
            "clicks": 100,
            "installs": 50,
            "purchase_users": 5,
            "RUC1": 3,
        },
        {
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ENABLED",
            "spend": 80.0,
            "impressions": 800,
            "clicks": 80,
            "installs": 40,
            "purchase_users": 10,
            "RUC1": 8,
        }
    ]

    report = module.aggregate_cohort_slice(rows, "RUC1")
    assert len(report) == 1
    kw1 = report[0]
    assert kw1["keyword"] == "kw1"
    assert kw1["spend"] == 180.0
    assert kw1["impressions"] == 1800
    assert kw1["clicks"] == 180
    assert kw1["installs"] == 90
    assert kw1["purchases"] == 15
    assert kw1["renewals"] == 11
    assert kw1["RRC"] == 0.7333  # 11 / 15 = 0.73333...


def test_aggregate_daily_metrics_keeps_keyword_id_distinct():
    module = load_module()
    today_dt = date(2026, 5, 22)

    def row(keyword_id: str, spend: float, purchases: int) -> dict:
        return {
            "report_date": "2026-05-01",
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "same keyword",
            "keyword_id": keyword_id,
            "keyword_status": "ENABLED",
            "spend": spend,
            "impressions": 100,
            "clicks": 10,
            "installs": 5,
            "purchase_income": 0.0,
            "active_users": 0,
            "purchase_users": purchases,
            "RU15m": 0,
            "RU": 0,
            "RUC1": 1,
            "RUC2": 0,
            "RUC3": 0,
            "RUC4": 0,
            "RUC5": 0,
        }

    agg = module.aggregate_daily_metrics(
        [row("k1", 10.0, 1), row("k2", 20.0, 2)],
        trial_days=3,
        billing_period_days=7,
        today_dt=today_dt,
    )

    assert len(agg) == 2
    assert {r["keyword_id"] for r in agg} == {"k1", "k2"}
    assert {r["spend"] for r in agg} == {10.0, 20.0}


def test_target_cpi_is_derived_from_keyword_ltv():
    module = load_module()
    today_dt = date(2026, 5, 22)
    rows = [
        {
            "report_date": "2026-03-01",
            "ad_group_id": "111",
            "ad_group": "Group1",
            "match_type": "EXACT",
            "keyword": "kw1",
            "keyword_status": "ENABLED",
            "spend": 200.0,
            "impressions": 1000,
            "clicks": 200,
            "installs": 100,
            "purchase_income": 0.0,
            "active_users": 0,
            "purchase_users": 10,
            "RU15m": 0,
            "RU": 0,
            "RUC1": 5,
            "RUC2": 3,
            "RUC3": 0,
        }
    ]

    agg = module.aggregate_daily_metrics(
        rows,
        trial_days=3,
        billing_period_days=30,
        today_dt=today_dt,
        first_purchase_gross=48.0,
        regular_period_gross=48.0,
        apple_fee=0.15,
    )

    expected_ltv = module.calculate_ltv(
        first_purchase_gross=48.0,
        regular_period_gross=48.0,
        trial_days=3,
        billing_period_days=30,
        payback_days=180,
        apple_fee=0.15,
        rrc1=0.5,
        rrc2=0.3,
        rrc3=0.0,
    )
    assert agg[0]["payback_days"] == 180
    assert agg[0]["LTV_per_purchase_user"] == expected_ltv
    assert agg[0]["Target_CPI"] == round(expected_ltv * 10 / 100, 2)


def test_main_writes_split_csvs(tmp_path, monkeypatch):
    module = load_module()

    # Mock BQ run queries
    def mock_run(client_, sql, config, timeout):
        # If currency query
        if "CURRENCY_QUERY" in sql or "DISTINCT" in sql:
            return [{"currency": "CNY"}]
        # Main daily query
        return [
            {
                "report_date": "2999-01-01",
                "campaign_id": "999",
                "ad_group_id": "111",
                "ad_group": "Group1",
                "match_type": "EXACT",
                "keyword": "kw1",
                "keyword_id": "k1",
                "keyword_status": "ENABLED",
                "spend": 100.0,
                "impressions": 1000,
                "clicks": 100,
                "installs": 50,
                "purchase_income": 500.0,
                "active_users": 10,
                "purchase_users": 5,
                "RU15m": 4,
                "RU": 3,
                "RUC1": 3,
                "RUC2": 1,
                "RUC3": 0,
                "RUC4": 0,
                "RUC5": 0,
            }
        ]

    class FakeBQ:
        project = "test-project-123"

    monkeypatch.setattr(module, "run", mock_run)
    monkeypatch.setattr(module, "client", lambda path: FakeBQ())
    monkeypatch.setattr(module, "credentials_path", lambda path: Path("/tmp/fake.json"))

    output_file = tmp_path / "report.csv"
    
    import sys
    test_args = [
        "fetch_asa_bigquery_report",
        "--bundle-id", "app.blynkai.todo",
        "--output", str(output_file),
        "--credentials-file", "/tmp/fake.json",
        "--trial-days", "7",
        "--billing-period-days", "30",
        "--payback-days", "120",
        "--start-date", "2026-04-01"
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    code = module.main()
    assert code == 0

    # Verify that files are created
    assert output_file.is_file()
    assert (tmp_path / "report_daily.csv").is_file()
    assert (tmp_path / "report_ruc1.csv").is_file()
    assert (tmp_path / "report_ruc2.csv").is_file()
    assert (tmp_path / "report_ruc3.csv").is_file()
    assert (tmp_path / "report_ruc4.csv").is_file()
    assert (tmp_path / "report_ruc5.csv").is_file()

    # Read and assert output headers
    with open(output_file, "r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
        assert "payback_days" in header
        assert "LTV_per_purchase_user" in header
        assert "expected_revenue" in header
        assert "payback_ratio" in header
        assert "RUC4" in header
        assert "RUC5" in header
        assert "keyword_id" in header
        assert "RRC4" in header
        assert "RRC5" in header
        assert "effective_RRC1" in header
        assert "effective_RRC5" in header
        assert "RUC4_mature_purchases" in header
        assert "RUC5_mature_purchases" in header
        assert "Target_CPI" in header
        assert "required_CPS_reduction" in header

    # Read and assert ruc1 file headers and values
    with open(tmp_path / "report_ruc1.csv", "r", encoding="utf-8") as f:
        lines = f.readlines()
        assert "ad_group_id,ad_group,match_type,keyword,keyword_status,spend,impressions,clicks,installs,purchases,renewals,RRC" in lines[0].strip()
        # Future-dated mock row is immature, resulting in no keyword rows in the cohort splits.
        assert len(lines) == 1


def test_calculate_ltv_weekly():
    module = load_module()
    
    # Weekly with 7-day trial
    # net_first = 2.55, net_regular = 2.55
    # LTV = 2.55 * sum(r_curve[0] to r_curve[24])
    # Inputs (rrc1, rrc2, rrc3) must be cumulative rates.
    # If marginal rates were 0.60, 0.80, 0.90:
    # rrc1 = 0.60
    # rrc2 = 0.60 * 0.80 = 0.48
    # rrc3 = 0.48 * 0.90 = 0.432
    ltv = module.calculate_ltv(
        first_purchase_gross=3.0,
        regular_period_gross=3.0,
        trial_days=7,
        billing_period_days=7,
        payback_days=180,
        apple_fee=0.15,
        rrc1=0.60,
        rrc2=0.48,
        rrc3=0.432
    )
    assert 17.0 < ltv < 18.0


def test_calculate_ltv_monthly():
    module = load_module()
    
    # Monthly with 7-day trial
    # net_first = 8.5, net_regular = 8.5
    # Inputs (rrc1, rrc2, rrc3) must be cumulative rates:
    # rrc1 = 0.50
    # rrc2 = 0.50 * 0.70 = 0.35
    # rrc3 = 0.35 * 0.80 = 0.28
    # r_curve[0] = 0.50, r_curve[1] = 0.35, r_curve[2] = 0.28, r_curve[3] = 0.252, r_curve[4] = 0.23184, r_curve[5] = 0.220248
    # LTV = 8.5 * (0.50 + 0.35 + 0.28 + 0.252 + 0.23184 + 0.220248) = 15.59
    ltv = module.calculate_ltv(
        first_purchase_gross=10.0,
        regular_period_gross=10.0,
        trial_days=7,
        billing_period_days=30,
        payback_days=180,
        apple_fee=0.15,
        rrc1=0.50,
        rrc2=0.35,
        rrc3=0.28
    )
    assert ltv == 15.59


def test_calculate_ltv_uses_real_rrc4_and_rrc5_before_extrapolating():
    module = load_module()

    ltv = module.calculate_ltv(
        first_purchase_gross=10.0,
        regular_period_gross=10.0,
        trial_days=0,
        billing_period_days=30,
        payback_days=150,
        apple_fee=0.0,
        rrc1=0.5,
        rrc2=0.4,
        rrc3=0.3,
        rrc4=0.2,
        rrc5=0.1,
    )

    assert ltv == 25.0


def test_effective_rrc_curve_caps_cumulative_renewal_increases():
    module = load_module()

    assert module.effective_rrc_curve([0.3875, 0.3448, 0.3438, 0.2857, 0.75]) == [
        0.3875,
        0.3448,
        0.3438,
        0.2857,
        0.2857,
    ]


def test_calculate_ltv_uses_effective_monotonic_rrc_curve():
    module = load_module()

    ltv = module.calculate_ltv(
        first_purchase_gross=48.0,
        regular_period_gross=48.0,
        trial_days=3,
        billing_period_days=7,
        payback_days=180,
        apple_fee=0.15,
        rrc1=0.3875,
        rrc2=0.3448,
        rrc3=0.3438,
        rrc4=0.2857,
        rrc5=0.75,
    )

    assert ltv == 226.59


def test_calculate_ltv_yearly():
    module = load_module()
    
    # Yearly with 7-day trial
    # net_first = 50.0 * 0.85 = 42.50
    # LTV = 42.50 * 0.40 = 17.00
    ltv = module.calculate_ltv(
        first_purchase_gross=50.0,
        regular_period_gross=50.0,
        trial_days=7,
        billing_period_days=365,
        payback_days=180,
        apple_fee=0.15,
        rrc1=0.40,
        rrc2=None,
        rrc3=None
    )
    assert ltv == 17.00


def test_calculate_ltv_notrial_monthly():
    module = load_module()
    
    # Monthly with NO trial
    # net_first = 8.5, net_regular = 8.5
    # Inputs (rrc1, rrc2, rrc3) must be cumulative rates:
    # rrc1 = 0.50
    # rrc2 = 0.35
    # rrc3 = 0.28
    # LTV = 8.5 + 8.5 * (0.50 + 0.35 + 0.28 + 0.252 + 0.23184 + 0.220248) = 24.09
    ltv = module.calculate_ltv(
        first_purchase_gross=10.0,
        regular_period_gross=10.0,
        trial_days=0,
        billing_period_days=30,
        payback_days=180,
        apple_fee=0.15,
        rrc1=0.50,
        rrc2=0.35,
        rrc3=0.28
    )
    assert ltv == 24.09
