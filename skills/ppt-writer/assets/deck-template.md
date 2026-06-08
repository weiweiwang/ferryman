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
  "media_required": false,
  "reference_constraints": {
    "target_slide_count": 6,
    "max_avg_text_chars_per_slide": 90,
    "max_text_chars_per_slide": 140,
    "min_image_slide_ratio": 0.6,
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
- `number`: 1-based slide number.
- `type`: `cover`, `thesis`, `section`, `comparison`, `flow`, `timeline`,
  `metrics`, `table`, `quote`, `appendix`, or `generic`.
- `layout`: a concrete layout name from `references/slide-patterns.md`.
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
- `requires_image`: set to `true` when the slide must include a real image.
- `image`: one primary image object with workspace-relative `path`, `alt`, and
  `source`. Prefer paths returned by `register_asset.py`.
- `images`: optional list of image objects for image-led layouts.
- `asset_id`: stable id from `asset-manifest.json`; optional but recommended.
- `register_asset.py` records asset metadata in `asset-manifest.json`,
  including `width`, `height`, `format`, `aspect_ratio`, and `bytes`. Use those
  returned values to choose suitable screenshots or photos; do not create a
  workspace script to inspect image files.

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
