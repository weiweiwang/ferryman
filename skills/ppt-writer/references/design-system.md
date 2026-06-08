# PPT Design System Rules

Default to a polished business deck, not a generic slide template.

## Canvas

- Use 16:9 widescreen (`13.333 x 7.5 in`) unless the user requests another size.
- Keep a consistent safe area: `0.65-0.85 in` left/right, `0.42-0.65 in` top,
  and `0.30-0.45 in` bottom.

## Typography

- CJK default: `PingFang SC` on macOS, fallback `Microsoft YaHei` or `Noto Sans CJK SC`.
- English default: use the same sans family for body; use a display weight for
  claims only if available.
- Claim title: `24-34 pt` for normal slides, `30-40 pt` for thesis slides.
- Body: `10.5-15 pt`.
- Table/chart labels: `7.5-10 pt`.
- Avoid relying on shrink-to-fit. Shorten copy or redesign the layout first.

## Palette

Use a three-layer palette:

- base surface: paper/off-white or deep ink.
- text: high-contrast ink and muted secondary text.
- accents: one primary and one secondary accent.

Avoid one-note decks where every slide is a variation of the same blue, purple,
beige, or gray. If using a calm executive palette, add a restrained secondary
contrast such as amber, green, or red-brown.

## Layout Grammar

- Every slide needs one dominant proof object.
- Avoid decorative boxes around prose.
- Cards must represent real grouping, comparison, or stages.
- Do not use more than two card-grid slides in a 10-slide deck.
- Do not let three consecutive slides share the same `layout_family`.
- Align page markers, kickers, titles, and footers consistently.

## Chart and Diagram Rules

- Direct-label charts whenever possible.
- Avoid legends that force the reader to look back and forth.
- Arrows are only for direction or sequence.
- Connectors must attach visually to their source and target.
- Equal-role boxes must share dimensions, padding, border, and text treatment.

## Brand and Asset Rules

- Do not invent logos, mascots, app icons, product screenshots, or partner marks.
- Use user-provided assets, verified official assets, or omit the identity asset.
- Record asset provenance in `source-notes.md`.

## Image-Led Decks

When the user asks for "图文并茂", an introduction deck, a news/event brief, a
profile, a travel/place deck, or any image-led output:

- Set `media_required=true` in `deck-spec.json`.
- Use real images with provenance, not decorative placeholders.
- At least the cover and 60% of non-appendix slides should include an image or
  screenshot.
- Prefer one strong image plus a small evidence rail over repeated text cards.
- If no verified image assets can be obtained, state the blocker rather than
  silently producing a text-only deck.
