# Playbook

A lightweight orchestrator that dispatches Claude Code headless agents to work on GitHub Issues. Agents code, test, and review PRs autonomously while you're away. GitHub Projects is your dashboard, Slack is your alert channel.

## How It Works

```
You label an issue "ai-ready" on GitHub (phone, desktop, anywhere)
        ↓
Playbook picks it up (cron, every 10 min)
        ↓
Coding agent → branches from ai/dev, implements, opens draft PR
        ↓
Testing agent → runs tests, verifies acceptance criteria
        ↓
Review agent → reviews PR against issue requirements
        ↓
Auto-merge → PR merged into ai/dev
        ↓
You review ai/dev → main in the morning
```

### Label State Machine

```
ai-ready → ai-in-progress → ai-testing → ai-review-needed → ai-pr-ready → ai-merged
              ↑                                  |
              └──────────────────────────────────┘  (rejected → back to coding)

ai-blocked  — agent needs human input
ai-error    — agent crashed or timed out
```

### Integration Branch Pattern

Agents work on `ai/dev`, never `main`. Each coding agent branches from the latest `ai/dev`, so it sees all previously merged work. No merge conflicts between concurrent agents.

```
main (you control)
  └── ai/dev (agents merge here)
        ├── ai/issue-1
        ├── ai/issue-2
        └── ai/issue-3
```

In the morning, review the cumulative diff and merge `ai/dev → main` with one click.

## Agent Types

| Agent | Purpose | Tool Access |
|-------|---------|------------|
| **Coding** | Implements the issue, opens draft PR | Full write (Edit, Write, Bash, Read, Glob, Grep) |
| **Testing** | Runs tests, verifies acceptance criteria, adds missing tests | Read + Bash + Write (test files only) |
| **Review** | Reviews PR against acceptance criteria, comments on issues | Read-only (Read, Glob, Grep, Bash) |

All agents are `claude -p` invocations with tailored prompts and restricted `--allowedTools`.

## Project Structure

```
playbook/
├── orchestrator.py          # Main entry point — cron runs this every 10 min
├── summary.py               # Generates Slack activity summaries (8am/8pm)
├── config.yaml              # Repos, concurrency, timeouts, labels
├── config.py                # Config loading with env var resolution
├── state.py                 # JSON state file for tracking active agents
├── github_client.py         # GitHub API wrapper (labels, comments, PRs, merges)
├── logger.py                # Structured JSON logger
├── setup.sh                 # One-time setup helper
├── requirements.txt         # Python dependencies
├── agents/
│   ├── base.py              # Shared claude -p command builder
│   ├── coding.py            # Coding agent prompt + config
│   ├── testing.py           # Testing agent prompt + config
│   └── review.py            # Review agent prompt + config
├── notifications/
│   └── slack.py             # Slack incoming webhook sender
├── tests/                   # 46 tests
└── docs/
    └── superpowers/
        ├── specs/           # Design spec
        └── plans/           # Implementation plan
```

### Runtime Files

```
~/.agent-orchestrator/
├── state.json               # Active agent PIDs and metadata
├── summary_state.json       # Last summary timestamp
└── logs/
    └── <repo>-<issue>-<timestamp>.json   # Per-agent stream-json logs
```

## Setup

### Prerequisites

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- GitHub personal access token with repo scope
- (Optional) Slack incoming webhook URL

### Install

```bash
git clone git@github.com:BryGo1995/playbook.git
cd playbook

# Set environment variables
export GITHUB_TOKEN=ghp_your_token_here
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...  # optional

# Run setup
./setup.sh
```

### Configure

Edit `config.yaml` with your repos:

```yaml
repos:
  - your-username/your-repo
  - your-username/another-repo

branches:
  integration: "ai/dev"

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
```

### Per-Repo Setup

For each repo in your config:

1. **Create the `ai/dev` branch** from `main`
2. **Create the labels:** `ai-ready`, `ai-in-progress`, `ai-testing`, `ai-review-needed`, `ai-pr-ready`, `ai-merged`, `ai-blocked`, `ai-error`
3. **Set up GitHub Projects** automation rules to map labels to KanBan columns
4. **Add agent instructions** to the repo's `CLAUDE.md` (project standards, test commands, etc.)
5. **Set up the Integration PR workflow** — Copy `templates/integration-pr-caller.yml` to `.github/workflows/integration-pr.yml` in the target repo. This auto-creates a persistent `ai/dev -> main` PR whenever agents merge work into `ai/dev`. Edit the branch names in the file if your integration branch differs. No secrets required.

### Cron

Add to your crontab (`crontab -e`):

```cron
GITHUB_TOKEN=your_token
SLACK_WEBHOOK_URL=your_webhook

# Orchestrator: dispatch agents every 10 minutes
*/10 * * * * cd /path/to/playbook && python3 orchestrator.py >> /var/log/agent-orchestrator.log 2>&1

# Morning summary: 8am
0 8 * * * cd /path/to/playbook && python3 summary.py >> /var/log/agent-orchestrator.log 2>&1

# Evening summary: 8pm
0 20 * * * cd /path/to/playbook && python3 summary.py >> /var/log/agent-orchestrator.log 2>&1
```

## Usage

### Dispatch Work

From anywhere (GitHub mobile, desktop, Projects board):

1. Add the `ai-ready` label to an issue
2. Within 10 minutes, Playbook picks it up and starts a coding agent

### Monitor

- **GitHub Projects** — KanBan board updates automatically as labels change
- **Slack** — alerts for blocked agents, errors, timeouts, and PR-ready notifications
- **Summaries** — 8am and 8pm Slack summaries of all activity

### Morning Review

1. Check Slack for the overnight summary and any blocked/error alerts
2. Open the persistent `ai/dev -> main` PR on GitHub — it lists all completed issues and commits
3. Review the diff, then merge using a **regular merge commit** (not squash) to keep branches in sync
4. A new integration PR will be created automatically when the next batch of work lands on `ai/dev`

### Manual Summary

```bash
python3 summary.py                # since last summary
python3 summary.py --since 2h     # last 2 hours
python3 summary.py --since 12h    # last 12 hours
```

## Slack Notifications

| Event | When |
|-------|------|
| Agent blocked | Agent can't proceed, needs human input |
| Agent error | Agent crashed or hit a guardrail |
| Agent timeout | Agent exceeded time limit |
| Max retries | Issue cycled 3 times through coding/testing/review |
| PR ready | Draft PR merged into `ai/dev` |
| Review rejected | Review agent sent issue back for rework |

## Guardrails

- **Concurrency limits** — configurable max agents per type
- **Timeouts** — coding: 60min, testing: 30min, review: 30min
- **Retry cap** — 3 cycles (any combo of test failures + review rejections) before marking blocked
- **Scope limits** — max 10 files changed per coding agent
- **Draft PRs only** — agents never merge to `main`
- **Tool restrictions** — review agent is read-only, testing agent can only write test files

## Integration PR Workflow

When agents merge work into `ai/dev`, a GitHub Action automatically creates (or updates) a PR targeting `main`. The PR body lists:

- All `Closes #N` references extracted from commit history (so merging auto-closes the issues)
- A commit log of everything included

### How It Works

1. Agent merges feature PR into `ai/dev`
2. Push triggers the integration PR workflow
3. Workflow scans `git log main..ai/dev` for issue references
4. Creates a new PR or updates the existing one

The PR stays open and accumulates work. Merge it when you're ready — all referenced issues close automatically.

### Setup for New Repos

Copy `templates/integration-pr-caller.yml` to `.github/workflows/integration-pr.yml` in the target repo. Edit branch names if needed. No secrets required.

> **Important:** Always merge the integration PR with a regular merge commit (not squash). Squash-merging causes `ai/dev` and `main` to diverge in history, leading to ghost conflicts on future PRs.

## Tests

```bash
python3 -m pytest tests/ -v
```
