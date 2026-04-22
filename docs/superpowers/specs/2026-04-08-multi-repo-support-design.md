# Multi-Repo Support for Playbook

**Date:** 2026-04-08
**Status:** Approved
**Approach:** Minimal changes — per-repo config + state isolation

## Problem

The playbook orchestrator and skills are coupled to the `paint-ballas-auto` project through hardcoded values in `config.yaml`, `agents/base.py`, and skill instructions. Using playbook with a different repo requires editing these files. Running concurrent orchestrator sessions for different repos is unsafe because they share `~/.agent-orchestrator/state.json`.

## Goals

1. Any repo can use playbook skills and orchestrator by adding a single `playbook.yaml` file
2. Concurrent orchestrator sessions for different repos work without conflicts
3. Minimal changes to existing code — no packaging, no CLI overhaul

## Design

### 1. Per-Repo Config (`playbook.yaml`)

Each target repo gets a `playbook.yaml` at its root with project-specific settings:

```yaml
repo: BryGo1995/paint-ballas-auto

gdd_path: "docs/paint-ballas-gdd.md"

project:
  owner: BryGo1995
  number: 9
  status_field_id: "PVTSSF_lAHOAmiy_s4BTvqizhA8ggw"

concurrency:
  max_coding: 1

branches:
  integration: "ai/dev"
```

Only project-specific fields are required. Everything else inherits from defaults.

### 2. Shared Defaults (`defaults.yaml`)

The current `config.yaml` in the playbook repo is renamed to `defaults.yaml` with all project-specific fields removed. It retains only shared defaults:

```yaml
concurrency:
  max_coding: 1
  max_testing: 1
  max_review: 1

timeouts:
  coding_minutes: 60
  testing_minutes: 30
  review_minutes: 30

guardrails:
  max_files_changed: 10
  max_retry_cycles: 3

versioning:
  enabled: true
  auto_create_issues: false
  bootstrap_timeout_minutes: 120
  bootstrap_max_budget_usd: 5.0

statuses:
  backlog: "Backlog"
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review: "ai-review"
  complete: "ai-complete"
  done: "Done"
  blocked: "ai-blocked"
  error: "ai-error"

slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
```

### 3. Config Loading (changes to `config.py`)

`load_config` is updated to:

1. Accept a working directory path (defaults to CWD)
2. Look for `playbook.yaml` in that directory
3. Load `defaults.yaml` from the playbook repo (located via `__file__` relative path, i.e., `os.path.dirname(__file__)`)
4. Deep merge: defaults first, then `playbook.yaml` overrides
5. Resolve env vars (existing behavior)

The `local_paths` field is eliminated. The orchestrator runs from within the target repo, so CWD is the repo.

A new required field `repo` (e.g., `BryGo1995/paint-ballas-auto`) replaces the `repos` list since each config is scoped to a single repo.

**Deep merge behavior:** Nested dicts are merged recursively. Scalars and lists in `playbook.yaml` override defaults entirely.

### 4. State Isolation (changes to `state.py`)

`StateManager` default `base_dir` changes from `~/.agent-orchestrator` to `.playbook/` relative to CWD.

Directory structure inside each target repo:

```
target-repo/
├── playbook.yaml
├── .playbook/           # gitignored
│   ├── state.json       # agent tracking
│   └── logs/            # per-issue agent logs
└── ...
```

Each repo must add `.playbook/` to its `.gitignore`.

Since each repo has its own state file, concurrent orchestrator sessions for different repos have zero shared state. No file locking is needed.

### 5. Orchestrator Changes (`orchestrator.py`)

`main()` changes:

- Look for `playbook.yaml` in CWD instead of `config.yaml` next to the script
- Use the new `load_config` that merges defaults + per-repo config
- Pass `.playbook/` as `state_dir` to `StateManager`

Dispatch methods (`_dispatch_coding`, `_dispatch_testing`, `_dispatch_review`):

- Remove `local_paths` lookup: `cwd = self.config.get("local_paths", {}).get(issue["repo"])` becomes `cwd = None` (subprocess inherits CWD, which is already the target repo)
- The `issue["repo"]` field from GitHub project board queries still works for keying state — no change needed there

### 6. Agent Base Fix (`agents/base.py`)

Line 12 changes from:

```python
"/home/bryang/.local/bin/claude",
```

to:

```python
"claude",
```

`subprocess.Popen` resolves via `$PATH`. This is required for portability since the orchestrator now runs from any repo/machine.

### 7. Skill Updates

#### `skills/scout/SKILL.md`

Phase 1, step 1 — config discovery changes from:

> Read `config.yaml` in the playbook project directory.

to:

> Read `playbook.yaml` in the current working directory.

Phase 4, step 2 — config update changes from:

> Update `config.yaml`

to:

> Update `playbook.yaml`

All references to `config.yaml` in the skill become `playbook.yaml`.

#### `skills/gameplan/SKILL.md`

Phase 1, step 1 — config discovery changes from:

> Find and read `config.yaml` in the playbook project directory (`/home/bryang/Dev_Space/playbook/config.yaml`). Extract:
> - `gdd_path` (or default to `docs/*-gdd.md` glob if not set)
> - `repos` and `local_paths` — the target repo and its local checkout path

to:

> Read `playbook.yaml` in the current working directory. Extract:
> - `repo` — the GitHub repo identifier (e.g., `BryGo1995/paint-ballas-auto`)
> - `gdd_path` (or default to `docs/*-gdd.md` glob if not set)
> - `project.owner` and `project.number` — for GitHub project board queries

References to `repos` (list) become `repo` (single string). References to `local_paths` are removed — the CWD is the target repo.

Both skills: if `playbook.yaml` is not found in CWD, display:

> "No `playbook.yaml` found in the current directory. Run this skill from a repo that has a `playbook.yaml`."

### 8. Migration Path

**Step 1: Update the playbook repo**
- Rename `config.yaml` to `defaults.yaml`, remove project-specific fields (`repos`, `local_paths`, `gdd_path`, `project`)
- Update `config.py` with CWD discovery + deep merge logic
- Update `state.py` default path to `.playbook/`
- Update `orchestrator.py` main() for CWD-based config loading
- Fix `agents/base.py` hardcoded path
- Update both SKILL.md files

**Step 2: Set up paint-ballas-auto**
- Add `playbook.yaml` with its project-specific settings
- Add `.playbook/` to `.gitignore`

**Setting up any new repo:** Add a `playbook.yaml` with the required fields (`repo`, `gdd_path`, `project`) and `.playbook/` to `.gitignore`.

**Old state:** Existing `~/.agent-orchestrator/` data from previous runs remains on disk but is no longer referenced. It can be cleaned up manually at any time.

## Files Changed

| File | Change |
|------|--------|
| `config.yaml` | Renamed to `defaults.yaml`, project-specific fields removed |
| `config.py` | CWD discovery, deep merge with defaults, env var resolution |
| `state.py` | Default `base_dir` changed to `.playbook/` relative to CWD |
| `orchestrator.py` | `main()` uses CWD config; dispatch methods drop `local_paths` |
| `agents/base.py` | Hardcoded claude path → `"claude"` |
| `skills/scout/SKILL.md` | `config.yaml` references → `playbook.yaml` in CWD |
| `skills/gameplan/SKILL.md` | `config.yaml` references → `playbook.yaml` in CWD; `repos`/`local_paths` → `repo` |
| `.claude/settings.local.json` | Remove hardcoded paint-ballas paths from allowlist |
| `paint-ballas-auto/playbook.yaml` | New file — project-specific config |
| `paint-ballas-auto/.gitignore` | Add `.playbook/` entry |

## Out of Scope

- Packaging playbook as a pip-installable CLI tool (future enhancement)
- Multi-repo orchestration from a single process (each repo runs its own orchestrator)
- Auto-discovery of repos with `playbook.yaml` files
