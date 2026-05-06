---
name: seo-new-keyword-discovery
description: Opportunity engine for emerging SEO keywords. Detects fresh demand, validates SERP weaknesses, and generates build-or-reject decisions.
version: 0.1.1
author: Ferryman
updated: 2026-05-05
---

# SEO New Keyword Discovery

**Quality Goal**: Identify "Build Now" opportunities where fresh demand meets weak SERP results.

## Execution SOP
1. **Signal Scan**: Browse Reddit, HN, Product Hunt, GitHub, and niche forums for emerging topics or "seed" clues.
2. **Demand Validation**: Use Google Trends, Autocomplete, and "People Also Ask" to confirm search volume direction.
3. **SERP Audit**: Inspect ranking pages for weaknesses (e.g., thin content, off-intent results, outdated pages, or lack of dedicated tools).
4. **Scoring**: Apply the New Keyword Opportunity model from `references/scoring-guide.md`.
5. **Categorization**: Map candidates to **Intent** (Informational/Commercial/Transactional/Tool/Game) and **Page Type** (Single-tool/Micro-site/Listicle/Comparison).
6. **Packaging**: Save Strategy MD and CSV using `assets/report-template.md`. Link both in the final reply.

## Output Contract
- **Strategy Report**: `reports/new-keyword-discovery-<topic>-<date>.md`
- **Keyword CSV**: `reports/new-keyword-discovery-<topic>-<date>.csv`
- **CSV Columns**: `keyword, source, source_url, trend_signal, demand_evidence, serp_weakness, intent, page_type, opportunity_score, decision, build_priority, notes`

## Decision Matrix
- **Build Now**: Strong demand + clear SERP weakness + feasible page type.
- **Build Light**: Promising but uncertain; test with a small "thin" page first.
- **Observe**: Interesting trend, but demand/intent is not yet stabilized.
- **Reject**: Weak demand, impenetrable SERP (e.g., official dominance), or low-value spike.

## Quality Standards
1. **Fidelity**: No fabricated volume or KD. Label heuristic data as `[estimated]`.
2. **Evidence-Driven**: Every "Build Now" recommendation MUST cite a specific SERP weakness and demand signal.
3. **Traceability**: Include source URLs for all web-derived findings.
4. **Actionability**: Recommendations must include a suggested Title Tag and H1 for the new page.

## Relationship to Other Skills
- Use `seo-keyword-research` for broader content roadmaps after niche selection.
- Use `seo-backlink-research` when selected keywords require link-building to compete.
- Use `ai-hotspot-miner` for trend articles rather than SEO tool/page selection.

## Final Pass
- **Language**: Match user prompt language.
- **Chinese Typography**: No spaces between Chinese characters and English words/numbers.
