---
name: seo-new-keyword-discovery
description: Opportunity engine for emerging SEO keywords. Discovers seed terms, expands candidates through public search signals, audits SERP feasibility, and produces build-or-reject decisions for fast SEO page or micro-site opportunities.
version: 0.1.2
author: Ferryman
created: 2026-05-05
updated: 2026-05-17
---

# SEO New Keyword Discovery

**Quality Goal**: Find keywords worth building, not merely keywords worth noticing.

Act like a senior SEO strategist and product opportunity investor. The goal is not to produce a conventional keyword spreadsheet; the goal is to discover emerging search demand that can justify a small but useful product page, tool, template, workflow, or micro-site.

## Execution SOP
1. **Market Naming Discovery**: Identify how users are newly naming the problem, workflow, tool, format, platform change, model capability, regulation, role, or template need. Look for raw language, wrong words, long-tail combinations, alternatives, and newly repeated phrases.
2. **Seed Mining**: Expand candidates from user seeds, root words, public rankings, directories, site-to-site discovery, keyword-to-keyword expansion, competitor pages, sitemaps, autocomplete, related searches, PAA, public discussions, product communities, app/plugin stores, GitHub, YouTube, and public trend surfaces.
3. **Demand Check**: Validate demand with Google Trends when accessible, autocomplete, PAA, related searches, repeated public discussion, product-directory signals, competitor targeting, or multiple weak signals across independent sources. When using Google Trends, compare a query ladder: exact product terms, broader natural-language demand terms, and adjacent workflow terms. Do not treat a Trends value of `0` as absolute zero search volume; treat it as a weak relative signal that requires broader-term or alternate-source validation.
4. **Coverage Audit**: Identify which products, templates, directories, marketplaces, official sources, forums, and AI tools already cover the need. Separate broad incumbents from exact-match niche tools and record whether they solve the recurring workflow or only the one-off query.
5. **SERP Audit**: Inspect the visible results deeply enough to identify intent, exact-match coverage, the leader to beat, and the current opening. Check homepage vs inner page, Title/H1/URL match, weak hosted pages, forums, directories, thin/outdated/off-intent content, missing tools, and KD/DR/backlinks only when actually available.
6. **Product Gate**: Reject or downgrade candidates that are not AI-intensive, low-frequency, lack a user-data flywheel, or have unclear monetization.
7. **Counter-Check**: Record the decisive reason for the final verdict: tiny traffic ceiling, deceptively strong #1, official/navigational intent, unstable spike, weak monetization, weak AI value, weak retention, or incumbent coverage that already satisfies the recurring workflow.
8. **Scoring**: Apply `references/scoring-guide.md`, then assign `build_now`, `build_light`, `observe`, or `reject`.
9. **Packaging**: Save Strategy MD and CSV using `assets/report-template.md`. Link both in the final reply.

## Evidence Depth Policy

Use adaptive research depth based on opportunity maturity. Do not use fixed candidate counts as a substitute for judgment.

### Discovery Mode
Use when the topic is new, ambiguous, or product-direction oriented.
- Collect a broad candidate pool from at least 4 accessible source types, such as search surfaces, public discussions, competitor pages, directories, product communities, app/plugin stores, GitHub, YouTube, or trend surfaces.
- Do not require paid-tool volume. Emerging opportunities often have low, delayed, or unavailable volume in keyword tools.
- Promote a candidate only when it has at least one of these evidence patterns:
  - two independent weak demand signals;
  - one demand signal plus one clear SERP weakness;
  - one competitor/product signal plus a clearly buildable useful page.
- Reject or downgrade candidates that only have novelty, hype, or a single unverifiable mention.

### Validation Mode
Use when the user already provides a concrete keyword, product niche, URL, or target market.
- Audit the visible SERP deeply enough to identify the leader to beat, result types, intent match, exact-match coverage, and the smallest useful page that could compete.
- Prefer inspecting the top organic results that determine user intent; normally this means Top 5-10, but stop early if intent and competition are already decisive.
- Include an incumbent coverage table when the user asks whether a demand has opportunity, or when live research reveals direct product competition.
- Record why more depth was or was not needed when evidence is limited.

### Decision Mode
A `build_now` recommendation requires:
- a named user intent;
- concrete demand evidence;
- a specific SERP opening;
- a smallest useful page/tool shape;
- product-fit rationale covering AI intensity, repeat use, data flywheel, and monetization;
- explicit kill criteria.

## Output Contract
- **Strategy Report**: `reports/new-keyword-discovery-<topic>-<date>.md`
- **Keyword CSV**: `reports/new-keyword-discovery-<topic>-<date>.csv`
- **CSV Columns**: `keyword,source,source_url,trend_signal,demand_evidence,serp_weakness,product_gate,decision_rationale,kill_criteria,intent,page_type,minimum_useful_page,title_tag,h1,opportunity_score,decision,build_priority,notes`

## Decision Matrix
- **Build Now**: Strong demand + clear SERP weakness + feasible useful page + acceptable upside.
- **Build Light**: Promising but uncertain; test with a small but useful page.
- **Observe**: Interesting trend, but demand/intent is not yet stabilized.
- **Reject**: Weak demand, impenetrable SERP (e.g., official dominance), or low-value spike.

## Product Gate
A candidate must pass most of these to be `build_now`:
- **AI-intensive**: AI is the core value, not a cosmetic wrapper.
- **High-frequency**: users have recurring or multi-session need.
- **Data flywheel**: user inputs/results can improve personalization, templates, quality, or retention.
- **Clear monetization**: ads, affiliate, credits, subscription, leads, or upgrade path is plausible.

If a candidate fails two or more, default to `observe` or `reject` even if the keyword looks searchable.

## Recurring AI Product Fit

For new website product opportunities, prioritize recurring AI-native products over one-off generators. A candidate should normally satisfy all 3 core fit requirements before it can be `build_now`:

- **High-frequency use**: The user returns weekly, monthly, seasonally, or across repeated projects. One-time stressful tasks may be useful, but they are usually poor subscription products.
- **Retained data**: The product becomes more valuable when it remembers user inputs, history, preferences, documents, examples, clients, projects, or prior outputs.
- **AI-native workflow**: AI is required to deliver the main value through classification, extraction, reasoning, personalization, generation, agentic execution, or iterative improvement. Avoid ideas where AI merely fills a template that rules could handle.

Use these rules when judging common opportunity types:
- **One-off letter/document generators**: default to `observe` or `reject` unless the workflow repeats and stored case history materially improves outcomes.
- **Calculators/checklists**: default to `build_light` at most unless they become ongoing trackers or planners with retained data.
- **Professional workflow tools**: prefer these when they combine repeated usage, saved work history, and AI-assisted decision support.
- **Content/SEO operations tools**: prioritize when they connect recurring data imports, historical performance, and iterative recommendations.

## Human Verification Handling
If Google Search, Google Trends, or another high-value public source triggers human verification:
1. Ask the user to complete verification in the visible browser.
2. Wait up to 3 minutes unless the user sets another timeout.
3. Continue the original workflow if verification succeeds.
4. If it times out or the user declines, use fallback sources and mark affected fields as `blocked_by_verification` or `[limited]`.

Do not silently skip Google SERP/Trends when central to the decision. Do not loop retries.

## Quality Standards
1. **Fidelity**: No fabricated volume or KD. Label heuristic data as `[estimated]`.
2. **Evidence-Driven**: Every decision needs one concrete `decision_rationale` based on current evidence. Do not fill both generic go and no-go boilerplate.
3. **Traceability**: Include source URLs for all web-derived findings.
4. **Actionability**: Recommendations must include a suggested Title Tag and H1 for the new page.
5. **People-First**: Do not recommend thin SEO pages; recommend the smallest useful page that satisfies intent.

## Relationship to Other Skills
- Use `seo-keyword-research` for broader content roadmaps after niche selection.
- Use `seo-backlink-research` when selected keywords require link-building to compete.
- Use `ai-hotspot-miner` for trend articles rather than SEO tool/page selection.

## Final Pass
- **Language**: Match user prompt language.
- **Chinese Typography**: No spaces between Chinese characters and English words/numbers.
