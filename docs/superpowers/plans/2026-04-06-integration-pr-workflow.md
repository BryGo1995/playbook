# Integration PR Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `merge_to_main.py` with a GitHub Actions reusable workflow that automatically creates and updates a persistent `ai/dev -> main` PR whenever code is pushed to `ai/dev`.

**Architecture:** A reusable workflow in the orchestrator repo contains all logic (extract issue refs, build PR body, create/update PR). Target repos call it with a thin 10-line caller workflow. The workflow uses only `gh` CLI and `git` — no Python, no project board coupling.

**Tech Stack:** GitHub Actions (reusable workflows), `gh` CLI, bash, `git log`

---

### Task 1: Create the Reusable Workflow

**Files:**
- Create: `.github/workflows/integration-pr.yml`

- [ ] **Step 1: Create the .github/workflows directory**

```bash
mkdir -p /home/bryang/Dev_Space/agent-orchestrator/.github/workflows
```

- [ ] **Step 2: Write the reusable workflow**

Create `.github/workflows/integration-pr.yml`:

```yaml
name: Integration PR

on:
  workflow_call:
    inputs:
      integration_branch:
        description: "Source branch for the integration PR"
        required: false
        type: string
        default: "ai/dev"
      base_branch:
        description: "Target branch for the integration PR"
        required: false
        type: string
        default: "main"

permissions:
  contents: read
  pull-requests: write

jobs:
  integration-pr:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0
          ref: ${{ inputs.integration_branch }}

      - name: Check if integration branch is ahead of base
        id: check-ahead
        run: |
          git fetch origin ${{ inputs.base_branch }}
          AHEAD=$(git rev-list --count origin/${{ inputs.base_branch }}..HEAD)
          echo "ahead=$AHEAD" >> "$GITHUB_OUTPUT"
          if [ "$AHEAD" -eq 0 ]; then
            echo "No commits ahead of ${{ inputs.base_branch }}. Nothing to do."
          fi

      - name: Extract issue references
        if: steps.check-ahead.outputs.ahead != '0'
        id: extract-refs
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          # Get all commit messages between base and integration branch
          COMMITS=$(git log origin/${{ inputs.base_branch }}..HEAD --pretty=format:"%h %s")

          # Extract unique issue numbers from Closes/Fixes/Resolves patterns
          ISSUE_NUMS=$(echo "$COMMITS" | grep -oiE '(closes|fixes|resolves)\s+#[0-9]+' | grep -oE '[0-9]+' | sort -un)

          # Also match bare #N in squash-merge subjects (e.g., "feat: add auth (#42)")
          BARE_NUMS=$(echo "$COMMITS" | grep -oE '#[0-9]+' | grep -oE '[0-9]+' | sort -un)

          # Combine and deduplicate
          ALL_NUMS=$(echo -e "${ISSUE_NUMS}\n${BARE_NUMS}" | sort -un | grep -v '^$')

          if [ -z "$ALL_NUMS" ]; then
            echo "found=false" >> "$GITHUB_OUTPUT"
            echo "No issue references found in commits."
          else
            echo "found=true" >> "$GITHUB_OUTPUT"

            # Build closes lines with issue titles
            CLOSES_LINES=""
            for NUM in $ALL_NUMS; do
              TITLE=$(gh issue view "$NUM" --json title --jq '.title' 2>/dev/null || echo "")
              if [ -n "$TITLE" ]; then
                CLOSES_LINES="${CLOSES_LINES}- Closes #${NUM} -- ${TITLE}\n"
              else
                CLOSES_LINES="${CLOSES_LINES}- Closes #${NUM}\n"
              fi
            done
            echo "closes_lines<<CLOSES_EOF" >> "$GITHUB_OUTPUT"
            echo -e "$CLOSES_LINES" >> "$GITHUB_OUTPUT"
            echo "CLOSES_EOF" >> "$GITHUB_OUTPUT"
          fi

          # Save commit log for PR body
          echo "commits<<COMMITS_EOF" >> "$GITHUB_OUTPUT"
          echo "$COMMITS" >> "$GITHUB_OUTPUT"
          echo "COMMITS_EOF" >> "$GITHUB_OUTPUT"

      - name: Build PR body
        if: steps.check-ahead.outputs.ahead != '0'
        id: build-body
        run: |
          INTEGRATION="${{ inputs.integration_branch }}"
          BASE="${{ inputs.base_branch }}"

          {
            echo "body<<BODY_EOF"
            echo "## Merge \`${INTEGRATION}\` -> \`${BASE}\`"
            echo ""
            if [ "${{ steps.extract-refs.outputs.found }}" = "true" ]; then
              echo "### Completed Issues"
              echo ""
              echo -e "${{ steps.extract-refs.outputs.closes_lines }}"
            else
              echo "_No issue references found in commits._"
              echo ""
            fi
            echo "### Commits"
            echo ""
            echo '${{ steps.extract-refs.outputs.commits }}' | while IFS= read -r line; do
              [ -n "$line" ] && echo "- $line"
            done
            echo ""
            echo "---"
            echo "*Auto-maintained by [integration-pr](https://github.com/BryGo1995/agent-orchestrator) workflow*"
            echo "BODY_EOF"
          } >> "$GITHUB_OUTPUT"

      - name: Create or update PR
        if: steps.check-ahead.outputs.ahead != '0'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          INTEGRATION="${{ inputs.integration_branch }}"
          BASE="${{ inputs.base_branch }}"
          TITLE="Merge ${INTEGRATION} -> ${BASE}"
          BODY=$(cat <<'BODY_EOF'
          ${{ steps.build-body.outputs.body }}
          BODY_EOF
          )

          # Check for existing open PR
          EXISTING_PR=$(gh pr list --head "$INTEGRATION" --base "$BASE" --state open --json number --jq '.[0].number // empty')

          if [ -z "$EXISTING_PR" ]; then
            echo "Creating new PR: $TITLE"
            gh pr create --head "$INTEGRATION" --base "$BASE" --title "$TITLE" --body "$BODY"
          else
            echo "Updating existing PR #${EXISTING_PR}"
            # Only update if body changed
            CURRENT_BODY=$(gh pr view "$EXISTING_PR" --json body --jq '.body')
            if [ "$CURRENT_BODY" != "$BODY" ]; then
              gh pr edit "$EXISTING_PR" --body "$BODY"
              echo "PR #${EXISTING_PR} body updated."
            else
              echo "PR #${EXISTING_PR} body unchanged. Skipping."
            fi
          fi
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/integration-pr.yml
git commit -m "feat: add reusable integration PR workflow"
```

---

### Task 2: Create the Caller Workflow Template

**Files:**
- Create: `templates/integration-pr-caller.yml`

- [ ] **Step 1: Create the templates directory**

```bash
mkdir -p /home/bryang/Dev_Space/agent-orchestrator/templates
```

- [ ] **Step 2: Write the caller template**

Create `templates/integration-pr-caller.yml`:

```yaml
# Copy this file to .github/workflows/integration-pr.yml in your target repo.
# Requires: BryGo1995/agent-orchestrator to be public (or same org with workflow sharing).
# No secrets needed — uses the default GITHUB_TOKEN.

name: Integration PR

on:
  push:
    branches: [ai/dev]  # Change if your integration branch has a different name

jobs:
  integration-pr:
    uses: BryGo1995/agent-orchestrator/.github/workflows/integration-pr.yml@main
    with:
      integration_branch: ai/dev   # Must match the branch above
      base_branch: main
```

- [ ] **Step 3: Commit**

```bash
git add templates/integration-pr-caller.yml
git commit -m "feat: add caller workflow template for target repos"
```

---

### Task 3: Update README with Setup Instructions

**Files:**
- Modify: `README.md` (Per-Repo Setup section, ~line 145-153, and Morning Review section, ~line 189-193)

- [ ] **Step 1: Add Integration PR section to Per-Repo Setup**

In `README.md`, after the existing Per-Repo Setup step 4, add step 5:

```markdown
5. **Set up the Integration PR workflow** — Copy `templates/integration-pr-caller.yml` to `.github/workflows/integration-pr.yml` in the target repo. This auto-creates a persistent `ai/dev -> main` PR whenever agents merge work into `ai/dev`. Edit the branch names in the file if your integration branch differs. No secrets required.
```

- [ ] **Step 2: Update Morning Review section**

Replace the Morning Review section with:

```markdown
### Morning Review

1. Check Slack for the overnight summary and any blocked/error alerts
2. Open the persistent `ai/dev -> main` PR on GitHub — it lists all completed issues and commits
3. Review the diff, then merge using a **regular merge commit** (not squash) to keep branches in sync
4. A new integration PR will be created automatically when the next batch of work lands on `ai/dev`
```

- [ ] **Step 3: Add Integration PR Workflow section**

After the Guardrails section, add:

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add integration PR workflow setup instructions to README"
```

---

### Task 4: Remove merge_to_main.py

**Files:**
- Delete: `merge_to_main.py`

- [ ] **Step 1: Verify no other code imports merge_to_main**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator && grep -r "merge_to_main" --include="*.py" .
```

Expected: Only hits in `merge_to_main.py` itself (no imports from other modules).

- [ ] **Step 2: Delete the file**

```bash
rm /home/bryang/Dev_Space/agent-orchestrator/merge_to_main.py
```

- [ ] **Step 3: Commit**

```bash
git add -u merge_to_main.py
git commit -m "refactor: remove merge_to_main.py, replaced by integration PR workflow"
```

---

### Task 5: Deploy Caller Workflow to paint-ballas-auto

**Files:**
- Create: `<paint-ballas-auto-path>/.github/workflows/integration-pr.yml` (copy of caller template)

- [ ] **Step 1: Locate the paint-ballas-auto repo**

```bash
find /home/bryang -maxdepth 3 -name "paint-ballas-auto" -type d 2>/dev/null
```

If not cloned locally, clone it:

```bash
cd /home/bryang/Dev_Space && gh repo clone BryGo1995/paint-ballas-auto
```

- [ ] **Step 2: Create the workflow directory and copy the caller**

```bash
mkdir -p <paint-ballas-auto-path>/.github/workflows
cp /home/bryang/Dev_Space/agent-orchestrator/templates/integration-pr-caller.yml <paint-ballas-auto-path>/.github/workflows/integration-pr.yml
```

- [ ] **Step 3: Commit and push**

```bash
cd <paint-ballas-auto-path>
git add .github/workflows/integration-pr.yml
git commit -m "ci: add integration PR workflow for ai/dev -> main"
git push
```

- [ ] **Step 4: Verify the orchestrator repo is public**

```bash
gh repo view BryGo1995/agent-orchestrator --json visibility --jq '.visibility'
```

If private, the reusable workflow won't be accessible. Either make it public or move the full workflow inline into paint-ballas-auto.

---

### Task 6: End-to-End Verification

- [ ] **Step 1: Push the orchestrator repo workflows**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git push
```

- [ ] **Step 2: Trigger a test push to ai/dev in paint-ballas-auto**

Create a trivial commit on `ai/dev` to trigger the workflow:

```bash
cd <paint-ballas-auto-path>
git checkout ai/dev
echo "# test" >> .github/.keep
git add .github/.keep
git commit -m "test: trigger integration PR workflow"
git push
```

- [ ] **Step 3: Verify the workflow ran**

```bash
gh run list --repo BryGo1995/paint-ballas-auto --workflow integration-pr.yml --limit 1
```

Expected: One completed run.

- [ ] **Step 4: Verify the PR was created**

```bash
gh pr list --repo BryGo1995/paint-ballas-auto --head ai/dev --base main
```

Expected: One open PR titled `Merge ai/dev -> main`.

- [ ] **Step 5: Clean up test commit**

```bash
cd <paint-ballas-auto-path>
git checkout ai/dev
git revert HEAD --no-edit
git push
```
