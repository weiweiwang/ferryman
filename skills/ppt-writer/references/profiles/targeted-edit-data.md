# targeted-edit-data

Use when the user asks to add or revise a data, comparison, table, or chart slide.

Portable limitation:

- Prefer regenerating a new version from the source/spec. Exact in-place PPTX
  mutation is not guaranteed.

Hard gates:

- Verify calculations before visual work.
- Keep units, denominators, and source dates visible.
- Use direct labels and compact tables when native charts cannot express the
  story cleanly.
- The inserted/rebuilt slide should match the surrounding deck grammar when a
  reference deck is supplied.
