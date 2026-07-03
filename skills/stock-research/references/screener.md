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
- `--max-count` limits the raw snapshot pool. Do not invent a separate
  enrichment limit.
- Persist ad hoc outputs only when useful with `--json-out` and/or `--xlsx-out`.
- Resumable runs store `universe.json`, `enrich.jsonl`, and
  `stock-screen-<run_date>.xlsx`; treat `enrich.jsonl` as the checkpoint source.
- Runtime progress is logged to stderr every `--progress-interval` rows; stdout
  remains the final JSON summary.
- Cross-day runs need a new date directory because prices, market cap, PE/PB,
  and valuation judgment are date-sensitive. Reuse financial-row cache only for
  report-period financial rows.

## Candidate Fields

Candidate rows use `metrics`, `quality_flags`, `valuation_flags`,
`reject_reasons`, and `data_gaps`. Treat flags as computed hints only. Current
`valuation_flags`: `cheap_pe`, `cheap_profit`, `cheap_fcf`, and
`reasonable_pb`. `expected_return` is a metric, not a flag.

Use `market_cap_rank`, `market_cap_percentile`, and `analyzed` to explain why a
stock was or was not financially analyzed.
