# Profile Router

Choose `task_mode` first, then exactly one `primary_profile`. Put both in
`deck-spec.json`.

## Task Modes

- `create`: build a new deck from prompt, sources, or notes.
- `source-driven`: build from user documents, reports, or datasets.
- `template-inspired`: use a supplied PPTX/PDF/image as a quality/style
  reference, but rebuild a new portable PPTX.
- `targeted-regenerate`: regenerate a revised version from an existing spec or
  deck output.
- `template-following`: audit a supplied template/source deck and preserve its
  visual grammar where possible. In this portable skill, this is not exact
  in-place PPTX editing.
- `targeted-edit`: small local change request. Prefer regenerate unless a
  future exact-edit engine is available.

## Primary Profiles

- `finance-ir`: financial, investor, earnings, operating review.
- `product-platform`: SaaS, product, platform, workflow, product strategy.
- `gtm-growth`: GTM, growth, marketing, sales motion, subscription funnel.
- `engineering-platform`: AI, developer, infrastructure, security, data systems.
- `strategy-leadership`: board, executive, transformation, market strategy.
- `consumer-retail`: consumer, lifestyle, travel, classroom, people, places,
  product lookbooks, image-led storytelling.
- `template-following`: supplied source/template deck is the visual contract.
- `targeted-edit-data`: add or revise a data/comparison slide.
- `targeted-edit-media`: add or revise images, logos, screenshots, headshots.
- `appendix-heavy`: dense tables, source packs, disclosures, appendices.

## Routing Rules

- Pick the profile that creates the highest delivery risk.
- Put secondary concerns in `secondary_gates`, e.g. `["classroom-sharing",
  "current-event"]`.
- For a reference PPTX, run `inspect_reference.py` and copy its recommended
  constraints into `deck-spec.json.reference_constraints`.
- If the user provides a sample deck as a quality bar, treat it as a reference,
  not a template, unless they explicitly ask to follow the same template.
