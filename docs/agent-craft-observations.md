# Agent-Craft Observations

A running log of agent-craft signals captured by the agent-craft distiller
during film-room sessions. Each entry records a failure mode that did
**not** meet the bar for an immediate prompt edit (single occurrence, not
severe enough to justify a one-shot guardrail, or ambiguous root cause).

When the same observation recurs across multiple versions or projects, a
future film-room session can promote it to an actual prompt edit against
`agents/coding.py`, `agents/review.py`, or `agents/testing.py`.

The distiller appends new entries below this header. Do not reorder.

---

## v0.12 — BryGo1995/paint-ballas-auto

**Date:** 2026-05-01
**Source:** https://github.com/BryGo1995/paint-ballas-auto/issues/248

- **Observation:** Review agent approved a producer-only PR (PR #247 generated map preview PNG thumbnails and their `.import` metadata for 5 layouts) without verifying any consumer in the running game actually loads or displays them. The merged PR shipped a complete producer pipeline whose output went unread; the human had to add a `PreviewImage` `TextureRect`, a `PREVIEW_DIR` constant, and a `_load_preview()` call to `map_select.gd` in a follow-up fix to close the loop.
  - **Agent:** review
  - **Fixes that motivated this:** #2 (wire map_select to display the generated map preview PNGs)
  - **Why it's not yet a prompt edit:** Single occurrence, and the root cause is muddied by the issue body itself instructing the coding agent "Do NOT touch: `scripts/map_select.gd` — the consumer; should not need changes since output paths and dimensions match what it already reads," which was factually wrong — the review agent followed the issue's incorrect scoping rather than independently grepping for any reference to the generated assets. Watch for repeat across versions: review agent rubber-stamping producer-only PRs whose downstream consumers were assumed by the issue but never verified.

