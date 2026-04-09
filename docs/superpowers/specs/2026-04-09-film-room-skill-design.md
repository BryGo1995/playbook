# Film Room Skill Design

**Date:** 2026-04-09
**Status:** Draft
**Skill name:** `playbook:film-room`

## Purpose

Post-agent review and fix workflow for the playbook orchestrator. After agents
complete all tasks on a version branch, the user invokes film-room to
interactively review the work, identify issues, fix them, and merge the fixes
back into the version branch.

This closes the pipeline gap between agent completion and version sign-off:

```
scout → gameplan → orchestrator → agents → film-room → version ready
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Branch detection | Current branch if version branch, else auto-detect from project board | Zero friction if already on branch; no manual input needed otherwise |
| Fix branch naming | `film-room/vX.Y` | Ties to version (always known), not issue number (may not exist yet at invocation time) |
| Branch reuse | Delete and recreate if exists | Previous session is already merged; stale branches are clutter |
| Tracking issue format | Lightweight checklist | User drives the session, not agents — heavy gameplan template is unnecessary |
| Issue title format | `[vX.Y] Film Room: Post-Agent Review` | Consistent with playbook `[vX.Y]` convention |
| Merge strategy | User chooses PR or direct merge at wrap-up | Flexibility — PR for extra review, direct merge for speed |
| Checklist management | Claude updates issue body via `gh issue edit` as fixes are identified and completed | Living record that grows organically; no upfront lock-in |

## Two-Phase Architecture

The skill has two explicit phases with an unstructured working period between
them. The skill does not own the middle — it handles setup and teardown.

```
Phase 1: Setup
  ├── Detect version branch
  ├── Read playbook.yaml for repo/project config
  ├── Summarize agent work
  ├── Create tracking issue
  ├── Create fix branch
  └── Hand off to user

[User works — fixes issues, Claude updates checklist]

Phase 2: Wrap-up (user triggers)
  ├── Status check
  ├── Update tracking issue
  ├── Offer merge strategy
  ├── Execute merge
  ├── Clean up branch
  └── Close issue with summary
```

## Phase 1: Setup

### Step 1 — Detect version branch

1. Check the current git branch.
2. If it matches `ai/dev-v*` or `ai/dev-bootstrap`, use it as the version
   branch.
3. Otherwise:
   - Read `playbook.yaml` from CWD. If not found, stop with an error:
     > "No `playbook.yaml` found in the current directory. Run this skill from
     > a repo that has a `playbook.yaml`."
   - Extract `repo`, `project.owner`, and `project.number`.
   - Query the project board via `gh project item-list`.
   - Find the most recently completed version — all issues in `Done` or
     `ai-complete` status.
   - Derive the branch name using the existing `version_branch_name()`
     convention (e.g., `ai/dev-v0.3`).
4. If no completed version is found, stop with an error:
   > "No completed version found on the project board. Film room is for
   > reviewing finished agent work."

### Step 2 — Summarize agent work

1. Run `git diff main...{version_branch} --stat` to get a file-level summary.
2. Query the project board for all issues tagged with this version — list
   titles and statuses.
3. List merged PRs targeting the version branch via
   `gh pr list --base {version_branch} --state merged`.
4. Present a concise summary to the user:
   - What was built (issue titles)
   - How many files changed
   - Which PRs were merged

### Step 3 — Create tracking issue

1. Create a GitHub issue via `gh issue create`:
   - **Title:** `[vX.Y] Film Room: Post-Agent Review`
   - **Body:**
     ```markdown
     ## Film Room: vX.Y Post-Agent Review

     **Branch:** `film-room/vX.Y`
     **Version branch:** `ai/dev-vX.Y`

     ## Fixes
     (items added during session)

     ## Notes
     ```
2. Add the issue to the project board via `gh project item-add`.

### Step 4 — Create fix branch

1. Check if `film-room/vX.Y` exists locally (`git branch --list`) or remotely
   (`git ls-remote --heads origin film-room/vX.Y`).
2. If it exists, delete it:
   - Local: `git branch -D film-room/vX.Y`
   - Remote: `git push origin --delete film-room/vX.Y`
3. Create the branch: `git checkout -b film-room/vX.Y {version_branch}`
4. Push to remote: `git push -u origin film-room/vX.Y`

### Step 5 — Hand off

Present a confirmation message:
- Issue link
- Branch name
- Version branch being reviewed
- Reminder: "Tell me what needs fixing. I'll add items to the tracking issue
  as we go and check them off when done."

## Working Session (Between Phases)

The skill does not control this period. The user drives. Claude's
responsibilities:

1. **When the user identifies a problem:** Append an unchecked item to the
   issue body (`- [ ] Description of fix`). Update via `gh issue edit --body`.

2. **When a fix is committed:** Check off the corresponding item in the issue
   body (`- [x] Description of fix`). Update via `gh issue edit --body`.

3. **When new problems are discovered during a fix:** Append them to the
   checklist.

The issue body is rebuilt and replaced on each update. The full body is
maintained in the conversation context and pushed to GitHub as a whole via
`gh issue edit`.

## Phase 2: Wrap-up

Triggered when the user indicates they are done (e.g., "let's wrap up",
"I'm done", "merge it back").

### Step 1 — Status check

1. Compare `film-room/vX.Y` against the version branch:
   `git log {version_branch}..film-room/vX.Y --oneline`
2. If no commits ahead, ask the user:
   > "No changes on the fix branch. Close the issue and delete the branch
   > without merging?"

### Step 2 — Update tracking issue

1. Review the checklist in the issue body.
2. If any items are unchecked, ask the user:
   > "These items are still unchecked: [list]. Are you leaving them for later,
   > or do they still need to be addressed?"
3. Update the issue body if needed.

### Step 3 — Offer merge strategy

Present two options:
- **PR:** "I'll create a PR from `film-room/vX.Y` → `ai/dev-vX.Y` with a
  summary of all fixes. You can review the diff before merging."
- **Direct merge:** "I'll merge `film-room/vX.Y` into `ai/dev-vX.Y` locally
  and push. No extra review step."

Wait for the user's choice.

### Step 4 — Execute

**If PR:**
1. Create PR via `gh pr create`:
   - Title: `[vX.Y] Film Room Fixes`
   - Body: summary of fixes from the checklist
   - Base: `ai/dev-vX.Y`
   - Link the tracking issue
2. Inform the user the PR is ready for their merge.

**If direct merge:**
1. `git checkout {version_branch}`
2. `git merge film-room/vX.Y`
3. `git push origin {version_branch}`

### Step 5 — Clean up

1. Delete the fix branch:
   - Local: `git branch -D film-room/vX.Y`
   - Remote: `git push origin --delete film-room/vX.Y`
2. Close the tracking issue with a comment summarizing what was fixed:
   ```
   gh issue close {issue_number} --comment "Film room session complete.
   Fixed N items. Changes merged to ai/dev-vX.Y via [PR #N / direct merge]."
   ```
3. Present a final summary:
   - Number of fixes applied
   - Files changed
   - Merge target and method

## File Structure

```
skills/
  film-room/
    SKILL.md          # The skill definition (prompt)
    issue-template.md  # Lightweight issue body template
```

## Integration with Existing Pipeline

- **playbook.yaml:** Film-room reads the same config as gameplan and the
  orchestrator — `repo`, `project.owner`, `project.number`.
- **Versioning:** Uses `version_branch_name()` convention from `versioning.py`.
- **Project board:** Issues are added to the same board the orchestrator uses.
  The `[vX.Y]` title prefix keeps them discoverable alongside agent issues.
- **No new statuses:** Film-room issues don't need orchestrator statuses
  (`ai-ready`, etc.) since they're human-driven. They use GitHub's default
  open/closed state.

## Out of Scope

- **Automated review/diffing:** The skill does not walk through changes
  section by section. The user identifies problems.
- **Escalation to new gameplan issues:** If a problem is too large for
  film-room, the user handles that separately. The skill doesn't gate on
  complexity.
- **Multi-version sessions:** One film-room session reviews one version. To
  review multiple versions, invoke the skill multiple times.
