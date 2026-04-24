# Playbook Metrics — Design

## Motivation

The playbook orchestrator produces good agent output today, but we have no data on *where* quality leaks when it does. Every film-room fix is information — about whether the criterion was vague, the coding agent misread it, the test didn't catch it, or the spec itself was wrong. Without classifying that information, every improvement proposal is speculation.

The goal of this system is to capture that signal with as little friction as possible — specifically zero friction for non-technical users when the plugin is distributed — and surface it to the tuner (plugin maintainer) so investment in prompt/skill improvements is data-driven rather than guessed.

## Goals

- Identify which part of the pipeline (gameplan criteria, coding, testing, review, GDD) is the top source of film-room fixes, per version and as a trend.
- Catch structurally-vague acceptance criteria at generation time so they don't reach the coding agent.
- Require zero cognitive load from non-technical users.
- Give the tuner a lightweight dashboard (one markdown table) that highlights where to invest.

## Non-goals

- Statistical rigor (no significance testing, no changepoint detection — simple counts only).
- Automatic prompt optimization (metrics inform human decisions; they do not trigger automated changes).
- Telemetry across distributed installs (v1 is local-only; revisit if adoption warrants).
- Replacing human product-owner judgment in film-room.

## Architecture

Two independent components writing to a shared `metrics/` location. They do not share code or state; either can be disabled without breaking the other.

```
gameplan                                film-room
  │                                       │
  ├─ expand issue to full template        ├─ user fixes things
  ├─ [Component 1] structural check       ├─ merge fix branch
  │   └─ self-revise weak criteria        ├─ [Component 2] LLM classifies each fix
  ├─ present to user ──────────────────►  └─ write metrics/vX.Y.md
  └─ create issues                          regenerate metrics/SUMMARY.md
                                            [Component 3: storage/surface]
```

## Component 1 — Structural spec check (inside gameplan)

Runs during Phase 4, after gameplan expands each issue to the full template from `skills/gameplan/issue-template.md`, before presenting the final expanded issues to the user.

### What it checks

For each acceptance criterion, at least one of these must be present:

- A **number** (threshold, count, duration, percentage).
- A **specific state or boolean** ("enemy is in pursuit state", "door is locked").
- A **named entity from the GDD** (specific mechanic, system, or value defined elsewhere).
- A **before/after comparison** ("pursuit range narrows from X to Y").

### What it flags as weak

Criteria built around hollow verbs with no anchor: "works", "functions correctly", "handles properly", "responds appropriately", "as expected".

### Special case: subjective criteria

Game dev has real criteria that cannot be operationalized — "combat feels snappy", "the menu looks clean". Do not try to sharpen these. Tag them `subjective: needs-human-eval` and let them through. This tag flows to film-room so the product owner knows to check them first.

### Behavior

- For weak criteria: gameplan runs **at most one revision attempt per flagged criterion** ("this criterion lacks a number or observable state; revise to include one, or mark as subjective if genuinely about feel/aesthetics"). If the revision is still weak, the original stands.
- For genuinely subjective criteria: tag with `subjective: needs-human-eval`, do not revise.
- **Advisory, never blocking.** If self-revision fails or cannot sharpen, keep the original and proceed. Component 2 is the backstop.

### Message to user (when `metrics.show_checks: true`)

Shown before the "does this decomposition look right?" prompt, one block per issue:

```
[gameplan] structural check results:
  Issue 1: 5 clean
  Issue 2: 4 clean, 1 sharpened
    · "enemy AI works correctly"
      → "enemies pursue player within 5 tiles, return to patrol after 3s LOS loss"
  Issue 3: 3 clean, 1 sharpened, 1 marked subjective
    · sharpened: "handles input properly"
      → "jump input accepted within 100ms of button press"
    · subjective: "jump feels responsive"
```

When `metrics.show_checks: false` (the distribution default), the check runs silently. Results are still written to `metrics/vX.Y.md`.

## Component 2 — LLM classification (inside film-room)

Runs at the end of a film-room session, after the fix branch is merged. Not a separate agent — the film-room skill itself does the pass as a final instruction.

### Inputs

- The original issue (acceptance criteria + any `subjective` tags from Component 1).
- The coding agent's PRs (what was delivered).
- The fix commits (what film-room changed).
- The film-room checklist notes with the user's reasoning (richest signal).

### Taxonomy

One primary tag per fix, one optional secondary:

| Tag | Meaning | Counts as |
|---|---|---|
| `gameplan-criteria` | Criterion was vague/wrong/missing | Failure |
| `gameplan-scope` | Wrong files, wrong decomposition | Failure |
| `coding-misread` | Criterion was clear, agent misread | Failure |
| `coding-bug` | Implementation bug | Failure |
| `testing-missed` | Tests passed but shouldn't have | Failure |
| `review-missed` | Review agent should have flagged | Failure |
| `gdd-gap` | Spec itself was wrong/missing | Failure |
| `design-change` | User changed their mind | Iteration |
| `subjective-eval` | Fix to a pre-tagged subjective criterion | Iteration |

Iteration tags are reported separately from failures — they are expected and must not contaminate failure counts.

### Multi-cause fixes

Primary tag is the **earliest upstream** leak point (gameplan > coding > testing > review). Secondary captures additional causes. This optimizes for "where should this have been caught first" rather than distributing blame evenly.

### Per-fix output format

```yaml
- fix: "Tightened enemy pursuit range to 5 tiles"
  primary: gameplan-criteria
  secondary: null
  confidence: high
  reasoning: "Original criterion said 'enemies chase player' with no range. Agent picked 20, felt wrong in playtest."
```

### Summary shown to user (when `metrics.show_checks: true`)

```
[film-room] classification for v0.3 — 9 fixes:

  Failures (where quality leaked):
    · gameplan-criteria:   4  (44%)
    · coding-misread:      2
    · gdd-gap:             1

  Expected iteration (not failures):
    · design-change:       2
    · subjective-eval:     0

  Top signal: gameplan-criteria. Patterns seen:
    - Missing numeric anchors (3/4 cases)
    - Ambiguous actor ("enemy" vs specific enemy type)

  Written to: metrics/v0.3.md
```

### Edge cases

- **No fixes made.** Skip classifier entirely. Write a minimal `metrics/vX.Y.md` showing all issues as first-pass clean (`first_pass_clean` equals issue count, `fixes_total: 0`, no failure/iteration counts).
- **Sparse user notes.** Judge falls back to diff + criteria. Confidence drops to `low`. Output still written.
- **Classification budget exceeded.** Truncate and note in output. Never block the film-room session itself — the merge has already happened.
- **Classifier error (API failure, malformed output).** Log the error to the metrics file and continue. Do not retry in the same session.

### Budget

Capped via `metrics.classification_budget_usd` in `playbook.yaml` (default `0.25`). Attributed to the version's total cost in the metrics file.

## Component 3 — Storage and surface

### Location

`metrics/` at the project repo root. Committed to git as a separate `chore: record metrics for vX.Y` commit on `main` after the fix branch is merged.

### Two file types

1. **`metrics/vX.Y.md`** — per-version source of truth, one file per version. Combines Component 1 structural output and Component 2 classification output.
2. **`metrics/SUMMARY.md`** — auto-regenerated at end of each film-room session. Cross-version rollup.

For bootstrap issues, the file is `metrics/bootstrap.md`.

### File format

YAML frontmatter + markdown body. Frontmatter is machine-parseable (used by SUMMARY regeneration and future tooling); body is human-readable narrative.

### Example `metrics/v0.3.md`

```markdown
---
version: v0.3
date: 2026-04-24
issues: 3
first_pass_clean: 1
fixes_total: 9
failures:
  gameplan-criteria: 4
  coding-misread: 2
  gdd-gap: 1
iterations:
  design-change: 2
  subjective-eval: 0
cost_usd: 4.87
---

## Structural check (gameplan)
- Issue #15: 5 clean
- Issue #16: 4 clean, 1 sharpened
    · "enemy AI works correctly" → "enemies pursue within 5 tiles..."
- Issue #17: 3 clean, 1 sharpened, 1 marked subjective

## Classification (film-room)

### Failures
- Tightened pursuit range to 5 tiles
    primary: gameplan-criteria | confidence: high
    reasoning: original criterion said "enemies chase" with no range

### Expected iteration
- Adjusted jump arc after playtest
    primary: design-change
    reasoning: criterion was met, user preference shifted
```

### Example `metrics/SUMMARY.md`

```markdown
# Playbook Metrics

| Version | First-pass | Fixes | Top failure       | Cost   | Date       |
|---------|-----------:|------:|-------------------|-------:|------------|
| v0.3    |      33%   |   9   | gameplan-criteria | $4.87  | 2026-04-24 |
| v0.2    |      50%   |   6   | coding-misread    | $3.21  | 2026-04-18 |
| v0.1    |      25%   |  12   | gameplan-criteria | $5.04  | 2026-04-11 |

## Current top failure modes (last 3 versions)
1. gameplan-criteria (8 fixes, 31% of failures)
2. coding-misread (4 fixes, 15%)
3. gdd-gap (2 fixes, 8%)

## Trends
- gameplan-criteria: 5 → 1 → 4 (not improving; consider prompt tuning)
- first-pass success: 25% → 50% → 33% (noisy, need more data)
```

SUMMARY regeneration reads frontmatter from all `metrics/v*.md` files. If a file is missing or malformed, it is skipped with a comment in SUMMARY; it does not fail the film-room session.

### Migration

On first run against a project with prior versions: SUMMARY.md contains only the current version. No backfill. Historical versions without metrics simply do not appear.

## Configuration

Added to `playbook.yaml`:

```yaml
metrics:
  enabled: true                    # master switch; default true
  show_checks: false               # echo Component 1/2 summaries to user; default false
  classification_budget_usd: 0.25  # per-version cap for Component 2
```

When `metrics.enabled: false`, no structural check runs, no classification runs, no files are written. The skills behave exactly as they do today.

## Tradeoffs explicitly accepted

- **Heuristic structural check, not semantic.** A clever-but-vague criterion with a coincidental number passes. Acceptable — the check raises the floor, Component 2 is the backstop.
- **Judge shares the film-room model's blind spots.** If the session model made a misjudgment during fixing, it may repeat that in classification. Acceptable for v1; the recipe-F (human-audit) upgrade path exists if needed.
- **Metrics files in git add diff noise.** Small files, acceptable trade for transparency and git-history-based trend inspection.
- **SUMMARY.md analysis is dumb.** Intentional — simple counts and rolling windows. Over-engineering this is a known trap.
- **No backfill on existing projects.** Simpler v1; losing historical data is acceptable given it doesn't exist in a structured form anyway.

## Open questions (to be resolved during planning, not design)

- Exact schema for the per-fix YAML output — may be refined when we see real classifier output.
- Whether `metrics/SUMMARY.md` should include a "stale" marker if it wasn't regenerated recently (probably not for v1).
- Whether to add a `/playbook:metrics` command to view SUMMARY without opening the file (nice-to-have; defer).
