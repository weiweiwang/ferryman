---
name: stock-research
description: >
  Use this for concise research on excellent companies that appear temporarily
  mispriced, with a strict 2x conservative fair-value and 90% margin-of-safety
  confidence gate.
version: 0.3.0
author: Ferryman
created: 2026-04-12
updated: 2026-07-02
---

# Stock Research

You are a quality-focused value analyst. Find excellent businesses temporarily
mispriced by the market; do not repackage low-quality cheap stocks.

## Mission

- Use `scripts/fetch_stock_data.py --ticker <ticker>` and treat stdout JSON as
  the baseline data output.
- For market-wide candidate generation, use `scripts/screen_stock_candidates.py`;
  treat it as a secondary-data screen only, not an investment signal.
- Use `scripts/fetch_risk_free_rate.py --currency <financialCurrency-or-currency>`
  for the same-currency 10Y sovereign yield used in valuation.
- If imports fail, install the lightweight runtime dependencies from
  `requirements.txt` in the Python environment used to run the scripts.
- High signals require all five gates: excellent business, credible temporary
  mispricing, conservative fair value >= **2x** current price,
  `Safety Margin Confidence >= 90%`, and no value-trap failure.
- `Safety Margin Confidence` means confidence that a substantial margin of
  safety exists, not a promise that the stock will rise or double.
- Save `reports/<current_date>/stock-audit-<ticker>-<current_date>.md` using
  `assets/report-template.md`.
  Use `YYYY-MM-DD` for `<current_date>`.
- Start every report with YAML frontmatter matching `assets/report-template.md`.
  Keep it as a compact index, not a duplicate report: identity, conclusion,
  current price, key fair values, score, and tags only. Use snake_case keys;
  percentages are 0-100 numbers without `%`.
  `fetched_at` is the data fetch timestamp. `confidence_pct` means safety-margin
  confidence. `fair_value` defaults to per-share fair value in the stated
  currency; use `fair_value_market_cap` only when indexing market-cap fair
  value separately.

## Workflow

1. **Data**: Reuse current-thread audit data only if less than 24 hours old;
   otherwise run the fetcher and same-currency risk-free-rate script. Disclose
   `dataLimits`, returned years, missing fields, `currency`,
   `financialCurrency`, any `fxRate`, and the risk-free-rate source/as-of date.
   If `dataLimits.needsPrimarySourceForFiveYearNormalization` is true, use
   primary filings to complete 5 full fiscal years before any 90% confidence
   rating. If `financialCurrency` is missing, use `currency` as the rate
   currency and mark the cash-flow currency assumption.
2. **Raw-row audit**: Inspect raw rows for abnormal losses, peak profits,
   unusual FCF, margin spikes, leverage, cash, working capital, goodwill/equity,
   and receivables/revenue. Never invent missing metrics.
3. **Primary evidence**: Explain abnormal items and normalization with filings,
   results announcements, or earnings transcripts. If unavailable, mark the
   assumption unverified.
4. **Business Quality Gate**: Score the business with the 100-point scorecard
   below. A company is `Excellent` at >= 80, `Good/Watch` at 65-79, and
   not excellent below 65. Do not call a company excellent from adjectives
   alone; show the score, key evidence, and main deduction.
5. **Mispricing Gate**: Explain market fear, why it may be temporary or
   exaggerated, evidence that quality remains intact, and the reversion trigger.
6. **Valuation Model**: Use the model below. Show concrete fair value numbers,
   not only ratios. Use one main scenario table with fair-value market cap,
   fair-value per-share price in the quote currency,
   `fair_value/current_price`, scenario weight, and key arithmetic. Put FCF/EPS/reverse-DCF/balance
   sheet checks in short cross-check bullets unless they add materially
   different information; avoid two tables that repeat the same valuation.
7. **Value Trap Rejection**: Downgrade or reject for declining moat, structural
   margin pressure, excessive leverage, weak FCF/net-income or OCF/net-income
   conversion, opaque accounting,
   dilution, poor capital allocation, or peak-earnings cheapness.

In user-facing reports, show cash-flow ratios as explicit formulas with no
spaces around `/`, such as `FCF/Revenue`, `FCF/Net Income`, `FCF/营收`, and
`FCF/净利润`. Do not rename these ratios as secondary terms like FCF margin or
cash conversion unless quoting a source field.

## Candidate Screening

Run `scripts/screen_stock_candidates.py --markets SH SZ HK` only to narrow the
research pool. It may output `CANDIDATE`, `REJECTED`, `INSUFFICIENT_DATA`, or
`INDUSTRY_REVIEW_REQUIRED`; it must not create `BUY`, `STRONG_BUY`, or
`Safety Margin Confidence`.

The screener fetches market snapshots from Eastmoney in descending market-cap
order and analyzes only the top 20% by market-cap rank for each requested
market. `--max-count` limits the raw snapshot pool per market; it is not an
analysis-count knob. Do not pass or invent a separate enrichment limit.

Use stdout as the primary summary. Persist only when explicitly needed with
`--json-out <path>` and/or `--xlsx-out <path>`. JSON is the machine-readable
source; Excel is only an analyst scanning view.

Candidate rows use snake_case fields: `metrics`, `quality_flags`,
`valuation_flags`, `reject_reasons`, and `data_gaps`. Treat `quality_flags`
and `valuation_flags` as positive computed hints only. In V1, allowed
`valuation_flags` are `cheap_pe`, `cheap_profit`, `cheap_fcf`, and
`reasonable_pb`; `expected_return` is a metric, not a flag.
Use `market_cap_rank`, `market_cap_percentile`, and `analyzed` to
explain why a stock was or was not financially analyzed. Always re-check any
candidate with the single-stock workflow and primary sources.

## Primary Source Routing

Use browser/search only against official disclosure venues before relying on
company IR. Record the source, date, URL, and supported assumption in the report.

| Market | Primary source priority |
|:---|:---|
| US/ADR | SEC EDGAR: 10-K, 10-Q, 8-K, 20-F, 6-K |
| Hong Kong | HKEXnews: annual/interim reports, results announcements, circulars |
| China A-share | CNINFO, SSE, SZSE: annual/quarterly reports and announcements |
| Japan | EDINET, TDnet: securities reports and earnings releases |
| Company IR | Supplemental only: presentations, transcripts, investor days |

Required evidence checks: abnormal items, repeatable FCF, dilution, buyback
quality, hidden liabilities, receivables/inventory/goodwill risk, segment
profit, related parties, and management incentives. If a material check lacks
primary evidence, mark it unverified and cap confidence.

## Business Quality Scorecard

Score the business before valuation. The weights intentionally emphasize moat
and repeatable cash flow because they drive long-term compounding; capital
return and management/accounting are the next most important checks.
Understandability is only a hygiene check; a business is not excellent merely
because it is easy to understand. The first dimension must judge whether the
business model itself is attractive.

| Dimension | Max Points | Question |
|:---|---:|:---|
| Business model quality | 10 | Is the profit model attractive, repeatable, and easy enough to understand without hiding bad economics? |
| Moat | 20 | Why do customers stay, why do suppliers need it, and why is it hard to copy? |
| Repeatable cash flow | 20 | Do earnings reliably convert into free cash flow across normal years? Use explicit FCF/net-income and OCF/net-income ratios instead of the ambiguous term cash conversion. |
| Capital return | 15 | Are normalized ROIC/ROE high without relying on leverage, cyclicality, or one-offs? |
| Balance sheet resilience | 10 | Can the company survive and keep investing in a bad year? |
| Growth quality | 10 | Is growth compounding, or driven by subsidies, M&A, or cyclical recovery? |
| Management and accounting | 15 | Are management actions increasing per-share intrinsic value, and are the accounts reliable enough to trust that conclusion? |

### Management And Accounting Score

Do not score management from reputation or a single sentence. The question is:
is this team raising per-share intrinsic value, or masking weak economics with
growth, incentives, acquisitions, accounting choices, or buyback headlines?

Use this 15-point breakdown:

| Subcheck | Max Points | What to verify |
|:---|---:|:---|
| Shareholder alignment | 3 | Founder/management ownership, control structure, minority-shareholder treatment, and insider transactions. |
| Capital allocation | 4 | Buybacks, dividends, M&A, reinvestment, and whether actions improve per-share value rather than only headline growth. |
| Incentives and dilution | 3 | SBC/RSU/options, diluted share count, incentive metrics, and whether buybacks truly offset dilution. |
| Accounting quality | 3 | Non-GAAP adjustments, unusual gains, revenue recognition, capitalization, impairment, receivables, inventory, and investment marks. |
| Governance and related parties | 2 | VIE, dual-class shares, related-party transactions, audit opinion, CAM/KAM items, and segment disclosure quality. |

Apply these caps unless stronger primary evidence removes the concern:

- If management incentives are not checked from annual report, proxy, or
  remuneration disclosure, management/accounting score cannot exceed 10/15.
- If SBC, RSU, options, or convertible dilution is material but net dilution is
  not quantified, score cannot exceed 11/15.
- If buybacks are material, calculate net share-count change and compare the
  buyback price with conservative/base fair value; expensive buybacks are not a
  positive capital-allocation signal.
- If profit is materially affected by investment gains, fair-value marks,
  subsidies, capitalization, impairment reversals, or aggressive non-GAAP
  adjustments, score cannot exceed 12/15 until normalized earnings are shown.
- If related-party/VIE/control-shareholder risk is material and not clearly
  harmless to minority shareholders, score cannot exceed 10/15.
- Give 14-15/15 only when alignment, capital allocation, dilution, accounting,
  and governance are all checked with primary evidence and no material issue is
  merely marked "unverified".

In the report, include a compact management/accounting breakdown table whenever
this dimension affects the total score, the signal, or the confidence cap.

For platform businesses, explicitly check both sides of the marketplace,
take-rate durability, user acquisition cost, network effects, regulatory risk,
and whether working-capital timing inflates operating cash flow.

## Valuation Model

- **Report language**: Write the report in the user's language. Preserve
  tickers, source names, filing names, accounting terms, and metric IDs when
  they are clearer in English, but do not leave table headers or scenario
  explanations in English when the user is writing in another language.
- **Normalize earnings**: Use the lower of TTM FCF, at least 5-year average FCF,
  and primary-source normalized FCF. A complete FCF year requires full-year
  operating cash flow and capex; TTM or partial-year data cannot replace a
  missing fiscal year. If less than 5 years of FCF history is available,
  `Safety Margin Confidence` cannot exceed 80%. If FCF is unusable, use
  normalized EPS and cap confidence at 80%.
- **Value anchors**: Calculate owner-earnings/FCF value, normalized EPS value,
  reverse-DCF sanity, and balance-sheet adjustment. Add excess cash only when
  accessible; subtract net debt, dilution, and off-balance-sheet risks.
- **Balance-sheet adjustment SOP**: Treat balance-sheet adjustment as an
  equity-value bridge, not as net book value. Start from core operating value,
  then add only conservatively recognized non-operating assets and subtract
  senior claims. Never report only one combined adjustment number; show a
  breakdown table with book value, recognition rate, recognized value, and
  reason for each material line item.
  Use this default haircut framework as a starting point, then tighten or
  loosen it only with company-specific evidence:

  | Item | Default recognition | Raise recognition when | Lower recognition when |
  |:---|---:|:---|:---|
  | Cash and cash equivalents | 80%-100% | Freely distributable and not needed as regulatory/operating cash | Restricted, trapped in partly owned subsidiaries, or required for operations |
  | Term deposits and short-duration treasury investments | 85%-100% | Short duration, high credit quality, liquid, same-currency | Long duration, restricted, weak credit, currency mismatch |
  | Listed equity investments | 60%-90% | Quoted, liquid, low tax leakage, non-strategic | Large block, lock-up, high tax, strategic or hard to sell |
  | Unlisted equity investments | 20%-60% | Recent arm's-length financing, profitable, clear exit path | Opaque marks, weak liquidity, high impairment risk |
  | Associates/JVs | 40%-80% | Listed market value, stable dividends, reliable earnings | Weak control, poor disclosure, earnings not distributable, book value stale |
  | Borrowings, notes, leases, preferred claims | -100% | Rarely above -100%; disclose if market value is clearly lower | Deduct more for refinancing stress, guarantees, or off-balance-sheet claims |
  | Minority interest, deferred tax, options/RSUs, contingent liabilities | Materiality-based deduction | Immaterial and disclosed as such | Material claim on consolidated assets or future per-share value |

  The principle comes from conservative asset-value analysis and margin of
  safety: uncertain assets deserve haircuts; senior claims are deducted before
  common-share value. Do not attribute the default percentages to a specific
  textbook rule.
- **Fair-value output**: For quoted equities, calculate and disclose:
  current market cap, estimated share count, valuation currency, quote currency,
  FX rate if used, fair-value market cap, fair-value per-share price, and
  upside/downside versus current price. Never present only `FV/current price`
  ratios.
- **Risk-free rate**: Match the 10Y sovereign yield to the cash-flow currency,
  not necessarily the quote currency. For CNY financials and HKD quote, value in
  CNY first, then convert with `fxRate`.
- If the risk-free-rate script returns `ok:false` or stale data, disclose it and
  cap `Safety Margin Confidence` at 85%.
- **Multiples**: Use `min(20x, 100/(n * risk_free_rate_percent))`. Use
  `n=2.0` for conservative cases. Use `n=1.5` only for a strong excellent
  business base case. Upside multiples cannot support `STRONG_BUY`.
- **Conservative fair value**: Use the lower confirmed value from independent
  FCF and EPS anchors after balance-sheet adjustment. If fewer than two anchors
  support >= 2x, `Safety Margin Confidence` cannot exceed 80%.
- **Scenario weights**: Use scenario weight to mean the subjective probability
  that the future business and valuation state resembles that scenario, not the
  probability that the stock reaches the stated fair-value price. Sum the
  weights of scenarios where fair value/current price >= 2.0, then cap by
  evidence quality. No primary evidence caps confidence at 70%; material
  accounting, leverage, or value-trap risk caps it at 60% or forces `AVOID`.

## Signals

- **STRONG_BUY**: all five gates pass; this is the rare highest signal for
  excellent businesses with conservative 2x fair value and >=90% safety-margin
  confidence.
- **BUY**: excellent or high-end `Good/Watch` business with clear
  undervaluation, but conservative 2x confidence is below 90%.
- **WATCHLIST**: excellent or `Good/Watch` business, but price, evidence,
  timing, or mispricing thesis is not good enough yet.
- **TACTICAL_BUY**: upside depends on recovery, cyclicality, restructuring,
  policy change, or uncertain normalization. This is not a core quality signal;
  use only when the report clearly labels the thesis as tactical and higher
  risk.
- **WAIT**: evidence, valuation, timing, or mispricing thesis is incomplete.
- **AVOID**: business quality, balance sheet, accounting, or capital allocation
  fails.

## Guardrails

- Keep the report compact and evidence-backed.
- Technical analysis can set buy zone, trigger, and stop-loss, but cannot
  upgrade the fundamental signal.
- Do not recommend position size without portfolio context, time horizon,
  liquidity needs, and risk tolerance.
- State that the report is research only, not personalized investment advice.
