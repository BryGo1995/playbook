# CI/CD Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the minimal single-version CI with a two-track pipeline — a hardened PR gate (Python matrix, plugin validation, coverage report, audit, shellcheck) and a tag-triggered release pipeline with a one-command helper script and idempotent publish.

**Architecture:** Two GitHub Actions workflows (`ci.yml` rewritten, `release.yml` new) plus a Python validator script, a bash release helper, a Dependabot config, and a user-facing workflow doc. The validator script is pytest-covered and runnable locally; the release helper enforces preconditions (clean main, in sync with origin) and bumps `plugin.json` + `marketplace.json` versions atomically. `release.yml` reuses `ci.yml` via `workflow_call` so there is one source of truth for "is the build green."

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`), Python 3.11/3.12/3.13, `pytest`, `coverage`, `ruff`, `pyyaml`, `pip-audit`, `shellcheck`, `gh` CLI, Dependabot v2.

**Spec:** `docs/specs/2026-05-16-ci-cd-pipeline-design.md`

---

## File Structure

**New files:**
- `scripts/validate_plugin.py` — standalone Python validator for `plugin.json`, `marketplace.json`, skills, agent prompts. Runnable locally (`python scripts/validate_plugin.py`); used by `ci.yml`.
- `scripts/release.sh` — one-command release helper: assert preconditions, bump versions, commit, tag, push.
- `tests/test_validate_plugin.py` — pytest coverage for the validator using temp-dir fixtures.
- `.github/workflows/release.yml` — tag-triggered release pipeline; reuses `ci.yml` as a gate.
- `.github/dependabot.yml` — weekly grouped bumps for `pip` and `github-actions`.
- `docs/ci-cd.md` — user/maintainer-facing workflow documentation.

**Modified files:**
- `.github/workflows/ci.yml` — rewritten: matrix (3.11/3.12/3.13), `validate-plugin` job, `shellcheck` job, coverage, `pip-audit` (warn-only), `workflow_call` trigger added.
- `requirements-dev.txt` — add `coverage` and `pip-audit`.
- `tests/test_distribution.py` and `tests/test_snapshot_integration.py` — audit; mark any network-touching tests with `@pytest.mark.skipif` so CI runs them honestly.

---

## Authoritative version locations (referenced throughout)

Three places hold the version; they must agree on every release:

1. `.claude-plugin/plugin.json` → top-level `version` field.
2. `.claude-plugin/marketplace.json` → `metadata.version`.
3. `.claude-plugin/marketplace.json` → `plugins[0].version`.

The validator asserts all three agree. The release script updates all three atomically.

---

## Agent prompt reference pattern (referenced in Task 1)

Agent Python files use this exact pattern (verified):

```python
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "<name>.md")
```

Files: `agents/coding.py`, `agents/testing.py`, `agents/review.py`. Each references `agents/prompts/<name>.md`. The validator parses these files and verifies each referenced prompt file exists.

---

## Skill frontmatter conventions (referenced in Task 1)

Existing skills (`skills/scout/SKILL.md`, `skills/gameplan/SKILL.md`, `skills/film-room/SKILL.md`) all use:

```yaml
---
name: playbook:<dir-name>
description: >
  Multi-line description in YAML folded scalar form.
---
```

Validator rule for skill name: the `name:` value must be `playbook:<dirname>` where `<dirname>` is the parent directory name. (E.g., `skills/scout/SKILL.md` → `name: playbook:scout`.)

---

## Task 1: Write `scripts/validate_plugin.py` skeleton with first failing test

**Files:**
- Create: `scripts/validate_plugin.py`
- Create: `tests/test_validate_plugin.py`
- Create: `tests/fixtures/validate_plugin/` (directory)

- [ ] **Step 1: Create fixture directory and a known-good plugin layout**

Run:
```bash
mkdir -p tests/fixtures/validate_plugin/good/.claude-plugin
mkdir -p tests/fixtures/validate_plugin/good/skills/sample
mkdir -p tests/fixtures/validate_plugin/good/agents/prompts
```

Create `tests/fixtures/validate_plugin/good/.claude-plugin/plugin.json`:
```json
{
  "name": "sample",
  "description": "Sample plugin for tests",
  "version": "0.1.0",
  "author": { "name": "test" }
}
```

Create `tests/fixtures/validate_plugin/good/.claude-plugin/marketplace.json`:
```json
{
  "name": "sample",
  "owner": { "name": "test" },
  "metadata": {
    "description": "Sample plugin for tests",
    "version": "0.1.0"
  },
  "plugins": [
    { "name": "sample", "source": "./", "description": "Sample", "version": "0.1.0" }
  ]
}
```

Create `tests/fixtures/validate_plugin/good/skills/sample/SKILL.md`:
```markdown
---
name: playbook:sample
description: A sample skill for validator tests.
---

# Sample Skill
```

Create `tests/fixtures/validate_plugin/good/agents/coding.py`:
```python
import os
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "coding.md")
```

Create `tests/fixtures/validate_plugin/good/agents/prompts/coding.md`:
```markdown
# Coding agent prompt
```

- [ ] **Step 2: Write the first failing test (validator accepts known-good fixture)**

Create `tests/test_validate_plugin.py`:
```python
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "validate_plugin"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_plugin.py"


def run_validator(plugin_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(plugin_root)],
        capture_output=True,
        text=True,
    )


def test_good_fixture_passes():
    result = run_validator(FIXTURES / "good")
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
```

- [ ] **Step 3: Run test to verify it fails (script doesn't exist yet)**

Run: `python -m pytest tests/test_validate_plugin.py::test_good_fixture_passes -v`
Expected: FAIL with non-zero return code (script file not found).

- [ ] **Step 4: Write minimal validator that passes the good fixture**

Create `scripts/validate_plugin.py`:
```python
#!/usr/bin/env python3
"""Validate the playbook plugin layout.

Checks plugin.json, marketplace.json, skill frontmatter, and agent prompt
references. Exits non-zero on any hard failure; warnings do not affect exit.

Usage:
    python scripts/validate_plugin.py [--root PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


@dataclass
class Report:
    passes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.passes.append(msg)

    def fail(self, msg: str) -> None:
        self.failures.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def print(self) -> None:
        for m in self.passes:
            print(f"✓ {m}")
        for m in self.warnings:
            print(f"⚠ {m}")
        for m in self.failures:
            print(f"✗ {m}")

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


def validate(root: Path) -> Report:
    report = Report()
    _check_plugin_manifests(root, report)
    _check_skills(root, report)
    _check_agent_prompts(root, report)
    return report


def _check_plugin_manifests(root: Path, report: Report) -> None:
    plugin_path = root / ".claude-plugin" / "plugin.json"
    marketplace_path = root / ".claude-plugin" / "marketplace.json"

    if not plugin_path.exists():
        report.fail(f"{plugin_path.relative_to(root)} missing")
        return
    if not marketplace_path.exists():
        report.fail(f"{marketplace_path.relative_to(root)} missing")
        return

    try:
        plugin = json.loads(plugin_path.read_text())
    except json.JSONDecodeError as e:
        report.fail(f"plugin.json invalid JSON: {e}")
        return
    try:
        marketplace = json.loads(marketplace_path.read_text())
    except json.JSONDecodeError as e:
        report.fail(f"marketplace.json invalid JSON: {e}")
        return

    for field_name in ("name", "version"):
        if field_name not in plugin:
            report.fail(f"plugin.json missing required field '{field_name}'")

    plugin_version = plugin.get("version")
    market_metadata_version = marketplace.get("metadata", {}).get("version")
    market_plugins = marketplace.get("plugins", [])
    market_plugin_version = market_plugins[0].get("version") if market_plugins else None

    versions = {
        "plugin.json": plugin_version,
        "marketplace.json metadata.version": market_metadata_version,
        "marketplace.json plugins[0].version": market_plugin_version,
    }
    distinct = {v for v in versions.values() if v is not None}
    if len(distinct) > 1:
        report.fail(f"version mismatch across manifests: {versions}")
    else:
        report.ok(f"plugin.json + marketplace.json (version {plugin_version})")


def _check_skills(root: Path, report: Report) -> None:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            report.fail(f"{skill_md.relative_to(root)} missing")
            continue
        text = skill_md.read_text()
        m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not m:
            report.fail(f"{skill_md.relative_to(root)}: missing YAML frontmatter")
            continue
        try:
            front = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            report.fail(f"{skill_md.relative_to(root)}: frontmatter YAML error: {e}")
            continue
        for required in ("name", "description"):
            if not front.get(required):
                report.fail(f"{skill_md.relative_to(root)}: missing required field '{required}'")
        expected_name = f"playbook:{skill_dir.name}"
        if front.get("name") and front["name"] != expected_name:
            report.fail(
                f"{skill_md.relative_to(root)}: name '{front['name']}' "
                f"does not match expected '{expected_name}'"
            )
        if front.get("name") == expected_name and front.get("description"):
            report.ok(f"{skill_md.relative_to(root)}")


def _check_agent_prompts(root: Path, report: Report) -> None:
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return
    pattern = re.compile(r'os\.path\.join\(\s*os\.path\.dirname\(__file__\)\s*,\s*"prompts"\s*,\s*"([^"]+)"')
    for py in sorted(agents_dir.glob("*.py")):
        text = py.read_text()
        for match in pattern.finditer(text):
            prompt_name = match.group(1)
            prompt_path = agents_dir / "prompts" / prompt_name
            if not prompt_path.exists():
                report.fail(
                    f"{py.relative_to(root)} references missing prompt "
                    f"{prompt_path.relative_to(root)}"
                )
            else:
                report.ok(f"{py.relative_to(root)} → prompts/{prompt_name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="Plugin root (default: cwd)")
    args = parser.parse_args(argv)
    report = validate(args.root.resolve())
    report.print()
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_validate_plugin.py::test_good_fixture_passes -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/validate_plugin.py tests/test_validate_plugin.py tests/fixtures/validate_plugin/
git commit -m "feat(ci): add plugin validator script with good-fixture test"
```

---

## Task 2: Validator — missing plugin.json fails

**Files:**
- Modify: `tests/test_validate_plugin.py` (add test)
- Create: `tests/fixtures/validate_plugin/missing_plugin_json/.claude-plugin/marketplace.json`

- [ ] **Step 1: Create the bad fixture**

Run:
```bash
mkdir -p tests/fixtures/validate_plugin/missing_plugin_json/.claude-plugin
```

Create `tests/fixtures/validate_plugin/missing_plugin_json/.claude-plugin/marketplace.json` (just need *something* there so only plugin.json is missing):
```json
{
  "name": "sample",
  "metadata": { "version": "0.1.0" },
  "plugins": [{ "name": "sample", "version": "0.1.0" }]
}
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_validate_plugin.py`:
```python
def test_missing_plugin_json_fails():
    result = run_validator(FIXTURES / "missing_plugin_json")
    assert result.returncode == 1
    assert "plugin.json" in result.stdout
    assert "missing" in result.stdout
```

- [ ] **Step 3: Run test to verify it passes**

The validator already handles this case in `_check_plugin_manifests`. Run:
`python -m pytest tests/test_validate_plugin.py::test_missing_plugin_json_fails -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/validate_plugin/missing_plugin_json/ tests/test_validate_plugin.py
git commit -m "test(ci): validator catches missing plugin.json"
```

---

## Task 3: Validator — version mismatch across manifests fails

**Files:**
- Create: `tests/fixtures/validate_plugin/version_mismatch/.claude-plugin/{plugin,marketplace}.json`
- Modify: `tests/test_validate_plugin.py`

- [ ] **Step 1: Create fixture with mismatched versions**

Run:
```bash
mkdir -p tests/fixtures/validate_plugin/version_mismatch/.claude-plugin
```

Create `tests/fixtures/validate_plugin/version_mismatch/.claude-plugin/plugin.json`:
```json
{
  "name": "sample",
  "version": "0.1.0",
  "author": { "name": "test" }
}
```

Create `tests/fixtures/validate_plugin/version_mismatch/.claude-plugin/marketplace.json`:
```json
{
  "name": "sample",
  "owner": { "name": "test" },
  "metadata": { "description": "x", "version": "0.2.0" },
  "plugins": [{ "name": "sample", "source": "./", "description": "x", "version": "0.1.0" }]
}
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_validate_plugin.py`:
```python
def test_version_mismatch_fails():
    result = run_validator(FIXTURES / "version_mismatch")
    assert result.returncode == 1
    assert "version mismatch" in result.stdout
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_validate_plugin.py::test_version_mismatch_fails -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/validate_plugin/version_mismatch/ tests/test_validate_plugin.py
git commit -m "test(ci): validator catches version mismatch across manifests"
```

---

## Task 4: Validator — skill missing required frontmatter field fails

**Files:**
- Create: `tests/fixtures/validate_plugin/bad_skill_frontmatter/...`
- Modify: `tests/test_validate_plugin.py`

- [ ] **Step 1: Create fixture (good manifests + skill with no description)**

Run:
```bash
mkdir -p tests/fixtures/validate_plugin/bad_skill_frontmatter/.claude-plugin
mkdir -p tests/fixtures/validate_plugin/bad_skill_frontmatter/skills/sample
```

Create `tests/fixtures/validate_plugin/bad_skill_frontmatter/.claude-plugin/plugin.json`:
```json
{ "name": "sample", "version": "0.1.0", "author": { "name": "test" } }
```

Create `tests/fixtures/validate_plugin/bad_skill_frontmatter/.claude-plugin/marketplace.json`:
```json
{
  "name": "sample",
  "owner": { "name": "test" },
  "metadata": { "description": "x", "version": "0.1.0" },
  "plugins": [{ "name": "sample", "source": "./", "description": "x", "version": "0.1.0" }]
}
```

Create `tests/fixtures/validate_plugin/bad_skill_frontmatter/skills/sample/SKILL.md`:
```markdown
---
name: playbook:sample
---

# Sample with no description
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_validate_plugin.py`:
```python
def test_skill_missing_description_fails():
    result = run_validator(FIXTURES / "bad_skill_frontmatter")
    assert result.returncode == 1
    assert "description" in result.stdout
    assert "sample/SKILL.md" in result.stdout
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_validate_plugin.py::test_skill_missing_description_fails -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/validate_plugin/bad_skill_frontmatter/ tests/test_validate_plugin.py
git commit -m "test(ci): validator catches missing skill description"
```

---

## Task 5: Validator — skill name mismatch with directory fails

**Files:**
- Create: `tests/fixtures/validate_plugin/skill_name_mismatch/...`
- Modify: `tests/test_validate_plugin.py`

- [ ] **Step 1: Create fixture**

Run:
```bash
mkdir -p tests/fixtures/validate_plugin/skill_name_mismatch/.claude-plugin
mkdir -p tests/fixtures/validate_plugin/skill_name_mismatch/skills/sample
```

Create `tests/fixtures/validate_plugin/skill_name_mismatch/.claude-plugin/plugin.json`:
```json
{ "name": "sample", "version": "0.1.0", "author": { "name": "test" } }
```

Create `tests/fixtures/validate_plugin/skill_name_mismatch/.claude-plugin/marketplace.json`:
```json
{
  "name": "sample",
  "owner": { "name": "test" },
  "metadata": { "description": "x", "version": "0.1.0" },
  "plugins": [{ "name": "sample", "source": "./", "description": "x", "version": "0.1.0" }]
}
```

Create `tests/fixtures/validate_plugin/skill_name_mismatch/skills/sample/SKILL.md`:
```markdown
---
name: playbook:wrong
description: name slug doesn't match directory
---
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_validate_plugin.py`:
```python
def test_skill_name_mismatch_fails():
    result = run_validator(FIXTURES / "skill_name_mismatch")
    assert result.returncode == 1
    assert "playbook:wrong" in result.stdout
    assert "playbook:sample" in result.stdout
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_validate_plugin.py::test_skill_name_mismatch_fails -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/validate_plugin/skill_name_mismatch/ tests/test_validate_plugin.py
git commit -m "test(ci): validator catches skill name/directory mismatch"
```

---

## Task 6: Validator — missing agent prompt file fails

**Files:**
- Create: `tests/fixtures/validate_plugin/missing_prompt/...`
- Modify: `tests/test_validate_plugin.py`

- [ ] **Step 1: Create fixture (agent .py references a prompt that doesn't exist)**

Run:
```bash
mkdir -p tests/fixtures/validate_plugin/missing_prompt/.claude-plugin
mkdir -p tests/fixtures/validate_plugin/missing_prompt/agents/prompts
```

Create `tests/fixtures/validate_plugin/missing_prompt/.claude-plugin/plugin.json`:
```json
{ "name": "sample", "version": "0.1.0", "author": { "name": "test" } }
```

Create `tests/fixtures/validate_plugin/missing_prompt/.claude-plugin/marketplace.json`:
```json
{
  "name": "sample",
  "owner": { "name": "test" },
  "metadata": { "description": "x", "version": "0.1.0" },
  "plugins": [{ "name": "sample", "source": "./", "description": "x", "version": "0.1.0" }]
}
```

Create `tests/fixtures/validate_plugin/missing_prompt/agents/coding.py`:
```python
import os
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "coding.md")
```

Note: deliberately do NOT create `agents/prompts/coding.md`.

- [ ] **Step 2: Write failing test**

Append to `tests/test_validate_plugin.py`:
```python
def test_missing_agent_prompt_fails():
    result = run_validator(FIXTURES / "missing_prompt")
    assert result.returncode == 1
    assert "coding.md" in result.stdout
    assert "missing" in result.stdout
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_validate_plugin.py::test_missing_agent_prompt_fails -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/validate_plugin/missing_prompt/ tests/test_validate_plugin.py
git commit -m "test(ci): validator catches missing agent prompt file"
```

---

## Task 7: Run validator against the real playbook repo

**Files:** none changed (smoke test)

- [ ] **Step 1: Run the validator against the actual repo**

Run: `python scripts/validate_plugin.py`
Expected: exit 0 with `✓` lines for `plugin.json + marketplace.json`, each `skills/<dir>/SKILL.md`, and each agent → prompt mapping.

- [ ] **Step 2: If any failures appear, fix the repo (not the validator)**

If real-world failures appear, document them and fix the underlying repo issue (e.g., add a missing description). The validator is reflecting reality; do not loosen rules to make playbook pass.

- [ ] **Step 3: Commit any repo fixes (if needed)**

If a repo fix was required:
```bash
git add <fixed-files>
git commit -m "fix: <what was wrong>"
```

If no fixes needed, skip this step.

---

## Task 8: Add `coverage` and `pip-audit` to dev requirements

**Files:**
- Modify: `requirements-dev.txt`

- [ ] **Step 1: Read current contents**

Current `requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0
ruff>=0.15
```

- [ ] **Step 2: Append new dev deps**

Update `requirements-dev.txt` to:
```
-r requirements.txt
pytest>=8.0
ruff>=0.15
coverage>=7.6
pip-audit>=2.7
pyyaml>=6.0
```

(`pyyaml` is already in `requirements.txt` but listing it here is harmless and makes the validator's dep explicit. Verify first; if it's there, omit.)

- [ ] **Step 3: Install locally and verify**

Run:
```bash
pip install -r requirements-dev.txt
coverage --version
pip-audit --version
```
Expected: both print versions without error.

- [ ] **Step 4: Commit**

```bash
git add requirements-dev.txt
git commit -m "chore(deps): add coverage and pip-audit to dev requirements"
```

---

## Task 9: Audit network-touching tests for CI safety

**Files:**
- Modify: `tests/test_distribution.py` (only if it makes real network calls)
- Modify: `tests/test_snapshot_integration.py` (only if it makes real network calls)

- [ ] **Step 1: Inspect both test files for live network/auth dependencies**

Run:
```bash
grep -nE 'requests\.|http|gh |subprocess.*gh |GitHubClient|api\.github' tests/test_distribution.py tests/test_snapshot_integration.py
```

Read each file end-to-end. Determine:
- Does the test make a real HTTP request?
- Does it shell out to `gh` (which needs auth)?
- Does it rely on a local file path or `gh auth status`?

- [ ] **Step 2: For each unsafe test, add a skip guard**

If a test depends on `gh` auth, add at the top of the test function:
```python
import shutil
import subprocess

import pytest

def _gh_authed() -> bool:
    if not shutil.which("gh"):
        return False
    return subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0

requires_gh = pytest.mark.skipif(not _gh_authed(), reason="requires authenticated gh CLI")
```

Then decorate the test:
```python
@requires_gh
def test_thing_that_calls_gh():
    ...
```

If a test makes a real HTTP request that requires a token, gate with:
```python
import os
requires_github_token = pytest.mark.skipif(
    not os.environ.get("GITHUB_TOKEN"),
    reason="requires GITHUB_TOKEN env var",
)
```

If both files are fully mocked already (uses `unittest.mock` exclusively), do nothing.

- [ ] **Step 3: Run the audited tests**

Run: `python -m pytest tests/test_distribution.py tests/test_snapshot_integration.py -v`
Expected: PASS (with skips noted for network-gated tests if `gh` is not authed in this shell).

- [ ] **Step 4: Commit (only if changes were made)**

```bash
git add tests/test_distribution.py tests/test_snapshot_integration.py
git commit -m "test(ci): skip network-dependent tests when credentials absent"
```

---

## Task 10: Rewrite `.github/workflows/ci.yml` with matrix + validate-plugin + shellcheck + coverage + pip-audit + workflow_call

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Replace the file**

Overwrite `.github/workflows/ci.yml` with:
```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]
  workflow_call:

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ['3.11', '3.12', '3.13']
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: requirements-dev.txt

      - name: Install dependencies
        run: pip install -r requirements-dev.txt

      - name: Lint with ruff
        run: ruff check .

      - name: Run tests with coverage
        run: |
          coverage run -m pytest tests/ -v
          coverage report

      - name: Audit dependencies (warn-only)
        continue-on-error: true
        run: pip-audit -r requirements.txt --strict

  validate-plugin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
          cache-dependency-path: requirements-dev.txt

      - name: Install pyyaml
        run: pip install pyyaml

      - name: Validate plugin layout
        run: python scripts/validate_plugin.py

  shellcheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install shellcheck
        run: sudo apt-get update && sudo apt-get install -y shellcheck

      - name: Lint shell scripts
        run: |
          shopt -s nullglob
          files=(scripts/*.sh setup.sh run-all.sh)
          if [ ${#files[@]} -eq 0 ]; then
            echo "No shell scripts to lint."
            exit 0
          fi
          shellcheck "${files[@]}"
        shell: bash
```

- [ ] **Step 2: Validate the YAML locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: exits 0 with no output.

- [ ] **Step 3: Run shellcheck locally to confirm `scripts/` and existing scripts pass**

Run: `shellcheck setup.sh run-all.sh`
Expected: exit 0. If shellcheck reports issues on these existing scripts, fix them (one commit per fix, separately) — do not silence shellcheck.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: matrix Python + plugin validation + shellcheck + coverage + audit"
```

- [ ] **Step 5: Push and watch the run**

```bash
git push origin <branch>
gh run watch
```
Expected: all four jobs (`test (3.11)`, `test (3.12)`, `test (3.13)`, `validate-plugin`, `shellcheck`) pass.

If any matrix entry fails: investigate the Python-version-specific issue. Do not weaken the matrix to make CI pass.

---

## Task 11: Write `scripts/release.sh` with TDD-style assertion tests

**Files:**
- Create: `scripts/release.sh`
- Create: `tests/test_release_script.py`

- [ ] **Step 1: Write failing tests first**

Create `tests/test_release_script.py`:
```python
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.sh"


def _init_git_repo(tmp_path: Path, with_plugin_files: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    if with_plugin_files:
        (repo / ".claude-plugin").mkdir()
        (repo / ".claude-plugin" / "plugin.json").write_text(
            '{\n  "name": "p",\n  "version": "0.1.0"\n}\n'
        )
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            '{\n  "name": "p",\n'
            '  "metadata": { "version": "0.1.0" },\n'
            '  "plugins": [{ "name": "p", "version": "0.1.0" }]\n}\n'
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _run_script(repo: Path, version: str, *, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PLAYBOOK_RELEASE_SKIP_PUSH"] = "1"  # script honors this for tests
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT), version],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def test_aborts_when_not_on_main(tmp_path):
    repo = _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    result = _run_script(repo, "1.0.0")
    assert result.returncode != 0
    assert "main" in (result.stdout + result.stderr).lower()


def test_aborts_when_working_tree_dirty(tmp_path):
    repo = _init_git_repo(tmp_path)
    (repo / "dirty.txt").write_text("uncommitted")
    result = _run_script(repo, "1.0.0")
    assert result.returncode != 0
    assert "clean" in (result.stdout + result.stderr).lower() or "dirty" in (result.stdout + result.stderr).lower()


def test_happy_path_bumps_versions_commits_and_tags(tmp_path):
    repo = _init_git_repo(tmp_path)
    # Fake an origin so the "in sync with origin" check has something to look at.
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)

    result = _run_script(repo, "1.0.0")
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    plugin = (repo / ".claude-plugin" / "plugin.json").read_text()
    market = (repo / ".claude-plugin" / "marketplace.json").read_text()
    assert '"version": "1.0.0"' in plugin
    assert plugin.count('"version": "1.0.0"') >= 1
    assert market.count('"version": "1.0.0"') >= 2  # metadata + plugins[0]

    tags = subprocess.run(
        ["git", "tag", "--list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "v1.0.0" in tags

    last_msg = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert last_msg == "chore: release v1.0.0"
```

- [ ] **Step 2: Run tests to verify they fail (script doesn't exist)**

Run: `python -m pytest tests/test_release_script.py -v`
Expected: all three FAIL (script not found).

- [ ] **Step 3: Write the script**

Create `scripts/release.sh`:
```bash
#!/usr/bin/env bash
# release.sh — one-command playbook release.
#
# Usage: scripts/release.sh <version>
#   e.g. scripts/release.sh 1.0.0
#
# Preconditions enforced:
#   * Current branch is `main`
#   * Working tree is clean
#   * Local `main` matches `origin/main` (if origin is configured)
#
# Side effects:
#   * Bumps version in .claude-plugin/plugin.json (top-level `version`)
#   * Bumps version in .claude-plugin/marketplace.json (metadata.version + plugins[0].version)
#   * Commits "chore: release v<version>"
#   * Tags v<version>
#   * Pushes commit and tag to origin (unless PLAYBOOK_RELEASE_SKIP_PUSH=1)
#
# Environment:
#   PLAYBOOK_RELEASE_SKIP_PUSH=1   Skip git push (used by tests)

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <version>   (e.g. $0 1.0.0)" >&2
    exit 2
fi

VERSION="$1"

# Basic semver shape check (X.Y.Z, optional -rc.N / -beta.N suffix).
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
    echo "ERROR: version '$VERSION' is not a valid semver (e.g. 1.0.0 or 1.0.0-rc.1)" >&2
    exit 2
fi

TAG="v${VERSION}"

# Precondition 1: on main
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "ERROR: must be on 'main' (currently on '$CURRENT_BRANCH')" >&2
    exit 1
fi

# Precondition 2: clean working tree
if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: working tree is not clean. Commit or stash before releasing." >&2
    git status --short >&2
    exit 1
fi

# Precondition 3: in sync with origin (if origin exists)
if git remote get-url origin >/dev/null 2>&1; then
    git fetch -q origin main
    LOCAL="$(git rev-parse HEAD)"
    REMOTE="$(git rev-parse origin/main)"
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "ERROR: local main ($LOCAL) does not match origin/main ($REMOTE)." >&2
        echo "Pull or push first." >&2
        exit 1
    fi
fi

PLUGIN_JSON=".claude-plugin/plugin.json"
MARKETPLACE_JSON=".claude-plugin/marketplace.json"

if [ ! -f "$PLUGIN_JSON" ] || [ ! -f "$MARKETPLACE_JSON" ]; then
    echo "ERROR: expected $PLUGIN_JSON and $MARKETPLACE_JSON to exist." >&2
    exit 1
fi

echo "Releasing v$VERSION..."
echo "  - Updating $PLUGIN_JSON"
echo "  - Updating $MARKETPLACE_JSON"

# Use Python (already a dep) for safe JSON edits — sed on JSON is error-prone.
python3 - "$VERSION" "$PLUGIN_JSON" "$MARKETPLACE_JSON" <<'PY'
import json
import sys
from pathlib import Path

version, plugin_path, marketplace_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])

plugin = json.loads(plugin_path.read_text())
plugin["version"] = version
plugin_path.write_text(json.dumps(plugin, indent=2) + "\n")

market = json.loads(marketplace_path.read_text())
market.setdefault("metadata", {})["version"] = version
plugins = market.get("plugins") or []
for p in plugins:
    p["version"] = version
marketplace_path.write_text(json.dumps(market, indent=2) + "\n")
PY

echo "  - Committing"
git add "$PLUGIN_JSON" "$MARKETPLACE_JSON"
git commit -q -m "chore: release $TAG"

echo "  - Tagging $TAG"
git tag "$TAG"

if [ "${PLAYBOOK_RELEASE_SKIP_PUSH:-0}" = "1" ]; then
    echo "  - PLAYBOOK_RELEASE_SKIP_PUSH=1, skipping push"
else
    if git remote get-url origin >/dev/null 2>&1; then
        echo "  - Pushing commit and tag to origin"
        git push origin main
        git push origin "$TAG"
    else
        echo "  - No origin configured, skipping push"
    fi
fi

echo "Done. Release $TAG ready."
```

Make it executable:
```bash
chmod +x scripts/release.sh
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_release_script.py -v`
Expected: all three PASS.

- [ ] **Step 5: Run shellcheck on the new script**

Run: `shellcheck scripts/release.sh`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/release.sh tests/test_release_script.py
git commit -m "feat(release): one-command release helper script"
```

---

## Task 12: Write `.github/workflows/release.yml`

**Files:**
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/release.yml`:
```yaml
name: Release

on:
  push:
    tags: ['v*']
  release:
    types: [published]
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Build bundle artifact without publishing"
        type: boolean
        default: true

permissions:
  contents: write

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  gate:
    uses: ./.github/workflows/ci.yml

  publish:
    needs: gate
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Resolve version and tag
        id: vars
        env:
          GITHUB_REF: ${{ github.ref }}
          EVENT_NAME: ${{ github.event_name }}
          INPUT_TAG: ${{ github.event.release.tag_name }}
        run: |
          set -euo pipefail
          if [ "$EVENT_NAME" = "release" ]; then
            TAG="$INPUT_TAG"
          elif [[ "$GITHUB_REF" == refs/tags/* ]]; then
            TAG="${GITHUB_REF#refs/tags/}"
          else
            TAG=""
          fi
          if [ -z "$TAG" ]; then
            echo "No tag context (workflow_dispatch dry-run). Using version from plugin.json."
            VERSION="$(python3 -c 'import json; print(json.load(open(\".claude-plugin/plugin.json\"))[\"version\"])')"
            TAG="v${VERSION}"
          else
            VERSION="${TAG#v}"
          fi
          echo "tag=$TAG" >> "$GITHUB_OUTPUT"
          echo "version=$VERSION" >> "$GITHUB_OUTPUT"

      - name: Verify tag matches plugin.json version
        if: github.event_name != 'workflow_dispatch'
        env:
          TAG: ${{ steps.vars.outputs.tag }}
          VERSION: ${{ steps.vars.outputs.version }}
        run: |
          set -euo pipefail
          FILE_VERSION="$(python3 -c 'import json; print(json.load(open(".claude-plugin/plugin.json"))["version"])')"
          if [ "$FILE_VERSION" != "$VERSION" ]; then
            echo "::error::Tag $TAG does not match plugin.json version $FILE_VERSION."
            echo "Did you forget to run scripts/release.sh?"
            exit 1
          fi

      - name: Build bundle
        env:
          VERSION: ${{ steps.vars.outputs.version }}
        run: |
          set -euo pipefail
          BUNDLE="playbook-${VERSION}.zip"
          # Inclusion list (do NOT use exclusion-list zip flags here).
          zip -r "$BUNDLE" \
            .claude-plugin agents notifications skills templates docs \
            $(ls *.py) \
            defaults.yaml requirements.txt README.md setup.sh run-all.sh
          ls -lh "$BUNDLE"
          echo "BUNDLE=$BUNDLE" >> "$GITHUB_ENV"

      - name: Generate release notes
        if: github.event_name != 'workflow_dispatch'
        env:
          TAG: ${{ steps.vars.outputs.tag }}
        run: |
          set -euo pipefail
          PREV="$(git describe --tags --abbrev=0 "${TAG}^" 2>/dev/null || true)"
          if [ -z "$PREV" ]; then
            RANGE="$(git rev-list --max-parents=0 HEAD)..HEAD"
            HEADING="### Initial release"
          else
            RANGE="${PREV}..HEAD"
            HEADING="### Changes since ${PREV}"
          fi
          {
            echo "$HEADING"
            echo ""
            for prefix in feat fix chore docs refactor test ci; do
              LINES="$(git log "$RANGE" --pretty=format:'- %s' | grep -E "^- ${prefix}(\\(|:|!)" || true)"
              if [ -n "$LINES" ]; then
                echo "**${prefix}**"
                echo "$LINES"
                echo ""
              fi
            done
            OTHERS="$(git log "$RANGE" --pretty=format:'- %s' | grep -Ev '^- (feat|fix|chore|docs|refactor|test|ci)(\\(|:|!)' || true)"
            if [ -n "$OTHERS" ]; then
              echo "**other**"
              echo "$OTHERS"
            fi
          } > release-notes.md
          cat release-notes.md

      - name: Upload artifact (dry-run mode)
        if: github.event_name == 'workflow_dispatch'
        uses: actions/upload-artifact@v4
        with:
          name: ${{ env.BUNDLE }}
          path: ${{ env.BUNDLE }}

      - name: Create or update GitHub Release (idempotent)
        if: github.event_name != 'workflow_dispatch'
        env:
          GH_TOKEN: ${{ github.token }}
          TAG: ${{ steps.vars.outputs.tag }}
        run: |
          set -euo pipefail
          DRAFT_FLAG=""
          if [[ "$TAG" == *-rc* || "$TAG" == *-beta* ]]; then
            DRAFT_FLAG="--draft"
          fi
          if gh release view "$TAG" >/dev/null 2>&1; then
            echo "Release $TAG exists, updating assets and notes."
            gh release upload "$TAG" "$BUNDLE" --clobber
            gh release edit "$TAG" --notes-file release-notes.md
          else
            echo "Creating release $TAG."
            gh release create "$TAG" "$BUNDLE" --title "$TAG" --notes-file release-notes.md $DRAFT_FLAG
          fi
```

- [ ] **Step 2: Validate the YAML locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"`
Expected: exits 0 with no output.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: tag-triggered release workflow with idempotent publish"
```

- [ ] **Step 4: Dry-run the workflow from the Actions tab**

After pushing this branch, go to GitHub → Actions → "Release" → "Run workflow", select your branch, leave `dry_run` checked, click Run.
Expected: `gate` job passes, `publish` job builds `playbook-<version>.zip` and uploads it as a workflow artifact. No GitHub Release is created.

If the dry-run fails, fix on the same branch and re-run before merging.

---

## Task 13: Add `.github/dependabot.yml`

**Files:**
- Create: `.github/dependabot.yml`

- [ ] **Step 1: Write the file**

Create `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      python-deps:
        patterns: ["*"]

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      actions:
        patterns: ["*"]
```

- [ ] **Step 2: Validate the YAML locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/dependabot.yml'))"`
Expected: exits 0 with no output.

- [ ] **Step 3: Commit**

```bash
git add .github/dependabot.yml
git commit -m "ci: enable dependabot for pip and github-actions, weekly grouped"
```

---

## Task 14: Write `docs/ci-cd.md`

**Files:**
- Create: `docs/ci-cd.md`

- [ ] **Step 1: Write the doc**

Create `docs/ci-cd.md`:
```markdown
# Playbook CI/CD

This doc covers the two workflows that gate and release playbook.
The full design is in `docs/specs/2026-05-16-ci-cd-pipeline-design.md`.

## The two loops

### Day-to-day (every change)

1. Feature branch -> open PR.
2. `.github/workflows/ci.yml` runs: matrix tests (Python 3.11/3.12/3.13),
   `ruff`, plugin validation, coverage report, `pip-audit` (warn-only),
   `shellcheck`.
3. Review, merge to `main`.
4. `ci.yml` runs again on `main`.

No version bumps, no tags, no release artifacts.

### Release (only when cutting a version)

```bash
git checkout main
git pull
./scripts/release.sh 1.0.0
```

That's it. The script:

1. Asserts you are on `main`, working tree is clean, in sync with `origin/main`.
2. Bumps `version` in `.claude-plugin/plugin.json` and both version fields in
   `.claude-plugin/marketplace.json` (`metadata.version`, `plugins[0].version`).
3. Commits `chore: release v1.0.0`.
4. Tags `v1.0.0`.
5. Pushes commit and tag to `origin`.

Pushing the tag fires `.github/workflows/release.yml`, which:

1. Re-runs the full CI gate against the tagged commit.
2. Verifies the tag matches `plugin.json` version (foot-gun guard).
3. Builds `playbook-<version>.zip` from the distributable file list.
4. Generates release notes grouped by conventional-commit prefix
   (`feat`, `fix`, `chore`, ...).
5. Creates a GitHub Release with the bundle attached.

Releases matching `v*-rc*` or `v*-beta*` are created as drafts.

## Release triggers

| Trigger | When to use |
|---------|-------------|
| Tag push (`git push origin v1.0.0`) | Primary. 90% of releases. |
| GitHub Release UI ("Draft new release") | When you want to write notes by hand and review before publishing. Same workflow runs; `publish` job uploads the bundle to the existing release. |
| Manual `workflow_dispatch` (dry-run) | Before a major release, run this from the Actions tab with `dry_run` checked to build the bundle as an artifact without publishing. |

## CI failures: how to read them

| Job | Failure means |
|-----|---------------|
| `test (3.11/3.12/3.13)` | Tests or lint failed on that Python version. The matrix is `fail-fast: false`, so you see all three results. |
| `validate-plugin` | Plugin manifest, skill frontmatter, or agent prompt reference is broken. Read the `✗` lines. |
| `shellcheck` | A shell script in `scripts/`, `setup.sh`, or `run-all.sh` has a shellcheck-flagged issue. |
| `pip-audit` warning | A dependency CVE was reported. Triage; do not block PRs solely on this for now. |

## Running validation locally

```bash
ruff check .
pytest tests/
python scripts/validate_plugin.py
shellcheck scripts/*.sh setup.sh run-all.sh
```

## Recovering from a failed release

If `release.yml` fails after the tag was pushed:

1. Do **not** delete the tag and re-push it. Force-overwriting tags is a
   foot-gun and breaks anyone who already fetched.
2. Fix the underlying problem on `main`.
3. Bump the patch version and run `./scripts/release.sh <new-version>` again.

If the version-match check failed (tag and `plugin.json` disagree), it almost
always means the release was tagged without running `scripts/release.sh`.
Either bump-and-tag via the script, or hand-edit `plugin.json` to match the
tag, commit on `main`, then push.

## Branch protection setup (one-time)

In GitHub repo settings -> Branches -> Branch protection rules -> `main`,
mark these required status checks:

- `test (3.11)`
- `test (3.12)`
- `test (3.13)`
- `validate-plugin`
- `shellcheck`

This makes them block merges until green.

## What is NOT covered here

- `.github/workflows/integration-pr.yml` — runtime orchestrator tooling
  (creates merge PRs from `ai/dev` -> `main`). Unrelated to contributor CI
  or release.
- PyPI publishing — playbook is a Claude Code plugin, not a pip package.
- macOS / Windows matrix — deferred until something actually breaks on those.
```

- [ ] **Step 2: Commit**

```bash
git add docs/ci-cd.md
git commit -m "docs: CI/CD workflow guide for maintainers"
```

---

## Task 15: Update README to link the new CI/CD doc

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find an appropriate spot to link the doc**

Run: `grep -n -E '^(#|##|###)' README.md | head -30`
Look for a "Development", "Contributing", "Testing", or similar section. If
none exists, the link goes near the bottom under a new short section.

- [ ] **Step 2: Add the link**

If a "Development" / "Contributing" section exists, add a line like:

```markdown
See [docs/ci-cd.md](docs/ci-cd.md) for the CI gating and release process.
```

If no such section exists, append to the end of `README.md`:

```markdown
## Development

- CI gating and release process: [docs/ci-cd.md](docs/ci-cd.md)
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): link the CI/CD workflow guide"
```

---

## Task 16: End-to-end PR validation

**Files:** none changed; this is a CI smoke test.

- [ ] **Step 1: Push the branch and open a PR**

If you have been committing on a feature branch the whole time, push it and
open a PR against `main`:
```bash
git push -u origin <branch>
gh pr create --fill
```

- [ ] **Step 2: Watch the run**

Run: `gh pr checks --watch`
Expected:
- `test (3.11)`, `test (3.12)`, `test (3.13)` — pass
- `validate-plugin` — pass
- `shellcheck` — pass

If any job fails, fix the underlying issue (do not weaken the check) and push
a fixup commit. The concurrency block cancels the previous run automatically.

- [ ] **Step 3: Merge the PR**

After all checks are green and you have reviewed the diff, squash or merge
per your normal preference.

- [ ] **Step 4: Configure branch protection (one-time)**

Once `main` has at least one passing run that includes the new jobs, go to
GitHub repo settings -> Branches -> Branch protection rules -> `main` and add
the five required status checks listed in `docs/ci-cd.md`.

This is a manual UI step. CI cannot configure its own protection.

---

## Task 17: Dry-run release from the Actions tab

**Files:** none changed; smoke test of `release.yml`.

- [ ] **Step 1: Trigger a dry-run release**

Go to GitHub -> Actions -> "Release" -> "Run workflow". Select `main`. Leave
`dry_run` checked. Click "Run workflow".

- [ ] **Step 2: Confirm the run succeeds and produces an artifact**

Expected:
- `gate` job: passes (all CI jobs green against `main`).
- `publish` job: builds `playbook-<version>.zip` and uploads it as a workflow
  artifact (not a Release).
- No GitHub Release is created.

Download the artifact and unzip it. Verify it contains the inclusion list
from Task 12 (e.g., `.claude-plugin/`, `agents/`, `skills/`, top-level `*.py`,
`README.md`, etc.) and does NOT contain `tests/`, `.github/`, `scripts/`, or
cache directories.

- [ ] **Step 3: If anything is wrong, fix and re-run**

The bundle inclusion list is the highest-risk piece. Adjust the `zip` command
in `release.yml`, commit, push, re-run the dry-run. Iterate until the bundle
contents look right.

---

## Task 18: Cut the next real release

**Files:**
- Modified by the script: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: Decide the next version**

Current version is in `.claude-plugin/plugin.json` (e.g., `1.4.0`). Pick the
next version per semver. For the first release after this CI/CD work, a
patch bump (`1.4.1`) is appropriate unless other user-facing changes
warrant minor/major.

- [ ] **Step 2: Run the release script**

```bash
git checkout main && git pull
./scripts/release.sh <new-version>
```

Expected: script bumps both manifests, commits `chore: release v<new-version>`,
tags, and pushes both commit and tag.

- [ ] **Step 3: Watch the release workflow**

Run: `gh run watch`
Expected: `gate` passes, `publish` creates a GitHub Release named
`v<new-version>` with `playbook-<new-version>.zip` attached and auto-generated
notes.

- [ ] **Step 4: Verify the release on GitHub**

Open the release in the GitHub UI. Confirm:
- Bundle is attached.
- Release notes list the commits since the previous tag, grouped by
  conventional-commit prefix.
- Tag is not marked as a draft (unless `-rc` / `-beta`).

---

## Self-Review Summary

Spec coverage (cross-checked against `docs/specs/2026-05-16-ci-cd-pipeline-design.md`):
- File layout (specs/Component 1-6) -> Tasks 1, 8, 10, 11, 12, 13, 14, 15
- `ci.yml` matrix + jobs -> Task 10
- `validate_plugin.py` checks + caveat handled conservatively -> Tasks 1-7
- `release.yml` triggers, idempotent publish, dry-run, version-match -> Task 12
- `scripts/release.sh` preconditions and atomic version bump -> Task 11
- Dependabot grouped config -> Task 13
- `docs/ci-cd.md` contents -> Task 14
- README link -> Task 15
- Test audit for network-touching tests -> Task 9
- End-to-end validation + branch protection setup -> Tasks 16-17
- First real release using the new pipeline -> Task 18

Out-of-scope items (deliberately not implemented): macOS/Windows matrix,
coverage gate, `pip-audit` hard-fail, PyPI publish, marketplace.json
cross-repo updates, auto-merge for Dependabot. All listed in the spec
"Out of Scope" section.
