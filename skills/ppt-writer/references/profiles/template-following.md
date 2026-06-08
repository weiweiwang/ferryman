# template-following

Use when the user supplies a PPTX as the visual/template contract.

Portable limitation:

- This skill rebuilds new PPTX files with `pptxgenjs`; it does not guarantee
  exact in-place editing of a supplied PPTX.

Hard gates:

- Run `inspect_reference.py` and create `reference-audit.md`.
- Record what to preserve: typography, palette, spacing, image crops, page
  markers, and layout rhythm.
- Record what not to copy: weak slides, broken hierarchy, low-quality assets.
- If exact source-slide duplication is required, report that the current
  portable engine cannot guarantee it.
