# Deck Spec Template

Create `deck-spec.json` in the current session workspace under
`reports/<yyyy-mm-dd>/ppt-writer-<task_slug>/`.

Minimum structure:

```json
{
  "title": "Deck title",
  "subtitle": "Optional subtitle",
  "language": "zh-CN",
  "audience": "Decision makers",
  "theme": {
    "colors": {
      "bg": "F5F2EA",
      "ink": "141A17",
      "muted": "59635E",
      "accent": "944B3D",
      "accent2": "255D78",
      "gold": "B8791E",
      "hair": "D8D2C4",
      "white": "FFFFFF"
    },
    "font": {
      "heading": "PingFang SC",
      "body": "PingFang SC"
    }
  },
  "task_mode": "create",
  "primary_profile": "product-platform",
  "secondary_gates": [],
  "slide_size": "wide",
  "render_mode": "hybrid",
  "hybrid": {
    "raster_background": true,
    "background_mode": "skeleton",
    "editable_layer": "visible"
  },
  "media_required": false,
  "reference_constraints": {
    "target_slide_count": 6,
    "max_avg_text_chars_per_slide": 90,
    "max_text_chars_per_slide": 140,
    "min_image_slide_ratio": 0.5,
    "min_effective_image_slide_ratio": 0.5,
    "min_media_per_slide": 0.5
  },
  "source_summary": "One sentence about source basis.",
  "slides": [
    {
      "number": 1,
      "type": "cover",
      "layout": "cover-process",
      "layout_family": "cover",
      "kicker": "AI SALES",
      "claim": "The one-sentence claim this slide proves.",
      "proof_object": "three-stage process",
      "support": "Short factual support note.",
      "body": "Optional body copy.",
      "requires_image": false,
      "image": {
        "asset_id": "cover-hero",
        "path": "reports/<yyyy-mm-dd>/ppt-writer-<task_slug>/assets/source-image.jpg",
        "fit": "cover",
        "alt": "Short image description",
        "source": "Where the image came from"
      },
      "items": [
        { "label": "Input", "text": "Source data" },
        { "label": "System", "text": "Workflow or engine" },
        { "label": "Output", "text": "Business result" }
      ],
      "sources": ["User-provided notes"]
    }
  ]
}
```

Recommended slide fields:

- `task_mode`: one of the modes in `references/profile-router.md`.
- `primary_profile`: one of the ten profile names in
  `references/profile-router.md`.
- `secondary_gates`: optional strings such as `classroom-sharing`,
  `current-event`, or `template-inspired`.
- `reference_constraints`: optional thresholds copied from
  `reference-audit.json.recommended_constraints`.
- `render_mode`: use `hybrid` for visual-first/Codex-like decks; omit it or use
  `native` for simpler fully native decks.
  - `hybrid`: optional builder hint. In hybrid mode, bundled scripts generate
    controlled slide HTML and render it into PPTX. Default `background_mode:
    "skeleton"` plus `editable_layer: "visible"` keeps native PPTX layers while
    using HTML for composition. Pure screenshot output is available with
    `background_mode: "visual"` plus `editable_layer: "none"` for visual ceiling
    tests. These are the only valid mode pairs. Do not hand-write workspace HTML
    or scripts.
- `theme.template` or `visual_style`: optional visual pattern library. Current
  high-polish hybrid libraries include `premium-editorial` for strategy and
  `science-storybook` for documentary/science/classroom narratives.
- `number`: 1-based slide number.
- `type`: `cover`, `thesis`, `section`, `comparison`, `flow`, `timeline`,
  `metrics`, `table`, `quote`, `appendix`, or `generic`.
- `layout`: a concrete layout name from `references/slide-patterns.md`.
  For `science-storybook`, use page-level patterns such as
  `science-cover`, `time-river`, `scale-day`, `chapter-spread`,
  `mechanism-light`, `impact-reset`, `evidence-triptych`, and
  `closing-awe`.
- `layout_family`: concrete rhythm family used for QA, such as `cover-photo`,
  `photo-caption`, `timeline-grid`, `topic-grid`, `metric-rail`, or
  `takeaway-photo`. Do not use only a generic media label such as `image-led`
  across the whole deck.
- `kicker`: 1-4 words that frame the slide role.
- `claim`: conclusion title, not a topic label.
- `proof_object`: chart, table, flow, comparison, metric rail, or visual proof.
- `support`: concise factual note.
- `items`: list of cards, steps, metrics, rows, or timeline entries.
- `sources`: source names, URLs, or provenance notes.
- `media_required`: set to `true` at deck level when the user asks for
  image-rich, visual-first, news/event, profile, or "图文并茂" output.
  This is a deck-level coverage target. Not every slide needs media.
  - `requires_image`: set to `true` when the slide must include a real image.
    Use this only for image-led slides. Do not set it on every slide just
    because the deck is `media_required=true`.
- `image`: one primary image object with workspace-relative `path`, `alt`, and
  `source`. Prefer paths returned by `register_asset.py`.
- `images`: optional list of image objects for image-led layouts.
  - `fit`: optional image fit strategy, `cover` for photo-led hero slots and
    `contain` for screenshots or diagrams that must remain fully visible.
  - Pattern-specific media gates apply in QA. `impact-reset` expects a large
    visual; `evidence-triptych` expects three image instances; `time-river` and
    `scale-day` can be shape-led.
- `asset_id`: stable id from `asset-manifest.json`; optional but recommended.
- `register_asset.py` records asset metadata in `asset-manifest.json`,
  including `width`, `height`, `format`, `aspect_ratio`, `bytes`,
  `content_bbox`, `content_area_ratio`, and whether a padding crop was applied.
  Use those returned values to reject screenshots with huge empty borders or to
  choose `cover`/`contain`; do not create a workspace script to inspect image
  files.

Unsupported image fields:

- Do not use `download_images`, `image_urls`, `image_url`, `url`, `urls`, or
  slide-level `image_idx`.
- The builder embeds local image files only. Capture, provide, or generate the
  image into the workspace first, register it with `register_asset.py`, then
  reference it through workspace-relative `image.path` or `images[].path`. Keep
  the original URL in `source` for provenance.
- Do not write ad hoc workspace scripts to download images.

For appendix-only slides, `claim` may be short, but `proof_object` and `sources`
still matter.
