---
name: ppt-writer
description: >
  Use this for creating, improving, QAing, and exporting portable PowerPoint
  PPTX decks inside the current Ferryman session workspace. Use for Chinese or
  English business decks, sales proposals, product strategy decks, investor or
  management updates, and deck-spec-driven PPTX generation without relying on
  Codex internal artifact runtimes.
version: 0.1.0
author: Ferryman
created: 2026-06-04
updated: 2026-06-04
---

# PPT Writer

You are a presentation strategist, designer, and build engineer. Produce
editable PowerPoint decks with a repeatable quality loop: narrative planning,
structured deck specification, portable PPTX generation, rendering when
available, visual QA, and iteration.

## Non-Negotiables

- Do not rely on `@oai/artifact-tool`, `artifact_tool_utils.mjs`, or Codex
  internal runtimes. Portable build paths are the native `pptxgenjs` builder
  and the preferred HTML-first hybrid builder.
- Ferryman's `run_skill_script` can only execute files bundled under this
  skill's `scripts/` directory. Do not create ad hoc executable scripts in the
  workspace and try to run them. Workspace files are inputs and outputs, passed
  to bundled scripts as arguments.
- Use Python wrapper scripts for execution. In particular, call
  `build_deck.py` or `build_hybrid_deck.py`; do not call `.js` builders
  directly through `run_skill_script`.
- Write all generated files inside the current Ferryman session workspace.
  Use workspace-relative paths in plans and scripts. Bundled scripts reject
  paths that escape the workspace.
- Default output directory:
  `reports/<yyyy-mm-dd>/ppt-writer-<task_slug>/`
- Keep final deliverables and QA artifacts together in the output directory.
  Do not use repo-root `reports/`, `outputs/<thread-id>/`, OS temp folders, or
  hidden scratch directories unless the user explicitly requests another
  workspace-relative location.
- Do not deliver a final PPTX until the required QA steps have run. If rendering
  QA cannot run because LibreOffice or a PDF renderer is unavailable, state that
  clearly and complete structural/spec QA.
- Prefer editable PowerPoint primitives: text boxes, shapes, lines, tables, and
  chart-like shape systems. Use raster images only when they are actual source
  images, screenshots, generated illustrations, or visual references.
- For visually polished, Codex-like decks, prefer HTML-first hybrid mode:
  controlled HTML plans the composition, a skeleton background is rendered, and
  visible native PPTX text/image/shape layers are placed over it. This is the
  default. Pure screenshot output is optional, not the default.
- Hybrid mode has only two valid mode pairs:
  `--background-mode skeleton --editable-layer visible` for editable decks, or
  `--background-mode visual --editable-layer none` for screenshot-only visual
  ceiling tests. Do not mix visual backgrounds with visible native overlays.
- For documentary, classroom, science, history, or storybook-style topics,
  prefer the `science-storybook` hybrid pattern library instead of applying
  generic business/report templates. Use concrete page patterns such as
  `science-cover`, `time-river`, `scale-day`, `chapter-spread`,
  `mechanism-light`, `impact-reset`, `evidence-triptych`, and `closing-awe`.
- If the user asks for "图文并茂", image-rich, introduction, profile, venue,
  travel, product, or news/event decks, set `media_required=true` in
  `deck-spec.json` and include real image assets with provenance. This is a
  deck-level requirement: not every slide must contain media, but the final deck
  must have strong overall image coverage and any slide that declares image
  intent must render a real picture.
- Image fields must reference real local files under the current workspace.
  Use workspace-relative slide-level `image.path` or `images[].path`; keep URLs
  in `source` or `sources` for provenance only. Do not invent
  `download_images`, `image_urls`, `image_url`, `url`, or `image_idx` fields;
  QA and the builder reject them.
- Do not create workspace scripts to download images. Use browser screenshots,
  user-provided image files, or image generation. Then register the local file
  with bundled `register_asset.py`.
- Do not create any workspace Python, JavaScript, shell, or other executable
  helper scripts for inspection, downloading, conversion, rendering, contact
  sheets, or cleanup. If a capability is missing, use an existing bundled script
  under this skill's `scripts/` directory or report the blocker.
- For CJK decks, follow Ferryman typography convention: no spaces between
  Chinese characters and English/numbers unless the source text requires it.

## Task Modes

- `create`: Build a new deck from the user's prompt and sources.
- `source-driven`: Build a new deck from documents, notes, data, or prior
  reports.
- `targeted-regenerate`: Apply requested changes by regenerating the deck or a
  new version from the source/spec. Exact in-place editing of an existing PPTX is
  not guaranteed in this portable skill.
- `template-inspired`: Use a supplied PPTX/PDF/image as a visual reference, but
  do not promise exact clone/edit fidelity unless a future template-edit engine
  is available.

If the user requires exact mutation of an existing PPTX template, explain the
limitation and offer the closest portable option: rebuild a new editable PPTX
using the template's observed typography, palette, spacing, and layout grammar.

## Ferryman Tool Usage Contract

Inside Ferryman, use `run_skill_script` only for bundled scripts in this skill's
`scripts/` directory. The current working directory is already the session
workspace.

Allowed calls:

- `run_skill_script(script_name="check_deps.py", args=[])`
- `run_skill_script(script_name="check_deps.py", args=["--require-hybrid"])` when the task needs the HTML-first hybrid path.
- `run_skill_script(script_name="inspect_reference.py", args=["--pptx", "<reference.pptx>", "--out", "<workspace-relative reference-audit.md>", "--json-out", "<workspace-relative reference-audit.json>"])`
- `run_skill_script(script_name="register_asset.py", args=["--source", "<workspace-relative screenshot-or-image>", "--id", "<asset-id>", "--asset-dir", "<task-dir>/assets", "--manifest", "<task-dir>/asset-manifest.json", "--source-note", "<url or provenance>", "--role", "<slide role>", "--alt", "<alt text>"])`
- `run_skill_script(script_name="build_deck.py", args=["--spec", "<workspace-relative deck-spec.json>", "--out", "<workspace-relative output.pptx>"])`
- `run_skill_script(script_name="build_hybrid_deck.py", args=["--spec", "<workspace-relative deck-spec.json>", "--out", "<workspace-relative output.pptx>"])`
- Optional pure screenshot mode for visual ceiling tests only:
  `run_skill_script(script_name="build_hybrid_deck.py", args=["--spec", "<workspace-relative deck-spec.json>", "--out", "<workspace-relative output.pptx>", "--background-mode", "visual", "--editable-layer", "none"])`
- For hybrid debugging only: `build_html_deck.py`, `render_html_deck.py`, and
  `build_hybrid_pptx.py` may be run individually with workspace-relative
  inputs/outputs. Do not replace them with workspace scripts.
- `run_skill_script(script_name="inspect_pptx.py", args=["--pptx", "<workspace-relative output.pptx>", "--expected-slides", "<n>"])`
- `run_skill_script(script_name="qa_deck.py", args=["--spec", "<workspace-relative deck-spec.json>", "--pptx", "<workspace-relative output.pptx>", "--out", "<workspace-relative qa-report.md>", "--json-out", "<workspace-relative qa-report.json>"])`
- `run_skill_script(script_name="render_deck.py", args=["--pptx", "<workspace-relative output.pptx>", "--out-dir", "<workspace-relative preview-dir>"])`
- `run_skill_script(script_name="make_contact_sheet.py", args=["--output", "<workspace-relative contact-sheet.png>", "<slide png 1>", "<slide png 2>"])`
- `run_skill_script(script_name="score_deck.py", args=["--spec", "<workspace-relative deck-spec.json>", "--qa-json", "<workspace-relative qa-report.json>", "--preview-dir", "<workspace-relative preview-dir>", "--out", "<workspace-relative contact-sheet-scorecard.md>", "--json-out", "<workspace-relative contact-sheet-scorecard.json>"])`

Forbidden calls:

- Do not pass a workspace script path as a positional argument to
  `inspect_pptx.py`; it requires `--pptx`.
- Do not create `check_deps.py`, `build.py`, or other executable helper scripts
  in the workspace and try to run them through `run_skill_script`.
- Do not write ad hoc workspace Python/JS/shell scripts, including scripts for
  image inspection, image download, conversion, rendering, or contact sheets.
- Do not call `build_deck.js` directly through `run_skill_script`; call
  `build_deck.py`.
- Do not use shell globs such as `preview/slide-*.png` in
  `run_skill_script` args; pass explicit file paths after listing or knowing
  the rendered files.

## Required Workflow

1. **Set up workspace paths**
   - Use `reports/<yyyy-mm-dd>/ppt-writer-<task_slug>/`.
   - Create or maintain these files as the work proceeds:
     - `source-notes.md`
     - `reference-audit.md` and `reference-audit.json` when a sample deck is
       supplied
     - `profile-plan.md`
     - `claim-spine.md`
     - `design-system.md`
     - `contact-sheet-plan.md`
     - `asset-manifest.json` when media is used
     - `deck-spec.json`
     - `qa-report.md`
     - `qa-report.json`
     - `contact-sheet-scorecard.md` and `contact-sheet-scorecard.json`
     - `weak-slides.md` whenever scorecard fails
     - `output/<deck_title_slug>.pptx`
     - optional `preview/` and `contact-sheet.png` when rendering works.
2. **Choose task mode and profile**
   - Read [references/profile-router.md](references/profile-router.md).
   - Choose `task_mode`, one `primary_profile`, and optional
     `secondary_gates`.
   - For profile-specific gates, read only the relevant file under
     `references/profiles/`.
   - Write `profile-plan.md` with the mode, profile, gates, required proof
     objects, asset rules, and QA blockers.
3. **Audit reference decks when supplied**
   - If the user supplies a PPTX as a quality reference or template inspiration,
     run `inspect_reference.py` and save `reference-audit.md` plus
     `reference-audit.json` in the task directory.
   - Use the audit's recommended constraints in
     `deck-spec.json.reference_constraints`.
   - Treat a reference deck as a quality bar, not an exact clone contract, unless
     the user explicitly asks for template following.
4. **Extract the source story**
   - Capture facts, claims, source links, assumptions, and missing inputs in
     `source-notes.md`.
   - Never invent metrics, customer names, logos, product UI, or partner marks.
   - For current or recent events, verify the premise with current sources,
     record exact dates, places, participants, and reported outcomes, and cite
     source URLs in `source-notes.md`. Avoid vague diplomatic boilerplate when
     specific reported details are available.
5. **Acquire media as workspace assets**
   - Prefer user-provided files, browser screenshots of official/source pages,
     or generated images. Do not download images through ad hoc workspace
     scripts.
   - For browser capture, navigate to the source, take a screenshot, list
     `screenshots/`, then register the chosen file. `register_asset.py`
     returns and records image metadata including `width`, `height`, `format`,
     `aspect_ratio`, `bytes`, `content_bbox`, `content_area_ratio`, and whether
     obvious flat padding was cropped:
     `run_skill_script(script_name="register_asset.py", args=["--source", "screenshots/<file>.jpg", "--id", "cover-hero", "--asset-dir", "<task-dir>/assets", "--manifest", "<task-dir>/asset-manifest.json", "--source-note", "<source URL>", "--role", "cover hero", "--alt", "<description>"])`
   - Use the returned `asset.path` in `deck-spec.json` as `image.path` or
     `images[].path`.
   - Reject or recapture assets whose content area is tiny after registration;
     avoid using full browser/search-result pages as hero imagery.
6. **Write the claim spine**
   - Every non-appendix slide needs a claim title, a proof object, and a support
     note.
   - Avoid topic titles such as `Revenue Trends`; use conclusion titles.
7. **Lock the design system**
   - Define slide size, language, fonts, palette, page marker grammar, chart
     grammar, table grammar, and banned motifs.
   - Use [references/design-system.md](references/design-system.md) when the
     design direction is not already specified.
8. **Plan the contact sheet**
   - Write `contact-sheet-plan.md` before building. It must name the intended
     macro-layout rhythm, which slides are visual-led vs text-led, the proof
     object on each slide, and the weak-slide failure modes to avoid.
   - For 8+ slide decks, plan at least four distinct macro-layout families; for
     10+ slide decks, aim for five or more. Avoid three consecutive slides with
     the same visual cadence.
9. **Create `deck-spec.json`**
   - Treat deck-spec as the deck blueprint: title, audience, theme, and slide
     objects with `claim`, `proof_object`, `layout`, and content fields.
   - Include `task_mode`, `primary_profile`, `secondary_gates`, and
     `reference_constraints` when available.
   - Use concrete `layout_family` values for rhythm QA. For image-led decks,
     vary families such as `cover-photo`, `photo-caption`, `timeline-grid`,
     `topic-grid`, and `takeaway-photo`; do not label every slide `image-led`.
   - For image-led decks, set `media_required=true`; add slide-level `image`,
     `images`, or `requires_image` fields with source provenance. Store the
     actual image file in the workspace and point `image.path` at that file.
   - Set `render_mode: "hybrid"` for visual-first, Codex-like, image-rich,
     reference-inspired, or consumer-facing decks. Use the native builder for
     simple internal decks where maximum native editability is more important
     than visual finish.
   - `media_required=true` is a deck-level coverage target, not a command to
     put images on every slide. Mark only truly image-led slides with
     `requires_image`, `image`, `images`, or photo/screenshot layouts; ordinary
     timeline, comparison, metric, and analysis slides may be text/shape-only.
   - On image objects, use `fit: "cover"` for photo-led hero slots and
     `fit: "contain"` for screenshots, documents, or diagrams that must remain
     fully visible.
   - Use [assets/deck-template.md](assets/deck-template.md) for the expected
     structure.
10. **Build the PPTX**
   - First check runtime readiness:
     `run_skill_script(script_name="check_deps.py", args=[])`
   - For high-visual decks, check hybrid readiness and use the default hybrid
     pipeline:
     `run_skill_script(script_name="check_deps.py", args=["--require-hybrid"])`
     `run_skill_script(script_name="build_hybrid_deck.py", args=["--spec", "<deck-spec.json>", "--out", "<output.pptx>"])`
     This creates `html/`, `preview-hybrid/`, and `layout.json` next to the
     spec unless explicit workspace-relative paths are provided. The default is
     `--background-mode skeleton --editable-layer visible`.
     The hybrid builder stops when rendered HTML text boxes overflow; revise the
     slide copy/layout instead of forcing delivery.
   - Use pure screenshot output only when explicitly testing the visual ceiling
     or when the user does not need editable PPTX layers:
     `--background-mode visual --editable-layer none`.
   - For simple native decks, use bundled `scripts/build_deck.py`, which
     invokes the Node `pptxgenjs` builder:
     `run_skill_script(script_name="build_deck.py", args=["--spec", "<deck-spec.json>", "--out", "<output.pptx>"])`
   - If `pptxgenjs` is not installed in the skill package, install/package the
     skill dependency with the checked-in lockfile, for example
     `npm ci --prefix skills/ppt-writer`, rather than switching to Codex
     internal runtimes.
11. **Run QA**
   - Run structural/spec QA:
     `run_skill_script(script_name="qa_deck.py", args=["--spec", "<deck-spec.json>", "--pptx", "<output.pptx>", "--out", "<qa-report.md>", "--json-out", "<qa-report.json>"])`
   - Run render QA when local render dependencies are available:
     `run_skill_script(script_name="render_deck.py", args=["--pptx", "<output.pptx>", "--out-dir", "preview"])`
   - Create a contact sheet when slide PNGs exist:
     `run_skill_script(script_name="make_contact_sheet.py", args=["--output", "contact-sheet.png", "preview/slide-01.png", "..."])`
   - Run the comeback scorecard:
     `run_skill_script(script_name="score_deck.py", args=["--spec", "<deck-spec.json>", "--qa-json", "<qa-report.json>", "--preview-dir", "preview", "--out", "<contact-sheet-scorecard.md>", "--json-out", "<contact-sheet-scorecard.json>"])`
12. **Iterate weak slides**
   - If QA or scorecard fails, write `weak-slides.md` from the scorecard's weak
     slide list, rebuild the weakest 2-4 slides first, then rerun build, render,
     QA, and scorecard.
   - Do not deliver just because a PPTX exists. Delivery requires structural QA
     pass plus contact-sheet scorecard pass, unless render dependencies are
     unavailable and that limitation is explicitly reported.

## Quality Gates

Before final delivery:

- PPTX exists and is non-empty.
- Expected slide count matches `deck-spec.json`.
- No empty media files.
- If `media_required=true`, the final PPTX contains media files and the QA
  report does not flag missing slide images, visible URLs, or report-like text
  density.
- Media assets used by the deck are recorded in `asset-manifest.json`.
- Slides that promise an image have meaningful rendered picture area; tiny
  corner thumbnails fail QA even when the PPTX technically contains a picture.
- Pattern-specific media gates apply. For example, `impact-reset` expects a
  large visual, and `evidence-triptych` expects three rendered images. Timeline,
  scale, comparison, and analysis slides may remain text/shape-led when the
  deck-level image coverage is strong.
- In hybrid decks, full-slide raster backgrounds do not count as proof/media
  coverage. QA only counts content pictures layered over the background.
- `qa-report.md` exists and records pass/fail status.
- `contact-sheet-plan.md` exists before build.
- `contact-sheet-scorecard.md` exists after QA. It must PASS before final
  delivery when rendering/scorecard inputs are available.
- If `contact-sheet-scorecard.md` fails, `weak-slides.md` lists the slides to
  rebuild and the deck is not final.
- `task_mode` and `primary_profile` are present in `deck-spec.json`.
- Each non-appendix slide has a claim, proof object, and support note.
- Reference constraints pass when a reference audit is used.
- No three consecutive slides use the same concrete layout family.
- Slides with `requires_image`, `image`, `images`, or image/photo/screenshot
  layouts render actual pictures. Ordinary analysis slides may be text-only.
- No visible `http://`, `https://`, or `www.` URLs appear on slides; source URLs
  belong in `source`/`sources` provenance.
- Contact sheet has been reviewed when rendering is available.
- Final reply links the PPTX and QA report with absolute local file paths.

## References

- Use [references/design-system.md](references/design-system.md) for visual
  system rules.
- Use [references/profile-router.md](references/profile-router.md) for task mode
  and profile selection.
- Use [references/slide-patterns.md](references/slide-patterns.md) for supported
  layout families.
- Use [references/qa-rubric.md](references/qa-rubric.md) for QA scoring and
  iteration rules.
