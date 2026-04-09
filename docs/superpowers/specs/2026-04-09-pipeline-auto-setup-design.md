# Pipeline Auto-Setup Design

**Date:** 2026-04-09
**Status:** Draft

## Purpose

Eliminate manual setup steps when starting a new project with playbook.
Currently, users must manually create `playbook.yaml`, a GitHub Project (V2),
configure status fields, and find the `status_field_id`. This change makes
scout and gameplan handle all of that automatically.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Who creates `playbook.yaml` | Scout (Phase 1) | Scout is the pipeline entry point; config should exist before GDD |
| Who creates the GitHub Project | Gameplan (Phase 1) | Gameplan is the first skill that needs the project board |
| Repo detection | `git remote get-url origin`, confirmed by user | Auto-detect with human gate |
| No-repo handling | Stop with prereq message | Repo provisioning has too many user-specific choices to automate |
| Project name | Derived from repo name, confirmed by user | Consistent with "you propose, they approve" pattern |
| Project linking | `gh project link` to default repo | Issues created in the repo auto-associate with the project |

## Change 1: Scout — Create `playbook.yaml` if missing

### Where

`skills/scout/SKILL.md`, Phase 1 — new Step 0 before existing Step 1.

### Prerequisite Check

Before anything else, verify the environment:

1. Check if CWD is a git repo: `git rev-parse --git-dir`
2. Check if a remote exists: `git remote get-url origin`
3. If either fails, stop with:

> **Prerequisites for Playbook:**
> 1. A local git repo with a GitHub remote (`git remote -v` to check)
> 2. A GitHub repository (create one with `gh repo create` if needed)
>
> Once your repo and remote are ready, run `/playbook:scout` again.

### Config Creation

If prerequisites pass but no `playbook.yaml` exists:

1. Parse repo from remote URL:
   - `git@github.com:BryGo1995/my-new-game.git` → `BryGo1995/my-new-game`
   - `https://github.com/BryGo1995/my-new-game.git` → `BryGo1995/my-new-game`
2. Confirm with user:
   > "No `playbook.yaml` found. I'll create one for this project.
   > Repo detected as **BryGo1995/my-new-game** — is that right?"
3. Create `playbook.yaml`:
   ```yaml
   repo: BryGo1995/my-new-game
   ```
4. Commit:
   ```bash
   git add playbook.yaml
   git commit -m "chore: initialize playbook.yaml"
   ```
5. Continue to existing Phase 1 Step 1 (GDD/PRD check).

### Flow Diagram Update

The scout flow diagram needs a new entry node before the existing
"Phase 1: Setup & Context Gathering":

```
"Prereqs met?" → yes → "playbook.yaml exists?" → yes → existing Phase 1
                                                 → no  → create config → existing Phase 1
                → no  → stop with prereq message
```

## Change 2: Gameplan — Create GitHub Project if missing

### Where

`skills/gameplan/SKILL.md`, Phase 1 — new Step 1b between existing Step 1
(read config) and Step 2 (read GDD/PRD).

### Detection

After reading `playbook.yaml`, check if `project.number` and
`status_field_id` are present. If either is missing, the project board hasn't
been set up yet.

### Project Creation Flow

1. Derive project name from repo:
   `BryGo1995/my-new-game` → `My New Game`
   (split on `/`, take repo name, replace `-` with spaces, title case)

2. Confirm with user:
   > "No GitHub Project board configured for this repo. I'll create one to
   > track agent work.
   >
   > Project name: **My New Game** — want to change it?"

3. Create the project:
   ```bash
   gh project create --owner <owner> --title "<project name>" --format json
   ```
   Extract the project number from the response.

4. Link the repo to the project:
   ```bash
   gh project link <project_number> --owner <owner> --repo <owner>/<repo>
   ```

5. Get the project ID and Status field ID via GraphQL:
   ```bash
   gh api graphql -f query='
     query($owner: String!, $number: Int!) {
       user(login: $owner) {
         projectV2(number: $number) {
           id
           field(name: "Status") {
             ... on ProjectV2SingleSelectField {
               id
             }
           }
         }
       }
     }
   ' -f owner="<owner>" -F number=<project_number>
   ```
   Extract `project_id` and `status_field_id`.

6. Add status options. For each status in `defaults.yaml` (`Backlog`,
   `ai-ready`, `ai-in-progress`, `ai-testing`, `ai-review`, `ai-complete`,
   `ai-blocked`, `ai-error`, `Done`):
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
   ' -f projectId="<project_id>" -f fieldId="<status_field_id>" -f name="<status>"
   ```

   Note: New GitHub Projects come with default statuses (`Todo`, `In Progress`,
   `Done`). The `Done` status already exists so it should be skipped.
   `Todo` and `In Progress` should be removed after adding the playbook
   statuses, since they're not used by the orchestrator. Deletion mutation:
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
   ' -f projectId="<project_id>" -f fieldId="<status_field_id>" -f optionId="<option_id>"
   ```

7. Update `playbook.yaml`:
   ```yaml
   repo: BryGo1995/my-new-game
   project:
     owner: BryGo1995
     number: 3
     status_field_id: "PVTSSF_lAHOAmiy..."
   ```

8. Commit:
   ```bash
   git add playbook.yaml
   git commit -m "chore: configure GitHub Project board"
   ```

9. Continue to existing Step 2 (Read GDD/PRD).

### Flow Diagram Update

The gameplan flow diagram needs a new decision node after
"Phase 1: Context Gathering":

```
"Phase 1: Context Gathering" → "Project board configured?" 
  → yes → existing Step 2 (Read GDD/PRD)
  → no  → "Create project & statuses" → existing Step 2
```

## Out of Scope

- **Repo creation** — too many user-specific choices (public/private, org vs
  personal, license, .gitignore). User handles this manually.
- **Organization-owned projects** — the GraphQL queries use `user(login:)`.
  Org-owned projects use `organization(login:)`. Supporting both adds
  complexity for a minority case. Can be added later.
- **Custom status names** — statuses come from `defaults.yaml`. Per-project
  overrides in `playbook.yaml` could be added later but aren't needed now.
