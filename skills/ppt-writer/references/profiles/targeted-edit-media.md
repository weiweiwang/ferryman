# targeted-edit-media

Use when the user asks to add or revise images, logos, headshots, screenshots,
or other media.

Portable limitation:

- Prefer rebuilding a new version from the source/spec. Exact in-place PPTX
  mutation is not guaranteed.

Hard gates:

- Verify media provenance.
- Do not draw or approximate logos, app icons, mascots, or signature marks from
  scratch.
- Crops must respect the subject's focal point and text-safe areas.
- If a reference deck is supplied, preserve its crop language and spacing.
