# Playbook

A lightweight orchestrator that dispatches Claude Code headless agents to work on GitHub Issues. Agents code, test, and review PRs autonomously while you're away. GitHub Projects is your dashboard, Slack is your alert channel.

Playbook also ships as a Claude Code plugin with three skills — **Scout**, **Gameplan**, and **Film Room** — that cover design, planning, and post-run review.

---

## Usage

### Prerequisites

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- GitHub personal access token with `repo` scope
- (Optional) Slack incoming webhook URL

### Install

```bash
git clone git@github.com:BryGo1995/playbook.git
cd playbook

export GITHUB_TOKEN=ghp_your_token_here
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...  # optional

./setup.sh
```

### Per-Project Config

Each project you want agents working on needs a `playbook.yaml` at its root. Shared defaults live in `defaults.yaml` inside the playbook repo and are merged in automatically.

```yaml
# <project>/playbook.yaml
repo: your-username/your-repo
gdd_path: docs/my-project-gdd.md       # set by /playbook:scout
orchestrator_dir: /path/to/playbook

project:
  owner: your-username
  number: 1                             # GitHub Projects board number
  status_field_id: "PVTSSF_..."         # Projects status field node ID
```

Override any shared default (concurrency, timeouts, guardrails, versioning) by adding the same key to `playbook.yaml`.

### Per-Repo Setup on GitHub

For each repo Playbook manages:

1. Create the `ai/dev` branch from `main`.
2. Create the labels: `ai-ready`, `ai-in-progress`, `ai-testing`, `ai-review`, `ai-complete`, `ai-blocked`, `ai-error`.
3. On the GitHub Projects board, map those labels to columns via the status field.
4. Add agent instructions to the repo's `CLAUDE.md` (project standards, test commands, etc.).
5. Copy `templates/integration-pr-caller.yml` to `.github/workflows/integration-pr.yml` in the target repo. This auto-creates a persistent `ai/dev -> main` PR whenever agents merge work. Edit branch names if yours differ. No secrets required.

### Cron

List your projects in `run-all.sh`, then add to `crontab -e`:

```cron
GITHUB_TOKEN=your_token
SLACK_WEBHOOK_URL=your_webhook

# Dispatch agents every 10 minutes
*/10 * * * * /path/to/playbook/run-all.sh >> /var/log/playbook.log 2>&1

# Morning / evening Slack summaries
0 8,20 * * * cd /path/to/playbook && python3 summary.py >> /var/log/playbook.log 2>&1
```

`run-all.sh` iterates each project directory you list and runs the orchestrator against that project's `playbook.yaml`.

### Day-to-Day

**Dispatch work.** Add the `ai-ready` label to any issue (from GitHub mobile, desktop, or the Projects board). Within 10 minutes Playbook picks it up.

**Monitor.** The Projects board updates automatically as labels change. Slack fires alerts on blocks, errors, timeouts, and PR-ready events, plus 8am/8pm activity summaries.

**Morning review.**

1. Check Slack for the overnight summary and any alerts.
2. Open the persistent `ai/dev -> main` PR — it lists every completed issue and commit.
3. Merge it with a **regular merge commit** (not squash) so `ai/dev` and `main` stay in sync.

**Manual summary.**

```bash
python3 summary.py                # since last summary
python3 summary.py --since 2h     # last 2 hours
```

### Using the Skills

Invoke inside any project with a `playbook.yaml`:

- `/playbook:scout` — create or iterate on a GDD/PRD via conversational interview.
- `/playbook:gameplan` — plan the next version and create agent-ready issues.
- `/playbook:film-room` — review a completed version branch, fix issues, merge back.

### Running Tests

```bash
python3 -m pytest tests/ -v
```

---

## How It Works

### Workflow Overview

```
/playbook:scout      → GDD/PRD creation
        ↓
/playbook:gameplan   → decompose into agent-ready issues
        ↓
Orchestrator picks up "ai-ready" issues (cron, every 10 min)
        ↓
Coding agent  → branches from ai/dev, implements, opens draft PR
        ↓
Testing agent → runs tests, verifies acceptance criteria
        ↓
Review agent  → reviews PR against requirements
        ↓
Auto-merge    → PR merged into ai/dev
        ↓
/playbook:film-room  → morning review of ai/dev, merge to main
```

### Skills

**Scout** guides you through creating a Game Design Document or Product Requirements Document via conversational interview. Ships templates for Game, Application, and Library projects; custom templates can be added to `skills/scout/templates/`. Outputs to `docs/<project>-gdd.md` (or `-prd.md`) and updates `gdd_path` in `playbook.yaml`.

**Gameplan** reads the GDD/PRD, analyzes repo state and the project board, proposes the next version's scope, and creates conflict-free issues using a structured template (acceptance criteria, file scope, testing criteria). Its conflict-avoidance strategy adapts to the `max_coding` concurrency setting.

**Film Room** runs a post-agent review session on a completed version branch. Sets up a tracking issue and fix branch, manages a checklist as you identify problems, and handles merge-back when you're done.

### Agents

| Agent | Purpose | Tool Access |
|-------|---------|------------|
| **Coding** | Implements the issue, opens a draft PR | Full write (Edit, Write, Bash, Read, Glob, Grep) |
| **Testing** | Runs tests, verifies acceptance criteria, adds missing tests | Read + Bash + Write (test files only) |
| **Review** | Reviews PR against acceptance criteria | Read-only |

All agents are `claude -p` invocations with tailored prompts and restricted `--allowedTools`.

### Integration Branch Pattern

Agents work on `ai/dev`, never `main`. Each coding agent branches from the latest `ai/dev`, so it sees all previously merged work — no conflicts between concurrent agents.

```
main (you control)
  └── ai/dev (agents merge here)
        ├── ai/issue-1
        ├── ai/issue-2
        └── ai/issue-3
```

### Label State Machine

```
ai-ready → ai-in-progress → ai-testing → ai-review → ai-complete
              ↑                               |
              └───────────────────────────────┘  (rejected → back to coding)

ai-blocked  — needs human input
ai-error    — crashed or timed out
```

### Version-Gated Dispatch

Issues are dispatched in version order based on `[vX.Y]` tags in titles. The orchestrator only runs issues from the lowest incomplete version — all v0.1 issues must reach `Done` before any v0.2 issue starts.

- `[bootstrap]` — runs first, alone (max 1 concurrent), for project scaffold
- `[v0.1]`, `[v0.2]`, … — run in order; issues within a version run in parallel
- No tag — runs after all versioned work is complete

All issues in a version must be safe to run in parallel (no shared file writes). A blocked issue holds the version open until resolved. Slack fires when a version completes.

### Integration PR Workflow

When agents merge into `ai/dev`, a GitHub Action creates or updates a PR targeting `main`. The PR body lists every `Closes #N` reference from the commit log, so merging auto-closes the issues.

> **Important:** always merge the integration PR with a regular merge commit, not squash. Squashing causes `ai/dev` and `main` to diverge and leads to ghost conflicts on future PRs.

### Guardrails

- **Concurrency limits** — configurable max agents per type
- **Timeouts** — coding 60min, testing 30min, review 30min (default)
- **Retry cap** — 3 cycles of test failures or review rejections before marking blocked
- **Scope limits** — max 10 files changed per coding agent
- **Draft PRs only** — agents never merge to `main`
- **Tool restrictions** — review agent is read-only; testing agent can only write test files

### Slack Notifications

| Event | When |
|-------|------|
| Agent blocked | Agent needs human input |
| Agent error | Agent crashed or hit a guardrail |
| Agent timeout | Agent exceeded its time limit |
| Max retries | Issue cycled 3 times through coding/testing/review |
| PR ready | Draft PR merged into `ai/dev` |
| Review rejected | Review agent sent the issue back for rework |
| Version complete | All issues in a version reached `Done` |

### Learning Loop

Each film-room session ends by running two distillers that turn the
human-validated fixes into proposed improvements:

- **Project distiller** — proposes additions to the project repo's
  `CLAUDE.md` so future agents working on the same repo pick up the
  conventions automatically. Output: a PR against the project repo.
- **Agent-craft distiller** — looks for failure modes of the agents
  themselves (not project conventions) and either proposes a prompt edit
  to `agents/{coding,review,testing}.py` (when ≥2 fixes show the same
  pattern, or one severe occurrence) or appends an entry to
  `docs/agent-craft-observations.md` for future pattern-matching. Output:
  a PR against the playbook repo.

Both distillers always produce PRs — never auto-merges. The human is the
gate. Disable per-project via `playbook.yaml`:

```yaml
learning:
  enabled: true              # set false to disable both distillers
  project_distiller: true
  agent_craft_distiller: true
  playbook_repo: "BryGo1995/playbook"
```

### Project Structure

```
playbook/
├── orchestrator.py          # main entry point, invoked per project by run-all.sh
├── run-all.sh               # runs orchestrator across all configured projects
├── summary.py               # Slack activity summaries (8am/8pm)
├── defaults.yaml            # shared defaults merged into each project's playbook.yaml
├── config.py                # config loading (defaults + project) with env var resolution
├── versioning.py            # version-gated dispatch logic
├── state.py                 # JSON state file for tracking active agents
├── github_client.py         # GitHub API wrapper
├── logger.py                # structured JSON logger
├── setup.sh                 # one-time setup helper
├── agents/
│   ├── base.py              # shared claude -p command builder
│   ├── coding.py
│   ├── testing.py
│   └── review.py
├── notifications/
│   └── slack.py
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── skills/
│   ├── scout/               # GDD/PRD creation
│   ├── gameplan/            # version planning + issue decomposition
│   └── film-room/           # post-run review session
├── templates/
│   └── integration-pr-caller.yml
├── tests/
└── docs/superpowers/        # specs and plans
```

### Runtime Files

```
~/.agent-orchestrator/
├── state.json               # active agent PIDs and metadata
├── summary_state.json       # last summary timestamp
└── logs/
    └── <repo>-<issue>-<timestamp>.json   # per-agent stream-json logs
```
