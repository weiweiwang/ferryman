# Evidence And Signal Gates

This file is the source of truth for evidence states and public signals. Read it
before scoring a company or selecting a signal.

## Evidence Classification

Classify every check before scoring. A missing source and an adverse verified
fact are different states.

| Class | Definition | Only allowed action |
|:---|:---|:---|
| `required` | A Completion Gate field, same-currency risk-free rate, required citation, or primary evidence needed to calculate or normalize a published value. | If missing or unusable, output the blocked-data checklist. Do not score or assign a signal. |
| `material` | A thesis check whose unresolved answer could change quality score by 5 or more points, base fair value by 10% or more, the signal, or the value-trap conclusion. | If unresolved, output the blocked-data checklist. Do not replace the gap with a haircut or score cap. |
| `non_critical` | A disclosed gap that cannot change the thresholds above and is not needed to support a published claim. | Publication is allowed only with the gap stated in the body; cap the signal at `WATCHLIST`. |

Use `not_applicable` only when the company has no relevant exposure and explain
why. Use `verified_adverse` when primary evidence establishes a negative fact;
score and value that fact normally instead of treating it as missing evidence.

The management/accounting score requires primary evidence for shareholder
alignment, capital allocation, incentives/dilution, accounting quality, and
governance/related parties. Conditional checks such as dividends and buybacks
become `material` when they affect the thesis, valuation, or capital-allocation
score. Unchecked required or material subchecks block publication.

## Independent Valuation Anchors

An anchor is independent only when its core economic inputs differ. Reusing the
same normalized FCF with another multiple, growth rate, or scenario weight is
not independent.

Valid families include:

- `normalized_fcf`: normalized FCF or owner earnings;
- `normalized_eps`: normalized EPS or earnings power;
- `reverse_dcf`: reverse DCF using market-implied operating assumptions;
- `segment_sotp`: segment SOTP based on disclosed segment economics;
- `net_assets`: conservatively recognized net assets when assets independently
  support value.

For `STRONG_BUY`, at least two families, including normalized FCF, must each
support fair value of at least 2x the current price. For `BUY`, normalized FCF
must support the base-value threshold and at least one non-FCF cross-check must
not materially contradict it.

## Boolean Gates

Copy `assets/evidence-working-note.yaml` beside every published stock-audit
report. Name it by replacing `stock-audit-` with `evidence-` and `.md` with
`.yaml`, for example `stock-audit-00700.HK-2026-07-13.md` and
`evidence-00700.HK-2026-07-13.yaml`. The sidecar is an internal validation
artifact: do not import, publish, quote, or link it from the reader-facing
report.

Record every check in the sidecar with exactly one class and state. Use only
`verified`, `verified_adverse`, `not_applicable`, or `unresolved`. Verified
states require at least one source URL; `not_applicable` requires a rationale;
`unresolved` requires a concrete gap description. Completion checks use class
`required`; the five management/accounting checks use class `material`.

Set each gate to true or false in the sidecar. Record distinct valuation-anchor
families and whether each supports 2x. Record the final signal and at least one
decision-table reason. Do not render gate values, evidence states, the sidecar,
or an evidence percentage in the report.

The report validator is the executable gate. It requires all Completion Gate
and management/accounting check IDs from the sidecar template, derives the
Publication, BUY, and STRONG_BUY gates from their evidence states, evaluates
the signal table top to bottom, and rejects a report whose declared gates or
signal differ from the computed result. Do not edit a gate boolean merely to
make a report pass.

### Publication Gate

True only when all of these are true:

- the Completion Gate is satisfied;
- every Completion Gate check is `verified`, every management/accounting check
  is `verified` or `verified_adverse`, and every other `required` or `material`
  check is resolved as `verified`, `verified_adverse`, or genuinely
  `not_applicable`;
- the same-currency risk-free rate is usable;
- conservative, base, and optimistic fair values are evidence-based;
- no required report field, citation, or source URL is missing.

If false, output the blocked-data checklist and stop before scoring or assigning
a signal. A blocked-data checklist does not require an evidence sidecar.

### BUY Evidence Gate

True only when the Publication Gate is true, no `non_critical` thesis-relevant
gap remains, the mispricing explanation is supported by primary evidence, the
normalized FCF anchor supports the BUY threshold, and a non-FCF cross-check does
not materially contradict it.

### STRONG_BUY Evidence Gate

True only when the BUY Evidence Gate is true, all five management/accounting
subchecks are verified, at least two independent valuation-anchor families each
support fair value of at least 2x current price, and no material accounting,
leverage, dilution, governance, or value-trap concern remains.

## Signal Decision Table

Evaluate rows from top to bottom after the Publication Gate passes.

| Signal | Required conditions |
|:---|:---|
| `STRONG_BUY` | Quality score >=80; credible temporary mispricing; `current price / base fair value <= 0.50`; `current price / conservative fair value <= 0.85`; STRONG_BUY Evidence Gate true; no value-trap failure. |
| `BUY` | Quality score >=75; credible temporary mispricing; `current price / base fair value <= 0.70`; `current price / conservative fair value <= 1.00`; BUY Evidence Gate true; no value-trap failure. |
| `WATCHLIST` | Quality score >=65 and the company remains investable, but price, timing, mispricing proof, or a documented `non_critical` gap prevents `BUY` or `STRONG_BUY`. |
| `AVOID` | Verified evidence produces quality score <65 or establishes a business-quality, balance-sheet, accounting, governance, dilution, capital-allocation, or value-trap failure. |

Never lower a score to 64 merely to create `AVOID`. A sub-65 score must be the
sum of evidence-backed dimension scores. If the Publication Gate fails, the
result is blocked data, not `WATCHLIST` or `AVOID`.

If `current price / conservative fair value <= 0.50`, describe it as an
exceptional deep-value condition, but do not upgrade the signal unless every
other row condition is satisfied.
