# Agent Orchestrator Design Spec

## Overview

A lightweight Python orchestrator that dispatches Claude Code headless agents to work on GitHub Issues, coordinates coding/testing/review workflows via label-based state management, and sends Slack notifications for events requiring human attention. GitHub Projects serves as the monitoring dashboard.

## Goals

- Automate the coding, testing, and review cycle for GitHub Issues using Claude Code headless (`claude -p`)
- Provide remote visibility via GitHub Projects KanBan (mobile-accessible)
- Alert via Slack when human attention is needed
- Allow remote task dispatch by adding labels from GitHub mobile
- Keep the system simple: no database, no daemon, no web server

## Non-Goals

- Custom web dashboard (backlog item)
- Webhook-driven instant dispatch (backlog — polling is sufficient for now)
- Full superpowers skill invocation (lean prompts used instead for token efficiency)
- Cross-session agent memory via claude-mem (backlog item)

---

## Label-Based State Machine

GitHub Issue labels drive the entire workflow. GitHub Projects automation rules map labels to KanBan columns automatically.

```
ai-ready → ai-in-progress → ai-testing → ai-review-needed → ai-pr-ready → ai-merged
              ↑                                |
              └────────────────────────────────┘  (review rejects → back to coding)

Special states:
  ai-blocked    — agent couldn't proceed, needs human input
  ai-error      — agent crashed or hit a guardrail
```

### State Transitions

| From | To | Trigger |
|------|----|---------|
| `ai-ready` | `ai-in-progress` | Orchestrator dispatches coding agent |
| `ai-in-progress` | `ai-testing` | Coding agent completes, opens draft PR targeting `ai/dev` |
| `ai-testing` | `ai-review-needed` | Testing agent passes |
| `ai-testing` | `ai-ready` | Testing agent fails, comments with failures |
| `ai-review-needed` | `ai-pr-ready` | Review agent approves |
| `ai-review-needed` | `ai-ready` | Review agent rejects, comments with feedback |
| `ai-pr-ready` | `ai-merged` | Orchestrator auto-merges PR into `ai/dev` |
| Any | `ai-blocked` | Agent detects ambiguity or unresolvable issue |
| Any | `ai-error` | Agent crashes, times out, or hits guardrail |

---

## Integration Branch Pattern

All agent work targets an integration branch (`ai/dev`) rather than `main` directly.

```
main (human-controlled)
  └── ai/dev (agents merge here freely)
        ├── ai/issue-1 (feature branch)
        ├── ai/issue-2 (feature branch)
        └── ai/issue-3 (feature branch)
```

**Why:** Prevents merge conflicts. Each coding agent branches from the latest `ai/dev`, so it sees all previously merged agent work. Agents never touch `main`.

**Morning workflow:** Human reviews the cumulative `ai/dev → main` diff. If it's good, merge with one click. If individual changes are bad, revert specific commits or cherry-pick the good ones.

**Per-repo setup:** The `ai/dev` branch must exist before the orchestrator runs. The setup script creates it if missing.

**Auto-merge:** When the review agent approves a PR (label moves to `ai-pr-ready`), the orchestrator merges it into `ai/dev` automatically. If the merge fails (conflict), it labels the issue `ai-blocked` and notifies via Slack.

---

## Agent Types

All agents are `claude -p` invocations with different prompts and tool access.

### Coding Agent

- **Purpose:** Implement the work described in the issue
- **Tool access:** Full write — Edit, Write, Bash, Glob, Grep, Read
- **Behavior:**
  - Creates a feature branch from `ai/dev` (not `main`)
  - Implements the work following the issue checklist and acceptance criteria
  - Writes tests before implementation (TDD principles, lean prompt)
  - Opens a draft PR targeting `ai/dev`, linking to the issue
  - On completion: removes `ai-in-progress`, adds `ai-testing`
- **Guardrails:**
  - Max 10 files changed
  - 60-minute timeout
  - If ambiguity detected: label `ai-blocked`, stop

### Testing Agent

- **Purpose:** Verify the coding agent's work passes tests and meets acceptance criteria
- **Tool access:** Read + Bash (run tests) + Write (test files only)
- **Behavior:**
  - Checks out the PR branch
  - Runs existing test suite
  - Verifies acceptance criteria coverage
  - Adds missing test cases if needed
  - On pass (tests green): removes `ai-testing`, adds `ai-review-needed`
  - On fail (tests red): removes `ai-testing`, adds `ai-ready`, comments with specific test failures. This counts toward the retry cycle limit.
  - On agent crash/timeout: orchestrator labels `ai-error` (distinct from test failures)
- **Guardrails:**
  - 30-minute timeout

### Review Agent

- **Purpose:** Code review the PR against the original issue's acceptance criteria
- **Tool access:** Read-only + comment (Read, Glob, Grep, Bash read-only)
- **Behavior:**
  - Reads the PR diff and original issue
  - Checks against acceptance criteria
  - Reviews for bugs, security issues, edge cases, style
  - Leaves review comments on the PR
  - On approval: removes `ai-review-needed`, adds `ai-pr-ready`
  - On rejection: removes `ai-review-needed`, adds `ai-ready`, comments with what needs fixing
- **Guardrails:**
  - 30-minute timeout
  - Max 3 total cycles per issue (any combination of test failures + review rejections) before labeling `ai-blocked`

---

## Orchestrator Architecture

### Execution Model

A single Python script (`orchestrator.py`) executed by cron every 10 minutes. Each run is self-contained:

1. **Poll** — query GitHub API for issues with actionable labels across configured repos
2. **Check running agents** — read `state.json`, verify PIDs are still alive, detect stuck/timed-out agents
3. **Enforce concurrency** — respect configured limits (e.g., max 2 coding + 1 testing + 1 review)
4. **Dispatch** — spawn `claude -p` for eligible issues, update labels, record in state file
5. **Handle completions** — for exited agent PIDs, check results, update labels accordingly
6. **Notify** — send Slack messages for actionable events

### State Management

Local state file at `~/.agent-orchestrator/state.json`:

```json
{
  "agents": [
    {
      "pid": 12345,
      "issue": "owner/repo#42",
      "repo": "owner/repo",
      "type": "coding",
      "started_at": "2026-04-05T02:00:00Z",
      "timeout_minutes": 60,
      "attempt": 1
    }
  ]
}
```

No database. If the state file is lost, worst case is orphaned `ai-in-progress` issues requiring manual label cleanup.

### Structured Logging

Each agent run produces a log file:

```
~/.agent-orchestrator/logs/<repo>-<issue-number>-<timestamp>.json
```

Contains the `stream-json` output from `claude -p` for debugging.

---

## Slack Notifications

A single incoming webhook pointed at a dedicated channel (e.g., `#agent-activity`).

### Notification Events

| Event | Priority | Message |
|-------|----------|---------|
| Agent blocked | High | "Issue #42 blocked: <reason>" |
| Agent error/crash | High | "Agent failed on #42: <exit code/error>" |
| Max retries hit | High | "Issue #42 hit 3 cycles — marked blocked" |
| Agent timeout | High | "Agent on #42 killed after 60min timeout" |
| PR ready for review | Medium | "Draft PR #15 ready for review (issue #42)" |
| Review rejected | Low | "Review agent sent #42 back for rework (attempt 2/3)" |

### Events NOT Notified (to reduce noise)

- Agent started working (visible on KanBan)
- Normal state transitions
- Routine completions

---

## Remote Dispatch

To queue work for agents remotely:

1. Open GitHub mobile app or GitHub Projects board
2. Add the `ai-ready` label to an issue (or move the card to the appropriate column)
3. Next cron cycle (within 10 minutes), the orchestrator picks it up

No additional infrastructure needed — GitHub's UI is the dispatch interface.

---

## Configuration

### `config.yaml`

```yaml
repos:
  - owner/repo-a
  - owner/repo-b

concurrency:
  max_coding: 2
  max_testing: 1
  max_review: 1

timeouts:
  coding_minutes: 60
  testing_minutes: 30
  review_minutes: 30

guardrails:
  max_files_changed: 10
  max_retry_cycles: 3

slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"

branches:
  integration: "ai/dev"  # agents branch from and merge into this

labels:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review_needed: "ai-review-needed"
  pr_ready: "ai-pr-ready"
  merged: "ai-merged"
  blocked: "ai-blocked"
  error: "ai-error"
```

---

## File Structure

```
/home/bryang/Dev_Space/agent-orchestrator/
├── orchestrator.py          # Main entry point (cron runs this)
├── config.yaml              # Repos, labels, concurrency, timeouts
├── agents/
│   ├── coding.py            # Coding agent dispatch + prompt template
│   ├── testing.py           # Testing agent dispatch + prompt template
│   └── review.py            # Review agent dispatch + prompt template
├── notifications/
│   └── slack.py             # Slack webhook sender
├── github_client.py         # GitHub API wrapper (issues, labels, PRs)
├── state.py                 # State file read/write
├── logger.py                # Structured JSON logging
├── requirements.txt         # PyGithub, requests, pyyaml
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-04-05-agent-orchestrator-design.md
```

### Runtime Files

```
~/.agent-orchestrator/
├── state.json               # Active agent tracking
└── logs/
    └── <repo>-<issue>-<timestamp>.json
```

### Cron Entry

```
*/10 * * * * cd /home/bryang/Dev_Space/agent-orchestrator && python orchestrator.py >> /var/log/agent-orchestrator.log 2>&1
```

---

## Backlog

Items explicitly deferred for future consideration:

1. **claude-mem integration** — cross-session agent memory for learning from past attempts
2. **Web dashboard** — lightweight FastAPI status page if GitHub Projects isn't sufficient
3. **Webhook-driven dispatch** — near-instant agent pickup via GitHub webhooks
4. **Full superpowers skills** — for high-complexity issues labeled `ai-complex`
5. **Documentation agent** — auto-update docs/changelogs after PR merge
6. **Triage agent** — auto-assess issue quality and readiness before entering the queue
