# Playbook

A lightweight orchestrator that dispatches Claude Code headless agents to work on GitHub Issues. Agents code, test, and review PRs autonomously while you're away. GitHub Projects is your dashboard, Slack is your alert channel.

Playbook also ships as a Claude Code plugin with three skills — **Scout**, **Gameplan**, and **Film Room** — that cover design, planning, and post-run review.

**Tech stack:** Python 3.11 · Claude Code (`claude -p` headless, runs on your Pro/Max subscription — no `ANTHROPIC_API_KEY` required) · GitHub REST API (PyGithub) · Slack webhooks · cron

## Contents

- [Why Playbook](#why-playbook)
- [Cost & Billing](#cost--billing)
- [Usage](#usage) — [Prerequisites](#prerequisites) · [Install](#install) · [Per-Project Config](#per-project-config) · [Per-Repo Setup on GitHub](#per-repo-setup-on-github) · [Run It](#run-it) · [Day-to-Day](#day-to-day) · [Skills](#using-the-skills)
- [Security & Trust Model](#security--trust-model)
- [How It Works](#how-it-works) — [Workflow](#workflow-overview) · [Skills](#skills) · [Agents](#agents) · [Integration Branch Pattern](#integration-branch-pattern) · [Label State Machine](#label-state-machine) · [Version-Gated Dispatch](#version-gated-dispatch) · [Snapshot Refs](#snapshot-refs-on-coding-agent-failure) · [Slack Notifications](#slack-notifications) · [Learning Loop](#learning-loop) · [Quality Metrics](#quality-metrics)

### Highlights

- **Multi-agent pipeline.** Separate coding, testing, and review agents run as `claude -p` subprocesses with per-agent tool allowlists — review is read-only, testing can only write to test files, and force-push / push-to-main / branch-deletion are blocked at the tool layer. See [Security & Trust Model](#security--trust-model).
- **Version-gated dispatch.** Issues tagged `[vX.Y]` execute in waves — the orchestrator holds the next version until the current one is fully `Done`, preventing concurrent agents from clobbering each other's merges.
- **Integration branch pattern.** Agents work on `ai/dev`, never `main`. A GitHub Action maintains one persistent `ai/dev → main` PR as the single human-review checkpoint.
- **Self-improving workflow.** Each Film Room session distills human-validated fixes into proposed PRs — updating the target repo's `CLAUDE.md` and the agent prompts. Humans stay the gate; nothing auto-merges.
- **Quality-signal metrics (opt-in).** A structural check sharpens vague acceptance criteria at plan time; a classifier tags every Film Room fix by upstream point of failure. Per-version files plus a cross-version rollup surface which part of the pipeline needs tuning.
- **Guardrails.** Defaults: 60-min coding / 30-min testing / 30-min review timeouts, max 3 retry cycles, max 10 files per coding agent, draft-only PRs, Slack alerts on blocks/errors/timeouts plus 8am/8pm summaries.

---

## Why Playbook

If you already pay for Claude Pro or Max and want autonomous agents working your GitHub issues overnight, your options today are roughly:

| Tool | Where it runs | Billing | Best for |
|---|---|---|---|
| **GitHub Copilot Coding Agent** | Sandboxed cloud env | Bundled w/ Copilot subscription | Native GitHub UI, teams already on Copilot |
| **Devin / Cursor Background Agents** | Cloud VMs | Subscription + per-task compute | Slick UI, parallel cloud agents |
| **OpenHands** (OSS) | Local Docker | Your own API keys | Self-hosted, model-agnostic |
| **Playbook** | Your laptop / your VM | **Your existing Claude subscription** | Solo devs who plan in versions, want background work overnight, and prefer local execution |

Pick Playbook if you want to keep work local, you already have a Claude subscription, and you like the opinionated **GDD → versioned issues → integration branch → film-room review** workflow. Pick one of the cloud options if you want sandboxed execution, a polished web UI, or a team-oriented control plane.

Playbook is **not** trying to be an enterprise agent platform. It's a single-developer tool with strong opinions about how solo project work should flow.

## Cost & Billing

Playbook runs Claude Code as a subprocess (`claude -p`), so agents authenticate with **whatever your local `claude` CLI is logged into** — typically your Claude Pro or Max subscription. **No `ANTHROPIC_API_KEY` is required**, and agent runs count against your subscription quota, not pay-per-token API billing.

If you'd rather use API billing (e.g., your subscription quota is too small for overnight runs, or you want token-level cost visibility), set `ANTHROPIC_API_KEY` in your environment and Claude Code will prefer it. Mixing the two is fine — `claude` picks whichever auth is configured.

The only billed Claude operation Playbook performs is the `claude -p` subprocess itself; the orchestrator, GitHub API calls, and Slack notifications cost nothing beyond your existing GitHub/Slack accounts.

---

## Usage

### Prerequisites

- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and logged in (`claude` — uses your Pro/Max subscription, no API key required; see [Cost & Billing](#cost--billing))
- GitHub personal access token with `repo` scope ([create a fine-grained token](https://github.com/settings/tokens?type=beta) scoped to just the repos Playbook will manage)
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
gdd_path: docs/my-project-gdd.md       # populated by /playbook:scout
orchestrator_dir: /path/to/playbook

project:
  owner: your-username
  number: 1                             # GitHub Projects board number
  status_field_id: "PVTSSF_..."         # Projects status field node ID — populated by /playbook:gameplan
```

You don't have to fill `gdd_path` or `status_field_id` by hand — `/playbook:scout` and `/playbook:gameplan` create the GDD/PRD, set up (or detect) the GitHub Project board, and write both back into `playbook.yaml`. Minimum bootstrap config is just `repo` and `orchestrator_dir`. Any shared default (concurrency, timeouts, guardrails) can be overridden with the same key in `playbook.yaml`.

### Per-Repo Setup on GitHub

For each repo Playbook manages:

1. Create the `ai/dev` branch from `main`.
2. Create the labels: `ai-ready`, `ai-in-progress`, `ai-testing`, `ai-review`, `ai-complete`, `ai-blocked`, `ai-error`.
3. On the GitHub Projects board, map those labels to columns via the status field.
4. Add agent instructions to the repo's `CLAUDE.md` (project standards, test commands, etc.).
5. Copy `templates/integration-pr-caller.yml` to `.github/workflows/integration-pr.yml` in the target repo. This auto-creates a persistent `ai/dev -> main` PR whenever agents merge work. Edit branch names if yours differ. No secrets required.

### Run It

Playbook is a script you can run two ways: once at a time (good for first-time evaluation), or on a cron schedule (the intended steady state).

**Try it once.** From inside a project directory that has a `playbook.yaml`:

```bash
cd /path/to/your-project
GITHUB_TOKEN=ghp_... PYTHONPATH=/path/to/playbook python3 -c 'from orchestrator import main; main()'
```

This runs one dispatch cycle: scans `ai-ready` issues, dispatches agents subject to concurrency caps, and exits. Run it again to advance state. No cron needed for evaluation.

**Set up cron (steady state).** First, list the projects you want included in `~/.config/playbook/projects.sh` (honors `XDG_CONFIG_HOME`):

```bash
# In ~/.config/playbook/projects.sh
PROJECTS=(
    "$HOME/code/my-project"
    "$HOME/code/another-project"
)
```

This file lives outside the playbook repo so your project list never travels with the distribution. Each listed directory must contain a `playbook.yaml`. Then add to `crontab -e`:

```cron
GITHUB_TOKEN=your_token
SLACK_WEBHOOK_URL=your_webhook

# Dispatch agents every 10 minutes (iterates the projects in ~/.config/playbook/projects.sh)
*/10 * * * * /path/to/playbook/run-all.sh >> /var/log/playbook.log 2>&1

# Morning / evening Slack summaries — one line per project
0 8,20 * * * cd /path/to/your-project && PYTHONPATH=/path/to/playbook python3 -c 'from summary import main; main()' >> /var/log/playbook.log 2>&1
```

`run-all.sh` reads `~/.config/playbook/projects.sh`, iterates each directory in that `PROJECTS` array, and runs the orchestrator against the project's `playbook.yaml`. Per-agent stream-json logs land in `~/.agent-orchestrator/logs/`; orchestrator-cycle output goes wherever you redirect cron stdout (above: `/var/log/playbook.log`).

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

The typical first-run order is `/playbook:scout` → `/playbook:gameplan` → wait for the orchestrator to dispatch → `/playbook:film-room`. See [Skills](#skills) under "How It Works" for what each does in detail.

### Running Tests

```bash
python3 -m pytest tests/ -v
```

See [docs/ci-cd.md](docs/ci-cd.md) for the CI gating and release process.

---

## Security & Trust Model

Playbook dispatches autonomous agents that run shell commands, edit code, push branches, and call the GitHub API on your behalf. Read this section before you point it at any repo you care about.

### What the agent can do

When the orchestrator fires a coding agent, it is a `claude -p` subprocess running in the project directory with:

- **Shell access** via `Bash` (broad, with deny patterns — see below)
- **File access** via `Read`, `Edit`, `Write` across the project tree (and any directories your user can reach)
- **Git push access** via your local git credential helper — the agent can push to feature branches and the integration branch
- **GitHub API access** via `GITHUB_TOKEN` from the orchestrator's environment, with whatever scopes you granted

The testing and review agents have narrower allowlists (testing can only `Write` to test files; review has no `Edit`/`Write` at all), but both still have `Bash` and the GitHub token.

### A note on subscription auth

Playbook invokes `claude -p` in your environment, so each agent inherits *your* Claude Code login. Anthropic's terms permit using your Pro/Max subscription for personal automation and your own agents — which is exactly what Playbook is. You are not sharing your credential with anyone; each user runs Playbook against their own account, and there's no "Playbook service" mediating the call. If you'd rather use API billing, set `ANTHROPIC_API_KEY` and Claude Code will prefer it.

### Who can dispatch an agent

The orchestrator only dispatches agents on issues that have the `ai-ready` label. On GitHub, applying labels requires **triage or write access** to the repo. So the effective trust boundary is:

> **Anyone who can apply the `ai-ready` label to an issue in a Playbook-managed repo can cause an agent to act on its contents, with all the privileges your local environment + `GITHUB_TOKEN` allow.**

Concretely:

- **Private repo, you + vetted collaborators** — the trust set is the people you've added with triage/write access. Reasonable for most users.
- **Public repo with restrictive triage** — the trust set is whoever you've granted triage to (default: nobody outside maintainers).
- **Public repo with permissive triage / open contribution** — the trust set is much wider; treat with care.

The label gate is a meaningful boundary, not just any-issue-creator. But it is implicit in your GitHub repo configuration, not enforced by Playbook itself.

### Layered defenses (and their limits)

The agent reads issue title and body as part of its prompt. A maliciously crafted issue body could try to redirect the agent's behavior — known as **prompt injection**. Three layers of defense are in place:

**Layer 1 — Prompt framing.** Issue title and body are wrapped in `<untrusted_issue_content>` tags with explicit "data, not instructions" framing. The agent is told to follow legitimate work guidance ("use library X", "don't change the public API") but refuse operational redirection ("push to main", "force-push", "exfiltrate the token"). *Limit*: relies on the model's compliance; sufficiently clever injection can still talk the agent into compliance.

**Layer 2 — Tool-level deny patterns.** Claude Code's `--disallowedTools` blocks the highest-value attacks at the tool layer for all three agents: force-push (every variant), direct push to `main`/`master`, branch deletion via push, `gh pr merge`, `gh repo delete`, `gh release delete`, raw destructive `gh api -X DELETE` calls. Review agent additionally denies `git push`, `git commit`, `git merge` entirely. *Limits*: pattern matching is fragile — `bash -c "..."` wrappers, extra whitespace, novel flag aliases, custom git aliases, or destructive paths that aren't pre-enumerated will bypass the patterns.

**Layer 3 — This documentation.** You opt in knowingly.

### What is NOT protected

The current architecture does not prevent:

- **Reading sensitive files** outside the project tree — `~/.ssh/id_rsa`, `~/.aws/credentials`, `.env` files, etc. — `Read` is unrestricted.
- **Network exfiltration** — `curl`/`wget` to attacker-controlled servers can send anything the agent reads.
- **Modifying CI/CD workflows** — `.github/workflows/*.yml` is writable, and a malicious workflow merged via `ai/dev → main` would run with whatever secrets your CI has.
- **Creating GitHub artifacts** — issues, branches, comments, draft PRs in the managed repos can all be created.
- **Side effects in shared services** the orchestrator's environment can reach (your local Docker, kubectl context, cloud CLIs if authenticated, etc.).

A determined attacker with prompt-injection control of a coding agent can do anything your local environment + `GITHUB_TOKEN` allows. **Treat `ai-ready` label permission on a managed repo as roughly equivalent to local code execution on the orchestrator host.**

### Recommended deployment posture

| Posture | What it looks like | Risk |
|---|---|---|
| **Best** | Private repo · vetted collaborators · `GITHUB_TOKEN` scoped to the single managed repo · orchestrator runs in a dedicated VM/container with no access to other credentials | Low |
| **Reasonable** | Private repo · org collaborators · `GITHUB_TOKEN` scoped to managed repos only · orchestrator runs on a dev workstation without sensitive creds in env | Moderate |
| **Caution** | Public repo with restrictive triage · `GITHUB_TOKEN` with broad scope · orchestrator on a primary workstation with SSH keys, cloud creds, etc. | High |
| **Not recommended** | Public repo with open triage · org-wide write `GITHUB_TOKEN` · workstation with production credentials | Don't |

If you don't have a fine-grained personal access token already, [create one](https://github.com/settings/tokens?type=beta) scoped to just the repos Playbook will manage.

### Operational guidance

- **Review the persistent `ai/dev → main` PR** before merging — every agent change funnels through it. Read the diff like you'd read any external contributor's PR.
- **Monitor Slack alerts** for unexpected blocks, errors, timeouts. An agent suddenly hitting a deny pattern is a signal worth investigating.
- **Audit local repo state** periodically — `git for-each-ref refs/playbook/snapshots/` shows the orchestrator's failure-state snapshots; unexpected branches in the project repo are worth a look.
- **If you suspect a compromise:** rotate `GITHUB_TOKEN` immediately, kill the orchestrator (`pkill -f orchestrator`), inspect recent commits in the integration branch and any feature branches, and check `~/.bash_history` for unexpected commands.

### Sandboxing roadmap

A future version is planned to support running agents in ephemeral containers with a per-repo scoped token, eliminating the laptop-blast-radius problem. Until that ships, the deployment posture above is the right hardening. If your threat model demands stronger isolation today, run the orchestrator in a dedicated VM with no access to credentials beyond a repo-scoped `GITHUB_TOKEN`.

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

- **Scout** — conversational interview to create or iterate on a GDD/PRD. Ships templates for Game, Application, and Library projects (custom templates: `skills/scout/templates/`). Outputs to `docs/<project>-gdd.md` and updates `gdd_path` in `playbook.yaml`.
- **Gameplan** — reads the GDD, analyzes repo state and the project board, proposes the next version's scope, and creates conflict-free issues using a structured template. Conflict-avoidance adapts to the `max_coding` setting.
- **Film Room** — post-version review session. Sets up a tracking issue and fix branch, manages a checklist of issues you find, handles merge-back, and triggers the [learning loop](#learning-loop).

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

When agents merge into `ai/dev`, a GitHub Action creates or updates a single PR targeting `main`. The PR body lists every `Closes #N` reference from the commit log, so merging auto-closes the issues.

> **Important:** always merge the integration PR with a regular merge commit, not squash. Squashing causes `ai/dev` and `main` to diverge and leads to ghost conflicts on future PRs.

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

### Snapshot refs on coding-agent failure

When a coding agent times out or exits without creating a PR, the orchestrator pushes a forensic snapshot of the working tree to `ai/issue-N-attempt-K` (committed state) and optionally `ai/issue-N-attempt-K-wip` (stashed dirty state). Subsequent retries feed these into the next agent's prompt as prior-attempt context.

<details>
<summary>Operational notes</summary>

- Successful auto-merge cleans up all `ai/issue-N-attempt-*` refs for the issue. Max-retry failures leave snapshots in place as forensic evidence.
- The `ai/issue-*` namespace must remain unprotected (no force-push protection) for snapshots to function. If protection blocks the push, the failure is recorded as `snapshot: unavailable` and recovery still proceeds.
- Toggle off via `guardrails.snapshot_on_failure: false` in `playbook.yaml`.
- The first retry of any existing issue after this feature ships has no prior snapshots — that is expected.

</details>

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

Each Film Room session ends by running two distillers that turn human-validated fixes into proposed PRs. Both write **only to the project repo** — neither modifies the playbook installation, so project-specific signal cannot leak into the upstream playbook prompts.

- **Project distiller** — proposes additions to the project's `CLAUDE.md` so future agents pick up the conventions.
- **Agent-craft distiller** — captures recurring agent failure modes (≥2 fixes show the same pattern, or one severe case) as a project-local addendum in `.playbook/agents/{coding,review,testing}.md`, loaded by the orchestrator at dispatch and appended to the matching agent's prompt. Weaker signals accumulate in `.playbook/agent-craft-observations.md`.

Both distillers share a single branch (`learning/film-room-vX.Y`) and combine into one PR. The human is the gate — distillers never auto-merge. Disable per-project:

```yaml
learning:
  enabled: true              # set false to disable both distillers
  project_distiller: true
  agent_craft_distiller: true
```

### Quality Metrics

Two lightweight probes capture where quality leaks in the pipeline:

- **Structural check (gameplan).** Before presenting issues, auto-revises acceptance criteria that lack measurable anchors (numbers, states, comparisons). Genuinely subjective criteria get a `[subjective]` marker that flows to film-room.
- **Classifier (film-room).** At end of each session, a subagent classifies every fix by the earliest upstream point where it should have been caught. Writes per-version data to `metrics/vX.Y.md` and regenerates a cross-version `metrics/SUMMARY.md` rollup for trend spotting.

Disabled by default. Enable per-project via `playbook.yaml`:

```yaml
metrics:
  enabled: true
  show_checks: false               # flip to true to see inline summaries during skill sessions
  classification_budget_usd: 0.25  # per-version classifier cap
```

Format reference: `docs/metrics-format.md`.

<details>
<summary><strong>Project structure & runtime files</strong></summary>

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
├── agents/                  # base.py + coding.py + testing.py + review.py
├── notifications/slack.py
├── .claude-plugin/          # plugin.json + marketplace.json
├── skills/                  # scout/, gameplan/, film-room/
├── templates/integration-pr-caller.yml
├── tests/
└── docs/superpowers/        # specs and plans
```

Runtime files (created on first run):

```
~/.agent-orchestrator/
├── state.json               # active agent PIDs and metadata
├── summary_state.json       # last summary timestamp
└── logs/
    └── <repo>-<issue>-<timestamp>.json   # per-agent stream-json logs
```

</details>
