# Version-Gated Orchestration & Project Bootstrap Design

## Problem

The orchestrator dispatches all `ai-ready` issues in parallel regardless of dependencies. Agents working on related issues create competing file structures and merge conflicts. There is no mechanism to bootstrap a project before feature work begins, and no way to ensure earlier work completes before dependent work starts.

## Solution

Version-gated dispatch: the orchestrator reads `[vX.Y]` tags from issue titles and only dispatches issues from the lowest incomplete version. A `[bootstrap]` tag runs first, alone, to establish project scaffolding. Issue creation happens per-version against the actual codebase state, not upfront assumptions.

## Project Lifecycle

### Phase 1: PRD to Bootstrap

User brainstorms with an agent, producing a PRD stored in the repo (e.g., `docs/prd.md`). From the PRD, a single `[bootstrap]` issue is created. This issue sets up the full project skeleton: folder structure, project settings, base scenes/scripts, shared utilities. It should produce a working "hello world" state.

### Phase 2: Bootstrap Evaluation to v0.1

After the bootstrap issue merges to `ai/dev`, an issue creation agent reads the PRD and the actual codebase, then creates `[v0.1]` issues. All issues within v0.1 must be safe to run in parallel — no two issues may write to the same file.

### Phase 3: Version Completion to Next Batch

When all v0.1 issues reach `Done`, a Slack notification is sent. The user triggers the issue creation agent to create `[v0.2]` issues based on the current code state and PRD. This repeats per version.

A config flag `auto_create_issues` (default `false`) is reserved for future automatic issue creation.

## Version Parsing

Versions are extracted from issue titles using the pattern `[vX.Y]` (e.g., `[v0.1]`, `[v1.2]`). Sorted numerically — `v0.1` < `v0.2` < `v1.0`.

Special cases:
- `[bootstrap]` is treated as version `0.0` — always runs first
- Issues without a version tag are lowest priority — dispatched only after all versioned work is complete

## Dispatch Rules

| Condition | Behavior |
|-----------|----------|
| Bootstrap issues exist and are not Done | Only dispatch bootstrap issues, max concurrency 1 |
| Active version has `ai-ready` issues | Dispatch those issues (normal concurrency limits) |
| Active version has in-flight issues but none `ai-ready` | Wait — do not advance to next version |
| All issues in active version are Done | Version complete — notify via Slack, advance to next version |
| No versioned issues remain | Dispatch unversioned `ai-ready` issues if any |

The "active version" is the lowest version number that has any issue not in `Done` status.

## Orchestrator Changes

### `_process_ready_issues` modification

Before dispatching, the method:
1. Fetches all project issues (all statuses)
2. Extracts version tags, determines the active version
3. Filters `ai-ready` issues to only the active version
4. If the active version is `bootstrap`, enforces max concurrency of 1
5. Dispatches as normal within those constraints

### New method: `_check_version_completion`

Runs each orchestration cycle. When all issues in the active version are `Done`:
1. Logs `Version vX.Y complete`
2. Sends Slack notification: "Version vX.Y complete — N issues merged. Ready for next batch."
3. If `auto_create_issues: true` (future), triggers the issue creation agent

### Config additions

```yaml
versioning:
  enabled: true
  auto_create_issues: false
  bootstrap_timeout_minutes: 120
  bootstrap_max_budget_usd: 5.0
```

When `versioning.enabled` is `false`, the orchestrator behaves as before — all `ai-ready` issues dispatch without version filtering.

## Issue Creation Agent

A `claude -p` invocation triggered manually (for now). Not part of the orchestrator process.

### Inputs

- PRD file path (e.g., `docs/prd.md`)
- Current codebase (agent reads actual files)
- Completed version number
- Existing issues on the project board (via `gh`)

### Outputs

- GitHub issues with `[vN.M]` tags in titles
- Each issue includes: description, acceptance criteria, file references to existing code
- All issues within a version are parallelizable

### Rules

1. Never create two issues in the same version that write to the same file
2. Each issue should be completable in under 60 minutes by a coding agent
3. Reference specific files/scenes from the current codebase, not assumptions
4. Include acceptance criteria that a testing agent can verify
5. Tag with the next version number after the last completed version

### Bootstrap issue rules

- Single issue tagged `[bootstrap]`
- Creates the full project skeleton: folders, config, base scenes, shared scripts
- Produces a running project, even if it does nothing useful yet
- Gets extended timeout (120 min) and higher budget ($5.00)

### Invocation

```bash
python3 create_issues.py --repo BryGo1995/paint-ballas-auto --prd docs/prd.md --version 0.2
```

## What This Does NOT Change

- Agent prompts (coding, testing, review) are unchanged
- The state machine (coding -> testing -> review -> complete -> merge) is unchanged
- The integration PR workflow is unchanged
- The `ai/dev -> main` merge process is unchanged
- Concurrency limits within a version work as before (max_coding: 2, etc.)

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Issue has no version tag | Treated as lowest priority, runs after all versioned work |
| Issue has malformed version tag | Logged as warning, treated as unversioned |
| Bootstrap issue fails/blocks | Version 0.0 stays active, no other work dispatches until resolved |
| One issue in a version is blocked | Version stays active — other issues in the version continue, but next version does not start |
| All issues in version are Done except blocked ones | Version does NOT complete — blocked issues must be resolved or removed |
