# Agent Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire two distillers into the film-room wrap-up so each session produces (a) a CLAUDE.md PR against the project repo with project-scoped lessons, and (b) a playbook-repo PR with either an agent prompt edit (high bar) or an observation-log entry (low bar).

**Architecture:** Both distillers are `claude -p` invocations launched from `skills/film-room/SKILL.md` between the merge step and cleanup. They consume the tracking issue, the film-room branch commits, and the original agent PRs/issues. Distiller behavior lives in two markdown prompt files under `skills/film-room/distillers/`. A new `learning` block in `defaults.yaml` (with corresponding loader behavior in `config.py` — already covered by `_deep_merge`) toggles the feature. No runtime changes to `orchestrator.py` or `agents/*.py` — those files only change via the PRs the agent-craft distiller opens, which the human merges.

**Tech Stack:** Python 3 (config + tests via pytest), Bash (distiller invocation in skill), `claude -p` CLI (distiller execution), `gh` CLI (PR creation), `git` (data gathering), Markdown (skill + prompt files).

---

## File Structure

**Created:**
- `skills/film-room/distillers/project-distiller.md` — prompt that classifies fixes and produces a CLAUDE.md patch + PR body for the project repo.
- `skills/film-room/distillers/agent-craft-distiller.md` — prompt that decides between agent-prompt-edit PR and observation-log entry, then produces the appropriate patch + PR body for the playbook repo.
- `docs/agent-craft-observations.md` — created lazily on the first observation entry; this plan only seeds the file with a header.
- `tests/test_learning_config.py` — verifies defaults and merge behavior for the `learning` block.

**Modified:**
- `defaults.yaml` — adds the `learning` config block.
- `skills/film-room/SKILL.md` — adds Step 4.5 ("Run distillers") in Phase 2 between Step 4 (merge) and Step 5 (cleanup); skipped when learning is disabled or the fix branch had zero commits.

**Untouched (intentionally):**
- `orchestrator.py`, `agents/*.py` — they do not run the distillers and do not change runtime behavior. The agent-craft distiller proposes edits to `agents/*.py` via PR; the human merges.
- `config.py` — `_deep_merge` already handles new top-level keys.

---

## Task 1: Add `learning` config block to defaults

**Files:**
- Modify: `defaults.yaml`
- Create: `tests/test_learning_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_learning_config.py` with this exact content:

```python
# tests/test_learning_config.py
from config import load_config


def test_defaults_provide_learning_block(tmp_path):
    """defaults.yaml ships a learning block enabled by default."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("repo: owner/repo\n")

    cfg = load_config(project_dir=str(project_dir))

    assert cfg["learning"]["enabled"] is True
    assert cfg["learning"]["project_distiller"] is True
    assert cfg["learning"]["agent_craft_distiller"] is True
    assert cfg["learning"]["playbook_repo"] == "BryGo1995/playbook"


def test_project_can_disable_learning(tmp_path):
    """playbook.yaml override can disable the whole feature."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text(
        "repo: owner/repo\n"
        "learning:\n"
        "  enabled: false\n"
    )

    cfg = load_config(project_dir=str(project_dir))

    assert cfg["learning"]["enabled"] is False
    # other learning fields still inherit from defaults
    assert cfg["learning"]["project_distiller"] is True


def test_project_can_disable_one_distiller(tmp_path):
    """Distillers can be toggled independently."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text(
        "repo: owner/repo\n"
        "learning:\n"
        "  agent_craft_distiller: false\n"
    )

    cfg = load_config(project_dir=str(project_dir))

    assert cfg["learning"]["enabled"] is True
    assert cfg["learning"]["project_distiller"] is True
    assert cfg["learning"]["agent_craft_distiller"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/bryang/Dev_Space/playbook && pytest tests/test_learning_config.py -v`
Expected: 3 failures with `KeyError: 'learning'` (the block does not exist yet in `defaults.yaml`).

- [ ] **Step 3: Add the `learning` block to `defaults.yaml`**

Append this to the end of `defaults.yaml`:

```yaml

learning:
  enabled: true
  project_distiller: true
  agent_craft_distiller: true
  playbook_repo: "BryGo1995/playbook"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /home/bryang/Dev_Space/playbook && pytest tests/test_learning_config.py -v`
Expected: 3 passing tests.

- [ ] **Step 5: Run the full test suite**

Run: `cd /home/bryang/Dev_Space/playbook && pytest -q`
Expected: all tests pass. (Confirms no regression in existing config tests.)

- [ ] **Step 6: Commit**

```bash
cd /home/bryang/Dev_Space/playbook
git add defaults.yaml tests/test_learning_config.py
git commit -m "feat: add learning config block with default toggles

Toggles the agent learning loop on by default. Both distillers can be
disabled independently via playbook.yaml. Playbook repo defaults to
BryGo1995/playbook, where agent-craft PRs land."
```

---

## Task 2: Create the project distiller prompt

**Files:**
- Create: `skills/film-room/distillers/project-distiller.md`

- [ ] **Step 1: Create the directory**

```bash
cd /home/bryang/Dev_Space/playbook
mkdir -p skills/film-room/distillers
```

- [ ] **Step 2: Write the prompt file**

Create `skills/film-room/distillers/project-distiller.md` with this exact content:

````markdown
# Project Distiller

You are the **project distiller** for a Playbook film-room session. Your job:
turn the human-validated fixes from this film-room session into proposed
additions to the project repo's `CLAUDE.md`. The result is a PR that the
human will review.

## Inputs (provided in your invocation)

- **Tracking issue body** — the human-written checklist of fixes for version
  vX.Y, with each item describing one fix.
- **Fix commits** — the output of
  `git log origin/<version_branch>..film-room/vX.Y --patch` from the project
  repo. One commit per fix, with full diffs.
- **Original agent PRs and issues** — the PRs the coding/review/testing
  agents opened for this version, plus the original issues those PRs were
  built from. This is the "what was the agent asked to do, and what did the
  agent produce" context.
- **Current `CLAUDE.md`** — the contents of the project repo's existing
  `CLAUDE.md`, or empty if none exists.
- **Project repo** — `owner/repo` identifier.
- **Version** — `vX.Y` (or `bootstrap`).

## What you produce

1. A **proposed `CLAUDE.md`** (full file contents, ready to be written to the
   working tree).
2. A **PR body** summarizing the proposal.
3. **Counts** — number of fixes total, number proposed as lessons, number
   skipped as local incidents.

You return all three as a single JSON object on stdout (and only stdout —
no other narration), shaped exactly like:

```json
{
  "claude_md": "...full file contents...",
  "pr_body": "...markdown...",
  "fixes_total": N,
  "lessons_added": N,
  "local_incidents": N
}
```

If you decide there is **nothing worth adding** (every fix is a local
incident, or every candidate lesson is already in `CLAUDE.md`), return:

```json
{
  "claude_md": null,
  "pr_body": null,
  "fixes_total": N,
  "lessons_added": 0,
  "local_incidents": N
}
```

The film-room skill will skip PR creation in that case.

## How to classify each fix

For every fix in the bundle, classify as one of:

- **Convention** — a project-specific pattern agents should follow next
  time. Example: "use `pytest.fixture(scope='session')` for DB fixtures
  here." Add as a lesson.
- **Constraint** — a hard rule that was violated. Example: "never import
  from `legacy/` — it's deprecated." Add as a lesson.
- **Local incident** — a one-off bug fix with no generalizable lesson.
  Skip.

**Conservatism bias.** When in doubt, classify as a **local incident**.
Lesson sprawl is the primary failure mode here. A `CLAUDE.md` that gains
twenty bullets per version becomes noise and the agents stop reading it
carefully. Better to drop a borderline lesson than to add one that creates
noise.

## How to add a lesson

Each lesson is **one bullet, one sentence**. If the *why* is non-obvious,
add a `Why:` tail on the same bullet. Example:

```
- Use `pytest.fixture(scope='session')` for database fixtures.
  Why: the schema setup is expensive and per-test setup blew the suite
  past the 10-minute CI budget. (film-room v0.4, fix #2)
```

Every lesson **ends with a citation**: `(film-room vX.Y, fix #N)` where N
is the fix's position in the tracking issue checklist (1-indexed).

## How to deduplicate

Read the current `CLAUDE.md` carefully. If a lesson you would add is
already present (same rule, different wording — judge by meaning, not text
match), drop it. Do not propose redundant entries.

## How to place lessons in the file

- If `CLAUDE.md` already has a section that matches the topic of a lesson
  (e.g. "Testing", "Imports", "Conventions"), append the lesson at the end
  of that section.
- If no matching section exists, prefer adding the lesson under a generic
  `## Lessons from film-room` section. Create that section at the bottom
  of the file if it does not exist.
- Do not reorganize the existing `CLAUDE.md`. Append-only edits.

## PR body format

The PR body must be a short markdown summary, like:

```markdown
## Lessons from vX.Y film-room

Proposing N lessons captured from the post-agent review of vX.Y. M fixes
were classified as local incidents and skipped.

### Lessons added
- (one line per lesson, citing the fix number)

### Skipped (local incidents)
- (one line per skipped fix, summarizing why it was not generalizable)

Tracking issue: #<issue_number>
```

Replace `<issue_number>` with the tracking issue number provided in the
inputs.

## Hard rules

- Never modify any file other than `CLAUDE.md`.
- Never propose lesson text that names a specific fix author, PR number, or
  contributor — describe the rule, not the incident.
- Never propose a lesson that contradicts something already in `CLAUDE.md`.
  If you find a contradiction, skip the lesson and note it in the PR body
  under a `### Conflicts (not added)` section.
- Output is JSON-only. No surrounding prose.
````

- [ ] **Step 3: Verify the file was written correctly**

Run: `cd /home/bryang/Dev_Space/playbook && wc -l skills/film-room/distillers/project-distiller.md && head -5 skills/film-room/distillers/project-distiller.md`
Expected: file has ~110 lines, starts with `# Project Distiller`.

- [ ] **Step 4: Commit**

```bash
cd /home/bryang/Dev_Space/playbook
git add skills/film-room/distillers/project-distiller.md
git commit -m "feat: project distiller prompt for film-room learning loop

Captures the prompt that classifies film-room fixes into project-scoped
CLAUDE.md lessons. Conservative bias toward dropping borderline lessons
to prevent CLAUDE.md sprawl. Outputs JSON for the skill to consume."
```

---

## Task 3: Create the agent-craft distiller prompt

**Files:**
- Create: `skills/film-room/distillers/agent-craft-distiller.md`

- [ ] **Step 1: Write the prompt file**

Create `skills/film-room/distillers/agent-craft-distiller.md` with this exact content:

````markdown
# Agent-Craft Distiller

You are the **agent-craft distiller** for a Playbook film-room session.
Your job: identify failure modes of the **Playbook agents themselves**
(coding, review, testing) — not project-specific conventions — from the
human-validated fixes in this session. Decide whether to propose a prompt
edit (high bar) or to log an observation for future pattern-matching (low
bar).

## Inputs (provided in your invocation)

- **Tracking issue body** — checklist of fixes for vX.Y.
- **Fix commits** — `git log origin/<version_branch>..film-room/vX.Y --patch`
  from the project repo, with full diffs.
- **Original agent PRs and issues** — what each agent was asked to do, and
  what each agent produced (pre-fix).
- **Playbook agent prompts** — current contents of `agents/coding.py`,
  `agents/review.py`, `agents/testing.py` from the playbook repo.
- **Existing observations log** — current contents of
  `docs/agent-craft-observations.md` from the playbook repo (or empty).
- **Project film-room issue URL** — link back to the tracking issue, for
  citation.
- **Version** — `vX.Y` (or `bootstrap`).
- **Project repo** — `owner/repo` identifier of the project being reviewed.

## What you produce

A single JSON object on stdout (and only stdout — no other narration):

```json
{
  "mode": "prompt_edit" | "observation" | "skip",
  "target_file": "agents/coding.py" | "agents/review.py" | "agents/testing.py" | "docs/agent-craft-observations.md" | null,
  "patched_file_contents": "...full file contents after the edit, or null for skip...",
  "pr_body": "...markdown, or null for skip...",
  "rationale": "...one paragraph explaining the decision..."
}
```

`mode: "skip"` means this session produced nothing worth recording. The
film-room skill will skip PR creation.

## How to classify

For each fix, ask: **is this a failure mode of an agent (its prompt, its
defaults, its discipline), or is it a project-specific convention?**

**Agent-craft (yes):**
- Coding agent forgets to run tests before opening the PR.
- Review agent rubber-stamps PRs that have no test coverage.
- Testing agent writes assertions on mocks instead of behavior.
- Coding agent merges its own PRs.
- Any agent ignores the file-count guardrail.

**Not agent-craft (these belong to the project distiller):**
- "Use `pytest.fixture(scope='session')` here."
- "This codebase imports from `app.db` not `app.database`."
- "Use the legacy migration runner for schema changes."

If a fix is project-specific, do not propose anything for it — the project
distiller handles those. You only act on agent-craft signals.

## How to choose between `prompt_edit` and `observation`

**`prompt_edit` (high bar) — choose only when both:**

1. You can point to a clear root-cause prompt change in one of
   `agents/coding.py`, `agents/review.py`, `agents/testing.py` that would
   plausibly have prevented the failure, AND
2. **Either** ≥2 fixes in this session exhibit the same agent failure,
   **or** the failure is severe enough that one occurrence justifies a
   guardrail (examples of severe: agent merged its own PR, agent pushed to
   `main`, agent leaked a secret).

When the bar is met, set `mode: "prompt_edit"`, `target_file` to the agent
file you are editing, and `patched_file_contents` to the **full new file
contents** (not a diff). Edit the existing prompt string in-place — keep
the file's structure (`CODING_PROMPT = """..."""`, `ALLOWED_TOOLS`, the
class) intact. Add the new rule as a new numbered instruction at the end
of the existing list, or tighten an existing instruction in place.

**`observation` (low bar) — choose when:**

You see a real agent-craft signal but the bar above is not met (only one
fix, not severe). Append an entry to `docs/agent-craft-observations.md`
recording what you saw, so future sessions can pattern-match across
versions.

When the bar is not met, set `mode: "observation"`, `target_file` to
`docs/agent-craft-observations.md`, and `patched_file_contents` to the
full new file contents (existing log + your new entry appended).

**`skip` — choose when:**

No agent-craft signals in this session. (All fixes were project-specific
conventions or local incidents.) Set `mode: "skip"` and all other fields
to `null` except `rationale`.

## Observation log entry format

Append to `docs/agent-craft-observations.md` using this exact shape:

```markdown
## vX.Y — <project_repo>

**Date:** YYYY-MM-DD
**Source:** <project_film_room_issue_url>

- **Observation:** <one-sentence description of the agent failure>
  - **Agent:** coding | review | testing
  - **Fixes that motivated this:** #N, #M (positions in tracking issue)
  - **Why it's not yet a prompt edit:** <one sentence — usually "single
    occurrence" or "ambiguous root cause">
```

Use today's date (you have it in the inputs). Keep the structure flat —
new sessions append, no nesting beyond the H2.

## PR body format

For `prompt_edit`:

```markdown
## Agent-craft prompt edit from <project_repo> vX.Y film-room

Tightening `<target_file>` based on a recurring failure observed in the
post-agent review of <project_repo> vX.Y.

### What changed
<one short paragraph describing the prompt edit and why it should prevent
the failure>

### Motivating fixes
- (one line per fix, with the project film-room issue link)

### Bar met because
<one sentence — either "≥2 fixes in this session showed the same failure"
with the count, or "single severe occurrence: <description>">
```

For `observation`:

```markdown
## Agent-craft observation from <project_repo> vX.Y film-room

Logging an agent-craft signal that does not yet meet the bar for a prompt
edit. Appended to `docs/agent-craft-observations.md` for future
pattern-matching across versions.

### What was observed
<one short paragraph>

### Why not a prompt edit yet
<one sentence — single occurrence, or ambiguous root cause>

Source: <project_film_room_issue_url>
```

## Hard rules

- Never modify a file other than `agents/coding.py`, `agents/review.py`,
  `agents/testing.py`, or `docs/agent-craft-observations.md`.
- Never delete or reorder existing instructions in an agent prompt — only
  add new ones, or tighten an existing one in place by replacing its
  wording.
- Never propose a prompt edit that mentions a specific project, repo, or
  fix — agent prompts are cross-project, so keep them generic.
- Never propose a prompt edit and an observation in the same run. Choose
  one mode per invocation.
- Output is JSON-only. No surrounding prose.
````

- [ ] **Step 2: Verify the file was written correctly**

Run: `cd /home/bryang/Dev_Space/playbook && wc -l skills/film-room/distillers/agent-craft-distiller.md && head -5 skills/film-room/distillers/agent-craft-distiller.md`
Expected: file has ~150 lines, starts with `# Agent-Craft Distiller`.

- [ ] **Step 3: Commit**

```bash
cd /home/bryang/Dev_Space/playbook
git add skills/film-room/distillers/agent-craft-distiller.md
git commit -m "feat: agent-craft distiller prompt for film-room learning loop

Captures the prompt that decides between an agent prompt edit (high bar:
recurring or severe agent failure) and an observation-log entry (low
bar). Both targets are in the playbook repo. Outputs JSON for the skill
to consume."
```

---

## Task 4: Seed the agent-craft observations log

**Files:**
- Create: `docs/agent-craft-observations.md`

- [ ] **Step 1: Create the file with a header**

Create `docs/agent-craft-observations.md` with this exact content:

```markdown
# Agent-Craft Observations

A running log of agent-craft signals captured by the agent-craft distiller
during film-room sessions. Each entry records a failure mode that did
**not** meet the bar for an immediate prompt edit (single occurrence, not
severe enough to justify a one-shot guardrail, or ambiguous root cause).

When the same observation recurs across multiple versions or projects, a
future film-room session can promote it to an actual prompt edit against
`agents/coding.py`, `agents/review.py`, or `agents/testing.py`.

The distiller appends new entries below this header. Do not reorder.

---
```

- [ ] **Step 2: Commit**

```bash
cd /home/bryang/Dev_Space/playbook
git add docs/agent-craft-observations.md
git commit -m "feat: seed agent-craft observations log

Empty log header. The agent-craft distiller appends entries here when an
observed agent failure does not yet meet the bar for a prompt edit."
```

---

## Task 5: Add Step 4.5 ("Run distillers") to film-room skill

**Files:**
- Modify: `skills/film-room/SKILL.md`

This is the largest task — it adds the runtime instructions that the
film-room skill follows to invoke both distillers. It is one task because
the inserted content is one logical unit (the new step), but it is broken
into small steps for review.

- [ ] **Step 1: Read the current SKILL.md to find the exact insertion point**

Run: `cd /home/bryang/Dev_Space/playbook && grep -n "^### Step 5 — Clean up\|^## Phase 2" skills/film-room/SKILL.md`
Expected: shows lines `239:## Phase 2 — Wrap-up` and `337:### Step 5 — Clean up`. The new step inserts immediately before the line `### Step 5 — Clean up`.

- [ ] **Step 2: Insert the new step**

Use the Edit tool to replace the exact string `### Step 5 — Clean up`
(the H3 heading on its own line) with the following block. Note: the new
step ends with a blank line, then the original `### Step 5 — Clean up`
heading is reinstated at the bottom so it stays in the file.

Old string (this is one line):

```
### Step 5 — Clean up
```

New string (multi-line — copy exactly):

````
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

4. Parse the JSON output:
   ```bash
   jq -r .claude_md /tmp/project-distiller.json
   jq -r .pr_body  /tmp/project-distiller.json
   jq -r .lessons_added /tmp/project-distiller.json
   ```

5. **If `claude_md` is `null` or `lessons_added` is `0`**, tell the user:
   > "Project distiller ran but proposed no lessons (every fix was a local
   > incident or already covered in CLAUDE.md). No PR opened."
   Skip to the agent-craft distiller.

6. **Otherwise**, open a PR against the project repo:
   ```bash
   git checkout -b learning/film-room-vX.Y origin/main
   # Write the new CLAUDE.md from the distiller output:
   jq -r .claude_md /tmp/project-distiller.json > CLAUDE.md
   git add CLAUDE.md
   git commit -m "chore: capture lessons from vX.Y film-room"
   git push -u origin learning/film-room-vX.Y
   gh pr create --repo <repo> \
     --base main \
     --head learning/film-room-vX.Y \
     --title "Lessons from vX.Y film-room" \
     --body "$(jq -r .pr_body /tmp/project-distiller.json)"
   ```
   Tell the user the PR URL.

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

5. Parse the JSON output:
   ```bash
   MODE=$(jq -r .mode /tmp/agent-craft.json)
   TARGET=$(jq -r .target_file /tmp/agent-craft.json)
   ```

6. **If `mode` is `"skip"`**, tell the user:
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
          -f content="$(jq -r .patched_file_contents /tmp/agent-craft.json | base64 -w0)" \
          -f branch="$BRANCH" \
          -f sha="$EXISTING_SHA"
      else
        gh api -X PUT repos/<playbook_repo>/contents/$TARGET \
          -f message="agent-craft: $MODE from <project_repo> vX.Y" \
          -f content="$(jq -r .patched_file_contents /tmp/agent-craft.json | base64 -w0)" \
          -f branch="$BRANCH"
      fi
      ```

   d. Open the PR:
      ```bash
      gh pr create --repo <playbook_repo> \
        --base main \
        --head "$BRANCH" \
        --title "agent-craft: $MODE from <project_repo> vX.Y film-room" \
        --body "$(jq -r .pr_body /tmp/agent-craft.json)"
      ```

   Tell the user the PR URL.

#### Tell the user what happened

Before moving to Step 5, summarize:

> "Distillers complete:
> - Project distiller: <PR link, or 'no lessons proposed'>
> - Agent-craft distiller: <PR link, or 'no signals this session'>"

### Step 5 — Clean up
````

- [ ] **Step 3: Verify the edit**

Run: `cd /home/bryang/Dev_Space/playbook && grep -n "^### Step 4\.5\|^### Step 5 — Clean up" skills/film-room/SKILL.md`
Expected: two lines, `Step 4.5 — Run distillers` appears before `Step 5 — Clean up`, and the original `Step 5 — Clean up` line still exists exactly once.

- [ ] **Step 4: Update the Phase 2 section overview to mention the new step**

Use Edit to replace this exact string:

```
Triggered when the user indicates they are done (e.g., "let's wrap up",
"I'm done", "merge it back").
```

with:

```
Triggered when the user indicates they are done (e.g., "let's wrap up",
"I'm done", "merge it back"). Wrap-up runs the merge, then the learning
distillers (Step 4.5), then cleanup.
```

- [ ] **Step 5: Update the Common Mistakes section**

Use Edit to replace this exact string:

```
- **Closing the issue without a summary** — The close comment is the record
  of what happened. Always include the fix count and merge method.
```

with:

```
- **Closing the issue without a summary** — The close comment is the record
  of what happened. Always include the fix count and merge method.
- **Skipping the distillers** — Step 4.5 runs both distillers automatically
  unless `learning.enabled: false`. Do not skip them to "save time" —
  every skipped session is signal lost forever (no backfill in v1).
```

- [ ] **Step 6: Verify SKILL.md still parses as valid markdown**

Run: `cd /home/bryang/Dev_Space/playbook && wc -l skills/film-room/SKILL.md && grep -c "^### Step" skills/film-room/SKILL.md`
Expected: line count grew (was 391, will now be ~530+); the count of `### Step` headings increased by 1 (now includes Step 4.5).

- [ ] **Step 7: Commit**

```bash
cd /home/bryang/Dev_Space/playbook
git add skills/film-room/SKILL.md
git commit -m "feat: wire learning distillers into film-room wrap-up

Adds Step 4.5 between merge and cleanup. Both distillers run by default,
gated by learning.enabled and per-distiller toggles. Each opens a PR (or
exits cleanly with no PR) — never auto-merges. Project distiller PRs
target the project repo's CLAUDE.md; agent-craft distiller PRs target
the playbook repo's agents/*.py or docs/agent-craft-observations.md."
```

---

## Task 6: Document the loop in the README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Find the right section**

Run: `cd /home/bryang/Dev_Space/playbook && grep -n "^## " README.md`
Expected: shows top-level section headings. Look for a section like "How
It Works" or similar that describes the pipeline. The new content goes at
the end of that section (or as a new section right after it if no good
fit exists).

- [ ] **Step 2: Add a "Learning Loop" subsection to the README**

Append the following block to the end of the "How It Works" section (use
Edit to insert it before the next `## ` heading, or append at end of file
if "How It Works" is the last section):

```markdown
### Learning Loop

Each film-room session ends by running two distillers that turn the
human-validated fixes into proposed improvements:

- **Project distiller** — proposes additions to the project repo's
  `CLAUDE.md` so future agents working on the same repo pick up the
  conventions automatically. Output: a PR against the project repo.
- **Agent-craft distiller** — looks for failure modes of the agents
  themselves (not project conventions) and either proposes a prompt edit
  to `agents/{coding,review,testing}.py` (when ≥2 fixes show the same
  pattern, or one severe occurrence) or appends an entry to
  `docs/agent-craft-observations.md` for future pattern-matching. Output:
  a PR against the playbook repo.

Both distillers always produce PRs — never auto-merges. The human is the
gate. Disable per-project via `playbook.yaml`:

```yaml
learning:
  enabled: true              # set false to disable both distillers
  project_distiller: true
  agent_craft_distiller: true
  playbook_repo: "BryGo1995/playbook"
```
```

- [ ] **Step 3: Commit**

```bash
cd /home/bryang/Dev_Space/playbook
git add README.md
git commit -m "docs: describe the agent learning loop in README"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the full test suite**

Run: `cd /home/bryang/Dev_Space/playbook && pytest -q`
Expected: all tests pass (including the three new `test_learning_config.py` tests).

- [ ] **Step 2: Verify the new files exist and structure**

Run:
```bash
cd /home/bryang/Dev_Space/playbook
ls skills/film-room/distillers/
ls docs/agent-craft-observations.md
grep -c "^### Step" skills/film-room/SKILL.md
grep "learning:" defaults.yaml
```
Expected:
- `distillers/` contains `project-distiller.md` and `agent-craft-distiller.md`.
- `docs/agent-craft-observations.md` exists.
- `SKILL.md` has at least 7 `### Step` headings (was 6, plus the new 4.5).
- `defaults.yaml` contains the line `learning:`.

- [ ] **Step 3: Read back SKILL.md Phase 2 once end-to-end**

Run: `cd /home/bryang/Dev_Space/playbook && sed -n '/^## Phase 2/,/^## Red Flags/p' skills/film-room/SKILL.md`
Expected: the Phase 2 section reads cleanly start to finish, with Step 4
(merge) → Step 4.5 (distillers) → Step 5 (cleanup) in order, and no
duplicated headings.

- [ ] **Step 4: Push the branch and announce completion**

If working on a feature branch:
```bash
cd /home/bryang/Dev_Space/playbook
git push -u origin <current_branch>
```
Tell the operator the loop is wired and the next film-room session will
exercise it end-to-end.

---

## Out of Scope (do not implement)

These were explicitly deferred in the spec. Do not add them in this plan:

- CLAUDE.md gardening / consolidation when the file gets too long.
- Backfill of historical film-room sessions.
- Embedding-based retrieval over lessons.
- Cross-project sharing of project conventions.
- Real-time learning during agent execution.
- Any change to `orchestrator.py` or `agents/*.py` runtime behavior. The
  agent-craft distiller proposes edits to `agents/*.py` via PR; the human
  merges. No code in this plan modifies those files.
