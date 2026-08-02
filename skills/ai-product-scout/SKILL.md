---
name: ai-product-scout
description: >
  End-to-end AI product case-study workflow. Discovers and qualifies recent AI
  products, excludes previously covered companies and products, and produces an
  evidence-backed research brief, publishable article, HTML, and requested media.
metadata:
  version: 0.1.0
  author: Ferryman
  created: 2026-03-17
  updated: 2026-08-02
---

# AI Product Scout

## Goal

Produce a publication-ready AI product commercialization story that earns the click, sustains reading, and rewards unfamiliar readers with a useful, evidence-backed insight.

## Output Contract

Every successful run writes these files under `reports/<yyyy-mm-dd>/` using [assets/report-template.md](assets/report-template.md):

1. `ai-product-scout-<case_slug>.md`: research brief
2. `ai-product-case-article-<case_slug>.md`: publishable article
3. `ai-product-case-article-<case_slug>.html`: formatted article

Use a short lowercase ASCII slug. Keep the article Markdown publication-ready: one H1 title followed only by the final body. Research process, candidate comparisons, and selection rationale belong in the brief.

When usable tooling is available, create one title-specific cover as `ai-product-cover-<case_slug>.<ext>`. For single-case articles, attempt one official product image or video as `ai-product-visual-<case_slug>.<ext>` or `ai-product-media-<case_slug>.<ext>`.

Render the article with the bundled `scripts/render_article_html.py`; outside this skill directory, call it by absolute path. Report only files that actually exist.

## Publication Gate

Assess 3-5 candidates after duplicate exclusion. Publish a featured case only when all of these are true:

- AI is integral to a clear product workflow with a legible buyer and value.
- Evidence includes a concrete monetization signal such as pricing, paid contracts, revenue, or a verified transaction model.
- Evidence includes a separate adoption or growth signal.
- The case supports one timely, case-specific editorial thesis with a real consequence and at least two concrete proof points.

Funding alone, investor enthusiasm, or an unspecified partnership does not establish monetization. If reasonable discovery cannot produce a qualifying case, stop and report the missing evidence; do not produce article deliverables or update coverage history.

## Evidence Standard

Use enough meaningful sources to verify the product, business model, traction, and central thesis; 4-8 is usually sufficient. Discovery sources can surface candidates, but material claims should come from checked product surfaces, credible reporting, pricing, contracts, customer evidence, or other public records.

Link material facts where they support the argument. Identify company and founder metrics clearly and naturally as self-reported, without letting source caveats dominate the opening or interrupt the narrative. Keep confirmed facts, interpretation, and uncertainty distinguishable in the brief and in the article's wording.

## Editorial Standard

- Open with a concrete situation or decision that makes the product, user, value, and stakes immediately legible.
- Build a causal story around a consequential choice under constraint and its effect on adoption, monetization, or advantage.
- Sustain momentum by making each section alter the stakes or reveal a new consequence. Use concrete actors, outcomes, and evidence to change what the reader understands.
- Derive the title from the case's distinctive mechanism, customer, or commercial tension. For Chinese articles, keep it within 18-28 characters and make a specific promise the article fulfills.
- Develop the story far enough to explain the product mechanism, commercial outcome, transferable insight, and material limits. Let it determine its structure and length, then end on the implication with the highest decision value.
- Write natural Chinese publication prose and remove unnecessary spaces around adjacent Chinese, English, numbers, and units.

## Visual Standard

The opener must visibly explain the product through its interface, workflow, output, mechanism, or customer use. Inspect it before inclusion; when no useful official asset exists, record the reason in the brief. Verify the local file and its rendered HTML tag. WeChat GIFs must contain no more than 300 frames.

The cover should express one concrete subject, action, or consequence from the article and remain recognizable at WeChat thumbnail size. Deliver the requested dimensions and verify them. Cover art sells the story; opener media explains the product.

## Coverage History

Use `reports/ai-product-scout-history.json` only to exclude previously covered companies and products. Match product names, slugs, homepage variants, and domains. If the index is missing, build it from the current `reports/` root with the bundled history script; otherwise merge current reports into it. Refresh it only after a successful publication run.

Historical articles do not supply the current angle, title, structure, or prose. A covered product may be selected only when the user explicitly requests an update or rewrite.

## Final Quality Gate

Before completion, confirm:

- The case still passes every Publication Gate requirement.
- The title earns attention and the opening makes the product, stakes, and reason to continue immediately clear.
- Choices and consequences sustain momentum; repeated explanation and routine lessons are removed; the ending delivers the promised insight.
- Material facts are linked and caveated, and no research-only content appears in the article.
- Generated article, HTML, cover, and opener media are internally consistent and usable.
