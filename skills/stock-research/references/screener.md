# Screener Reference

Use this only for broad market screens, not for single-stock research.

## Modes

- Quick screen: run `scripts/screen_stock_candidates.py --markets SH SZ HK`;
  read stdout first.
- Full universe: use `--max-count 0 --min-market-cap <amount>`.
- Resumable run: use
  `--run-date YYYY-MM-DD --run-dir reports/stock-screen/YYYY-MM-DD --resume`.

## Data And Persistence

- The screener uses fixed market snapshot sources: Eastmoney stock selector for
  A-shares; HKEX listings plus Tencent batch quotes for Hong Kong.
- Do not add alternate providers, alternate hosts, or shell-command fetch paths
  without explicit user review.
- Do not silently fall back to generic statement schemas or proxy data. If a
  provider field needed to choose the correct schema is unavailable, return a
  failed enrich row so the analyst can review it.
- `--max-count` limits the raw snapshot pool. Do not invent a separate
  enrichment limit.
- Persist ad hoc outputs only when useful with `--json-out` and/or `--xlsx-out`.
- Resumable runs store `universe.json`, `enrich.jsonl`, and
  `stock-screen-<run_date>.xlsx`; treat `enrich.jsonl` as the checkpoint source.
- Runtime progress is logged to stderr every `--progress-interval` rows; stdout
  remains the final JSON summary.
- Cross-day runs need a new date directory because prices, market cap, PE/PB,
  and derived metrics are date-sensitive. Reuse financial-row cache only for
  report-period financial rows.

## Candidate Fields

Candidate rows use `metrics`, `reject_reasons`, and `data_gaps`. The screener
does not emit quality or valuation tags, scores, buy signals, or safety-margin
confidence. `expected_return`, PE/PB, profit multiple, FCF multiple, and
same-currency risk-free multiple cap stay inside `metrics` only.

`CANDIDATE` means enough data and no hard disqualifier. Use `REJECTED` only for
invalid price, missing or below-floor market cap, A-share ST/*ST status,
non-positive 5-year average profit, non-positive 5-year average FCF, 5-year
average OCF/profit below 0.5, or goodwill/equity above 0.5. Do not reject only
because valuation metrics, FCF/profit, or negative FCF year count are
unattractive.

Use `market_cap_rank`, `market_cap_percentile`, and `analyzed` to explain why a
stock was or was not financially analyzed.
