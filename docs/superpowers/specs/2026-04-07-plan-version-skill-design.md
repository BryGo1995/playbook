# Design Spec: `playbook:plan-version` Skill

**Date:** 2026-04-07
**Status:** Draft
**Related:** playbook orchestrator, version-gating system

---

## 1. Purpose

A skill that acts as a lead engineer running a version planning session. It reads the GDD/PRD, understands the current codebase state, proposes the next version's work, updates documentation, and creates agent-ready issues on the GitHub project board.

The skill bridges the gap between the GDD (what to build) and the orchestrator (how to execute) by decomposing version milestones into well-scoped, conflict-free issues that coding, testing, and review agents can act on independently.

---

## 2. Identity & Invocation

- **Name:** `playbook:plan-version`
- **Trigger:** When the user wants to plan and create issues for the next version of a project managed by the playbook orchestrator. Invoked via `/plan-version` or naturally (e.g., "let's plan the next version").
- **Mental model:** Lead engineer running a version planning session. The user is the product owner approving decisions.
- **Output:** GitHub issues on the project board, tagged with `[vX.Y]`, status set to "ai-ready", with full context for coding, testing, and review agents.

---

## 3. Inputs & Discovery

### Auto-discovered by the skill

| Input | Source |
|---|---|
| GDD/PRD content | `gdd_path` from `config.yaml`, or `docs/*-gdd.md` / `docs/*-prd.md` glob fallback |
| Repo file tree and structure | Local checkout from `local_paths` in config |
| Git history | `git log` of the target repo |
| Project board state | GitHub project API via `project.owner` and `project.number` from config |
| Next version number | Derived from board state (lowest version with all issues "Done" + 1) |
| Concurrency settings | `concurrency.max_coding` from config |

### Gathered from the user during the session

- Confirmation of proposed next version and priority
- Any GDD adjustments or scope changes
- Approval of the proposed issue set before creation

### Config addition

```yaml
gdd_path: "docs/paint-ballas-gdd.md"  # optional, defaults to docs/*-gdd.md glob
```

---

## 4. Skill Flow

### Phase 1 — Context Gathering (automatic, no user interaction)

- Read `config.yaml` for project settings, GDD path, and concurrency config
- Read the GDD/PRD
- Scan the repo file tree and recent git history
- Query the project board for existing issues and their statuses
- Determine the next logical version number

### Phase 2 — Version Proposal (gate: user confirms)

- Present the next version number, the proposed priority from the GDD roadmap, and a summary of what already exists in the repo from prior versions
- Ask: "Does this priority look right, or would you like to adjust?"
- Ask: "Are there any changes or additions to the GDD before we proceed?"

### Phase 3 — GDD Updates (gate: user approves changes)

- If the user wants GDD changes, discuss and apply them directly to the GDD file
- Commit the updated GDD before moving on, so issues are always derived from the canonical source
- If no changes needed, skip this phase

### Phase 4 — Issue Decomposition (gate: user approves issue set)

- Propose a set of issues for the version using the issue template (Section 5)
- If `max_coding > 1`: explain file ownership boundaries and conflict-avoidance reasoning
- If `max_coding == 1`: focus on clean scoping and logical sequencing
- Open for discussion — the user can split, merge, reorder, or adjust scope
- Nothing proceeds until the user approves the full issue set

### Phase 5 — Issue Creation (gate: user says go)

- Create each issue on the GitHub project board
- Tag with `[vX.Y]` in the title
- Set status to "ai-ready"
- Confirm creation with links to each issue

---

## 5. Issue Template

Each issue follows this structure to serve all three agent types (coding, testing, review):

```markdown
## Overview
What this issue delivers and how it fits into the version milestone.

## Relevant GDD Sections
- Section X.Y — [relevant requirements quoted or summarized]

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Scope
**Files to create or modify:**
- `path/to/file.gd` — orientation context about what exists + what changes

**Do NOT touch:** (critical when max_coding > 1)
- `path/to/other.gd` — owned by issue #N in this version

## Dependencies
- Assumes [vX.previous] work is merged: [brief description of what should already exist]

## Testing Criteria
- [ ] Expected behaviors to validate
- [ ] Edge cases to cover
- [ ] Specific inputs/outputs to verify

## Review Criteria
- [ ] GDD compliance checks
- [ ] Architectural constraints to verify
- [ ] Code quality concerns specific to this feature

## Definition of Done
This issue is done when [concise statement tying acceptance criteria to testing validation].

## Notes
Product-owner context, caveats, or guidance for edge cases the agent might otherwise guess wrong on.
```

---

## 6. Conflict Avoidance Strategy

The skill adapts its conflict strategy based on the `max_coding` setting in `config.yaml`.

### `max_coding: 1` (default)

Recommended for game development, monorepos with tightly coupled systems, and any project without clear system boundaries.

- Sequential execution eliminates merge conflicts by design
- The skill focuses on clean scoping: clear acceptance criteria, logical issue ordering, well-defined dependencies
- No file partitioning analysis needed
- The orchestrator still pipelines work — while issue #1 is in testing/review, issue #2 starts coding

### `max_coding: 2+`

Suitable for repos with clear system boundaries (e.g., frontend/backend in a monorepo with distinct folder scoping).

- The skill adds file ownership analysis to each issue
- "Do NOT touch" sections become critical enforcement boundaries
- **Hard rule for scene/config files:** Files like `.tscn`, `.tres`, or project-level configs are atomic — one owner per version, no exceptions. These formats are structurally fragile and git cannot merge them cleanly.
- **Soft rule for scripts:** No overlapping modifications to the same script file. Two issues may both read/import from a shared file, but only one may modify it. The skill explains its reasoning.
- If a version doesn't decompose cleanly for parallel execution, the skill says so honestly rather than force-fitting parallelism
- The skill warns the user about merge risk for borderline cases

### Risks of `max_coding: 2+`

Users should be aware:
- Merge conflicts between parallel agents are possible despite safeguards
- Agents may make architectural decisions that conflict conceptually even if file boundaries are respected
- Conflict-free decomposition constrains how work can be structured, potentially producing less natural issue boundaries

---

## 7. Design Decisions

### Why a single skill (not a two-phase chain)
The value is in the guided reasoning process — reading the GDD, understanding the repo, thinking about conflicts, proposing issues. This is fundamentally a conversation, and a single skill captures the whole flow. Review gates keep the user in control without needing skill chaining.

### Why the skill updates the GDD directly
The GDD is the canonical source of truth. Issues should be derived from an up-to-date GDD, not from a stale version. Having the skill update the GDD (with user approval) keeps the flow seamless and ensures consistency.

### Why issue template includes testing and review criteria
The orchestrator dispatches testing and review agents from the same issue. These agents need clear direction without re-deriving intent from code. Including their criteria in the issue makes each issue a single source of truth for the entire coding-testing-review pipeline.

### Relationship to `playbook:create-gdd` (future)
GDD creation is a separate creative/generative phase. `plan-version` assumes a GDD exists and decomposes it. A future `playbook:create-gdd` skill would handle the upstream process of shaping ideas into a structured GDD. The lifecycle is: create-gdd -> plan-version -> orchestrator.
