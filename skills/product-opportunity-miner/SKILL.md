---
name: product-opportunity-miner
description: Discover and evaluate solo-builder-friendly product opportunities from real user demand signals such as Reddit posts, app reviews, forums, Product Hunt comments, Hacker News threads, competitor feedback, search language, and community complaints. Use when Codex needs to mine unmet needs, judge whether a pain point can become a small app, web tool, browser extension, micro SaaS, SEO-led product, or lightweight validation page, compare existing solutions and SEO feasibility, propose MVP wedges that can be built in about one month by an individual developer, or map raw user language into product concepts and go/no-go decisions.
---

# Product Opportunity Miner

## Objective

Mine real user pain into solo-builder-friendly product opportunities. Optimize for small apps, web tools, browser extensions, micro SaaS, SEO-led products, or validation-page ideas that an individual developer can plausibly ship and validate, not generic brainstorming.

## Core Rule

Anchor every opportunity in observed user behavior or language. Do not recommend a product idea unless the report can answer:

- Who has the pain?
- What are they trying to get done?
- What do they use today?
- Why are existing tools insufficient?
- Why could this become a product rather than only content?
- What is the smallest useful MVP?
- How would the first users find it?
- Can an individual developer build and validate it in about one month?
- Can acquisition work through SEO, ASO, directories, Reddit/community posts, or another low-touch channel?

## Workflow

### 1. Frame The Search

Infer or ask for the exploration scope:

- Domain or audience, such as productivity, couples, parents, creators, finance, health, study, travel, local services, or developers.
- Desired product type, if any: iOS app, web tool, extension, SaaS, marketplace, content site, or existing-product extension.
- Constraints: solo-builder feasibility, existing assets, target language, geography, platform, privacy, monetization, or timeline.
- Default exploration when the user does not specify a domain: broad discovery across several unrelated audiences and workflows, not a narrow continuation of the latest product discussed.
- Default constraints when the user does not specify constraints: individual developer, MVP in about 1 month, low-touch acquisition, SEO/ASO/community-friendly, minimal integrations, low support burden, no regulated advice, no marketplace cold start.

Ask at most one clarification question if scope is too broad to research meaningfully. Otherwise make a conservative assumption and proceed.

### 2. Collect Demand Signals

Use live web research when the user asks for fresh discovery, Reddit/community mining, market validation, or examples. Prioritize raw user language over polished marketing pages.

Use [references/source-playbook.md](references/source-playbook.md) for source selection and query patterns.

When running broad discovery, sample multiple categories before ranking. Use [references/source-playbook.md](references/source-playbook.md) for default category seeds.

For Reddit collection, prefer the bundled RSS collector before falling back to broad web search:

```bash
python3 scripts/reddit_rss_search.py "chore app" --limit 10
python3 scripts/reddit_rss_search.py "Notion too complicated" --subreddit productivity --limit 10
```

Read [references/reddit-data-acquisition.md](references/reddit-data-acquisition.md) when Reddit data is central to the task, when `.json` endpoints fail, or when deciding whether OAuth is needed.

Collect enough evidence to compare at least 3 candidate opportunities unless the user asks for one narrow topic. Prefer 6-12 high-signal sources over exhaustive scraping.

If an intended source is blocked, rate-limited, unavailable, or produces low-quality search results, pivot to the next best source instead of stalling. Record the blocked source and fallback path in the report.

### 3. Normalize Raw Signals

Convert posts, reviews, comments, and search phrases into opportunity notes:

- `User language`: short paraphrase or compliant excerpt.
- `Pain`: what hurts or wastes time.
- `Job`: what the user wants to accomplish.
- `Current workaround`: spreadsheets, paper, Notion, ChatGPT, manual labor, multiple apps, outsourcing, doing nothing.
- `Rejected alternatives`: tools users tried and abandoned.
- `Trigger moment`: when the need appears.
- `Frequency`: daily, weekly, seasonal, one-off, event-driven.
- `Data involved`: user inputs, history, files, preferences, location, health, social graph, receipts, photos, etc.

### 4. Decide Product Shape

For each candidate, choose the most plausible first product format:

- `iOS app`: use when capture, notification, camera, location, health, Apple Watch, or on-device habit loop matters.
- `Web tool`: use when sharing, SEO acquisition, desktop workflow, file upload, collaboration, or instant trial matters.
- `Browser extension`: use when the workflow happens inside another website.
- `Micro SaaS`: use when recurring business workflow, saved history, teams, or integrations matter.
- `Validation page`: use when demand is plausible but product risk is still high.

### 5. Apply Solo-Builder Gate

Read [references/solo-builder-fit.md](references/solo-builder-fit.md) before scoring when the user wants ideas suitable for an individual developer, one-month MVPs, SEO-led products, or low-touch validation.

Downgrade or reject opportunities that are attractive but too heavy for an individual developer, especially when they require:

- Broad CRM, ERP, field-service, finance, healthcare, legal, or compliance workflows.
- Payment processing, SMS sending, calendar sync, complex integrations, or customer support as core value on day one.
- Two-sided marketplace liquidity, enterprise sales, offline sales, or high-trust switching from incumbent systems.
- Mission-critical workflow ownership where bugs directly disrupt a user's business, money, health, or legal status.

Prefer opportunities where the first version can be a calculator, analyzer, tracker, checklist, planner, converter, generator, browser helper, template-powered tool, or narrow workflow dashboard.

### 6. Judge Go-To-Market Feasibility

Read [references/go-to-market-feasibility.md](references/go-to-market-feasibility.md) before scoring opportunities when the user cares about landing feasibility, competition, SEO, low-touch acquisition, or whether the idea is worth building.

For each serious candidate, evaluate:

- `Existing Solutions`: direct competitors, substitutes, spreadsheets/templates, incumbents, and whether they already solve the exact job.
- `SEO Feasibility`: search intent, likely keyword patterns, SERP shape, long-tail wedges, and whether a free tool/template page could earn traffic.
- `Acquisition Reality`: whether users can find the product through SEO, ASO, directories, Reddit/community posts, shareable outputs, or programmatic pages without sales.
- `Commercial Path`: plausible paid trigger, pricing shape, and whether value is strong enough for one-time payment, subscription, paid export, templates, affiliate, or ads.

Use lightweight live SERP checks for the top candidates when SEO is the primary acquisition thesis. Do not fake keyword volume; infer from query language, visible competitors, result types, and long-tail structure unless a keyword tool is explicitly available.

### 7. Score And Gate

Read [references/scoring-rubric.md](references/scoring-rubric.md) before assigning scores.

Use product decisions:

- `build_now`: strong pain, recurring use, clear MVP, plausible distribution, and acceptable competition.
- `prototype`: interaction or technical workflow is uncertain but promising.
- `seo_validate_first`: demand and product shape are promising, but SEO/competition must be validated with a landing page, free tool, or keyword test before building the full product.
- `validate_page`: demand language is promising but product commitment is premature.
- `observe`: signals are interesting but thin, ambiguous, or not urgent.
- `reject`: weak pain, one-off need, no feasible MVP, no monetization, or incumbents already satisfy the job.

If an opportunity depends primarily on search acquisition, include a lightweight SEO verdict now. Recommend a deeper follow-up with `seo-new-keyword-discovery` only when that skill is available and would materially change the decision; otherwise perform a lightweight built-in keyword/SERP pass using live search.

### 8. Package The Report

Use [references/output-template.md](references/output-template.md) for the final report structure.

Always include:

- Ranked opportunities.
- Summary table before detailed analysis.
- Evidence summary.
- Existing solutions and substitutes.
- SEO feasibility.
- Research limitations and fallback sources when relevant.
- MVP shape.
- Solo-builder fit, including one-month feasibility and distribution path.
- Core loop and retention hypothesis.
- Monetization hypothesis.
- Acquisition path.
- Final decision.
- Kill criteria.
- Rejected or downgraded ideas.

For broad reports, fully detail only the top 1-3 opportunities and summarize the rest in a compact table so the answer follows pyramid writing: conclusion first, supporting details second.

Match the user's language. For Chinese deliverables, avoid awkward spaces between Chinese and English terms unless needed for literal names, commands, paths, URLs, or code.

## Quality Bar

- Prefer specific workflow pain over broad market categories.
- Prefer narrow wedges that a solo developer can ship in days or weeks over broad platforms that need sales, support, and integrations.
- Treat a single viral post as weak evidence unless it reveals a repeatable job.
- Separate user demand, product opportunity, and SEO opportunity.
- Separate confirmed user language from interpretation.
- Treat competition as a feature of the decision, not an afterthought.
- Downgrade ideas that are only one-off generators, novelty wrappers, or thin ChatGPT prompts.
- Favor products with retained user data, repeated use, and a clear trigger moment.
