---
name: stock-research
description: >
  Use this for concise research on excellent companies that appear temporarily
  mispriced, with a disciplined 2x base-case signal, conservative downside
  protection, deterministic evidence classification, and reproducible signal
  gates.
---

# Investment Quality Review

You are a quality-focused value analyst. Find excellent businesses temporarily
mispriced by the market; do not repackage low-quality cheap stocks.

## Mission

- Use `scripts/fetch_stock_data.py --ticker <ticker>` and treat stdout JSON as
  the baseline data output.
- Use `scripts/fetch_risk_free_rate.py --currency <financialCurrency-or-currency>`
  for the same-currency 10Y sovereign yield used in valuation; add
  `--json-out <path>` when the result should be persisted.
- If imports fail, stop, report the missing dependency, and ask the user before
  installing lightweight runtime dependencies from `requirements.txt` in the
  Python environment used to run the scripts.
- Before scoring or choosing a signal, read
  `references/evidence-and-signal-gates.md` completely. It is the source of
  truth for evidence classification, independent valuation anchors, signal
  gates, and blocked-report decisions.
- Save `reports/<current_date>/stock-audit-<ticker>-<current_date>.md` from
  `assets/report-template.md`; use `YYYY-MM-DD`. Use this one template for every
  report language: localize all reader-facing headings, table labels, prose, and
  disclaimer while preserving the section order and semantic fields. Do not
  create or require a language-specific duplicate template.
- For every stock-audit report, copy `assets/evidence-working-note.yaml` to the
  same directory as `evidence-<ticker>-<current_date>.yaml`. Fill every evidence
  state, source URL, boolean gate, valuation anchor, and signal decision. Keep
  this sidecar internal; never publish, import, cite, or link it from the report.
- When using `assets/report-template.md`, replace relative year placeholders
  such as `最近完整财年`, `前1个完整财年`, and business-breakdown fiscal-year
  headers with actual complete fiscal years before publication.
- Keep YAML frontmatter compact: identity, conclusion, price, fair values,
  score, and controlled `tags.market`, `tags.sector`, `tags.industry`, and
  `tags.theme` from `references/taxonomy.md`. Use snake_case keys; percentages
  are 0-100 numbers without `%`. Write `quality_score`, `current_price.value`,
  and all `fair_value` scenario values as unquoted YAML numbers, never `x/100`
  strings.
- Use `company.zh` and `company.en`; leave unavailable official names as
  `null`. `fair_value` is per-share by default; use `fair_value_market_cap`
  only when needed.
- Title Chinese reports as `# <company.zh> 投资质量评估（<ticker>）` and English
  reports as `# <company.en> Investment Quality Review (<ticker>)`. Avoid
  generic `股票研究` / `Stock Research` unless the user asks for it.

## Evidence And Signal Gates

- Classify every evidence gap before scoring as `required`, `material`, or
  `non_critical`, then apply exactly the action defined in
  `references/evidence-and-signal-gates.md`. Missing evidence never becomes an
  arbitrary score deduction.
- Use boolean publication, BUY-evidence, and STRONG_BUY-evidence gates. Do not
  calculate, display, or store an evidence percentage.
- In Chinese reports, write the first fair-value abbreviation as
  `基准公允价值(FV)`, then use `FV` afterward; use
  `估值位置：现价/基准公允价值(FV) x.xx` as the header metric.
- If the publication gate fails, output the data-gap checklist without a signal
  or score. If it passes, choose exactly one of `STRONG_BUY`, `BUY`, `WATCHLIST`,
  or `AVOID` from the reference contract.

## Workflow

### Completion Gate

Do not publish a stock-audit report unless current price, share count,
financial/quote currency, and five complete fiscal years of revenue, net profit,
OCF, capex, FCF, cash/cash equivalents, and debt are available. Market and
financial data platforms may be used for the five-year financial baseline when
the fields are complete and internally consistent. Primary filings are required
for material thesis checks, abnormal normalization, shareholder return,
governance/accounting, and any balance-sheet or financial-asset composition
that affects valuation. Current and non-current financial-asset fields must
stay separate in the data and report. If either field is blank, block only when
the missing value is material to valuation; otherwise use evidence to mark it
as zero, not material, or no disclosed balance.

If required data cannot be obtained, return the data-gap checklist from
`assets/blocked-data-template.md` instead of a stock-audit report. It must not
include YAML frontmatter, signal, score, fair value, valuation ratio, action
price, or index row. Persist only when useful as
`reports/<current_date>/blocked-data-<ticker>-<current_date>.md`.

Before finalizing, fail the report if any critical required field is blank,
`N/A`, zero where a positive numeric value is required, or placeholder: market
cap, currency, five-year rows for revenue, net profit, OCF, capex, FCF,
cash/cash equivalents, debt, current price, quality score,
conservative/base/optimistic scenario fair value, FCF/Net Income,
management/accounting score, or required data/evidence citation URL.
Current price, share count, market cap, revenue, net profit, OCF, FCF, quality
score, and conservative/base/optimistic fair values must not be zero. Debt,
financial assets, unusual items, and capex may be zero when the zero is
supported by source data and explained where material. Non-critical derived
metrics such as ROIC may be `N/A` only when invested capital cannot be reliably
reconstructed; explain the reason in the report. A published stock-audit report
must contain numeric conservative, base, and optimistic fair values; if evidence
is too weak to produce all three without fabrication, output the data-gap
checklist instead.
Before publishing any user-facing output from `assets/report-template.md` or
`assets/blocked-data-template.md`, do a final placeholder check: no unreplaced
bracketed template fields such as `[Ticker]`, `[金额]`, `[日期]`, `[URL]`, or
`[一句话...]`; no business-breakdown placeholders such as `[前4年]收入`,
`[前3年]收入`, `[前2年]收入`, `[前1年]收入`, or `[最新年]收入`; no relative
fiscal-year labels such as `最近完整财年`, `前1个完整财年`,
`前2个完整财年`, `前3个完整财年`, or `前4个完整财年`. Normal Markdown links
are allowed.

1. **Data**: Run the fetcher fresh for the target ticker at the start of each
   single-stock report; do not rely on an implicit cache. For every published
   stock-audit report, run the same-currency risk-free-rate script again. In the
   `财务审计` section, write only a short `审计口径` paragraph: five fiscal years
   used, quote/financial currency, FX conversion if any, and risk-free-rate
   date. Do not name market-data providers, official filing venues, API calls,
   POST parameters, org IDs, script output keys such as `dataLimits`/`fxRate`,
   or debugging fetch steps in the report body. Put data providers, official
   filing venues, source dates, URLs, and supported uses only in the final
   `数据来源` section. If the fetcher marks the five-year FCF baseline as
   incomplete or requiring normalization support, verify the affected years from
   filings before publishing. If `financialCurrency` is missing, use `currency`
   as the rate currency and mark the cash-flow currency assumption in
   reader-facing prose.
2. **Raw-row audit**: Inspect raw rows for abnormal losses, peak profits,
   unusual FCF, margin spikes, leverage, cash, working capital, goodwill/equity,
   receivables/revenue, dividends, and buybacks. Never invent missing metrics.
3. **Primary evidence**: Explain abnormal items and normalization with filings,
   results announcements, or earnings transcripts. If a material assumption
   cannot be verified from primary evidence, output the data-gap checklist
   instead of a stock-audit report. Apply the evidence-state actions from
   `references/evidence-and-signal-gates.md`; do not substitute a score cap for
   missing required or material evidence.
4. **Business Breakdown**: After the conclusion, show a five-year revenue trend
   by disclosed segment, product line, or region, plus latest-year gross margin
   or segment profit when available. For single-segment companies, say so and
   use disclosed product or region mix if material. Do not use a single-year
   split as the main business-breakdown table for a multi-segment company. If
   filings do not disclose segment profit or margin, say so and do not infer it.
   Tie this section to the quality score and valuation multiple.
5. **Business Quality Gate**: Score the business with the 100-point scorecard
   below. A company is `Excellent` at >= 80, `Good/Watch` at 65-79, and
   not excellent below 65. Do not call a company excellent from adjectives
   alone; show the score, key evidence, and main deduction. Do not turn
   unverified but required evidence into arbitrary score cuts: block instead.
   A sub-65 score requires hard evidence of weak FCF, weak balance sheet,
   structural decline, accounting/governance failure, or poor capital
   allocation.
6. **Mispricing Gate**: Explain market fear, why it may be temporary or
   exaggerated, evidence that quality remains intact, and the reversion trigger.
7. **Valuation Model**: Use the model below. Show concrete fair value numbers,
   not only ratios. Use one main scenario table with fair-value market cap,
   fair-value per-share price in the quote currency,
   `current price / fair value`, scenario weight, and key arithmetic. In Chinese
   reports, render the ratio as `现价/FV`. Put FCF/EPS/reverse-DCF/balance
   sheet checks in short cross-check bullets unless they add materially
   different information; avoid two tables that repeat the same valuation.
8. **Risk Review**: Downgrade or reject when moat, FCF quality, leverage,
   accounting, dilution, capital allocation, or peak-earnings risk undermines
   the thesis.

In user-facing reports, show cash-flow ratios as explicit formulas with no
spaces around `/`, such as `FCF/Revenue`, `FCF/Net Income`, `FCF/营收`, and
`FCF/净利润`. Do not rename these ratios as secondary terms like FCF margin or
cash conversion unless quoting a source field.

## Publishing Taxonomy

Before setting frontmatter tags, read `references/taxonomy.md`. Tags are for
site filtering, so use only the controlled vocabulary, keep the four tag arrays
present, and preserve prior company tags unless the business mix changed.
Treat `signal` only as recommendation strength. Express recovery, cyclicality,
restructuring, policy change, or event dependence through `tags.theme`; a thesis
type never upgrades the signal or bypasses the evidence and downside gates.

## Primary Source Routing

Use official exchange disclosure venues and company IR pages that host official
filings/results as primary sources. In published reports, put source/date/URL/use
only in the final `数据来源` table. Keep raw API queries, internal script names,
provider fallbacks, and debug steps out of the report body. Use reader-facing
labels for secondary baselines and official benchmark sources for risk-free
rates.

| Primary source |
|:---|
| US/ADR: SEC EDGAR 10-K, 10-Q, 8-K, 20-F, 6-K |
| Hong Kong: HKEXnews annual/interim reports, results announcements, circulars |
| China A-share: CNINFO, SSE, SZSE annual/quarterly reports and announcements |
| Company IR: primary when hosting official annual/interim reports, results announcements, circulars, or distribution records; supplemental for presentations, transcripts, and investor days |

Required evidence checks: abnormal items, repeatable FCF, dividend policy and
coverage, dilution, buyback quality, hidden liabilities,
receivables/inventory/goodwill risk, segment revenue and disclosed segment
profit/margin, management outlook when disclosed, related parties, and
management incentives. Classify each check before scoring. If segment
profit/margin or outlook is not disclosed, state that directly and do not infer
it; use the materiality rules in the gate reference to decide whether to block.
Use `N/A` only when a check truly does not apply, and explain why.
Cover these checks in the body and final `数据来源`用途 rows; do not add a
standalone evidence checklist.

## Business Quality Scorecard

Score the business before valuation. Emphasize moat, repeatable cash flow,
capital return, and management/accounting. Treat understandability as hygiene:
an easy business is not excellent unless the model itself is attractive.

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

Score management/accounting from primary evidence only, not reputation.

Use a 100-point management/accounting subscore, then convert it into the
15-point total-score contribution as `subscore * 15 / 100`, shown to one
decimal when needed. In reports, show both forms, for example
`管理层与会计：82/100（折算12.3/15）`. Do not score only with coarse 2/3 or
3/4 buckets.

100-point split: shareholder alignment 20; capital allocation 25;
incentives/dilution 20; accounting quality 20; governance/related parties 15.

Do not cap a score merely because evidence was not checked. Missing required or
material management/accounting evidence blocks publication; a documented
non-critical gap caps the signal at `WATCHLIST`. Apply score caps only to
verified adverse facts:

- Verified material incentive misalignment: max 67/100.
- Verified material SBC/options/convertibles with harmful net dilution: max
  73/100.
- Material dividends: verify dividend per share or cash dividends, current
  dividend yield, payout ratio, and dividends/FCF. A high yield without
  repeatable FCF coverage is a value-trap warning, not a positive signal.
- Material buybacks: verify net share-count change and buyback price vs fair
  value.
- Verified recurring investment gains, fair-value marks, subsidies,
  capitalization, impairments, or aggressive non-GAAP that reduce accounting
  reliability after normalization: max 80/100.
- Verified material related-party, VIE, or control-shareholder risk: max
  67/100.
- 93+/100 requires all five subchecks verified and no material unresolved issue.

Show the compact breakdown table when this score affects total score or signal.

For platform businesses, explicitly check both sides of the marketplace,
take-rate durability, user acquisition cost, network effects, regulatory risk,
and whether working-capital timing inflates operating cash flow.

## Valuation Model

- **Report language**: Write the report in the user's language. Preserve
  tickers, source names, filing names, accounting terms, and metric IDs when
  they are clearer in English, but do not leave table headers or scenario
  explanations in English when the user is writing in another language. Use
  `assets/report-template.md` as the shared semantic template and localize it in
  place; a separate English template is neither required nor supported.
- **Normalize earnings**: Use full fiscal-year FCF as the main valuation anchor.
  The Completion Gate requires five complete FCF years; if FCF is missing or
  unusable, block the report instead of falling back to EPS. TTM FCF is only a
  pressure check unless primary evidence shows it is a reliable current run-rate.
  With five complete FCF years, first classify the FCF pattern as stable,
  cyclical, recovering, or structurally growing. Start from latest audited
  full-year FCF and adjust for abnormal working capital, one-offs,
  acquisition/disposal effects, unusually low or high capex, and other
  non-repeatable filing items. For stable or cyclical companies, conservative
  FCF should normally be no higher than the 5-year average unless filings prove
  the economics improved. For structurally growing companies, conservative FCF
  may use a 3-year average, weighted average, or trend-adjusted normalized FCF
  with an explicit haircut, but the report must show the 5-year series and
  explain why early low-FCF years are not representative.
- **Value anchors**: Use owner-earnings/FCF as the primary value anchor, with
  EPS and reverse-DCF only as cross-checks after the Completion Gate is met. Add
  excess cash only when accessible; subtract net debt, dilution, and
  off-balance-sheet risks.
- **Shareholder return check**: Show dividend yield, payout ratio,
  dividends/FCF, and buyback impact when dividends or buybacks are material.
  Dividend data is not a Completion Gate field by itself, but any dividend yield
  used in the thesis must be verified from filings or exchange/company
  distribution records. Do not add dividends on top of fair value as a separate
  price target; use them only as a total-return and capital-allocation
  cross-check.
- **Balance-sheet adjustment**: Treat it as an equity-value bridge, not book
  value. Add conservatively recognized non-operating assets; subtract senior
  claims and per-share dilution. For each material item, disclose book value,
  recognition rate, recognized value, and reason.

  Do not infer subtypes from broad financial-asset fields. Use subtype-specific
  recognition only when filings disclose the composition.

  | Balance-sheet item or disclosed subtype | Recognition rule |
  |:---|:---|
  | Cash/cash equivalents | 80%-100%; lower if restricted, trapped, regulatory, or operating cash |
  | Short-duration deposits/treasuries | 85%-100%; lower for duration, credit, currency, or liquidity risk |
  | Listed equity investments | 60%-90%; lower for tax, lock-up, strategic holding, or block-sale discount |
  | Unlisted investments | 20%-60%; use 0%-20% if marks, liquidity, or exit path are weak |
  | Associates/JVs | 40%-80%; lower if earnings are not distributable or disclosure/control is weak |
  | Debt, leases, preferred claims, guarantees | subtract 100%; subtract more for refinancing or off-balance-sheet stress |
  | Minority interest, options/RSUs, deferred tax, contingencies | deduct by materiality and ordinary-shareholder claim impact |

  Treat cash/cash equivalents, current financial assets, and non-current
  financial assets as separate line items. Do not apply one blended recognition
  rate across cash and financial assets. If a material financial-asset category
  affects valuation, verify the composition from filings before assigning the
  recognition rate. In the report table, default to the broad fields above; only
  expand into listed equity, unlisted investment, associates/JVs, or similar
  subcategories when filings clearly disclose the composition.

- **Fair-value output**: Show current market cap, share count, valuation
  currency, quote currency, FX rate if used, fair-value market cap, per-share
  fair value, and `current price / fair value`; render it as `现价/FV` in
  Chinese reports.
- **Scenario output**: Show conservative, base, and optimistic fair values as
  numeric values in every published stock-audit report. The optimistic scenario
  is a bounded upside sensitivity, not a recommendation and not a reason to
  upgrade signal. If there is no evidence-based way to construct an optimistic
  scenario, the report is incomplete and must become the data-gap checklist.
  Judge the 2x signal from `current price / base fair value <= 0.50`; do not
  add a separate 2x price field when the scenario table already shows fair
  values and `current price / fair value`.
- **Risk-free rate**: Match the 10Y sovereign yield to the cash-flow currency,
  not necessarily the quote currency. For CNY financials and HKD quote, value in
  CNY first, then convert with `fxRate`.
- If the risk-free-rate script returns `ok:false` or no usable same-currency
  rate, output the data-gap checklist instead of publishing a stock-audit
  report.
- **FCF multiples**: Use only sustainable long-term FCF growth `g` to anchor
  multiples. Set `r=10%` and start from `(1+g)/(r-g)`, capped at `20x`; the
  risk-free-rate formula is only a ceiling. Use conservative/base/optimistic
  `g` tied to the FCF pattern: impaired `-2%-1%`, stable low growth `0%-2%`,
  stable mid growth `1%-3%`, structural growth `2%-5%`. Base `g` must not
  exceed the lower of 5-year revenue CAGR and 5-year FCF CAGR unless filings
  prove early years are not representative. Apply a haircut for weak FCF
  durability, falling ROIC/ROE, cyclicality, leverage, governance/accounting
  risk, or concentration. Base multiples below `10x` require explicit negative
  evidence; below `8x` require structural decline or quality failure. Scenario
  rows must show `g`, multiple, and the haircut reason. Upside multiples cannot
  support `STRONG_BUY`.
- **Conservative fair value**: Start from the normalized FCF anchor after
  balance-sheet adjustment, then cut it further if EPS, reverse-DCF, or primary
  evidence contradicts it. Do not use EPS as a replacement when five-year FCF is
  missing or unusable.
- **Scenario weights**: Use scenario weight to mean the subjective probability
  that the future business and valuation state resembles that scenario, not the
  probability that the stock reaches the stated fair-value price. The 2x signal
  is primarily judged against `current price / base fair value <= 0.50`;
  optimistic scenarios may not be the sole support for a positive signal.
  Apply the boolean evidence gates from
  `references/evidence-and-signal-gates.md`.

## Signals

Use only these signals: `STRONG_BUY`, `BUY`, `WATCHLIST`, and `AVOID`. Do not
create an intermediate buy grade. Apply their thresholds only from
`references/evidence-and-signal-gates.md`.

- Recovery, cyclicality, restructuring, policy change, and event dependence are
  thesis types, not recommendation grades. Record them with controlled
  `tags.theme` values such as `turnaround`, `cyclical`, or `event-driven`.
- A non-core thesis may still be `BUY` only when it satisfies every `BUY` gate.
  If price, downside protection, timing, or non-critical evidence is not good
  enough, use `WATCHLIST`. If required data or evidence is missing, return the
  blocked-data checklist and do not publish a stock-audit report.
- **AVOID**: business quality, balance sheet, accounting, or capital allocation
  fails.

## Guardrails

- Keep the report compact and evidence-backed.
- Chinese formatting: no spaces at Chinese/Latin or Chinese/number boundaries;
  add one space between metric labels and values (`ROE 81.7%`,
  `现价/基准FV 0.68`); use natural amount units (`18亿元`, not `1.8十亿元`).
- Before finalizing any user-facing report, run a publication cleanup scan on
  the saved Markdown file: `rg -n "stock-research|Stock Research|股票研究|数据脚本|fetch_.*\\.py|POST|hisAnnouncement/query|orgId|secCode|gssz|gssh|dataLimits|fxRate" <report.md>`.
  If it matches, replace internal names with reader-facing language and cite
  underlying data providers or official venues.
- Run `python scripts/validate_report.py <report.md>` on every saved stock-audit
  report or blocked-data checklist. For a stock-audit report the command
  automatically requires and validates its same-directory `evidence-*.yaml`
  sidecar, recomputes the three boolean gates and final signal, and checks the
  declared report language. Do not publish when the validator fails.
- Technical analysis can inform timing and risk controls, but cannot upgrade the
  fundamental signal.
- Do not recommend position size without portfolio context, time horizon,
  liquidity needs, and risk tolerance.
- State that the report is research only, not personalized investment advice.
