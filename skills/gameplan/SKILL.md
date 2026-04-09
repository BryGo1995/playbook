---
name: playbook:gameplan
description: >
  Use when the user wants to plan the next version of a project managed by the
  playbook orchestrator, create agent-ready issues from a GDD/PRD, or says
  "let's plan the next version", "plan version", "create issues for the next
  version", or references version planning for orchestrated agent work.
---

# Plan Version — Playbook Orchestrator

## Overview

Act as a lead engineer running a version planning session. Read the GDD/PRD,
analyze the current repo state, propose the next version's scope, and create
conflict-free issues on the GitHub project board that coding, testing, and
review agents can execute independently.

The user is the product owner. You propose, they approve. Nothing hits the
board without their explicit go-ahead.

## Flow

```dot
digraph plan_version {
    "Phase 1:\nContext Gathering" [shape=box];
    "Project board\nconfigured?" [shape=diamond];
    "Create project\n& statuses" [shape=box];
    "Phase 2:\nVersion Proposal" [shape=box];
    "Bootstrap\nneeded?" [shape=diamond];
    "User confirms\npriority?" [shape=diamond];
    "GDD changes\nneeded?" [shape=diamond];
    "Phase 3:\nGDD Updates" [shape=box];
    "Phase 4:\nIssue Decomposition" [shape=box];
    "User approves\nissues?" [shape=diamond];
    "Phase 5:\nIssue Creation" [shape=box];
    "Done" [shape=doublecircle];

    "Phase 1:\nContext Gathering" -> "Project board\nconfigured?";
    "Project board\nconfigured?" -> "Create project\n& statuses" [label="no"];
    "Project board\nconfigured?" -> "Phase 2:\nVersion Proposal" [label="yes"];
    "Create project\n& statuses" -> "Phase 2:\nVersion Proposal";
    "Phase 2:\nVersion Proposal" -> "Bootstrap\nneeded?" [label="fresh project"];
    "Bootstrap\nneeded?" -> "Phase 4:\nIssue Decomposition" [label="yes, bootstrap"];
    "Phase 2:\nVersion Proposal" -> "User confirms\npriority?" [label="existing project"];
    "User confirms\npriority?" -> "Phase 2:\nVersion Proposal" [label="adjust"];
    "User confirms\npriority?" -> "GDD changes\nneeded?" [label="confirmed"];
    "GDD changes\nneeded?" -> "Phase 3:\nGDD Updates" [label="yes"];
    "GDD changes\nneeded?" -> "Phase 4:\nIssue Decomposition" [label="no"];
    "Phase 3:\nGDD Updates" -> "Phase 4:\nIssue Decomposition";
    "Phase 4:\nIssue Decomposition" -> "User approves\nissues?";
    "User approves\nissues?" -> "Phase 4:\nIssue Decomposition" [label="adjust"];
    "User approves\nissues?" -> "Phase 5:\nIssue Creation" [label="approved"];
    "Phase 5:\nIssue Creation" -> "Done";
}
```

## Phase 1 — Context Gathering

Gather all context automatically. Do not ask the user anything in this phase.

1. **Read playbook config** — Read `playbook.yaml` in the current working
   directory. If not found, stop and tell the user:
   > "No `playbook.yaml` found in the current directory. Run
   > `/playbook:scout` first to create your GDD/PRD and initialize the
   > config."

   Extract:
   - `repo` — the GitHub repo identifier (e.g., `BryGo1995/paint-ballas-auto`)
   - `gdd_path` (or default to `docs/*-gdd.md` glob if not set)
   - `project.owner` and `project.number` — for GitHub project board queries
   - `concurrency.max_coding` — determines conflict avoidance rigor
   - `versioning` settings
   - `orchestrator_dir` — path to the playbook orchestrator repo (optional,
     used for auto-registration in Phase 5)

1b. **Check project board config** — After reading `playbook.yaml`, check if
    `project.number` and `project.status_field_id` are present. If either is
    missing, the GitHub Project hasn't been set up yet.

    **If project board is not configured:**

    a. Derive a project name from the repo:
       `BryGo1995/my-new-game` → `My New Game`
       (split on `/`, take the repo name, replace `-` with spaces, title case)

    b. Confirm with the user:
       > "No GitHub Project board configured for this repo. I'll create one
       > to track agent work.
       >
       > Project name: **My New Game** — want to change it?"

       Wait for confirmation. If the user provides a different name, use it.

    c. Create the project and link the repo:
       ```bash
       gh project create --owner <owner> --title "<project name>" --format json
       ```
       Extract the project number from the JSON response.

       ```bash
       gh project link <project_number> --owner <owner> --repo <owner>/<repo>
       ```

    d. Get the project ID and Status field ID via GraphQL:
       ```bash
       gh api graphql -f query='
         query($owner: String!, $number: Int!) {
           user(login: $owner) {
             projectV2(number: $number) {
               id
               field(name: "Status") {
                 ... on ProjectV2SingleSelectField {
                   id
                   options {
                     id
                     name
                   }
                 }
               }
             }
           }
         }
       ' -f owner="<owner>" -F number=<project_number>
       ```
       Extract `project_id`, `status_field_id`, and the list of existing
       status options (new projects come with `Todo`, `In Progress`, `Done`).

    e. Add playbook status options. For each status that doesn't already exist
       (`Backlog`, `ai-ready`, `ai-in-progress`, `ai-testing`, `ai-review`,
       `ai-complete`, `ai-blocked`, `ai-error`, `Done`), create it:
       ```bash
       gh api graphql -f query='
         mutation($projectId: ID!, $fieldId: ID!, $name: String!) {
           createProjectV2FieldOption(input: {
             projectId: $projectId
             fieldId: $fieldId
             name: $name
           }) {
             projectV2Field {
               ... on ProjectV2SingleSelectField {
                 options { id name }
               }
             }
           }
         }
       ' -f projectId="<project_id>" -f fieldId="<status_field_id>" \
         -f name="<status_name>"
       ```

       Skip `Done` — it already exists on new projects.

    f. Remove default statuses that playbook doesn't use. Delete `Todo` and
       `In Progress`:
       ```bash
       gh api graphql -f query='
         mutation($projectId: ID!, $fieldId: ID!, $optionId: String!) {
           deleteProjectV2FieldOption(input: {
             projectId: $projectId
             fieldId: $fieldId
             optionId: $optionId
           }) {
             projectV2Field {
               ... on ProjectV2SingleSelectField {
                 options { id name }
               }
             }
           }
         }
       ' -f projectId="<project_id>" -f fieldId="<status_field_id>" \
         -f optionId="<option_id>"
       ```

       Use the option IDs retrieved in step (d) to identify `Todo` and
       `In Progress`.

    g. Update `playbook.yaml` with the project config:
       ```yaml
       repo: BryGo1995/my-new-game
       project:
         owner: BryGo1995
         number: 3
         status_field_id: "PVTSSF_lAHOAmiy..."
       ```

       Use the Edit tool to add the `project:` block to the existing
       `playbook.yaml`. Do not overwrite other fields (like `repo` and
       `gdd_path` which scout already set).

    h. Set up the integration PR workflow. Check if
       `.github/workflows/integration-pr.yml` exists in the project repo.
       If not, create it from the caller template at
       `templates/integration-pr-caller.yml` in the orchestrator repo
       (at `orchestrator_dir` from `playbook.yaml`, if set). If
       `orchestrator_dir` is not set, write the file directly:
       ```yaml
       name: Integration PR

       on:
         push:
           branches: [ai/dev-*]

       permissions:
         contents: read
         pull-requests: write
         issues: read

       jobs:
         integration-pr:
           uses: BryGo1995/playbook/.github/workflows/integration-pr.yml@main
           with:
             integration_branch: ${{ github.ref_name }}
             base_branch: main
       ```

    i. Configure repo settings for the orchestrator workflow:
       ```bash
       # Allow GitHub Actions to create pull requests
       gh api repos/<owner>/<repo>/actions/permissions/workflow -X PUT \
         --input - <<'EOF'
       {"default_workflow_permissions": "write", "can_approve_pull_request_reviews": true}
       EOF

       # Auto-delete head branches after PR merge
       gh api repos/<owner>/<repo> -X PATCH --input - <<'EOF'
       {"delete_branch_on_merge": true}
       EOF
       ```

    j. Commit:
       ```bash
       git add playbook.yaml .github/workflows/integration-pr.yml
       git commit -m "chore: configure GitHub Project board and integration workflow"
       ```

    k. Confirm to the user:
       > "GitHub Project **My New Game** created and configured with playbook
       > statuses. Integration PR workflow installed. Continuing with version
       > planning."

    **If project board is already configured:** Skip this step and continue
    to Step 2 (Read the GDD/PRD).

2. **Read the GDD/PRD** — Read the file at `gdd_path` in the current working
   directory. Extract the roadmap/milestone table to understand version progression.

3. **Scan repo state** — In the current working directory:
   - List the file tree to understand what has been built
   - Run `git log --oneline -20` to see recent work
   - Identify which GDD milestones are already implemented based on existing files

4. **Query project board** — Using `gh` CLI:
   ```bash
   gh project item-list <project_number> --owner <owner> --format json
   ```
   - List all existing issues and their statuses
   - Identify which versions exist and which are complete (all issues "Done")
   - Determine the next logical version number

5. **Summarize findings internally** — Build a mental model of:
   - What the GDD says should be built for the next version
   - What already exists in the repo
   - What the next version number should be

6. **Check if bootstrap is needed** — Bootstrap is needed when ALL of these
   are true:
   - The project board has no existing issues (empty board)
   - The repo has no meaningful source code (only `playbook.yaml`, GDD/PRD,
     docs, and config files — no application code)
   - No `[bootstrap]` issue exists on the board (not even a completed one)

   If all three conditions are met, flag this as a bootstrap-needed project.
   If any condition is false, proceed with normal version planning.

## Phase 2 — Version Proposal

### If bootstrap is needed

Present a bootstrap proposal instead of the normal version proposal:

> "This is a fresh project — no versions on the board and no existing code.
> I recommend starting with a **[bootstrap]** issue to set up the project
> skeleton before versioned feature work.
>
> Based on the GDD, bootstrap would set up:
> - [tech stack / framework / engine setup from GDD]
> - [folder structure derived from GDD architecture sections]
> - [base config files from GDD technical requirements]
> - [entry point / main scene / app shell from GDD]
>
> **Want to start with bootstrap, or jump straight to v0.1?**"

Wait for the user's response.

- If bootstrap: Skip Phase 3 (the GDD was just written by scout — no updates
  needed yet). Proceed to Phase 4 with bootstrap mode.
- If skip to v0.1: Proceed with the normal version proposal below.

### Normal version proposal (no bootstrap needed, or user skipped bootstrap)

Present your findings to the user and get confirmation.

**Present (adapt to context, don't use verbatim):**

> Based on the project board, versions through [vX.Y] are complete. The next
> version is **[vX.Z]**.
>
> The GDD roadmap says [vX.Z] covers: **[milestone description from GDD]**.
>
> Here's what already exists in the repo: [brief summary of relevant files/features].
>
> Here's what would need to be built: [brief summary of the gap].
>
> **Does this priority look right, or would you like to adjust the scope?**
>
> **Also — are there any changes or additions to the GDD before we proceed?**

Wait for the user's response. If they adjust priority, update your plan. If they
want GDD changes, proceed to Phase 3. If everything is confirmed and no GDD
changes are needed, skip to Phase 4.

## Phase 3 — GDD Updates

If the user wants to adjust the GDD before proceeding:

1. Discuss the changes with the user — understand what they want added, removed, or clarified
2. Apply the changes directly to the GDD file using the Edit tool
3. Show the user the diff of what changed
4. Commit the updated GDD:
   ```bash
   git add <gdd_path>
   git commit -m "docs: update GDD for [vX.Y] planning"
   ```
5. Confirm: "GDD updated and committed. Proceeding with issue decomposition."

The GDD must be up-to-date before creating issues. Issues are derived from the
canonical GDD — never from stale requirements.

## Phase 4 — Issue Decomposition

Decompose the version milestone into individual issues. Read the issue template
from `issue-template.md` in this skill directory for the required structure.

### Bootstrap Mode

If the user chose bootstrap in Phase 2, create a single `[bootstrap]` issue
instead of decomposing into multiple versioned issues.

**Derive the bootstrap scope from the ENTIRE GDD roadmap:**

Bootstrap sets up the skeleton for the whole project, not just the first few
versions. Scan every version in the roadmap to identify all system components
that will eventually exist — even if they don't ship until later versions.

1. Read the **full GDD roadmap** (all versions, not just the next one) to
   identify every system component that will be built:
   - Backend services, APIs, databases
   - Frontend applications (web, mobile, desktop)
   - Game engine projects, scenes, assets pipelines
   - Infrastructure, deployment, CI/CD
   - Shared libraries, SDKs, packages

   If a component appears in any version (even v0.7 or later), the bootstrap
   skeleton must account for it. The folder structure should have a home for
   every major component from day one.

2. Read the GDD's technology/platform sections to identify:
   - Language, framework, or engine for each component
   - Dependencies and package manager
   - Build tooling and monorepo structure (if applicable)

3. For each identified technology, use **industry-standard folder structures
   and conventions**:
   - Next.js → `app/`, `components/`, `lib/`, `public/`, etc.
   - Godot → `scenes/`, `scripts/`, `assets/`, `shaders/`, etc.
   - Python/FastAPI → `src/`, `tests/`, `alembic/`, etc.
   - React Native → follow Expo or bare workflow conventions
   - Monorepos → `packages/` or `apps/` with shared config at root

   Do not invent custom structures. Follow what the community and official
   docs recommend for each framework/engine. If unsure, state the convention
   you're following and why.

4. Read the GDD's entry point / starting state to identify:
   - The minimal runnable artifact (main scene, app shell, CLI entry point)
   - What "hello world" looks like for this project

**Compose a single issue using the template from `issue-template.md`:**

- **Title:** `[bootstrap] Project skeleton setup`
- **Overview:** Sets up the full project skeleton from an empty repo to a
  working runnable state.
- **Acceptance criteria:**
  - [ ] All dependencies install cleanly
  - [ ] Folder structure matches GDD architecture
  - [ ] Entry point runs and produces minimal output
  - [ ] Base configuration files are in place
- **Scope:** List all files and directories to be created. Include directories
  for components that won't be built until later versions — the skeleton
  should accommodate the full roadmap.
- **Dependencies:** None — this is the first issue.
- **Testing criteria:**
  - [ ] Project builds/compiles without errors
  - [ ] Entry point executes and produces expected minimal output
  - [ ] All configuration files are valid
- **Review criteria:**
  - [ ] Folder structure accounts for all system components across the full
    GDD roadmap, not just the first version
  - [ ] Each technology component follows its industry-standard folder
    conventions (e.g., Next.js uses `app/`, Godot uses `scenes/`)
  - [ ] Tech stack matches GDD technology section
  - [ ] No placeholder or stub files — everything created should be
    functional
- **Definition of Done:** The project runs, produces minimal output, and the
  folder structure follows industry conventions and accommodates every system
  component in the GDD roadmap.

Present the bootstrap issue to the user for approval, then proceed to
Phase 5 (Issue Creation).

**Do not apply the decomposition rules below** — they are for multi-issue
versioned work. Bootstrap is always a single issue.

### Decomposition Rules

1. **Each issue must be independently executable** — A coding agent should be able
   to complete the issue without waiting for another issue in the same version to
   finish first.

2. **Scope files explicitly** — For each issue, identify exactly which files will
   be created or modified. Include orientation context (what exists, what changes).

3. **Conflict avoidance** — Adapt based on `max_coding` from config:

   **When `max_coding == 1` (default, recommended for game dev):**
   - Issues run sequentially. No file conflict risk.
   - Focus on clean scoping and logical ordering.
   - The orchestrator pipelines work (while issue #1 is in testing, issue #2 starts coding).

   **When `max_coding > 1`:**
   - No two issues may modify the same file.
   - Scene files (`.tscn`, `.tres`) and project configs are atomic — one owner only.
   - For scripts: no overlapping modifications. Two issues may import/read a shared
     file, but only one may modify it.
   - If parallelism doesn't decompose cleanly, say so. Recommend `max_coding: 1`
     for that version rather than force-fitting.

4. **Explain your reasoning** — When presenting issues, explain why they won't
   conflict and how you drew the boundaries. The user doesn't need raw file-overlap
   analysis, but they need to understand and trust your decomposition logic.

### Presenting Issues

Present each issue as a summary first (title + 2-3 sentence description + key files).
Don't dump the full template yet — let the user review the decomposition first.

Example format:

> **Issue 1: `[v0.3] Implement FOV cone rendering`**
> Creates the vision cone system as a standalone node. New files:
> `scripts/fov_controller.gd`, `shaders/fov_mask.gdshader`.
> No modifications to existing files.
>
> **Issue 2: `[v0.3] Integrate FOV with coverage system`**
> Connects the FOV controller to the existing coverage tracker via signals.
> Modifies: `scripts/player.gd` (add FOV node reference).
> Creates: `scripts/fov_integration.gd`.

After the user reviews and approves the decomposition, expand each issue into the
full template from `issue-template.md`.

**Open the floor for discussion.** The user may want to:
- Split an issue that's too large
- Merge issues that are too granular
- Reorder priority within the version
- Adjust scope (defer something to the next version)
- Add notes or caveats to specific issues

Iterate until the user says the issue set is approved.

## Phase 5 — Issue Creation

Once the user approves the full issue set:

1. **Create each issue** on GitHub using `gh`:
   ```bash
   gh issue create \
     --repo <owner/repo> \
     --title "[vX.Y] Issue title" \
     --body "$(cat <<'EOF'
   <full issue body from template>
   EOF
   )"
   ```

2. **Add each issue to the project board** and set status to "ai-ready":
   ```bash
   # Get the issue URL
   gh issue view <number> --repo <owner/repo> --json url -q '.url'

   # Add to project
   gh project item-add <project_number> --owner <owner> --url <issue_url>

   # Set status to ai-ready using the project's status field
   gh project item-edit --project-id <project_id> --id <item_id> \
     --field-id <status_field_id> --single-select-option-id <ai_ready_option_id>
   ```

3. **Confirm creation** — List all created issues with their numbers and links:
   > Created 3 issues for [v0.3]:
   > - #15: [v0.3] Implement FOV cone rendering
   > - #16: [v0.3] Integrate FOV with coverage system
   > - #17: [v0.3] Add FOV visual overlay shader
   >
   > All set to "ai-ready". The orchestrator will pick them up on the next cycle.

4. **Register with orchestrator** — Check if `orchestrator_dir` is set in
   `playbook.yaml`. If it is:

   a. Read `run-all.sh` in that directory.
   b. Check if the current project directory is already in the `PROJECTS`
      array.
   c. If not, add it:
      - Find the `PROJECTS=(` block in `run-all.sh`
      - Append the current working directory as a new entry before the
        closing `)`
      - Example — adding `/home/user/projects/snowie`:
        ```bash
        PROJECTS=(
            "/home/user/projects/paint-ballas"
            "/home/user/projects/snowie"
        )
        ```
   d. Commit the change:
      ```bash
      cd <orchestrator_dir>
      git add run-all.sh
      git commit -m "feat: register <project-name> with orchestrator"
      git push origin main
      cd <project_dir>
      ```
   e. Confirm to the user:
      > "Registered this project with the orchestrator at
      > `<orchestrator_dir>`. It will be included in the next orchestrator
      > run."

   If `orchestrator_dir` is not set in `playbook.yaml`, skip this step and
   tell the user:
   > "To have the orchestrator automatically pick up these issues, add
   > `orchestrator_dir: /path/to/playbook` to your `playbook.yaml` and
   > add this project directory to `run-all.sh`."

## Red Flags

These thoughts mean STOP — you're about to skip a gate:

| Thought | Reality |
|---------|---------|
| "The user will probably approve this" | Ask. Every gate exists for a reason. |
| "The GDD is clear enough" | Ask if changes are needed. The user knows context you don't. |
| "These issues won't conflict" | Explain your reasoning. Let the user verify. |
| "I'll create the issues and they can adjust later" | Issues on the board get dispatched. Get approval first. |
| "This is just one small issue, no need for the full template" | Every issue goes through the full template. Agents need the context. |
| "The testing/review criteria are obvious" | Obvious to you ≠ obvious to a testing agent with no prior context. |

## Common Mistakes

- **Vague acceptance criteria** — "Implement the FOV system" is not a criterion. "Player's vision cone narrows from 360 to 30 degrees proportional to coverage %" is.
- **Missing testing criteria** — The testing agent can only validate what you specify. Be explicit about expected behaviors, edge cases, and inputs/outputs.
- **Skipping the GDD update step** — If requirements are ambiguous, update the GDD first. Don't create issues from ambiguous requirements.
- **Over-decomposing** — 3-5 issues per version is typical. More than 7 is a red flag that the version scope is too large.
- **Under-specifying file scope** — "Modify player.gd" is insufficient. "Modify `scripts/player.gd` — add `$FOVController` node reference and connect `coverage_changed` signal" tells the agent exactly what to do.
- **Forgetting dependencies** — Each issue must state what prior work it assumes exists. An agent working on v0.3 needs to know what v0.2 built.
