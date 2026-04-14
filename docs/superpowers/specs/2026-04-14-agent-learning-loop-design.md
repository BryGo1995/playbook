# Agent Learning Loop — Design

**Date:** 2026-04-14
**Status:** Spec — pending implementation plan
**Backlog item:** Resolves "claude-mem integration — cross-session agent memory for learning from past attempts" (from `2026-04-05-agent-orchestrator-design.md` §Backlog).

---

## Goal

Let the orchestrator's agents (coding, review, testing) improve over time by
learning from work the human validates during film-room sessions. Two learning
channels:

1. **Project-scoped lessons** — conventions and constraints specific to one
   project, captured in that project's `CLAUDE.md` so future agents on the
   same repo pick them up automatically.
2. **Cross-project agent-craft lessons** — generalizable failure modes of the
   agents themselves, captured as proposed prompt edits to
   `agents/{coding,review,testing}.py` in the playbook repo.

Both channels produce **PRs that the human reviews and merges** — no
automatic prompt mutation, ever. The film-room session is the only source of
learning signal in v1.

## Why now

Film-room already manufactures a high-quality dataset for free: a tracking
issue with a checklist of human-described fixes, plus one commit per fix on
the `film-room/vX.Y` branch. Each fix is implicitly the tuple
`(original task, agent's output, human's correction, human's reason)` —
the cleanest learning signal we'll get without new instrumentation.

## Architecture

```
agent dispatch  →  agent does work  →  PR merged  →  film-room session
                                                            │
                                                            ▼
                                              tracking issue + film-room/vX.Y
                                                            │
                                            ┌───────────────┴───────────────┐
                                            ▼                               ▼
                            project distiller                 agent-craft distiller
                            (PR → project repo,                (PR → playbook repo,
                             updates CLAUDE.md)                 edits agents/*.py
                                                                or appends to
                                                                docs/agent-craft-
                                                                observations.md)
                                            │                               │
                                            ▼                               ▼
                            agents auto-load CLAUDE.md         next dispatch uses
                            on next dispatch                   updated prompts
```

Both distillers run at film-room **wrap-up**, between the merge step (Phase 2
Step 4) and cleanup (Phase 2 Step 5). They are themselves `claude -p`
invocations launched from the film-room skill — no new long-running infra.

## Capture: distiller inputs

At wrap-up, each distiller receives the same input bundle:

1. **Tracking issue body** — the human-written checklist of fixes.
2. **`git log origin/ai/dev-vX.Y..film-room/vX.Y`** — one commit per fix,
   with diffs.
3. **The original issue(s)** the agents worked on — the "what was the agent
   asked to do" context.
4. **The PRs the agents opened** for those issues — the "what did the agent
   produce" (pre-fix state).

Each fix becomes the tuple
`(original task, agent's output, human's correction, human's reason)`.

If the fix branch has zero commits, the distillers are skipped entirely
(matches film-room's existing early-exit case).

## Project distiller

**Job:** propose additions to the project repo's `CLAUDE.md`.

**Output:** a PR against the project repo with a single commit titled
`chore: capture lessons from vX.Y film-room`.

**Behavior** (encoded in the distiller prompt):

1. Classify each fix as one of:
   - **Convention** — a project-specific pattern agents should follow next
     time (e.g. "use `pytest.fixture(scope='session')` for DB fixtures here").
   - **Constraint** — a hard rule that was violated (e.g. "never import from
     `legacy/` — it's deprecated").
   - **Local incident** — a one-off bug fix with no generalizable lesson.
     Skip.
2. **Deduplicate** against existing `CLAUDE.md` content. Drop any lesson
   already present.
3. **Propose minimal additions.** Append to existing sections where they
   fit; create new sections sparingly. Each lesson is one bullet, one
   sentence, with a `Why:` tail when non-obvious. Same shape as the
   auto-memory entries in `~/.claude/projects/.../memory/`.
4. **Cite the source.** Each new bullet ends with
   `(film-room vX.Y, fix #N)` so future maintainers can trace it and remove
   it if it stops being true.

**PR body:** "Proposing N lessons from vX.Y film-room. M fixes were
classified as local incidents and skipped." Human reviews the diff; merge,
edit, or close.

**Conservatism bias.** The distiller prompt is explicit: when in doubt,
classify as local incident. Lesson sprawl is the primary failure mode — a
CLAUDE.md that gains 20 bullets per version becomes noise.

## Agent-craft distiller

**Job:** identify failure modes of the agents themselves (not project
conventions) and propose prompt edits.

**Examples of agent-craft lessons:**
- Coding agent forgets to run tests before claiming done → tighten
  `coding.py` prompt.
- Review agent rubber-stamps PRs missing test coverage → add a "block on
  missing tests" rule to `review.py`.
- Testing agent asserts on mocks instead of behavior → add a guideline to
  `testing.py`.

**Examples that are NOT agent-craft** (these go to the project distiller):
- "Use `pytest.fixture(scope='session')` here."
- "This codebase imports from `app.db`, not `app.database`."

**Inclusion bar:** the distiller may propose a prompt edit only when **≥2
fixes in the bundle exhibit the same agent failure**, OR when a single
failure is severe enough to justify a guardrail (e.g. agent merged its own
PR).

**Two output paths:**

1. **Bar met → PR against the playbook repo** (`BryGo1995/playbook`) with a
   diff against `agents/coding.py`, `agents/review.py`, or
   `agents/testing.py`. PR body lists the motivating fixes with links back
   to the project's film-room tracking issue.

2. **Bar not met → observation log entry.** A PR against the playbook repo
   that appends to `docs/agent-craft-observations.md` (one entry per
   film-room session). The log is the substrate for cross-version pattern
   recognition: when the same observation recurs across versions, a future
   session promotes it to an actual prompt edit.

**Auth:** the distiller opens PRs via `gh` using the operator's existing
auth, since film-room runs in the operator's local shell.

## Integration points

**New files (in this repo):**

- `skills/film-room/distillers/project-distiller.md` — prompt for the
  project distiller, loaded and passed to `claude -p`.
- `skills/film-room/distillers/agent-craft-distiller.md` — prompt for the
  agent-craft distiller.
- `docs/agent-craft-observations.md` — created lazily when the first
  observation entry lands.

**Modified files:**

- `skills/film-room/SKILL.md` — new "Step 4.5 — Run distillers" between the
  merge step and cleanup. Skipped if `learning.enabled: false` or if the
  fix branch has zero commits.
- `defaults.yaml` — add the `learning` config block with defaults.

**No changes to** `orchestrator.py` or `agents/*.py` runtime behavior. The
agent-craft loop changes those files via PRs that the human merges.

## Configuration

In `playbook.yaml` (with defaults from `defaults.yaml`):

```yaml
learning:
  enabled: true
  project_distiller: true
  agent_craft_distiller: true
  playbook_repo: "BryGo1995/playbook"
```

`learning.enabled: false` makes film-room behave exactly as it does today.
The two distillers can be toggled independently.

## Scope

**In scope (v1):**

- Film-room as the only learning source.
- Project distiller producing CLAUDE.md PRs.
- Agent-craft distiller producing playbook PRs (high bar) or
  observation-log entries (low bar).
- Both gated by human review of PRs.

**Explicit non-goals:**

- Agent fine-tuning or weight updates.
- Learning from sources other than film-room (mid-PR review, failing CI,
  agent self-reports).
- Embedding-based retrieval / RAG over lessons. Direct CLAUDE.md
  auto-load only.
- Cross-project sharing of *project conventions* (each project's CLAUDE.md
  is its own).
- Automatic CLAUDE.md gardening or consolidation.
- Backfill of past film-room sessions. Only sessions run after this feature
  ships are distilled.
- Real-time learning during agent execution.

## Follow-ups (not v1)

- **CLAUDE.md gardening.** When a project's CLAUDE.md exceeds N bullets, the
  next film-room session also opens a consolidation PR. Defer until lesson
  sprawl is observed in practice.
- **Backfill script.** A one-shot tool to retroactively distill historical
  film-room issues. Defer until the live loop has proved its value.
- **Retrieval.** If CLAUDE.md becomes too noisy for direct auto-load,
  introduce embedding-based retrieval that injects only the top-N relevant
  lessons per dispatch.

## Open questions

None blocking implementation. Review and surface any during plan-writing.
