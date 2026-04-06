# Integration PR Workflow Design

## Problem

After the orchestrator merges feature PRs into `ai/dev`, there is no automated way to create or maintain a PR from `ai/dev` to `main`. The current `merge_to_main.py` script must be run manually, and maintaining copies across repos doesn't scale.

## Solution

A lightweight GitHub Action that triggers on every push to `ai/dev`, automatically creating or updating a persistent PR targeting `main`. The PR body lists all `Closes #N` references extracted from merged commit history, so merging the PR auto-closes the referenced issues via GitHub's built-in behavior.

## Architecture

### Two components

1. **Reusable workflow** — Hosted in `BryGo1995/agent-orchestrator` at `.github/workflows/integration-pr.yml`. Contains all logic.
2. **Caller workflow** — A thin ~10-line file dropped into each target repo (e.g., `paint-ballas-auto`) that invokes the reusable workflow.

### Why a reusable workflow

- Logic lives in one place; update once, all repos pick it up.
- Target repos only need a thin caller file + no secrets beyond the default `GITHUB_TOKEN`.
- No GitHub Actions cost concern — runs for a few seconds (API calls only).

## Workflow Logic

### Trigger

Push to the integration branch (default `ai/dev`). This fires whenever the orchestrator merges a feature PR into `ai/dev`.

### Inputs (configurable per repo)

| Input | Default | Description |
|-------|---------|-------------|
| `integration_branch` | `ai/dev` | Source branch for the integration PR |
| `base_branch` | `main` | Target branch for the integration PR |

### Steps

1. **Check for existing PR** — Use `gh pr list --head <integration_branch> --base <base_branch>` to find any open integration PR.
2. **Check if commits ahead** — Compare `base_branch` and `integration_branch`. If no commits ahead, exit cleanly.
3. **Extract issue references** — Run `git log <base_branch>..<integration_branch>` to get all commit messages in the range. Parse for patterns: `Closes #N`, `Fixes #N`, `Resolves #N` (case-insensitive). Also match bare `#N` references in squash-merge commit subjects (which include the PR title). Deduplicate. For issue titles in the PR body, use `gh issue view #N --json title` for each unique reference.
4. **Build PR body** — Format:
   ```
   ## Merge `ai/dev` -> `main`

   ### Completed Issues (N)

   - Closes #42 -- Fix authentication bug
   - Closes #43 -- Add user profile endpoint

   ### Commits

   - abc1234 feat: fix auth bug (#42)
   - def5678 feat: add profile endpoint (#43)

   ---
   *Auto-maintained by [integration-pr](https://github.com/BryGo1995/agent-orchestrator) workflow*
   ```
5. **Create or update PR**:
   - No existing PR: `gh pr create` with title `Merge <integration_branch> -> <base_branch>` and the built body.
   - Existing PR: Compare new body to current. If different, `gh pr edit` to update. If identical, skip (avoid noise).

### Merge strategy

When the user merges this PR, it must use a **regular merge commit** (not squash). This keeps `ai/dev` and `main` in sync history-wise, avoiding ghost conflicts on future PRs. This is enforced by convention/documentation, not by the workflow itself.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No commits ahead of base | Exit cleanly, no PR created |
| No issue references found | Create/update PR with "No issue references found" note in body. The merge itself is still valuable. |
| PR body unchanged | Skip update to avoid noise |
| Merge conflicts between branches | PR is created regardless; GitHub shows conflict status. User resolves before merging. |
| Reusable workflow not accessible | Caller workflow fails with clear error. Orchestrator repo must be public or in same org with workflow sharing enabled. |

## Portability: Setup for a New Repo

1. Ensure `BryGo1995/agent-orchestrator` is accessible (public, or same org with sharing enabled).
2. Add `.github/workflows/integration-pr.yml` to the target repo:
   ```yaml
   name: Integration PR
   on:
     push:
       branches: [ai/dev]

   jobs:
     integration-pr:
       uses: BryGo1995/agent-orchestrator/.github/workflows/integration-pr.yml@main
       with:
         integration_branch: ai/dev
         base_branch: main
   ```
3. That's it. No secrets, no config files, no additional setup.

## Changes to Existing Codebase

- **Remove:** `merge_to_main.py` — replaced by this workflow.
- **Add:** `.github/workflows/integration-pr.yml` (reusable workflow) in orchestrator repo.
- **Add:** Template caller workflow in `templates/integration-pr-caller.yml` for easy copy-paste into new repos.
- **Update:** `README.md` — add setup instructions for the integration PR workflow.

## What This Does NOT Change

- The orchestrator remains a local Python + cron application.
- Agent dispatching, state management, and auto-merge to `ai/dev` are unchanged.
- GitHub Projects status workflow is unchanged.
- No new secrets or tokens required.

## Constraints

- Orchestrator repo must be public (or org-level workflow sharing enabled) for reusable workflows to work cross-repo.
- The default `GITHUB_TOKEN` in target repos must have `pull-requests: write` and `contents: read` permissions.
- Regular merge commit (not squash) must be used when merging the integration PR to avoid branch divergence.
