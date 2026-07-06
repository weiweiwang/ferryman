# Scoring Rubric

Score each opportunity from 0-100. Use evidence-weighted judgment rather than fake precision.

## Dimensions

| Dimension | Weight | What To Look For |
|---|---:|---|
| Pain intensity | 12 | Explicit frustration, urgency, embarrassment, anxiety, wasted time |
| Frequency | 9 | Daily/weekly/monthly or repeated project/event recurrence |
| Workaround pain | 8 | Spreadsheet, paper, multiple apps, manual copying, asking humans, abandoned systems |
| Productizability | 10 | Can be expressed as a clear tool with inputs, outputs, and workflow |
| One-month MVP simplicity | 12 | Individual developer can ship useful V1 in about 1 month without deep integrations |
| SEO/search feasibility | 12 | Search intent, tool/template/calculator keywords, reachable SERP, long-tail pages, or programmatic SEO angles |
| Low-touch distribution | 10 | SEO/ASO/search directories, templates, Reddit/community, content, or shareable outputs can acquire users |
| Retention | 8 | Saved history, reminders, repeated capture, personalization, ongoing data |
| Monetization | 8 | Subscription, one-time purchase, paid export, templates, affiliate, lightweight B2B, ads |
| Competitive gap | 9 | Incumbents too heavy, expensive, generic, enterprise, ugly, not mobile, missing niche, or do not serve the wedge |
| Operational risk | 2 | Low support, low trust barrier, low compliance, not mission-critical |

## Decision Thresholds

- `build_now`: 80+ with no fatal flaw, clear one-month MVP, acceptable competition, and credible low-touch distribution.
- `prototype`: 68-84 when workflow or technical feasibility needs proof but solo-builder fit is strong.
- `seo_validate_first`: 70-82 when demand and product shape are promising but SERP accessibility or search intent is the main uncertainty.
- `validate_page`: 58-74 when demand language exists but product, monetization, or channel risk remains high.
- `observe`: 40-59 when signal is interesting but thin or timing is uncertain.
- `reject`: below 40 or any fatal flaw.

## Fatal Flaws

Reject or downgrade heavily when:

- Need is one-off and has no natural retention.
- Existing free tools solve the exact job well.
- Product requires regulated/high-risk advice without a credible safety model.
- Acquisition depends on a SERP dominated by official or high-authority pages and no other channel exists.
- User data is too sensitive for a small product without a clear trust path.
- MVP requires unavailable data, partnerships, or platform permissions.
- MVP depends on payment processing, SMS, email deliverability, calendar sync, bank/accounting sync, or multiple APIs before it is useful.
- Business requires direct sales, onboarding calls, migration, or customer support that an individual developer cannot sustain.
- Product competes head-on with mature all-in-one platforms without a narrow wedge.
- SEO is the only acquisition plan, but the reachable keyword set is tiny, purely informational, or dominated by official/high-authority results with no long-tail wedge.

## Product Shape Hints

- Choose `iOS app` when the core loop is capture, reminders, camera, health, location, Apple Watch, offline use, or habit.
- Choose `web tool` when users need upload, share, export, desktop work, SEO discovery, or instant trial.
- Choose `extension` when the pain occurs inside a browser workflow.
- Choose `micro SaaS` when saved records, accounts, billing, teams, integrations, or recurring professional work matter.
- Choose `validation page` when the user language is promising but product format is not yet proven.
