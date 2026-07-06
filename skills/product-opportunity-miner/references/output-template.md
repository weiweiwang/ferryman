# Output Template

Use this structure unless the user requests a shorter answer.

```markdown
# Product Opportunity Report: <scope>

## Executive Takeaway

- Best opportunity:
- Best product format:
- Recommended next action:
- Why now:
- Solo-builder verdict:

## Opportunity Summary

| Rank | Opportunity | Decision | Score | Product Format | SEO Verdict | One-Month MVP | Main Risk | Next Action |
|---:|---|---|---:|---|---|---|---|---|
| 1 | <name> | build_now / prototype / seo_validate_first / validate_page / observe / reject | <0-100> | <format> | strong/medium/weak | yes/no/unclear | <risk> | <action> |

## Evidence Base

| Source | User Signal | What It Suggests | Confidence |
|---|---|---|---|
| <url> | <paraphrased user language> | <pain/job/workaround> | high/medium/low |

## Research Limitations

- Blocked or weak sources:
- Fallback sources used:
- Confidence caveat:

## Ranked Opportunities

Fully detail the top 1-3 opportunities. Put lower-ranked opportunities in `Other Candidates` unless the user asks for exhaustive detail.

### 1. <Opportunity Name>

- Decision: build_now / prototype / seo_validate_first / validate_page / observe / reject
- Score: <0-100>
- Product format: iOS app / web tool / extension / micro SaaS / validation page
- Solo-builder fit: strong / medium / weak
- One-month MVP:
- Low-touch acquisition path:
- Target user:

#### Demand Evidence

- User pain:
- Job to be done:
- Current workaround:
- Rejected alternatives:
- Trigger moment:
- Evidence:
- Interpretation:

#### Existing Solutions

- Direct competitors:
- Substitutes:
- What they solve well:
- Gaps or complaints:
- Competitive risk:

#### SEO Feasibility

- Likely search intent:
- Queries checked:
- Evidence URLs:
- Reachable result types:
- Small-site evidence:
- Candidate keyword patterns:
- SERP shape:
- SERP risk:
- Long-tail wedge:
- Programmatic SEO angle:
- SEO verdict: strong / medium / weak

#### Solo Builder Feasibility

- One-month build scope:
- Heavy dependencies avoided:
- Support/compliance risk:
- Feasibility verdict: strong / medium / weak

#### MVP Wedge

- MVP:
- Core loop:
- Retention driver:
- Acquisition path:

#### Monetization Path

- Free value:
- Paid trigger:
- Pricing shape:
- Monetization risk:

#### Final Decision

- Decision:
- Why:
- Kill criteria:
- Next action:

## Other Candidates

| Opportunity | Decision | Score | Why It Did Not Make Top 3 | Best Next Step |
|---|---|---:|---|---|
| <name> | observe / reject / validate_page | <0-100> | <reason> | <action> |

## Quick Validation Plan

| Experiment | What To Build | Success Signal | Timebox |
|---|---|---|---|
| SEO smoke test | <page/free tool/template> | <impressions/clicks/signups/community saves> | <duration> |
| Prototype | <flow> | <user completion/repeat use> | <duration> |

## Rejected Or Downgraded Ideas

| Idea | Why Not Now |
|---|---|

## Solo-Builder Filter

| Question | Answer |
|---|---|
| Can V1 ship in about 1 month? | yes/no/unclear |
| Can users self-serve without sales calls? | yes/no/unclear |
| Can acquisition rely on SEO/ASO/community/directories? | yes/no/unclear |
| Does V1 avoid heavy integrations? | yes/no/unclear |
| Does V1 avoid high support or compliance burden? | yes/no/unclear |
| Is there a narrow wedge against incumbents? | yes/no/unclear |

## Follow-Up Skill Handoffs

- Use `seo-new-keyword-discovery` when it is available and the recommended acquisition channel is SEO; otherwise run a lightweight built-in keyword/SERP pass.
- Use `vibe-prototype` when the interaction model is uncertain.
- Use `vibe-spec` when the user wants to turn the selected MVP into build-ready requirements.
```
