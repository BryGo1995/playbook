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

## v0.10 — BryGo1995/paint-ballas-auto

**Date:** 2026-04-27
**Source:** https://github.com/BryGo1995/paint-ballas-auto/issues/219

- **Observation:** Coding agent hand-wrote stub binary-asset metadata sidecars (Godot `.import` files for new `.ogg` music tracks) without populating the engine-generated `path=` / `uid=` / `dest_files=` fields, then committed them. The engine treats stub sidecars as already-processed and skips re-import on fresh clones, producing a hard runtime load failure. The general agent failure mode is: when an agent generates a binary artifact whose metadata is normally populated by a build/import/lock pipeline, the agent fakes the metadata file it can't actually generate rather than running the pipeline.
  - **Agent:** coding
  - **Fixes that motivated this:** #1 (music `.import` metadata stub-incomplete on agent PR #215 / issue #209)
  - **Why it's not yet a prompt edit:** Single occurrence in this film-room session, and the example shape is engine-specific (Godot `.import` sidecars). One more occurrence — same project or different stack (e.g. stubbed lockfiles, stubbed generated proto/codegen metadata, stubbed `*.import`/`*.meta`/`*.lock`) — would justify a generic guardrail in `agents/coding.py` along the lines of "after generating any binary or pipeline-processed artifact, run the project's import/build/lock pipeline that populates its sidecar metadata before committing; never hand-author sidecar metadata files." Project distiller has already captured the engine-specific version in the project's CLAUDE.md (film-room v0.10 lesson #1).
