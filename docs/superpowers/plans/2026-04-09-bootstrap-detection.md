# Bootstrap Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make gameplan detect when a project needs bootstrapping and propose a single `[bootstrap]` issue derived from the GDD before versioned feature work begins.

**Architecture:** Modifications to `skills/gameplan/SKILL.md` only — update Phase 1 Step 5 to include bootstrap detection, update Phase 2 to present a bootstrap proposal when detected, and update Phase 4 to handle single-issue bootstrap decomposition.

**Tech Stack:** Markdown skill file

---

## File Structure

```
skills/
  gameplan/
    SKILL.md          # Modify: Phase 1 Step 5, Phase 2, Phase 4
```

---

### Task 1: Update Phase 1 Step 5 — Add bootstrap detection

**Files:**
- Modify: `skills/gameplan/SKILL.md` (Phase 1, Step 5)

- [ ] **Step 1: Read current Phase 1 Step 5**

Read `skills/gameplan/SKILL.md` and locate Phase 1 Step 5 ("Summarize findings internally"). It currently reads:

```markdown
5. **Summarize findings internally** — Build a mental model of:
   - What the GDD says should be built for the next version
   - What already exists in the repo
   - What the next version number should be
```

- [ ] **Step 2: Replace Step 5 with expanded version**

Replace the existing Step 5 with:

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add skills/gameplan/SKILL.md
git commit -m "feat: add bootstrap detection to gameplan Phase 1"
```

---

### Task 2: Update Phase 2 — Add bootstrap proposal

**Files:**
- Modify: `skills/gameplan/SKILL.md` (Phase 2)

- [ ] **Step 1: Read current Phase 2**

Read `skills/gameplan/SKILL.md` and locate Phase 2 ("Version Proposal"). It
currently starts with "Present your findings to the user and get confirmation"
and shows a template for proposing the next version.

- [ ] **Step 2: Insert bootstrap proposal before the existing version proposal**

Insert the following immediately after the `## Phase 2 — Version Proposal`
heading and before the existing "Present your findings" paragraph:

```markdown
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
```

The existing version proposal content ("Present (adapt to context, don't use
verbatim):" and the blockquote template) stays in place, now under the
"Normal version proposal" subheading.

- [ ] **Step 3: Commit**

```bash
git add skills/gameplan/SKILL.md
git commit -m "feat: add bootstrap proposal to gameplan Phase 2"
```

---

### Task 3: Update Phase 4 — Handle bootstrap decomposition

**Files:**
- Modify: `skills/gameplan/SKILL.md` (Phase 4)

- [ ] **Step 1: Read current Phase 4**

Read `skills/gameplan/SKILL.md` and locate Phase 4 ("Issue Decomposition").
It currently starts with "Decompose the version milestone into individual
issues" and includes decomposition rules.

- [ ] **Step 2: Insert bootstrap handling before the decomposition rules**

Insert the following immediately after the Phase 4 heading and intro
paragraph, before the `### Decomposition Rules` subheading:

```markdown
### Bootstrap Mode

If the user chose bootstrap in Phase 2, create a single `[bootstrap]` issue
instead of decomposing into multiple versioned issues.

**Derive the bootstrap scope entirely from the GDD:**

1. Read the GDD's technology/platform sections to identify:
   - Language, framework, or engine
   - Dependencies and package manager
   - Build tooling

2. Read the GDD's architecture sections to identify:
   - Folder structure and directory layout
   - Core modules or components
   - Configuration approach

3. Read the GDD's entry point / starting state to identify:
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
- **Scope:** List all files and directories to be created, derived from the
  GDD architecture.
- **Dependencies:** None — this is the first issue.
- **Testing criteria:**
  - [ ] Project builds/compiles without errors
  - [ ] Entry point executes and produces expected minimal output
  - [ ] All configuration files are valid
- **Review criteria:**
  - [ ] Folder structure matches GDD architecture section
  - [ ] Tech stack matches GDD technology section
  - [ ] No placeholder or stub files — everything created should be
    functional
- **Definition of Done:** The project runs, produces minimal output, and the
  folder structure matches the GDD architecture.

Present the bootstrap issue to the user for approval, then proceed to
Phase 5 (Issue Creation).

**Do not apply the decomposition rules below** — they are for multi-issue
versioned work. Bootstrap is always a single issue.
```

- [ ] **Step 3: Commit**

```bash
git add skills/gameplan/SKILL.md
git commit -m "feat: add bootstrap decomposition to gameplan Phase 4"
```

---

### Task 4: Verification review

**Files:**
- Read: `skills/gameplan/SKILL.md` (full file)

- [ ] **Step 1: End-to-end review**

Read the complete `skills/gameplan/SKILL.md`. Verify:
- Phase 1 Step 6 (bootstrap detection) is positioned after Step 5
- Phase 2 has bootstrap proposal before normal version proposal
- Phase 4 has bootstrap mode before decomposition rules
- The flow is coherent: detection → proposal → decomposition → creation
- No contradictions between sections
- Existing content (Phase 3, Phase 5, Decomposition Rules, Presenting Issues,
  Red Flags, Common Mistakes) is unchanged

- [ ] **Step 2: Commit fixes (if any)**

Only commit if the review found issues.

```bash
git add skills/gameplan/SKILL.md
git commit -m "fix: address review findings in bootstrap detection"
```
