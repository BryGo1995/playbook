# CI/CD Pipeline Design

**Date:** 2026-05-16
**Status:** Draft

## Purpose

Replace the current minimal CI (single-version lint + pytest) with a two-track
pipeline that (a) catches install-time and version-compatibility regressions
during day-to-day development, and (b) provides a reliable, single-command
release path for cutting tagged versions of the playbook plugin.

Playbook ships as a Claude Code plugin installed on end-user machines. The
existing CI does not catch broken manifests, missing skill files, or
Python-version-specific issues — all of which manifest only at install time on
someone else's machine. This design closes that gap and adds a release pipeline
that the v1.0 cut (and every release after) will use.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary audience | Solo maintainer (the user), forward-looking for contributors | User is sole contributor today; design should also smooth the path for outside contributors without speculating on contributor-specific features |
| Python matrix | 3.11, 3.12, 3.13 | Distributed plugin; users have varied Python. Single-version CI is the actual risk being closed |
| OS matrix | `ubuntu-latest` only | Pure-Python orchestrator; defer macOS/Windows until something breaks |
| Coverage gate | Report only, no threshold | Solo project; hard thresholds become a fight with yourself |
| Plugin validation | Python script in `scripts/`, run from CI | Runnable locally; single source of truth for "what makes a valid plugin" |
| `pip-audit` | Warn only initially | Distributed software needs CVE visibility, but transitive CVEs shouldn't block unrelated PRs on day one |
| Release trigger | Tag-push primary, GitHub Release UI + `workflow_dispatch` secondary | Standard for project size; secondary triggers give escape hatches |
| Release helper | `scripts/release.sh <version>` | One-command release; eliminates "forgot to bump `plugin.json`" foot-gun |
| Version source of truth | `plugin.json` `version` field | Workflow refuses to publish if git tag and `plugin.json` disagree |
| Dependency updates | Dependabot, weekly, grouped, no auto-merge | Built-in, free; grouped PRs prevent noise; human-in-the-loop until v1.x stable |
| `integration-pr.yml` | Untouched | Runtime orchestrator tooling, unrelated to contributor/release CI |

## File Layout

```
.github/
├── workflows/
│   ├── ci.yml              ← REPLACED (matrix + plugin validation + coverage + audit)
│   ├── release.yml         ← NEW (tag-triggered; reuses ci.yml as gate)
│   └── integration-pr.yml  ← UNCHANGED
└── dependabot.yml          ← NEW
scripts/
├── validate_plugin.py      ← NEW (plugin manifest/skill/agent validator)
└── release.sh              ← NEW (version bump + commit + tag + push)
docs/
└── ci-cd.md                ← NEW (user-facing workflow documentation)
tests/
└── test_validate_plugin.py ← NEW (pytest coverage for the validator script)
```

## Trigger Map

| Event | Workflow(s) |
|-------|-------------|
| PR to `main` | `ci.yml` (test matrix + validate-plugin) |
| Push to `main` | `ci.yml` |
| Tag `v*` pushed | `release.yml` → `gate` (calls `ci.yml`) → `publish` (creates GitHub Release) |
| GitHub Release published (UI flow) | `release.yml` → `gate` re-runs → `publish` job uploads assets to the existing release instead of creating a new one |
| `workflow_dispatch` on `release.yml` | Dry-run: build bundle artifact, do not publish |
| Weekly cron | Dependabot opens PRs (which trigger `ci.yml`) |

## Component 1: `ci.yml`

Replaces the existing `ci.yml` entirely. Triggers:

```yaml
on:
  pull_request:
  push:
    branches: [main]
  workflow_call:  # so release.yml can reuse this as a gate

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```

### Job: `test`

- Matrix: `python-version: ['3.11', '3.12', '3.13']` on `ubuntu-latest`.
- `fail-fast: false` — surface version-specific failures even when one entry fails.
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` with `cache: pip`, `cache-dependency-path: requirements-dev.txt`
  3. `pip install -r requirements-dev.txt` (add `coverage` to `requirements-dev.txt`)
  4. `ruff check .`
  5. `coverage run -m pytest tests/ -v && coverage report`
  6. `pip-audit -r requirements.txt --strict` with `continue-on-error: true` (warn-only initially)

### Job: `validate-plugin`

- Runs once on `ubuntu-latest`, Python 3.11. No matrix.
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` with Python 3.11
  3. `pip install pyyaml` (and any other deps the validator needs)
  4. `python scripts/validate_plugin.py`

### Job: `shellcheck`

- Runs once. `shellcheck scripts/*.sh setup.sh run-all.sh`.

### Required Status Checks (out-of-band setup)

Branch protection on `main` should require: `test (3.11)`, `test (3.12)`,
`test (3.13)`, `validate-plugin`, `shellcheck`. This is a one-time GitHub
settings change documented in `docs/ci-cd.md`, not configured by CI.

### Test Audit Note

`tests/test_distribution.py` and `tests/test_snapshot_integration.py` need a
quick audit during implementation: if either makes real GitHub API calls or
depends on local `gh` auth, mark with `@pytest.mark.skipif` so CI runs them
honestly without flake. Not a redesign — just a make-CI-trustworthy step.

## Component 2: `scripts/validate_plugin.py`

A standalone Python script (no dependencies beyond `pyyaml`) committed at
`scripts/validate_plugin.py`. Runnable locally with `python scripts/validate_plugin.py`.

### Checks

1. **`plugin.json` and `marketplace.json`**
   - Parse as JSON (no syntax errors).
   - Required fields present per the Claude Code plugin schema.
   - `version` fields agree across both files.
   - Any file paths referenced exist on disk.

2. **Skills** (`skills/*/SKILL.md`)
   - Each skill directory has a `SKILL.md`.
   - YAML frontmatter parses.
   - Required frontmatter fields present (`name`, `description`).
   - `name:` slug matches the directory name.

3. **Agents** (`agents/prompts/*` and Python agent classes)
   - Files referenced from `agents/coding.py`, `agents/review.py`, `agents/testing.py`
     resolve to actual files in `agents/prompts/`.

4. **Stray non-distributable files** (warn, do not fail)
   - Warn if `.coverage`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`,
     `.worktrees/` appear in tracked git files.

### Output

Structured per-check report to stdout:

```
✓ plugin.json
✓ marketplace.json (version 0.9.3 matches plugin.json)
✓ skills/scout/SKILL.md
✗ skills/gameplan/SKILL.md: missing required field 'description'
⚠ tests/.coverage tracked in git (should be in .gitignore)
```

Exit non-zero on any `✗`. Warnings (`⚠`) do not affect exit code.

### Schema Source-of-Truth Caveat

The authoritative Claude Code plugin schema is not currently codified inside
this repo. Implementation should start with a conservative set (JSON parses,
versions agree, referenced files exist, skill frontmatter has `name` +
`description`) and tighten over time as the schema is confirmed against the
Claude Code plugin loader. This is an implementation decision, not a punt:
the conservative set already catches the bulk of install-time breakage.

### Test Coverage

`tests/test_validate_plugin.py` covers the validator with fixtures:
good manifest, missing field, mismatched version between `plugin.json` and
`marketplace.json`, missing skill file referenced from agent code, skill
directory without `SKILL.md`, frontmatter missing `description`, etc.

## Component 3: `release.yml`

Triggers:

```yaml
on:
  push:
    tags: ['v*']
  release:
    types: [published]
  workflow_dispatch:
    inputs:
      dry_run:
        description: "Build bundle artifact without publishing"
        default: 'true'

permissions:
  contents: write  # for gh release create
```

### Job: `gate`

Calls `ci.yml` via `workflow_call`. Failure here stops the release.

### Job: `publish` (`needs: gate`)

Skipped on `workflow_dispatch` when `inputs.dry_run == 'true'` (artifact-only mode).

1. `actions/checkout@v4` with `fetch-depth: 0` (full history for changelog).
2. **Version sanity check**: parse the git tag (strip leading `v`), parse
   `plugin.json` `version`. Fail if they disagree with a clear message:
   `Tag v1.0.0 does not match plugin.json version 0.9.3. Did you forget to run scripts/release.sh?`
3. **Build bundle**: zip the distributable files into
   `playbook-${VERSION}.zip`. Inclusion list:
   ```
   .claude-plugin/  agents/  notifications/  skills/  templates/  docs/
   *.py             defaults.yaml  requirements.txt  README.md
   setup.sh         run-all.sh
   ```
   Excluded: `tests/`, `requirements-dev.txt`, `.github/`, `scripts/`,
   `.coverage`, all cache dirs, `.worktrees/`.
4. **Generate release notes**:
   `git log <previous-tag>..HEAD --pretty=format:'- %s'` grouped by conventional
   commit prefix (`feat:`, `fix:`, `chore:`, etc.). If no previous tag exists,
   list all commits.
5. **Create or update GitHub Release** (idempotent):
   - If a release for `$TAG` already exists (UI-driven flow created it before
     the workflow ran), use `gh release upload "$TAG" playbook-${VERSION}.zip --clobber`
     to attach the bundle and `gh release edit "$TAG" --notes "$NOTES"` to set notes.
   - Otherwise, `gh release create "$TAG" playbook-${VERSION}.zip --title "$TAG" --notes "$NOTES"`,
     adding `--draft` if `$TAG` contains `-rc` or `-beta`.
   - This makes the publish job safe to run twice (e.g., tag-push + UI publish
     in either order) without erroring or duplicating.
6. On `workflow_dispatch` dry-run: upload the bundle as a workflow artifact
   instead of creating a Release.

### Out-of-Scope (Deliberately)

- No PyPI publish — playbook is not a pip package.
- No automatic `marketplace.json` version-pointer update across repos (if
  marketplace.json lives in this repo and tracks the latest tag, revisit in
  a follow-up).
- No npm / brew / Homebrew tap publishing.

## Component 4: `scripts/release.sh`

One-command release. Usage:

```bash
./scripts/release.sh 1.0.0
```

### Behavior

1. Assert current branch is `main`.
2. Assert working tree is clean (`git status --porcelain` empty).
3. Assert local `main` is up to date with `origin/main` (`git fetch && git diff --quiet HEAD origin/main`).
4. Update `version` field in `plugin.json` (and `marketplace.json` if it carries a version).
5. Commit: `git commit -am "chore: release v1.0.0"`.
6. Tag: `git tag v1.0.0`.
7. Push: `git push origin main && git push origin v1.0.0`.

The script is `set -euo pipefail` and prints what it's about to do before each
step. If any precondition fails, it aborts before making any changes.

## Component 5: `.github/dependabot.yml`

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

Grouped to one PR per ecosystem per week. No auto-merge.

## Component 6: `docs/ci-cd.md`

User/maintainer-facing reference (not implementation artifact). Goes in `docs/`,
not `docs/superpowers/specs/`. Contents:

1. **The two loops**: day-to-day (PR → CI → merge) vs release (pull main →
   `scripts/release.sh` → tag fires `release.yml`).
2. **One-command release**: how to use `scripts/release.sh`, what it does, when
   not to use it.
3. **Three release triggers**: tag-push (primary), GitHub Release UI (review-first),
   `workflow_dispatch` dry-run (sanity-check bundle).
4. **What CI checks on PRs**: matrix, lint, plugin validation, coverage,
   `shellcheck`, `pip-audit`. How to interpret each failure.
5. **Running validation locally**: `python scripts/validate_plugin.py`,
   `ruff check .`, `pytest tests/`, `shellcheck scripts/*.sh`.
6. **Version-match check**: what triggers it, how to fix a failed release
   (bump patch and re-tag; never delete and re-push the same tag).
7. **Branch protection setup**: the one-time GitHub settings change to make
   the required checks block merges.

## Error Handling Policy

| Condition | Behavior |
|-----------|----------|
| `ruff` finds issues | Fail |
| `pytest` fails on any matrix Python | Fail |
| `shellcheck` finds issues | Fail |
| `validate_plugin.py` finds schema/reference error | Fail |
| `validate_plugin.py` finds stray cache files in git | Warn (exit 0) |
| `pip-audit` finds a CVE | Warn (exit 0) initially; tighten to fail later |
| Coverage drops | No gate (visible in log only) |
| Release: tag does not match `plugin.json` version | Fail (no publish) |
| Release: gate (CI) fails | Fail (no publish) |
| Release: bundle build fails | Fail (no partial release) |

Pattern: hard-fail on anything that breaks correctness or release integrity;
warn on anything that is signal-without-emergency.

## Edge Cases

1. **First-ever release**: no previous tag exists; release notes generator
   falls back to "all commits."
2. **Re-running a failed tag**: never delete and re-push the same tag; bump
   patch version and re-tag. Documented in `docs/ci-cd.md`.
3. **PR from a fork**: `GITHUB_TOKEN` is read-only on fork PRs. Nothing in this
   design writes from a fork PR, so this works as-is.
4. **Dependabot PR breaking CI**: desired behavior — PR shows red, no merge,
   no impact. System working as designed.
5. **Release commit pushed, more PRs merged before next release**: `main`
   moves ahead of the tag; tag is a snapshot. Normal and expected.
6. **Tag-push and UI-publish both happen for the same release**: publish job
   is idempotent (see Component 3, step 5) — the second run uploads/edits
   instead of failing.

## Out of Scope

- Notifications (Slack, email) beyond GitHub's built-in.
- Metrics / dashboard (CI run times, flakiness tracking).
- Nightly or scheduled full-matrix runs separate from PRs.
- Release-candidate or beta channel beyond `v*-rc*` / `v*-beta*` → draft-release.
- Cross-OS matrix (macOS, Windows).
- Auto-merge for Dependabot PRs.
- Hardening `pip-audit` to fail builds (deferred until baseline is clean).

## Implementation Order

Suggested sequencing for the implementation plan (`writing-plans` will refine):

1. **`scripts/validate_plugin.py` + `tests/test_validate_plugin.py`** —
   independently testable, can land first behind any new workflow.
2. **`ci.yml` rewrite** — matrix, validate-plugin job, shellcheck, coverage,
   pip-audit. Includes test audit for `test_distribution.py` /
   `test_snapshot_integration.py`.
3. **`scripts/release.sh`** — local helper; works without any workflow change.
4. **`release.yml`** — depends on `ci.yml` being `workflow_call`-able.
5. **`.github/dependabot.yml`** — independent; can land any time.
6. **`docs/ci-cd.md`** — written after the workflows so the doc reflects what
   actually exists.
7. **Branch protection settings** — one-time GitHub UI change, post-merge.
