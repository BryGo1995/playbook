# Resume Coding-Agent Progress on Failure — Design

Tracking issue: [#12](https://github.com/BryGo1995/playbook/issues/12)

## Motivation

When a coding agent fails, the orchestrator wipes the in-progress branch and re-dispatches the same prompt with no awareness of the prior attempt. Concretely, `agents/coding.py:12` opens every attempt with `git fetch origin && git checkout {integration_branch} && git reset --hard origin/{integration_branch}` and `git branch -D ai/issue-{N}`, and `orchestrator.py:198-213` flips an errored issue back to `ai-ready` without forwarding any context.

The result: every retry is hermetic. Whatever the prior agent learned, tried, or partially built is discarded — paid for, never used. This caps quality at "what one agent can do in one budget window" and inflates retry cost without raising retry quality.

This design preserves prior-attempt progress as a forensic snapshot and feeds it as structured context into the next attempt's prompt. The retry agent sees what the previous one tried and why it failed, and decides whether to build on it or start over.

## Goals

- A failed coding-agent attempt leaves a recoverable, machine-readable trace of what it produced and why it stopped.
- The next attempt's prompt automatically includes that trace as structured context.
- The retry agent is told to treat the prior attempt as input, not truth — it may discard the prior approach freely.
- The mechanism degrades gracefully: snapshot/comment/parse failures reduce context, never block recovery.
- Bound the budget cost — the new context block is compact (`--stat` summary, not full diff) and capped at the most recent attempt's signal.

## Non-goals

- Resuming testing-agent or review-agent failures (modes d and e). Deferred for a follow-up.
- Detecting "max-retries-hit due to systemic cause" (e.g. broken integration branch). Out of scope.
- Cross-issue learning. Each issue is treated independently.
- Automated worktree-per-attempt isolation. Considered (Strategy Y) and deferred until [#13](https://github.com/BryGo1995/playbook/issues/13) drives a hard requirement.
- Making truly hard problems solvable. This raises the floor on retries; max-retries → blocked → human is still the terminal failure mode.

## Failure modes in scope

- **(a) Coding timeout** — process killed by SIGTERM at the timeout boundary. Working tree state is whatever the agent had locally; no agent-authored explanation.
- **(b) Coding exited without PR** — agent finished within budget but no PR was created (existing detection at `orchestrator.py:131-141`). The agent prompt today already instructs voluntary stops to be explained in a comment; that comment is the primary reasoning signal for this mode.
- **(c) Max-retry-hit → blocked** rides along implicitly: every retry-with-context becomes one more useful attempt before the limit; no special handling.

## Architecture

### End-to-end flow

```
1. Coding agent for issue #N exits or is timed-out
   │
2. SNAPSHOT  (best-effort — never blocks recovery)
   │   In the target-repo working tree, on branch ai/issue-N:
   │   a) git stash push --include-untracked --message "[playbook] attempt-K WIP"
   │   b) git push --force origin ai/issue-N:refs/heads/ai/issue-N-attempt-K
   │   c) if stash exists: git push --force origin <stash-sha>:refs/heads/ai/issue-N-attempt-K-wip
   │   d) git stash drop
   │   Each step is independently try/except'd. Status returned: ok | partial | unavailable.
   │   If ai/issue-N never existed (agent died at startup), skip the whole step.
   │
3. STATUS + STRUCTURED COMMENT
   │   Tagged failure comment posted to the issue (human-readable + JSON block).
   │   Status → ai-error.
   │
4. RETRY DECISION  (existing _retry_error_issues)
   │   Under max_retry_cycles → ai-ready, else → blocked.
   │
5. RESUMING DISPATCH  (new logic in _dispatch_coding when attempt > 1)
   │   • Resolve latest available snapshot via git ls-remote 'ai/issue-N-attempt-*'.
   │   • Fetch tagged orchestrator failure-history comments + the agent stop comment
   │     for the most recent failed attempt.
   │   • Render PRIOR_ATTEMPT_CONTEXT block.
   │
6. RESUMED CODING AGENT
   │   Prompt: original issue body + PRIOR_ATTEMPT_CONTEXT + existing instructions.
   │   Same git-reset-from-integration kickoff (clean slate for code).
   │
7. CLEANUP
   │   On successful auto-merge: best-effort delete of all ai/issue-N-attempt-* refs.
   │   On terminal blocked / max-retries: snapshots stay as forensic evidence.
```

### Storage choice — snapshot refs (Strategy Z)

Snapshots are pushed as remote git refs in the namespace `ai/issue-{N}-attempt-{K}` (committed state) and `ai/issue-{N}-attempt-{K}-wip` (stashed dirty state). This survives orchestrator-host loss and is portable across machines, which matters for any future distribution scenario.

A worktree-per-attempt approach (Strategy Y) was considered. It is strictly more capable for local isolation and is the natural primitive once concurrent agents on independent issues are allowed (the topic of [#13](https://github.com/BryGo1995/playbook/issues/13)), but it is local-only — it does not address distribution without *also* pushing remote refs. For this issue, with single-host serialized dispatch, snapshot refs alone are sufficient. Worktrees are reserved for the #13 scope.

## What the retry agent sees

The retry prompt extends the existing `CODING_PROMPT` template with a `PRIOR_ATTEMPT_CONTEXT` block placed between the issue body and the instructions. Skeleton:

```text
You are a coding agent working on GitHub issue {repo}#{issue_number}.

## Issue: {issue_title}

{issue_body}

## Prior Attempt Context
                                      ← only rendered when attempt > 1

This is your attempt {K}. {K-1} previous attempt(s) did not complete.

### Failure history
- Attempt 1: timeout after 60min, no PR opened
- Attempt 2: agent exited without PR (see comment below)

### Latest attempt's reasoning
                                      ← only if mode-b stop comment exists for attempt K-1
> "Stopping: the database adapter referenced in the issue does not exist
>  in this codebase — I cannot proceed without clarification on which
>  module to use."

### Latest attempt's code state
Snapshot ref: ai/issue-N-attempt-2  (committed only)
WIP ref:      ai/issue-N-attempt-2-wip  (uncommitted/untracked)

Files changed (vs {integration_branch}):
 src/foo.py          | 42 +++++++++++
 tests/test_foo.py   | 35 ++++++++++
 2 files changed, 77 insertions(+)

To inspect the full diff:
  git fetch origin && git diff origin/{integration_branch}...origin/ai/issue-N-attempt-2

### How to use this
A previous attempt produced the work above. Treat it as input, not truth.
If the approach is wrong, discard it and start over. Resuming is a means,
not a goal. You are NOT obligated to keep any of the prior code.

## Instructions
                                      ← unchanged from current CODING_PROMPT
1. Start from a clean state: ...
```

### Design decisions

- **Diff is `--stat` only.** Agent has Bash; the prompt provides a verbatim command to fetch the full diff on demand. Saves tokens, avoids stale-code anchoring, gives a one-glance sense of scope.
- **Single deep snapshot, multi-attempt shallow history.** The latest snapshot is cumulative — it already encodes everything from prior attempts. Only its diff and reasoning are deep-rendered. The full failure-history list is one-line-per-attempt so the agent can see patterns.
- **Stop comments are tagged with attempt number.** The coding-agent prompt instructs voluntary stops to be prefixed `[ai-coding-agent: stop attempt={K}]`. The retry pulls only the comment matching `attempt={K-1}`, eliminating cross-attempt misattribution.
- **Snapshot may be unavailable.** If neither base nor wip ref exists, the code-state subsection collapses to an explicit "no snapshot — feedback only" message. Retry still proceeds.

## Component changes

### `agents/coding.py`

- `CODING_PROMPT` gains a `{prior_attempt_context}` placeholder between the issue body and the instructions. Empty string when first attempt — renders cleanly.
- New helper `render_prior_attempt_context(history, latest_diff_stat, snapshot_ref, wip_ref, stop_comment, attempt) -> str`. Pure function, returns empty when `attempt == 1`.
- `build_prompt` and `build_command` accept an optional `prior_attempt_context: str = ""` parameter and an `attempt: int = 1` parameter (used to render the stop-tag instruction with the right number).
- New instruction in the existing 1-8 list: *"If you decide to stop voluntarily, prefix your final issue comment with `[ai-coding-agent: stop attempt={attempt}]` so future attempts can find your reasoning."*

### `github_client.py`

- New helper `get_attempt_failure_history(repo, issue_number) -> list[dict]`. Walks issue comments; for each orchestrator-tagged comment with an embedded JSON block, parses it and returns a sorted list of `{attempt, kind, reason, snapshot_ref, wip_ref, log_path, ts}`. Tolerates malformed/missing JSON by silently dropping that entry.
- New helper `get_latest_agent_stop_comment(repo, issue_number, attempt: int) -> str | None`. Returns the body of the most recent comment whose body starts with `[ai-coding-agent: stop attempt={attempt}]`, or `None`.
- **Bug fix in `get_attempt_count`** (line 285-294): the current substring filter `Attempt … completed … coding agent` does not match the timeout-failure comment format (`Agent timed out after N minutes.`), so timeout retries undercount and effectively double the retry budget. Replace with logic that counts any orchestrator-tagged comment whose JSON block contains an `attempt` field, falling back to the legacy substring match for backward compatibility with pre-feature comments.

### `orchestrator.py`

- New method `_snapshot_branch(repo, issue_number, attempt, kind, reason) -> dict`. Returns `{snapshot_ref, wip_ref, log_path, status: "ok"|"partial"|"unavailable", error: str|None}`. All git steps are independently try/except'd; never raises. Drops the local stash even on partial push failure to avoid contaminating the next run.
- `_handle_timeout` and `_handle_completion` (mode-b path): call `_snapshot_branch` before the existing status update and comment, then post a structured failure comment containing the human-readable summary plus the JSON block.
- `_dispatch_coding` (`attempt > 1` path): resolve the latest snapshot via `git ls-remote origin 'ai/issue-N-attempt-*'`, parsing only refs that match the *exact* pattern `ai/issue-N-attempt-{integer}` (i.e. excluding `-wip` suffixes from the highest-K calculation); fetch failure history and stop comment via the new GH client helpers; call `render_prior_attempt_context`; pass the result to `coding_agent.build_command(...)`. The corresponding `-wip` ref is included separately if present.
- `_process_complete_issues` cleanup (around line 182): alongside the existing local-branch deletion, best-effort `git push origin --delete` of all `ai/issue-N-attempt-*` refs. Failure here is non-fatal.

### `defaults.yaml` / `config.py`

Add one feature flag:

```yaml
guardrails:
  max_files_changed: 10
  max_retry_cycles: 3
  snapshot_on_failure: true   # NEW — kill switch; defaults true
```

`config.py` already deep-merges defaults; no structural change.

### Failure comment format

Human-readable summary on top, machine-parseable JSON in a `<details>` block:

```markdown
[agent-orchestrator] Attempt 2 failed: timeout after 60 minutes.
Snapshot: ai/issue-N-attempt-2 (with WIP ref ai/issue-N-attempt-2-wip)
Log: .playbook/logs/<file>

<details><summary>diagnostic</summary>

```json
{"attempt": 2, "kind": "timeout", "reason": "Agent timed out after 60 minutes", "snapshot_ref": "ai/issue-N-attempt-2", "wip_ref": "ai/issue-N-attempt-2-wip", "log_path": ".playbook/logs/...", "ts": "2026-05-01T..."}
```

</details>
```

`kind` is one of `timeout` or `no-pr`. Snapshot fields are `null` when status is `unavailable`.

## Edge cases & failure handling

The whole feature is best-effort context for the retry. Every step in the flow can fail; recovery must still proceed. The cost of a failed snapshot or malformed comment is "retry has less context than ideal," not "retry doesn't happen."

### Handled explicitly

1. **Agent died at startup, no `ai/issue-N` branch ever existed.** `_snapshot_branch` checks `git rev-parse --verify ai/issue-N` first; on miss returns `status: "unavailable"`. Retry sees "no snapshot."
2. **Stash succeeds but a push step fails.** Each step is independently try/except'd. Returned status is `partial`; comment lists what was preserved. Retry uses whichever ref is present.
3. **All snapshot pushes fail (network, auth, branch protection).** Status `unavailable`. Local stash still dropped. Retry degrades to feedback-only.
4. **Stop-comment misattribution across attempts.** Tag includes `attempt={K}`. Retry filters to `attempt={K-1}`. Missing tag → no stop comment, not a wrong one.
5. **Malformed/missing JSON in a failure comment.** Each parse is try/except'd; bad entries silently dropped. Failure-history list shrinks gracefully; never blocks dispatch.
6. **Gap in attempt snapshots.** `_dispatch_coding` uses `git ls-remote` to find the highest existing K (matching `ai/issue-N-attempt-{integer}` exactly, excluding `-wip` suffixes) and uses that — not a hard-coded `K-1`. Failure history explains the gap.
7. **Issue body edited between attempts.** Each dispatch re-fetches the body; agent always sees the latest acceptance criteria. The "prior diff is input, not truth" instruction covers the case where the diff no longer matches the criteria.
8. **Manual move of issue from `blocked` → `ai-ready`.** Existing dispatch logic sees `attempt > 1` and adds prior context as normal — exactly the case where prior context is most valuable.
9. **Concurrent orchestrator ticks (cron overlap).** `state.is_issue_active` already prevents same-issue double-dispatch. Cleanup is best-effort — `git push origin --delete` on a missing ref is non-fatal.

### Accepted (not solved)

10. **Orphan snapshot refs on terminally `blocked` issues.** Forensic artifacts; left in place. A periodic sweep can be a follow-up if ref count gets noisy.
11. **GitHub branch-protection on `ai/*`.** If protection blocks force-push to `ai/*`, snapshot is recorded as `unavailable` and recovery still works. Document that `ai/issue-*` must remain unprotected for snapshots to function.
12. **Stash includes large untracked files.** `git stash --include-untracked` respects `.gitignore` (only `--all` bypasses it), so `node_modules` etc. are excluded. The agent's `max_files_changed=10` limit caps realistic scope.
13. **Backward compatibility with existing comments.** Old failure comments lack JSON blocks; `get_attempt_failure_history` returns only parseable entries. Issues that failed before this feature shipped will retry with empty history — degraded but functional.

### Operational notes for the README / runbook

- Snapshot refs accumulate visibly in branch lists (`ai/issue-*-attempt-*`). Document so it isn't surprising.
- The `guardrails.snapshot_on_failure: false` flag is a kill switch.
- The first time an existing issue retries after this feature ships, it has no prior snapshots — expected, not a bug.

## Testing strategy

Four layers, mocked progressively heavier.

### Layer 1 — pure unit

- `render_prior_attempt_context`: empty on attempt 1; expected block for one prior failure; multi-failure history; snapshot unavailable variant; with/without stop comment.
- JSON serialize → parse round-trip for failure-comment payload.

### Layer 2 — GitHub client (mock REST)

- `get_attempt_failure_history` returns sorted list, tolerates malformed JSON, returns `[]` for old-format-only streams.
- `get_latest_agent_stop_comment` filters by attempt number; returns `None` on miss.
- `get_attempt_count` correctness fix: counts new structured timeout failures; mixed old/new format counts correctly.

### Layer 3 — orchestrator (mock subprocess + GH client)

- `_snapshot_branch` happy path returns `status: "ok"`.
- `_snapshot_branch` partial: stash-push fails → `partial`, base ref populated, no exception.
- `_snapshot_branch` unavailable: branch never existed → `unavailable`, no push commands run.
- `_snapshot_branch` total push failure → `unavailable`, stash still dropped, no exception.
- `_dispatch_coding` first attempt: prompt has no context block.
- `_dispatch_coding` retry: prompt contains rendered context with right snapshot + history.
- `_dispatch_coding` retry, no available snapshots: prompt has the "no snapshot — feedback only" variant.
- Cleanup on auto-merge: snapshot-ref deletion runs; failure tolerated.
- Feature flag off: `_snapshot_branch` not invoked; legacy unstructured comment posted; retry proceeds with empty context.

### Layer 4 — end-to-end (real git, no GitHub)

One integration test: temp git repo with integration branch + dirty `ai/issue-1` branch with commits + untracked file → call `_snapshot_branch` directly → assert refs at expected SHAs and working tree clean afterward.

### Explicitly out of scope

- The `claude` CLI itself or any agent reasoning.
- Whether the retry agent makes good use of the context — that's an empirical question answered by sampling logs once shipped.
- A real-GitHub end-to-end test; not an existing pattern in this repo.

## Alternatives considered

- **Strategy A — feedback-only, no snapshots.** Ship the failure comment + history wiring without any git plumbing. Simpler v1, but loses the most concrete progress signal (the prior diff). Considered as a stage-zero MVP and rejected; the snapshot work is bounded and the diff is the highest-value piece of context.
- **Strategy B — preserve and resume on the same branch.** Highest preservation, but inherits whatever broken state the prior agent left. Rejected: contamination risk outweighs the saved git operations.
- **Strategy Y — git worktrees per attempt.** Strictly more capable than snapshot refs for local isolation; the natural primitive once concurrent agents are allowed. Deferred to [#13](https://github.com/BryGo1995/playbook/issues/13) — implementing it now would pay lifecycle cost ahead of need *and* likely require redesign once #13 dictates worktree layout. Mentioned here for traceability.
- **Always-on agent journal (`.playbook/RESUME_NOTES.md`).** Considered as a richer alternative to leaning on issue comments. Rejected for v1: per-run token cost and commit-cadence fiddliness without proven need. Mode-b already produces good signal via stop comments; mode-a's marginal benefit is limited. Reconsider if shipped feature shows blind retries on timeouts.
