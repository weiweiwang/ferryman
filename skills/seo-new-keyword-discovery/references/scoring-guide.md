# New Keyword Opportunity Scoring Guide

Use this guide to score emerging SEO keyword candidates. The score is a decision aid, not a substitute for judgment.

## Score Dimensions

Each dimension is scored from 1 to 5.

| Dimension | 1 | 3 | 5 |
|:--|:--|:--|:--|
| Freshness | Old, mature, fully covered | Some recent mentions or renewed interest | Clearly rising, newly named, or recently discussed across sources |
| Demand | No visible search or community signal | One credible signal, weak or ambiguous | Multiple demand signals such as Trends, autocomplete, PAA, GSC, or repeated community mentions |
| SERP Weakness | Strong brands and high-quality exact-match pages dominate | Mixed SERP with some weak or off-intent results | Obvious opening: thin pages, forums, subdomains, old content, poor Title/H1 match, or missing tool/page |
| Buildability | Requires heavy product, data, authority, or original research | Buildable with moderate content or light tooling | Can ship a useful page/tool quickly with available resources |
| Expansion | One-off query with no obvious cluster | Some related long-tails or adjacent pages | Clear matrix potential: templates, variants, languages, comparisons, or related tools |
| Monetization Fit | No clear value capture | Indirect value through traffic or brand | Clear ads, affiliate, lead, SaaS, directory, or product conversion path |

Total possible score: 30.

## Decision Bands

| Total | Default Decision | Meaning |
|:--|:--|:--|
| 24-30 | `build_now` | Strong enough to recommend immediate page/tool creation |
| 18-23 | `build_light` | Worth a small test page or narrow MVP, then monitor |
| 12-17 | `observe` | Interesting but not validated enough |
| 6-11 | `reject` | Too weak, too competitive, or poor fit |

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
- `gsc`: Google Search Console data provided by the user.
- `community`: credible community discussion or repeated mentions.
- `product_directory`: directory/ranking/launch platform signal.
- `competitor_page`: competitor page suggests active SEO targeting.
- `no_visible_signal`: no meaningful demand signal found.

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

## Red Flags

Downgrade or reject even if the numeric score is high:

- Query intent is a known brand, login, official download, or customer support target.
- The topic is YMYL and requires trust the user cannot credibly provide.
- The trend is based on speculative release dates or unconfirmed rumors.
- The page would only summarize other pages without original value.
- The keyword has traffic but no plausible monetization, audience fit, or strategic value.
- The SERP has a clear official source and users likely only want that source.

## Example Scoring

| Keyword | Freshness | Demand | SERP Weakness | Buildability | Expansion | Monetization | Total | Decision |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| `example ai generator` | 4 | 4 | 4 | 5 | 4 | 4 | 25 | `build_now` |
| `example product login` | 3 | 5 | 1 | 1 | 1 | 1 | 12 | `reject` due to navigational intent |
| `new game name unblocked` | 5 | 3 | 4 | 4 | 3 | 3 | 22 | `build_light` |
