# Bootstrap Detection Design

**Date:** 2026-04-09
**Status:** Draft

## Purpose

Gameplan should detect when a project needs bootstrapping and propose a single
`[bootstrap]` issue before versioned feature work begins. Currently, nothing
in the pipeline decides when bootstrap is needed — the user has to know to
create a `[bootstrap]` issue manually.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where to detect | Gameplan Phase 1 Step 5 + Phase 2 | Gameplan already reads the board and repo state — it has all the signals |
| Bootstrap scope | Single `[bootstrap]` issue | The skeleton is one coherent unit; multiple issues add coordination overhead for sequential work |
| Content derivation | Entirely from GDD/PRD | The GDD has tech stack, architecture, and structure info — no fixed checklist needed |
| User gate | Propose bootstrap, user confirms or skips to v0.1 | Consistent with "you propose, they approve" |

## Detection Logic

In Phase 1 Step 5 ("Summarize findings internally"), gameplan already builds
a mental model of repo state and project board. Add bootstrap detection:

**Bootstrap is needed when ALL of these are true:**
1. The project board has no existing issues (empty board)
2. The repo has no meaningful code (just `playbook.yaml`, GDD/PRD, docs, config files — no source code)
3. No `[bootstrap]` issue exists on the board (not even a completed one)

If any condition is false, skip bootstrap and proceed with normal version
proposal.

## Phase 2 Change

When bootstrap is detected, Phase 2 presents a different proposal than the
normal version flow:

> "This is a fresh project — no versions on the board and no existing code.
> I recommend starting with a **[bootstrap]** issue to set up the project
> skeleton before versioned feature work.
>
> Based on the GDD, bootstrap would set up:
> - [tech stack / framework / engine setup]
> - [folder structure derived from GDD architecture]
> - [base config files]
> - [entry point / main scene / app shell]
>
> **Want to start with bootstrap, or jump straight to v0.1?**"

If the user chooses bootstrap:
- Skip Phase 3 (GDD updates — the GDD was just written by scout)
- Proceed to Phase 4 (Issue Decomposition) but create a single `[bootstrap]`
  issue instead of multiple versioned issues
- The issue uses the same template from `issue-template.md` with
  `[bootstrap]` title prefix
- Phase 5 creates the issue and sets it to `ai-ready`

If the user chooses to skip to v0.1:
- Proceed with normal Phase 2 version proposal flow

## Bootstrap Issue Content

The single `[bootstrap]` issue should cover everything needed to get from
an empty repo to a working "hello world" state. Gameplan derives this from
the GDD:

- **Tech stack setup** — Dependencies, package manager config, engine project
  file. Derived from the GDD's technology/platform sections.
- **Folder structure** — Directory layout matching the GDD's architecture.
  Not an arbitrary convention — the structure the GDD describes.
- **Base configuration** — Config files, environment setup, build scripts.
  Derived from the GDD's technical requirements.
- **Entry point** — The minimal runnable artifact. A main scene, an app
  shell, a CLI entry point — whatever the GDD describes as the starting
  point.
- **Acceptance criteria** — "The project runs and produces [minimal output
  described in GDD]. All dependencies install cleanly. The folder structure
  matches the GDD architecture."

## Integration with Orchestrator

The orchestrator already handles `[bootstrap]` issues with special treatment:
- `max_coding` forced to 1 (sequential execution)
- Custom timeout from `versioning.bootstrap_timeout_minutes` (default 120)
- Custom budget from `versioning.bootstrap_max_budget_usd` (default 5.0)
- Branch: `ai/dev-bootstrap`

Gameplan doesn't need to specify any of this — the orchestrator handles it
based on the `[bootstrap]` title prefix.

## Phase 4 Adaptation

When creating a bootstrap issue, Phase 4's decomposition rules simplify:
- No conflict avoidance needed (single issue)
- No multi-issue ordering needed
- The full issue template from `issue-template.md` is used
- Dependencies section states: "None — this is the first issue"

## Out of Scope

- **Multiple bootstrap issues** — One issue covers the full skeleton.
- **Bootstrap for existing projects** — If there's already code in the repo,
  bootstrap isn't needed even if the board is empty.
- **Custom bootstrap templates** — The GDD drives content. No separate
  bootstrap template.
