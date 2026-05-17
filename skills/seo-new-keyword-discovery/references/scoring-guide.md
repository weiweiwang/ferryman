# New Keyword Opportunity Scoring Guide

Use this guide to score emerging SEO keyword candidates. The score is a decision aid, not a substitute for judgment.

## Score Dimensions

Each dimension is scored from 1 to 5.

| Dimension | 1 | 3 | 5 |
|:--|:--|:--|:--|
| Freshness | Old, mature, fully covered | Some recent mentions or renewed interest | Clearly rising, newly named, or recently discussed across sources |
| Demand | No visible search or public discussion signal | One credible signal, weak or ambiguous | Multiple demand signals such as Trends, autocomplete, PAA, public discussions, or product-directory momentum |
| SERP Weakness | Strong brands and high-quality exact-match pages dominate | Mixed SERP with some weak or off-intent results | Obvious opening: thin pages, forums, subdomains, old content, poor Title/H1 match, or missing tool/page |
| Buildability | Requires heavy product, data, authority, or original research | Buildable with moderate content or light tooling | Can ship a useful page/tool quickly with available resources |
| Expansion | One-off query with no obvious cluster | Some related long-tails or adjacent pages | Clear matrix potential: templates, variants, languages, comparisons, or related tools |
| AI Intensity | AI is incidental or cosmetic | AI improves output quality | AI is the core product value |
| Usage Frequency | Mostly one-off use | Occasional repeat use | Recurring workflow or multi-session need |
| Data Flywheel | User data does not improve product | Some personalization possible | Inputs/results can improve quality, templates, recommendations, or retention |
| Monetization Clarity | No clear value capture | Indirect value through traffic or brand | Clear ads, affiliate, credits, subscription, leads, or upgrade path |

Total possible score: 45.

## Decision Bands

| Total | Default Decision | Meaning |
|:--|:--|:--|
| 36-45 | `build_now` | Strong keyword and product opportunity |
| 27-35 | `build_light` | Worth a narrow MVP, then monitor |
| 18-26 | `observe` | Interesting but not validated enough |
| 9-17 | `reject` | Too weak, too competitive, or poor fit |

## Priority Labels

| Priority | Use When |
|:--|:--|
| `P0` | Build immediately; likely quick win and strategically aligned |
| `P1` | Build in the current batch after P0 items |
| `P2` | Keep in backlog or test lightly |
| `Watch` | Track trend/search behavior before building |
| `Reject` | Do not pursue now |

## Demand Evidence Labels

Use compact labels in CSV/report tables:

- `trends_rising`: Google Trends shows rising interest.
- `trends_stable`: Google Trends shows stable interest.
- `trends_spike`: Visible spike but durability unclear.
- `autocomplete`: Google autocomplete suggests the query or variant.
- `paa`: People Also Ask exposes adjacent questions.
- `public_discussion`: credible public discussion or repeated mentions.
- `product_directory`: directory/ranking/launch platform signal.
- `competitor_page`: competitor page suggests active SEO targeting.
- `no_visible_signal`: no meaningful demand signal found.

When Google Trends is used, record whether the signal came from an exact product term, a broader natural-language demand term, or an adjacent workflow term. A low or `0` exact-term value should downgrade exact-match confidence, not automatically reject the underlying market.

## SERP Weakness Labels

- `thin_content`: current pages are shallow or incomplete.
- `poor_exact_match`: Title/H1/URL does not clearly match the keyword.
- `forum_ranking`: forums or Q&A pages rank, implying weak dedicated content.
- `subdomain_ranking`: hosted subdomains or inner pages rank high.
- `old_content`: ranking pages appear stale.
- `off_intent`: ranking pages satisfy a different user intent.
- `missing_tool`: tool-shaped query lacks a good interactive tool.
- `weak_brand_serp`: no dominant authoritative brand result.
- `strong_serp`: SERP looks hard to beat.
- `limited_serp_access`: SERP access was blocked or incomplete.

## SERP Audit Checklist

Record concise evidence for:

- Result type: homepage, inner page, forum, directory, hosted subdomain, or official source.
- Title/H1/URL match: exact, partial, missing, or unknown.
- Intent match: strong, mixed, or off-intent.
- Content quality: useful, thin, outdated, or missing tool.
- Authority signal: strong brand, medium site, weak site, or unknown.
- KD/DR/backlinks: record only if actually available.

## Incumbent Coverage Checklist

When judging whether a demand is still open, classify visible products and pages:

- Broad suite: a larger product covers the workflow but may be too heavy for the target user.
- Exact-match tool: a focused product already targets the same keyword and use case.
- Template/content page: static assets satisfy one-off intent but may not solve recurring work.
- Marketplace/directory: listings prove demand but may not deliver a differentiated product.
- Official source: official or compliance-oriented intent may be hard to beat.
- Forum/discussion: users are asking for solutions, often a weak-content opportunity.

Downgrade when exact-match tools already satisfy the recurring workflow well. Keep or promote when incumbents are broad, heavy, off-market, region-specific, or only solve the one-off query while the recurring data workflow remains underserved.

## Product Gate

Before scoring, judge:

- AI intensity: Is AI essential to the value?
- Usage frequency: Will users return?
- Data flywheel: Do user inputs/results improve product quality or retention?
- Monetization clarity: Is the value capture path obvious?

Failing two or more means no `build_now`.

For new website product opportunities, `AI Intensity`, `Usage Frequency`, and `Data Flywheel` are core fit dimensions, not merely nice-to-have traits. A candidate with weak scores in any two of these three should not be `build_now`, even if demand and SERP weakness are strong.

Use stricter defaults for one-off task types:

| Opportunity Type | Default Cap |
|:--|:--|
| One-time letter/document generator | `observe` unless it has recurring case management or stored history |
| Single-use checklist | `observe` unless it becomes an ongoing tracker |
| Simple calculator | `build_light` unless saved data improves future recommendations |
| Template filler | `reject` if AI is not materially better than rules or static templates |
| Professional workflow system | Can be `build_now` when repeated usage, retained data, and AI-native reasoning are all present |

When a one-off task has strong search demand, record it as an SEO traffic opportunity, not necessarily a durable product opportunity.

## Decision Rationale

Write one evidence-specific verdict, not generic pros and cons. Examples:

- `build_light because SERP has exact demand but generic pages are crowded; only a KDP-printable sub-niche has a plausible opening.`
- `reject because the keyword is high-volume but AI is cosmetic, usage is one-off, and SERP is dominated by mature exact-match tools.`

## Kill Criteria

Reject or downgrade if:

- intent is official, login, download, or support;
- trend is a one-day spike;
- SERP is dominated by official or high-authority exact-match pages;
- useful page requires unavailable product/data;
- no monetization or strategic value exists;
- AI is not central to the product;
- usage is one-off and no retention loop exists;
- user data cannot improve the product experience;
- only a low-quality SEO page can be produced.

## Red Flags

Downgrade or reject even if the numeric score is high:

- Query intent is a known brand, login, official download, or customer support target.
- The topic is YMYL and requires trust the user cannot credibly provide.
- The trend is based on speculative release dates or unconfirmed rumors.
- The page would only summarize other pages without original value.
- The keyword has traffic but no plausible monetization, audience fit, or strategic value.
- The SERP has a clear official source and users likely only want that source.

## Example Scoring

| Keyword | Freshness | Demand | SERP | Build | Expansion | AI | Frequency | Data | Monetization | Total | Decision |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| `workflow ai generator` | 4 | 4 | 4 | 4 | 4 | 5 | 4 | 4 | 4 | 37 | `build_now` |
| `one-off ai novelty` | 4 | 4 | 3 | 4 | 2 | 2 | 1 | 1 | 2 | 23 | `observe` |
