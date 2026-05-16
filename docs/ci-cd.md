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
| Manual `workflow_dispatch` (dry-run) | Before a major release, run this from the Actions tab to build the bundle as an artifact without publishing. (`workflow_dispatch` is always dry-run; the `release.yml` job uploads the bundle as an artifact and does not create a GitHub Release.) |

### Double-trigger note

If a tag is pushed and the same release is also published via the GitHub UI,
`release.yml` fires twice with the same concurrency group. The second run
queues behind the first, and its `publish` job is idempotent — it uses
`gh release upload --clobber` on existing assets and `gh release edit` on
notes. The end state is the same as a single run.

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
coverage run -m pytest tests/ && coverage report
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
