# Multi-Repo Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the playbook orchestrator and skills from the paint-ballas-auto project so any repo can use playbook by adding a `playbook.yaml` file.

**Architecture:** Each target repo gets a `playbook.yaml` with project-specific config. The playbook repo provides `defaults.yaml` with shared defaults. `config.py` deep-merges them. State moves from `~/.agent-orchestrator/` to `.playbook/` inside each target repo for full isolation.

**Tech Stack:** Python, YAML, pytest

**Spec:** `docs/superpowers/specs/2026-04-08-multi-repo-support-design.md`

---

### Task 1: Update `config.py` — CWD Discovery and Deep Merge

**Files:**
- Modify: `config.py` (entire file, 26 lines)
- Create: `defaults.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for the new config loading**

Add these tests to `tests/test_config.py`:

```python
def test_load_config_merges_defaults_and_project(tmp_path, monkeypatch):
    """Project playbook.yaml overrides defaults.yaml values."""
    # Create a defaults.yaml in a fake playbook dir
    defaults = tmp_path / "playbook"
    defaults.mkdir()
    (defaults / "defaults.yaml").write_text("""
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
statuses:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
slack:
  webhook_url: "default"
""")

    # Create a playbook.yaml in a fake project dir
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/my-project
gdd_path: "docs/my-gdd.md"
project:
  owner: owner
  number: 5
  status_field_id: "PVTSSF_test"
concurrency:
  max_coding: 2
""")

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults / "defaults.yaml"))
    # Project-specific values
    assert cfg["repo"] == "owner/my-project"
    assert cfg["gdd_path"] == "docs/my-gdd.md"
    assert cfg["project"]["number"] == 5
    # Override from project
    assert cfg["concurrency"]["max_coding"] == 2
    # Inherited from defaults
    assert cfg["concurrency"]["max_testing"] == 1
    assert cfg["timeouts"]["coding_minutes"] == 60
    assert cfg["statuses"]["ready"] == "ai-ready"


def test_load_config_no_playbook_yaml_raises(tmp_path):
    """Error when playbook.yaml is not found in the project directory."""
    with pytest.raises(FileNotFoundError, match="playbook.yaml"):
        load_config(project_dir=str(tmp_path), defaults_path="/nonexistent/defaults.yaml")


def test_load_config_env_vars_resolved_in_merged_config(tmp_path, monkeypatch):
    """Env vars are resolved after merging."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/merged")
    defaults_dir = tmp_path / "playbook"
    defaults_dir.mkdir()
    (defaults_dir / "defaults.yaml").write_text('slack:\n  webhook_url: "${SLACK_WEBHOOK_URL}"\n')

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text('repo: owner/proj\nproject:\n  owner: owner\n  number: 1\n  status_field_id: "test"\n')

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults_dir / "defaults.yaml"))
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/merged"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_config.py -v`
Expected: FAIL — `load_config` doesn't accept `project_dir` or `defaults_path` parameters yet.

- [ ] **Step 3: Create `defaults.yaml`**

Create `defaults.yaml` at the playbook repo root with the shared defaults extracted from `config.yaml`:

```yaml
# Playbook — Shared Defaults
# Project-specific settings go in each repo's playbook.yaml

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

- [ ] **Step 4: Rewrite `config.py`**

Replace the contents of `config.py` with:

```python
# config.py
import os
import re
import yaml


def _resolve_env_vars(value):
    """Replace ${VAR_NAME} patterns with environment variable values."""
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            value,
        )
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins for scalars and lists."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(project_dir: str | None = None, defaults_path: str | None = None) -> dict:
    """Load defaults.yaml from playbook repo, merge with playbook.yaml from project dir."""
    if project_dir is None:
        project_dir = os.getcwd()

    if defaults_path is None:
        defaults_path = os.path.join(os.path.dirname(__file__), "defaults.yaml")

    # Load project config (required)
    project_config_path = os.path.join(project_dir, "playbook.yaml")
    if not os.path.exists(project_config_path):
        raise FileNotFoundError(
            f"No playbook.yaml found in {project_dir}. "
            "Create a playbook.yaml with your project-specific settings."
        )
    with open(project_config_path) as f:
        project = yaml.safe_load(f) or {}

    # Load defaults (optional — works without it, just uses project config only)
    defaults = {}
    if os.path.exists(defaults_path):
        with open(defaults_path) as f:
            defaults = yaml.safe_load(f) or {}

    merged = _deep_merge(defaults, project)
    return _resolve_env_vars(merged)
```

- [ ] **Step 5: Update existing tests for new signature**

The existing tests in `tests/test_config.py` use the old `load_config(path)` signature. Update them to use the new interface. Replace `test_load_config_returns_all_sections`:

```python
def test_load_config_returns_all_sections(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/repo-a
gdd_path: "docs/gdd.md"
project:
  owner: owner
  number: 1
  status_field_id: "test"
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
  webhook_url: "https://hooks.slack.com/test"
statuses:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review: "ai-review"
  complete: "ai-complete"
  done: "Done"
  blocked: "ai-blocked"
  error: "ai-error"
""")
    # No defaults file — project config is self-contained
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg["repo"] == "owner/repo-a"
    assert cfg["concurrency"]["max_coding"] == 2
    assert cfg["timeouts"]["coding_minutes"] == 60
    assert cfg["guardrails"]["max_retry_cycles"] == 3
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/test"
    assert cfg["statuses"]["ready"] == "ai-ready"
```

Replace `test_load_config_resolves_env_vars`:

```python
def test_load_config_resolves_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/from-env")
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/repo-a
slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
""")
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/from-env"
```

Replace `test_gdd_path_missing_returns_none`:

```python
def test_gdd_path_missing_returns_none(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("repo: owner/repo-a\n")
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg.get("gdd_path") is None
```

Replace `test_gdd_path_explicit_value`:

```python
def test_gdd_path_explicit_value(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text(
        'repo: owner/repo-a\ngdd_path: "docs/my-game-gdd.md"\n'
    )
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg["gdd_path"] == "docs/my-game-gdd.md"
```

Replace `test_load_config_missing_file_raises`:

```python
def test_load_config_missing_playbook_yaml_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="playbook.yaml"):
        load_config(project_dir=str(tmp_path), defaults_path=str(tmp_path / "nonexistent.yaml"))
```

- [ ] **Step 6: Run all config tests**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_config.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add config.py defaults.yaml tests/test_config.py
git commit -m "feat: add CWD-based config loading with defaults merge"
```

---

### Task 2: Update `state.py` — Per-Repo State Directory

**Files:**
- Modify: `state.py:10` (default parameter)
- Test: `tests/test_state.py`

- [ ] **Step 1: Write failing test for CWD-relative default**

Add this test to `tests/test_state.py`:

```python
def test_default_base_dir_is_cwd_playbook(tmp_path, monkeypatch):
    """StateManager defaults to .playbook/ in the current working directory."""
    monkeypatch.chdir(tmp_path)
    sm = StateManager()
    expected = os.path.join(str(tmp_path), ".playbook")
    assert sm.base_dir == expected
    assert os.path.isdir(os.path.join(expected, "logs"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_state.py::test_default_base_dir_is_cwd_playbook -v`
Expected: FAIL — default is `~/.agent-orchestrator`, not `.playbook/`.

- [ ] **Step 3: Update `state.py` default**

In `state.py`, change line 10 from:

```python
def __init__(self, base_dir: str = os.path.expanduser("~/.agent-orchestrator")):
```

to:

```python
def __init__(self, base_dir: str | None = None):
    if base_dir is None:
        base_dir = os.path.join(os.getcwd(), ".playbook")
```

Note: the rest of `__init__` remains unchanged (`self.base_dir = base_dir`, etc.).

- [ ] **Step 4: Run all state tests**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_state.py -v`
Expected: All tests PASS. Existing tests pass an explicit `state_dir` so they're unaffected.

- [ ] **Step 5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat: default state directory to .playbook/ in CWD"
```

---

### Task 3: Update `orchestrator.py` — CWD-Based Config and Remove `local_paths`

**Files:**
- Modify: `orchestrator.py:306-307,334,360,375-378`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Update the orchestrator config fixture**

In `tests/test_orchestrator.py`, update the `config` fixture to use `repo` (string) instead of `repos` (list), and remove `local_paths`:

```python
@pytest.fixture
def config():
    return {
        "repo": "owner/repo",
        "project": {
            "owner": "owner",
            "number": 1,
            "status_field_id": "PVTSSF_test",
        },
        "concurrency": {"max_coding": 2, "max_testing": 1, "max_review": 1},
        "timeouts": {"coding_minutes": 60, "testing_minutes": 30, "review_minutes": 30},
        "guardrails": {"max_files_changed": 10, "max_retry_cycles": 3},
        "branches": {"integration": "ai/dev"},
        "slack": {"webhook_url": None},
        "statuses": {
            "backlog": "Backlog",
            "ready": "ai-ready",
            "in_progress": "ai-in-progress",
            "testing": "ai-testing",
            "review": "ai-review",
            "complete": "ai-complete",
            "done": "Done",
            "blocked": "ai-blocked",
            "error": "ai-error",
        },
    }
```

- [ ] **Step 2: Run tests to verify they still pass**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_orchestrator.py -v`
Expected: All PASS — the config fixture change doesn't affect any test logic since no test reads `repos` or `local_paths`.

- [ ] **Step 3: Remove `local_paths` from dispatch methods**

In `orchestrator.py`, update the three dispatch methods. Each has a line like:

```python
cwd = self.config.get("local_paths", {}).get(issue["repo"])
```

Replace each with:

```python
cwd = None  # Orchestrator runs from within the target repo
```

This appears on lines 306, 334, and 360.

- [ ] **Step 4: Update `main()` to use new config loading**

Replace lines 375-383 of `orchestrator.py`:

```python
def main():
    config = load_config()  # Reads playbook.yaml from CWD, merges with defaults.yaml
    orchestrator = Orchestrator(config)
    orchestrator.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run all orchestrator tests**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_orchestrator.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator uses CWD config, removes local_paths"
```

---

### Task 4: Fix `agents/base.py` — Remove Hardcoded Claude Path

**Files:**
- Modify: `agents/base.py:12`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Read existing agent tests**

Read `tests/test_agents.py` to understand the current test structure.

- [ ] **Step 2: Write failing test for PATH-based claude resolution**

Add to `tests/test_agents.py`:

```python
def test_claude_command_uses_path_not_absolute():
    """The claude binary should be resolved via PATH, not a hardcoded absolute path."""
    from agents.base import build_claude_command
    cmd = build_claude_command("test prompt", ["Read", "Write"])
    assert cmd[0] == "claude"
    assert not cmd[0].startswith("/")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_agents.py::test_claude_command_uses_path_not_absolute -v`
Expected: FAIL — `cmd[0]` is `/home/bryang/.local/bin/claude`.

- [ ] **Step 4: Fix the hardcoded path**

In `agents/base.py`, change line 12 from:

```python
        "/home/bryang/.local/bin/claude",
```

to:

```python
        "claude",
```

- [ ] **Step 5: Run all agent tests**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest tests/test_agents.py -v`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/base.py tests/test_agents.py
git commit -m "fix: resolve claude binary via PATH instead of hardcoded path"
```

---

### Task 5: Update Skills — Config Discovery via CWD

**Files:**
- Modify: `skills/scout/SKILL.md`
- Modify: `skills/gameplan/SKILL.md`

- [ ] **Step 1: Update `skills/scout/SKILL.md`**

Make these replacements in `skills/scout/SKILL.md`:

**Phase 1, step 1 (line 55-56):** Replace:
```
   - Read `config.yaml` in the playbook project directory. If `gdd_path` is set,
     that is the authoritative pointer to the existing document.
```
with:
```
   - Read `playbook.yaml` in the current working directory. If `gdd_path` is set,
     that is the authoritative pointer to the existing document.
```

**Phase 4, step 2 (line 179):** Replace:
```
2. **Update `config.yaml`** — Set `gdd_path` to the path of the newly written
```
with:
```
2. **Update `playbook.yaml`** — Set `gdd_path` to the path of the newly written
```

**Phase 4, step 3 (line 185):** Replace:
```
   git add docs/<project-name>-<suffix>.md config.yaml
```
with:
```
   git add docs/<project-name>-<suffix>.md playbook.yaml
```

**Phase 4, option C archive flow (line 90):** Replace:
```
     Then update `config.yaml` to clear `gdd_path`, and proceed as a fresh start.
```
with:
```
     Then update `playbook.yaml` to clear `gdd_path`, and proceed as a fresh start.
```

**Skill Guidelines (line 211):** Replace:
```
- **`gdd_path` is the single source of truth.** Always keep `config.yaml`
  up to date. Never let `gdd_path` point to a stale or archived file.
```
with:
```
- **`gdd_path` is the single source of truth.** Always keep `playbook.yaml`
  up to date. Never let `gdd_path` point to a stale or archived file.
```

**Common Mistakes (line 235-236):** Replace:
```
- **Leaving `gdd_path` stale** — If the output file path changes (fresh start,
  rename), update `config.yaml` immediately. The gameplan skill trusts that
  pointer completely.
```
with:
```
- **Leaving `gdd_path` stale** — If the output file path changes (fresh start,
  rename), update `playbook.yaml` immediately. The gameplan skill trusts that
  pointer completely.
```

- [ ] **Step 2: Update `skills/gameplan/SKILL.md`**

**Phase 1, step 1 (lines 54-59):** Replace:
```
1. **Read playbook config** — Find and read `config.yaml` in the playbook project
   directory (`/home/bryang/Dev_Space/playbook/config.yaml`). Extract:
   - `gdd_path` (or default to `docs/*-gdd.md` glob if not set)
   - `repos` and `local_paths` — the target repo and its local checkout path
   - `project.owner` and `project.number` — for GitHub project board queries
   - `concurrency.max_coding` — determines conflict avoidance rigor
   - `versioning` settings
```
with:
```
1. **Read playbook config** — Read `playbook.yaml` in the current working
   directory. If not found, stop and tell the user:
   > "No `playbook.yaml` found in the current directory. Run this skill from a
   > repo that has a `playbook.yaml`."

   Extract:
   - `repo` — the GitHub repo identifier (e.g., `BryGo1995/paint-ballas-auto`)
   - `gdd_path` (or default to `docs/*-gdd.md` glob if not set)
   - `project.owner` and `project.number` — for GitHub project board queries
   - `concurrency.max_coding` — determines conflict avoidance rigor
   - `versioning` settings
```

**Phase 1, step 2 (line 62):** Replace:
```
2. **Read the GDD/PRD** — Read the file at `gdd_path` in the target repo's local
   checkout. Extract the roadmap/milestone table to understand version progression.
```
with:
```
2. **Read the GDD/PRD** — Read the file at `gdd_path` in the current working
   directory. Extract the roadmap/milestone table to understand version progression.
```

**Phase 1, step 3 (line 65):** Replace:
```
3. **Scan repo state** — In the target repo's local checkout:
```
with:
```
3. **Scan repo state** — In the current working directory:
```

- [ ] **Step 3: Commit**

```bash
git add skills/scout/SKILL.md skills/gameplan/SKILL.md
git commit -m "docs: update skills to use playbook.yaml in CWD"
```

---

### Task 6: Remove Old `config.yaml` and Clean Up Settings

**Files:**
- Delete: `config.yaml`
- Modify: `.claude/settings.local.json`

- [ ] **Step 1: Delete `config.yaml`**

```bash
cd /home/bryang/Dev_Space/playbook
git rm config.yaml
```

- [ ] **Step 2: Clean up `.claude/settings.local.json`**

Remove the two hardcoded paint-ballas permission entries from `.claude/settings.local.json`:

Remove these lines:
```
"Bash(mkdir -p /home/bryang/Dev_Space/paint-ballas-auto/.github/workflows)",
"Bash(cp /home/bryang/Dev_Space/agent-orchestrator/.worktrees/integration-pr/templates/integration-pr-caller.yml /home/bryang/Dev_Space/paint-ballas-auto/.github/workflows/integration-pr.yml)",
```

Also remove the hardcoded GITHUB_TOKEN permission:
```
"Bash(GITHUB_TOKEN=<REDACTED> python3:*)",
```

This contains a token in plaintext and should not be in the settings file.

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.local.json
git commit -m "chore: remove old config.yaml and clean up settings"
```

Note: `config.yaml` is already staged by `git rm` in step 1.

---

### Task 7: Set Up `paint-ballas-auto` with `playbook.yaml`

**Files:**
- Create: `/home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto/playbook.yaml`
- Modify: `/home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto/.gitignore`

- [ ] **Step 1: Create `playbook.yaml` in paint-ballas-auto**

```yaml
# Playbook — Project Configuration
# Shared defaults are in the playbook repo's defaults.yaml

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

- [ ] **Step 2: Add `.playbook/` to `.gitignore`**

Append to `/home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto/.gitignore`:

```
# Playbook orchestrator state (local only)
.playbook/
```

- [ ] **Step 3: Commit in the paint-ballas-auto repo**

```bash
cd /home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto
git add playbook.yaml .gitignore
git commit -m "feat: add playbook.yaml for orchestrator config"
```

---

### Task 8: Run Full Test Suite and Verify

**Files:**
- No new files

- [ ] **Step 1: Run all playbook tests**

Run: `cd /home/bryang/Dev_Space/playbook && python -m pytest --tb=short -v`
Expected: All tests PASS.

- [ ] **Step 2: Verify config loading end-to-end**

Run from paint-ballas-auto to verify the full config merge works:

```bash
cd /home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto
python3 -c "
import sys; sys.path.insert(0, '/home/bryang/Dev_Space/playbook')
from config import load_config
cfg = load_config()
print('repo:', cfg['repo'])
print('gdd_path:', cfg['gdd_path'])
print('max_coding:', cfg['concurrency']['max_coding'])
print('coding_timeout:', cfg['timeouts']['coding_minutes'])
print('status ready:', cfg['statuses']['ready'])
print('Config loaded successfully')
"
```

Expected output:
```
repo: BryGo1995/paint-ballas-auto
gdd_path: docs/paint-ballas-gdd.md
max_coding: 1
coding_timeout: 60
status ready: ai-ready
Config loaded successfully
```

- [ ] **Step 3: Verify state isolation**

```bash
cd /home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto
python3 -c "
import sys; sys.path.insert(0, '/home/bryang/Dev_Space/playbook')
from state import StateManager
sm = StateManager()
print('State dir:', sm.base_dir)
assert '.playbook' in sm.base_dir
print('State isolation verified')
"
```

Expected: State dir ends with `.playbook` and is inside the paint-ballas-auto repo.
