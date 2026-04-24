---
name: playbook:film-room
description: >
  Use when agents have completed all tasks on a version branch and the user
  wants to review the work, fix issues, and merge fixes back. Invoked
  explicitly via /playbook:film-room. Sets up a tracking issue and fix branch,
  manages a checklist during the session, and handles merge-back when done.
---

# Film Room — Playbook Orchestrator

## Overview

Act as a senior engineer running a post-agent review session. Set up the
tracking infrastructure (issue, branch), help the user fix problems they
identify, and handle the merge-back when they're done.

The user is the reviewer. They identify problems, you fix them. Nothing gets
added to the checklist without their direction.

Film room supports one mode: review a completed version branch. One session
reviews one version. To review multiple versions, invoke the skill multiple
times.

## Flow

```dot
digraph film_room {
    "Phase 1:\nSetup" [shape=box];
    "Config found?" [shape=diamond];
    "Version branch\ndetected?" [shape=diamond];
    "Summarize\nagent work" [shape=box];
    "Create issue\n& branch" [shape=box];
    "Hand off\nto user" [shape=box];
    "Working Session:\nUser drives" [shape=box, style=dashed];
    "User says done" [shape=diamond];
    "Phase 2:\nWrap-up" [shape=box];
    "Done" [shape=doublecircle];

    "Phase 1:\nSetup" -> "Config found?";
    "Config found?" -> "Version branch\ndetected?" [label="yes"];
    "Config found?" -> "Stop:\nno playbook.yaml" [label="no"];
    "Version branch\ndetected?" -> "Summarize\nagent work" [label="yes"];
    "Version branch\ndetected?" -> "Stop:\nno completed\nversion" [label="no"];
    "Summarize\nagent work" -> "Create issue\n& branch";
    "Create issue\n& branch" -> "Hand off\nto user";
    "Hand off\nto user" -> "Working Session:\nUser drives";
    "Working Session:\nUser drives" -> "User says done";
    "User says done" -> "Phase 2:\nWrap-up";
    "Phase 2:\nWrap-up" -> "Done";
}
```

## Phase 1 — Setup

Gather context and set up the tracking infrastructure. Do not ask the user
anything until the hand-off step.

### Step 1 — Read config

1. Read `playbook.yaml` in the current working directory. If not found, stop:
   > "No `playbook.yaml` found in the current directory. Run this skill from a
   > repo that has a `playbook.yaml`."

2. Extract:
   - `repo` — the GitHub repo identifier (e.g., `BryGo1995/paint-ballas-auto`)
   - `project.owner` and `project.number` — for project board queries
   - `gdd_path` — to reference the GDD if needed for context

### Step 2 — Detect version branch

1. Check the current git branch: `git branch --show-current`
2. If the current branch matches `ai/dev-v*` or `ai/dev-bootstrap`, use it as
   the version branch. Extract the version from the branch name.
3. Otherwise, auto-detect:
   - Query the project board:
     ```bash
     gh project item-list <project_number> --owner <owner> --format json
     ```
   - Parse issue titles for version tags (`[vX.Y]`).
   - Find the highest completed version — the version with the largest
     `(major, minor)` tuple where all issues are in `Done` or `ai-complete`
     status.
   - Derive the branch name: `ai/dev-v{major}.{minor}` (or `ai/dev-bootstrap`
     for version `(0, 0)`).
4. If no completed version is found, stop:
   > "No completed version found on the project board. Film room is for
   > reviewing finished agent work."
5. Verify the branch exists on the remote:
   ```bash
   git ls-remote --heads origin <version_branch>
   ```
   If it doesn't exist, stop:
   > "Branch `<version_branch>` not found on remote. Has the agent work been
   > pushed?"

### Step 3 — Summarize agent work

1. Fetch latest:
   ```bash
   git fetch origin
   ```

2. Get file-level diff summary:
   ```bash
   git diff main...origin/<version_branch> --stat
   ```

3. Query project board for all issues in this version — list their titles and
   statuses.

4. List merged PRs targeting the version branch:
   ```bash
   gh pr list --repo <repo> --base <version_branch> --state merged
   ```

5. Present a concise summary to the user:
   - Version being reviewed
   - What was built (issue titles and their statuses)
   - How many files changed
   - Which PRs were merged

### Step 4 — Create tracking issue

1. Read the issue template from `issue-template.md` in this skill directory.

2. Create the issue:
   ```bash
   gh issue create --repo <repo> \
     --title "[vX.Y] Film Room: Post-Agent Review" \
     --body "$(cat <<'EOF'
   ## Film Room: vX.Y Post-Agent Review

   **Branch:** `film-room/vX.Y`
   **Version branch:** `ai/dev-vX.Y`

   ## Fixes
   (items added during session)

   ## Notes
   EOF
   )"
   ```

   For bootstrap versions, use `[bootstrap]` instead of `[vX.Y]`.

3. Add the issue to the project board:
   ```bash
   gh project item-add <project_number> --owner <owner> --url <issue_url>
   ```

4. Store the issue number and the current issue body in conversation context
   for later updates.

### Step 5 — Create fix branch

1. Check if `film-room/vX.Y` exists locally or remotely:
   ```bash
   git branch --list film-room/vX.Y
   git ls-remote --heads origin film-room/vX.Y
   ```

2. If it exists, delete it (previous session, already merged):
   - Local: `git branch -D film-room/vX.Y` (ignore errors if not local)
   - Remote: `git push origin --delete film-room/vX.Y` (ignore errors if not
     remote)

3. Make sure local tracking is up to date:
   ```bash
   git checkout <version_branch>
   git pull origin <version_branch>
   ```

4. Create and push the fix branch:
   ```bash
   git checkout -b film-room/vX.Y
   git push -u origin film-room/vX.Y
   ```

### Step 6 — Hand off

Present a confirmation message to the user:

> **Film room is set up for vX.Y.**
>
> - **Tracking issue:** #N — [link]
> - **Fix branch:** `film-room/vX.Y`
> - **Reviewing:** `ai/dev-vX.Y`
>
> Tell me what needs fixing. I'll add items to the tracking issue as we go
> and check them off when done.
>
> When you're finished, say "let's wrap up" and I'll handle the merge.

## Working Session (Between Phases)

The skill does not control this period. The user drives — they identify
problems and direct fixes. Your responsibilities:

### When the user identifies a problem

1. Add an unchecked item to the issue body: `- [ ] Description of fix`
2. Update the issue on GitHub:
   ```bash
   gh issue edit <issue_number> --repo <repo> --body "<full updated body>"
   ```
3. Confirm: "Added to the checklist. Let me fix that."

### When a fix is committed

1. Check off the item in the issue body: `- [x] Description of fix`
2. Update the issue on GitHub with the same `gh issue edit` command.
3. Confirm the fix is done and the checklist is updated.

### When new problems are discovered during a fix

Append them to the checklist. The list grows organically — no upfront lock-in.

### Issue body management

Maintain the full issue body in conversation context. On each update, replace
the entire body via `gh issue edit --body`. This is simpler and more reliable
than trying to patch individual checklist items via the API.

### Guidelines

- **Stay on the fix branch.** All commits go to `film-room/vX.Y`.
- **Commit each fix individually.** One fix = one commit. This makes the
  merge-back diff reviewable.
- **Don't scope-creep.** If the user identifies something that needs a
  redesign or new feature, suggest creating a separate issue for the next
  version via gameplan. Film room is for fixes, not new work.
- **Push periodically.** Push to remote after each fix so the branch is
  backed up:
  ```bash
  git push origin film-room/vX.Y
  ```

## Phase 2 — Wrap-up

Triggered when the user indicates they are done (e.g., "let's wrap up",
"I'm done", "merge it back"). Wrap-up runs the merge, then the learning
distillers (Step 4.5), then cleanup.

### Step 1 — Status check

1. Compare the fix branch against the version branch:
   ```bash
   git log origin/<version_branch>..film-room/vX.Y --oneline
   ```

2. If no commits ahead, ask the user:
   > "No changes on the fix branch. Close the issue and delete the branch
   > without merging?"
   If they confirm, skip to Step 5 (clean up).

### Step 2 — Update tracking issue

1. Review the checklist in the issue body.
2. If any items are still unchecked, ask the user:
   > "These items are still unchecked:
   > - [ ] Item A
   > - [ ] Item B
   >
   > Are you leaving them for later, or do they still need to be addressed?"
3. If the user wants to address them, return to the working session.
4. If leaving for later, add a note to the issue body under "## Notes"
   explaining they were deferred.
5. Push the final issue body update to GitHub.

### Step 3 — Offer merge strategy

Present two options:

> **How would you like to merge the fixes?**
>
> **A) Pull Request** — I'll create a PR from `film-room/vX.Y` →
> `ai/dev-vX.Y` with a summary of all fixes. You can review the diff one
> more time before merging.
>
> **B) Direct merge** — I'll merge `film-room/vX.Y` into `ai/dev-vX.Y`
> locally and push. No extra review step.

Wait for the user's choice.

### Step 4 — Execute merge

**If Pull Request (A):**

1. Push any unpushed commits:
   ```bash
   git push origin film-room/vX.Y
   ```

2. Build the PR body from the checklist — list all fixes that were applied.

3. Create the PR:
   ```bash
   gh pr create --repo <repo> \
     --base <version_branch> \
     --head film-room/vX.Y \
     --title "[vX.Y] Film Room Fixes" \
     --body "$(cat <<'EOF'
   ## Summary

   Post-agent review fixes for vX.Y.

   ## Fixes Applied
   - Fix 1 description
   - Fix 2 description

   Closes #<tracking_issue_number>
   EOF
   )"
   ```

4. Tell the user:
   > "PR created: [link]. Merge when you're ready — I'll clean up after."

   Wait for the user to confirm the PR is merged before proceeding to Step 5.

**If Direct merge (B):**

1. Push any unpushed commits:
   ```bash
   git push origin film-room/vX.Y
   ```

2. Merge into the version branch:
   ```bash
   git checkout <version_branch>
   git merge film-room/vX.Y
   git push origin <version_branch>
   ```

3. Proceed to Step 5.

### Step 4.5 — Run distillers

Two distillers run after the merge but before cleanup. Each is a `claude
-p` invocation that consumes the film-room data and either opens a PR or
exits cleanly with no PR. Both are skipped when:

- `learning.enabled` is `false` in `playbook.yaml` (use the merged config
  from `defaults.yaml` + `playbook.yaml`), **OR**
- the fix branch had zero commits ahead of the version branch (already
  the early-exit path from Step 1).

Skip individual distillers when their toggle is false:
- `learning.project_distiller: false` → skip the project distiller.
- `learning.agent_craft_distiller: false` → skip the agent-craft
  distiller.

#### Gather the input bundle (shared by both distillers)

Run these commands and capture each output for use in both distiller
invocations. All paths are absolute or rooted at the project repo's
working tree.

1. **Tracking issue body:**
   ```bash
   gh issue view <issue_number> --repo <repo> --json body --jq .body
   ```

2. **Fix commits with diffs:**
   ```bash
   git log origin/<version_branch>..film-room/<version_label> --patch
   ```
   Where `<version_label>` is `vX.Y` or `bootstrap` to match the branch.

3. **Original agent PRs for this version** (titles, bodies, diff URLs):
   ```bash
   gh pr list --repo <repo> --base <version_branch> --state merged \
     --json number,title,body,url
   ```

4. **Original issues** the agents worked on — for each PR from step 3,
   parse `Closes #N` / `Fixes #N` references from the PR body, then:
   ```bash
   gh issue view <N> --repo <repo> --json title,body
   ```

Combine all of the above into a single text bundle. The exact format does
not matter; the distillers are told what fields to expect.

#### Run the project distiller

Skip this section if `learning.project_distiller` is false.

1. Read the current `CLAUDE.md` from the project repo's working tree
   (empty string if it does not exist):
   ```bash
   if [ -f CLAUDE.md ]; then cat CLAUDE.md; fi
   ```

2. Read the distiller prompt:
   ```bash
   cat <playbook_repo_path>/skills/film-room/distillers/project-distiller.md
   ```
   Replace `<playbook_repo_path>` with the absolute path to the playbook
   repo on the operator's machine. (You can locate it via the skill's own
   directory: the prompt file lives next to `SKILL.md`.)

3. Build the distiller invocation. Pass the prompt + the input bundle +
   the current `CLAUDE.md` + the repo identifier + the version label as
   the `claude -p` prompt body. The distiller is told to emit JSON-only.

   ```bash
   claude -p --output-format json --max-budget-usd 1.0 "$DISTILLER_PROMPT_WITH_INPUTS" > /tmp/project-distiller.json
   ```

4. Unwrap the `claude -p` envelope and re-parse the distiller's payload:
   ```bash
   # Check the wrapper — skip if claude -p errored:
   SUBTYPE=$(jq -r .subtype /tmp/project-distiller.json)
   if [ "$SUBTYPE" != "success" ]; then
     echo "Project distiller errored (subtype=$SUBTYPE); skipping."
     # tell the user and continue to the agent-craft distiller
     # (do NOT treat this as 'no lessons proposed' — it's an error)
   fi

   # Unwrap the payload (distillers are told to emit raw JSON, no fences,
   # but be defensive — strip a leading/trailing ```json / ``` fence if
   # present):
   PAYLOAD=$(jq -r .result /tmp/project-distiller.json \
     | sed -e 's/^```json$//' -e 's/^```$//' \
     | sed -e '/./,$!d')

   # Now PAYLOAD is the distiller's JSON object. Re-parse:
   CLAUDE_MD=$(echo "$PAYLOAD" | jq -r .claude_md)
   PR_BODY=$(echo "$PAYLOAD" | jq -r .pr_body)
   LESSONS=$(echo "$PAYLOAD" | jq -r .lessons_added)
   ```

5. **If `CLAUDE_MD` is the string `null` or `LESSONS` is `0`**, tell the user:
   > "Project distiller ran but proposed no lessons (every fix was a local
   > incident or already covered in CLAUDE.md). No PR opened."
   Skip to the agent-craft distiller.

6. **Otherwise**, open a PR against the project repo:
   ```bash
   git checkout -b learning/film-room-vX.Y origin/main
   # Write the new CLAUDE.md from the distiller output:
   printf '%s' "$CLAUDE_MD" > CLAUDE.md
   git add CLAUDE.md
   git commit -m "chore: capture lessons from vX.Y film-room"
   git push -u origin learning/film-room-vX.Y
   printf '%s' "$PR_BODY" > /tmp/project-distiller.prbody.md
   gh pr create --repo <repo> \
     --base main \
     --head learning/film-room-vX.Y \
     --title "Lessons from vX.Y film-room" \
     --body-file /tmp/project-distiller.prbody.md
   ```
   Tell the user the PR URL.

   After the PR is created, return to the film-room fix branch:
   ```bash
   git checkout film-room/<version_label>
   ```

#### Run the agent-craft distiller

Skip this section if `learning.agent_craft_distiller` is false.

1. Resolve the playbook repo identifier from the merged config:
   `learning.playbook_repo` (default `BryGo1995/playbook`).

2. Read the current playbook agent prompts and the observations log from
   the playbook repo. Use `gh api` so the operator does not need a local
   clone:
   ```bash
   gh api repos/<playbook_repo>/contents/agents/coding.py   --jq .content | base64 -d
   gh api repos/<playbook_repo>/contents/agents/review.py   --jq .content | base64 -d
   gh api repos/<playbook_repo>/contents/agents/testing.py  --jq .content | base64 -d
   gh api repos/<playbook_repo>/contents/docs/agent-craft-observations.md --jq .content | base64 -d
   ```

3. Read the agent-craft distiller prompt (sibling of `SKILL.md`):
   ```bash
   cat <playbook_repo_path>/skills/film-room/distillers/agent-craft-distiller.md
   ```

4. Build the distiller invocation. Pass: the prompt + the input bundle +
   the three agent files + the observations log + the playbook repo id +
   the project repo id + the version + today's date + the project
   film-room issue URL.

   ```bash
   claude -p --output-format json --max-budget-usd 1.0 "$AGENT_CRAFT_PROMPT_WITH_INPUTS" > /tmp/agent-craft.json
   ```

5. Unwrap the `claude -p` envelope and re-parse the distiller's payload:
   ```bash
   SUBTYPE=$(jq -r .subtype /tmp/agent-craft.json)
   if [ "$SUBTYPE" != "success" ]; then
     echo "Agent-craft distiller errored (subtype=$SUBTYPE); skipping."
   fi
   PAYLOAD=$(jq -r .result /tmp/agent-craft.json \
     | sed -e 's/^```json$//' -e 's/^```$//' \
     | sed -e '/./,$!d')
   MODE=$(echo "$PAYLOAD" | jq -r .mode)
   TARGET=$(echo "$PAYLOAD" | jq -r .target_file)
   PATCHED=$(echo "$PAYLOAD" | jq -r .patched_file_contents)
   PR_BODY_AC=$(echo "$PAYLOAD" | jq -r .pr_body)
   ```

6. **If `MODE` is `"skip"`**, tell the user:
   > "Agent-craft distiller ran and found no agent-craft signals this
   > session. No PR opened."
   Done with distillers.

7. **Otherwise**, open a PR against the playbook repo. The branch name
   encodes the project + version so concurrent sessions do not collide.
   First, resolve `<project_repo_slug>` — take the project's `<repo>`
   identifier, lowercase it, and replace `/` with `-`.

   Then run these steps in order:

   a. Create the branch off `main` in the playbook repo (if it does not
      already exist). Get the SHA of `main` first, then create the ref:
      ```bash
      BRANCH="learning/<project_repo_slug>-vX.Y"
      MAIN_SHA=$(gh api repos/<playbook_repo>/git/refs/heads/main --jq .object.sha)
      gh api -X POST repos/<playbook_repo>/git/refs \
        -f ref="refs/heads/$BRANCH" \
        -f sha="$MAIN_SHA" \
        || echo "Branch already exists, continuing"
      ```
      The `|| echo ...` only catches the "already exists" case from
      re-running the distiller after a failure; do not use it to mask
      other errors — inspect the command's stderr.

   b. Fetch the SHA of the existing file on that branch (if any). The
      file may not exist (e.g. this is the first
      `docs/agent-craft-observations.md` write, though Task 4 seeded it,
      so it usually does exist):
      ```bash
      EXISTING_SHA=$(gh api repos/<playbook_repo>/contents/$TARGET?ref=$BRANCH --jq .sha 2>/dev/null || echo "")
      ```

   c. Write the patched file contents to the branch via `gh api -X PUT`.
      Include `-f sha="$EXISTING_SHA"` only when `$EXISTING_SHA` is
      non-empty (the API rejects empty-string SHAs but requires the SHA
      for updates):
      ```bash
      if [ -n "$EXISTING_SHA" ]; then
        gh api -X PUT repos/<playbook_repo>/contents/$TARGET \
          -f message="agent-craft: $MODE from <project_repo> vX.Y" \
          -f content="$(echo "$PATCHED" | base64 -w0)" \
          -f branch="$BRANCH" \
          -f sha="$EXISTING_SHA"
      else
        gh api -X PUT repos/<playbook_repo>/contents/$TARGET \
          -f message="agent-craft: $MODE from <project_repo> vX.Y" \
          -f content="$(echo "$PATCHED" | base64 -w0)" \
          -f branch="$BRANCH"
      fi
      ```

   d. Open the PR:
      ```bash
      printf '%s' "$PR_BODY_AC" > /tmp/agent-craft.prbody.md
      gh pr create --repo <playbook_repo> \
        --base main \
        --head "$BRANCH" \
        --title "agent-craft: $MODE from <project_repo> vX.Y film-room" \
        --body-file /tmp/agent-craft.prbody.md
      ```

   Tell the user the PR URL.

#### Tell the user what happened

Before moving to Step 5, summarize:

> "Distillers complete:
> - Project distiller: <PR link, or 'no lessons proposed'>
> - Agent-craft distiller: <PR link, or 'no signals this session'>"

### Step 4.6 — Run the classifier (metrics)

Runs the Component 2 classifier as a fresh `claude -p` subagent, mirroring the distiller pattern from Step 4.5. Skip this step entirely when:

- `metrics.enabled` is `false` in the merged config, **OR**
- the fix branch had zero commits ahead of the version branch (first-pass clean).

If skipped due to first-pass clean: update `metrics/vX.Y.md` by writing `_No fixes made — classification skipped._` in the `## Classification (film-room)` section and setting frontmatter `fixes_total: 0`, `first_pass_clean: <issues count>`. Still regenerate `SUMMARY.md` (Step 4.7) before proceeding to cleanup.

#### Invoke the classifier

Reuse the input bundle gathered by Step 4.5 (tracking issue body, fix commit patches, merged PRs, original issues).

1. Read the rubric and the subagent prompt:
   ```bash
   cat <playbook_repo_path>/skills/film-room/classification-rubric.md
   cat <playbook_repo_path>/skills/film-room/classifier-prompt.md
   ```

2. Build the combined prompt body in the order specified by `classifier-prompt.md` (`## Rubric` first, then the bundle sections).

3. Invoke with the budget cap from `metrics.classification_budget_usd`:
   ```bash
   BUDGET=$(python -c "import yaml, os; cfg = yaml.safe_load(open('playbook.yaml')); print(cfg.get('metrics', {}).get('classification_budget_usd', 0.25))")
   claude -p --output-format json --max-budget-usd "$BUDGET" "$CLASSIFIER_PROMPT_WITH_INPUTS" > /tmp/classifier.json
   ```

4. Unwrap the `claude -p` envelope and re-parse the classifier's payload (identical pattern to the distillers):
   ```bash
   SUBTYPE=$(jq -r .subtype /tmp/classifier.json)
   if [ "$SUBTYPE" != "success" ]; then
     echo "Classifier errored (subtype=$SUBTYPE); writing stub metrics and continuing."
     # Write a stub: "Classifier unavailable for this run." in the classification section.
     # Do NOT block the session.
     CLASSIFIER_FAILED=true
   else
     PAYLOAD=$(jq -r .result /tmp/classifier.json \
       | sed -e 's/^```json$//' -e 's/^```$//' \
       | sed -e '/./,$!d')
   fi
   ```

5. If the payload has `error: classifier-exceeded-budget-or-failed`, treat as `CLASSIFIER_FAILED=true`.

#### Write the classification section

Append (or replace, if it already exists as a `_Not yet run_` placeholder from gameplan) the `## Classification (film-room)` section in `metrics/vX.Y.md`.

- Split into `### Failures` and `### Expected iteration` subsections.
- For each fix in the payload, write:

  ```markdown
  - <fix description>
      primary: <tag> | confidence: <level>
      reasoning: <one to two sentences>
  ```

- If the fix has a secondary tag, add `| secondary: <tag>` after primary.

Update the frontmatter: set `failures`, `iterations`, `fixes_total`, `first_pass_clean`, and add `cost_usd` by summing the classifier's cost (from the `claude -p` envelope's `total_cost_usd` field) into any existing value.

If `CLASSIFIER_FAILED=true`, write this in place of the normal section:

```markdown
## Classification (film-room)

_Classifier unavailable for this run (subtype=<subtype> or error). Metrics for this version are incomplete._
```

Leave the frontmatter's failure/iteration counts absent.

#### Echo summary to user (only if `metrics.show_checks` is `true`)

Print the summary block in the same format as the structural check echo:

```
[film-room] classification for <version> — <N> fixes:

  Failures (where quality leaked):
    · <tag>: <count> (<percent>%)
    ...

  Expected iteration (not failures):
    · <tag>: <count>
    ...

  Top signal: <top failure tag>. Patterns seen:
    - <derived from reasoning fields>

  Written to: metrics/<version>.md
```

If `metrics.show_checks` is `false`, do not echo. The file is still written.

### Step 4.7 — Regenerate `metrics/SUMMARY.md`

Runs after Step 4.6 regardless of whether classification ran. Skip only if `metrics.enabled` is `false`.

1. Read all `metrics/v*.md` and `metrics/bootstrap.md` files (if present). Parse each file's frontmatter.

2. Sort by version descending (bootstrap sorts last).

3. Regenerate `metrics/SUMMARY.md` with this structure (exact formatting):

   ````markdown
   # Playbook Metrics

   | Version | First-pass | Fixes | Top failure       | Cost   | Date       |
   |---------|-----------:|------:|-------------------|-------:|------------|
   | <rows — one per metrics file>                                                   |

   ## Current top failure modes (last 3 versions)

   <numbered list — sum of failure counts across the 3 most recent versions, ranked desc, with `(N fixes, M% of failures)` per line>

   ## Trends

   <one line per failure tag that appears in at least 2 of the last 3 versions, showing `tag: N → N → N (direction-label)`>
   ````

   Direction labels for the trends section:
   - **improving** — strictly decreasing across the window.
   - **not improving** — flat or increasing with a nonzero final value.
   - **steady** — same value in each window position.
   - **noisy** — no clear monotonic trend (mixed direction).

   "First-pass" column renders as `first_pass_clean / issues` as a percentage rounded to the nearest whole percent.

   "Top failure" is the highest-count key in each version's `failures` dict. If `failures` is empty or missing, write `—`.

4. Commit both files:

   ```bash
   git add metrics/<version>.md metrics/SUMMARY.md
   git commit -m "chore: record metrics for <version>"
   ```

   This is a separate commit on `main` after the merge has landed (Step 4 already merged).

### Step 5 — Clean up

1. Delete the fix branch:
   ```bash
   git branch -D film-room/vX.Y
   git push origin --delete film-room/vX.Y
   ```

2. Close the tracking issue with a summary comment:
   ```bash
   gh issue close <issue_number> --repo <repo> --comment "$(cat <<'EOF'
   Film room session complete.
   Fixed N items. Changes merged to <version_branch> via [PR #N / direct merge].
   EOF
   )"
   ```

3. Present a final summary to the user:
   > **Film room complete for vX.Y.**
   >
   > - **Fixes applied:** N
   > - **Files changed:** [count]
   > - **Merged to:** `ai/dev-vX.Y` via [PR / direct merge]
   > - **Tracking issue:** #N (closed)

## Red Flags

These thoughts mean STOP — you're about to skip a gate:

| Thought | Reality |
|---------|---------|
| "I'll start fixing before setup is done" | Complete Phase 1 first. The tracking issue is the record. |
| "This fix is small, no need to add it to the checklist" | Every fix goes on the checklist. The issue is the audit trail. |
| "I'll batch these checklist updates" | Update the issue after each fix. Stale checklists defeat the purpose. |
| "The user said wrap up but there are unchecked items" | Ask about them. Don't silently close incomplete work. |
| "This needs a redesign, I'll do it in film room" | Film room is for fixes. Redesigns go to gameplan as new issues. |
| "I'll merge without asking which strategy" | Always offer the choice. The user may want to review the diff. |

## Common Mistakes

- **Forgetting to push the fix branch** — Push after each fix. The branch
  should always be backed up on the remote.
- **Not updating the issue body** — The GitHub issue is the persistent record.
  Conversation context is ephemeral. Keep the issue in sync.
- **Scope creep** — A film room session is for fixing what the agents built,
  not for adding new features. If something needs new work, suggest a gameplan
  issue.
- **Merging to main instead of the version branch** — The fix branch targets
  the version branch (`ai/dev-vX.Y`), never `main`. The version branch gets
  merged to main separately.
- **Leaving stale branches** — Always clean up `film-room/vX.Y` in Step 5,
  both local and remote.
- **Closing the issue without a summary** — The close comment is the record
  of what happened. Always include the fix count and merge method.
- **Skipping the distillers** — Step 4.5 runs both distillers automatically
  unless `learning.enabled: false`. Do not skip them to "save time" —
  every skipped session is signal lost forever (no backfill in v1).
