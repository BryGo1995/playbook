# Metrics File Format

This is the authoritative reference for the metrics files written by the playbook plugin. Both `skills/gameplan/SKILL.md` (Component 1) and `skills/film-room/SKILL.md` (Component 2) produce these files.

Metrics files live at `metrics/` in the **project repo** (not the playbook repo). They are written and committed by the skills during their normal flow.

## File types

- `metrics/vX.Y.md` — per-version source of truth. One file per version. Bootstrap uses `metrics/bootstrap.md`.
- `metrics/SUMMARY.md` — cross-version rollup. Auto-regenerated at end of every film-room session.

## Per-version file (`metrics/vX.Y.md`)

YAML frontmatter + markdown body.

### Frontmatter schema

```yaml
version: v0.3                   # string — version label, or "bootstrap"
date: 2026-04-24                # ISO date — when the file was last written
issues: 3                       # int — number of issues in this version
first_pass_clean: 1             # int — issues that required zero film-room fixes
fixes_total: 9                  # int — total fixes made in film-room for this version
failures:                       # dict[str, int] — counts per failure tag. Omit tags with zero.
  gameplan-criteria: 4
  coding-misread: 2
  gdd-gap: 1
iterations:                     # dict[str, int] — counts per iteration tag. Omit tags with zero.
  design-change: 2
cost_usd: 4.87                  # float — total agent spend for this version (including classifier)
```

Omit `failures` and `iterations` keys entirely if the version was first-pass clean (`fixes_total: 0`).

### Body sections

Two sections, written by two different skills:

1. `## Structural check (gameplan)` — written by Component 1 during gameplan Phase 4.
2. `## Classification (film-room)` — written by Component 2 as the distiller-peer subagent in film-room.

If a version is first-pass clean, only the structural check section appears and the classification section is replaced with `_No fixes made — classification skipped._`

## Summary file (`metrics/SUMMARY.md`)

No frontmatter. Plain markdown. Auto-regenerated from the frontmatter of all `metrics/v*.md` files at end of every film-room session.

Sections:

1. `# Playbook Metrics` — the title.
2. A markdown table with one row per version: `Version | First-pass | Fixes | Top failure | Cost | Date`. Sort descending by version.
3. `## Current top failure modes (last 3 versions)` — summed failure counts across the most recent 3 versions, ranked.
4. `## Trends` — for each failure tag that appears in at least 2 of the last 3 versions, a line showing `tag: N → N → N (direction-label)`. Direction labels: "improving", "not improving", "steady", "noisy".

## Git handling

Both files are committed to `main` as a separate `chore: record metrics for vX.Y` commit after the fix branch is merged. Metrics commits use only the `metrics/` path; they do not touch other files.

## Versions and completeness

If a version's metrics file is missing (e.g., the user disabled metrics for that version and later re-enabled), SUMMARY.md silently skips it. The plugin does not backfill.
