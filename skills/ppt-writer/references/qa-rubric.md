# PPT QA Rubric

QA is a blocking step, not a nice-to-have.

## Structural QA

Pass criteria:

- PPTX is a valid zip package.
- Required files exist: `[Content_Types].xml`, `ppt/presentation.xml`, and slide XML files.
- Slide count equals `deck-spec.json`.
- No empty media files.
- XML files parse successfully.

## Spec QA

Pass criteria:

- Deck has `title`, `audience`, and `slides`.
- Deck has `task_mode` and `primary_profile`.
- Each non-appendix slide has `claim`, `proof_object`, `layout`, and `layout_family`.
- Slide numbers are sequential.
- No three consecutive slides share the same concrete layout family. For
  image-rich decks, `layout_family` should still describe the rhythm, such as
  `cover-photo`, `photo-caption`, `timeline-grid`, or `takeaway-photo`, instead
  of repeating `image-led` on every slide.
- Claims read as conclusions, not topic labels.
- If the user asks for image-rich or "图文并茂" output, `media_required` must be
  true and the deck should set an explicit `min_image_slide_ratio`. Use 0.5 as
  the normal baseline; raise it only when the prompt or reference deck is
  strongly image-led.
- `media_required=true` is a deck-level media promise, not a rule that every
  slide must have a picture. Ordinary analysis slides may be text-only when the
  overall deck still has enough image coverage.
- If a slide sets `requires_image`, it must include an `image` or non-empty
  `images` list with provenance.
- Image paths must be workspace-relative local files. URLs belong in `source`,
  not in `image.path`.
- If `reference_constraints` are present, final PPTX metrics must stay within
  the text density and media density thresholds.
- `consumer-retail` requires media, provenance, and image-led rhythm.
- `classroom-sharing` requires short copy and 3-8 slides. Images should be used
  when they help the explanation; do not force every concept slide to carry a
  picture.

## Visual QA

Pass criteria when rendering is available:

- Contact sheet shows coherent rhythm and no obvious repeated template pattern.
- Slide text is readable at full size.
- No obvious text overflow, clipping, or object overlap.
- Charts, tables, connectors, and flows can be understood without speaker explanation.
- Brand or identity assets are verified or omitted.
- Image-led decks contain actual media files in the PPTX package. A deck with
  `media_required=true` and zero media files fails QA.
- Use `pictures_per_slide` to understand rendered image-instance density;
  `media_per_slide` only counts packaged media files.
- Use `effective_image_slide_ratio` and `weak_expected_image_slides` to catch
  slides where an image exists but is too small to carry the slide.
- Any visible `http://`, `https://`, or `www.` URL on a slide fails QA; source
  URLs belong in provenance fields, not rendered text.
- Slides that declare image intent through `requires_image`, `image`, `images`,
  or image/photo/screenshot layouts must render at least one actual picture,
  and the picture frame must meet the layout's minimum effective area.
- For `media_required=true`, extremely dense report-like slides fail, while
  moderately dense slides produce warnings for visual review.

## Iteration Triggers

Rebuild if any of these appear:

- `contact-sheet-scorecard.md` is FAIL.
- unsupported or invented metrics.
- missing source notes for factual claims.
- topic-only titles.
- more than two consecutive same-family layouts.
- tiny dense copy that relies on shrink-to-fit.
- tiny image frames on slides that promised an image.
- decorative boxes that do not encode structure.
- "图文并茂" decks with no real images or screenshots.
- reference-inspired decks that ignore the reference deck's text density, image
  density, or visual rhythm.
- rendered slide defects, including clipped text, unreadable labels, floating arrows, or misaligned tables.

## Comeback Scorecard

After structural QA and render preview, run `score_deck.py`. The scorecard is a
blocking delivery gate for serious decks:

- dimensions: story, specificity, rhythm, whitespace, visual proof, asset
  quality, precision, coherence.
- pass requires no underlying QA errors, total score at or above threshold, no
  dimension below 4, and no weak slides requiring iteration.
- weak slides should be rebuilt in batches of 2-4 before rerunning build,
  render, QA, and scorecard.
