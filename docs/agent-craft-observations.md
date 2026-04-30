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

## v0.11 — BryGo1995/paint-ballas-auto

**Date:** 2026-04-30
**Source:** https://github.com/BryGo1995/paint-ballas-auto/issues/233

- **Observation:** Coding agent meets every literal acceptance-criterion bullet but ships features without sweeping for related surfaces or common interaction patterns the AC didn't enumerate. Two distinct manifestations in this session: (a) a new state flag (`quick_test_mode`) was wired up per AC — flag, toggle action, main-menu badge — but the map-select screen still showed the best-of-7 "Round 1 of 7" label and 7-dot scoreboard when quick-test was active; the agent didn't grep for other UI surfaces reading the round counter / `MAX_WINS`. (b) a new tuning panel (`custom_preset_panel.tscn`) shipped with three separate UI-interaction bugs at the target 640×360 resolution — content overflowed the viewport with no scroll container, mouse-wheel hovering over a slider changed its value instead of scrolling the list, and the vertical scrollbar overlapped the slider rows for lack of right-edge padding. None of these were enumerated in the AC; all are baseline interaction concerns the agent would have caught by exercising the panel once.
  - **Agent:** coding
  - **Fixes that motivated this:** #1 panel overflow, #2 wheel-on-slider, #3 scrollbar padding, #5 map-select quick-test label
  - **Why it's not yet a prompt edit:** the underlying discipline ("after meeting AC, sweep the codebase for related surfaces and verify common interaction patterns") is hard to specify generically without project-specific language; want to see this pattern recur across more sessions/projects before proposing a tightening of `agents/coding.py`.

