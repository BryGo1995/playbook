# Scout Skill & Plugin Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure playbook skills into a proper Claude Code plugin and build the scout skill for GDD/PRD creation.

**Architecture:** The playbook repo becomes a Claude Code plugin via `.claude-plugin/plugin.json`. Two skills live under `skills/`: `gameplan` (migrated from `~/.claude/skills/playbook-plan-version/`) and `scout` (new). Scout uses template files in `skills/scout/templates/` to drive a conversational GDD/PRD creation flow.

**Tech Stack:** Claude Code plugin system, Markdown skill definitions, YAML config

---

### Task 1: Create Plugin Manifest

**Files:**
- Create: `.claude-plugin/plugin.json`

- [ ] **Step 1: Create the plugin manifest**

```json
{
  "name": "playbook",
  "description": "Orchestrator plugin for planning and dispatching autonomous coding agents",
  "skills": {
    "scout": "skills/scout/SKILL.md",
    "gameplan": "skills/gameplan/SKILL.md"
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "feat: add claude plugin manifest for playbook skills"
```

---

### Task 2: Migrate Gameplan Skill

**Files:**
- Create: `skills/gameplan/SKILL.md`
- Create: `skills/gameplan/issue-template.md`

- [ ] **Step 1: Copy the existing SKILL.md**

Copy the contents of `~/.claude/skills/playbook-plan-version/SKILL.md` to `skills/gameplan/SKILL.md`. Update the frontmatter:

```yaml
---
name: playbook:gameplan
description: >
  Use when the user wants to plan the next version of a project managed by the
  playbook orchestrator, create agent-ready issues from a GDD/PRD, or says
  "let's plan the next version", "plan version", "create issues for the next
  version", or references version planning for orchestrated agent work.
---
```

The rest of the SKILL.md content (phases 1-5, red flags, common mistakes) stays identical.

- [ ] **Step 2: Copy the issue template**

Copy `~/.claude/skills/playbook-plan-version/issue-template.md` to `skills/gameplan/issue-template.md`. No content changes needed.

- [ ] **Step 3: Update internal references**

In `skills/gameplan/SKILL.md`, search for any references to `playbook-plan-version` or `plan-version` and update them to `playbook:gameplan`. Check the title line and any self-references.

- [ ] **Step 4: Commit**

```bash
git add skills/gameplan/SKILL.md skills/gameplan/issue-template.md
git commit -m "feat: migrate gameplan skill into plugin structure"
```

---

### Task 3: Create Scout SKILL.md

**Files:**
- Create: `skills/scout/SKILL.md`

- [ ] **Step 1: Write the scout skill definition**

Create `skills/scout/SKILL.md` with the full skill definition. The frontmatter:

```yaml
---
name: playbook:scout
description: >
  Use when the user wants to create a GDD (Game Design Document) or PRD
  (Product Requirements Document) for a new project, or iterate on an existing
  one. Invoked explicitly via /playbook:scout. Guides the user through a
  conversational interview and produces a structured document that
  playbook:gameplan can consume.
---
```

The body should implement the four-phase flow from the design spec:

**Phase 1 — Setup & Context Gathering (automatic):**
- Check for existing GDD/PRD by reading `gdd_path` from `config.yaml` and scanning `docs/` for `*-gdd.md` / `*-prd.md`
- If found, present re-entry options:
  - A) Continue building it — review what's there, fill in stub/skipped sections
  - B) Revise specific sections — user specifies which parts need rework
  - C) Start fresh — double-confirm, archive old file to `docs/design-context/` with `<!-- ARCHIVED -->` comment, update `config.yaml`
- If not found, create `docs/` and `docs/design-context/` if they don't exist
- Scan `docs/design-context/` for reference material and summarize findings
- Tell user: "Place any existing notes, sketches, or reference material in `docs/design-context/` — I'll read through them to get context before we start."

**Phase 2 — Project Type & Vision (conversational):**
- Ask project type: Game / Application / Library / Custom
  - If Custom, scan `skills/scout/templates/` for user-provided templates with valid frontmatter
- Read the corresponding template to determine sections
- If reference material was found, read through it: "I found these files — let me read through them to get up to speed before we continue."
- Ask: "In 1-2 sentences, what is this project?"

**Phase 3 — Section-by-Section Interview (conversational, iterative):**
- Walk through each template section one at a time
- For each section: ask targeted questions (one at a time, multiple choice preferred), propose draft content, get approval
- Cover essential sections first (marked `<!-- essential -->`), then offer optional sections (marked `<!-- optional -->`)
- User can say "skip" on optional sections — they remain as stubs
- User can say "that's enough for now" to stop early

**Phase 4 — Output & Config (automatic):**
- Write GDD/PRD to `docs/<project-name>-gdd.md` or `docs/<project-name>-prd.md` based on template `output_suffix`
- Auto-update `config.yaml` with `gdd_path` pointing to the new file
- Commit the GDD/PRD and config change
- Tell the user: "Your GDD is ready. Run `/playbook:gameplan` when you're ready to plan your first version."

**Include these skill guidelines:**
- One question per message, multiple choice preferred
- The user is the product owner — propose, they approve
- YAGNI ruthlessly — don't add sections the user doesn't need yet
- Essential sections first, optional sections offered after
- Each template section should have enough detail for gameplan to decompose into issues

**Include red flags table:**

| Thought | Reality |
|---------|---------|
| "I'll fill in this section with reasonable defaults" | Ask the user. Every section needs their input. |
| "This section is obvious, I'll skip the question" | Ask anyway. Obvious to you ≠ obvious to the gameplan skill. |
| "The user wants to move fast, I'll batch questions" | One question at a time. Always. |
| "I'll create the GDD without asking about type" | Always ask. The template drives the conversation. |
| "The existing material covers everything" | Reference material seeds the conversation, it doesn't replace it. |

- [ ] **Step 2: Commit**

```bash
git add skills/scout/SKILL.md
git commit -m "feat: add scout skill for GDD/PRD creation"
```

---

### Task 4: Create Game GDD Template

**Files:**
- Create: `skills/scout/templates/game-gdd.md`

- [ ] **Step 1: Write the game GDD template**

```markdown
---
type: game
name: Game Design Document
output_suffix: gdd
---

## Core Concept
<!-- essential -->
What is this game? One paragraph covering the genre, core fantasy, and what
makes it unique. Include the target platform(s) and engine.

## Target Audience
<!-- essential -->
Who is this game for? Casual/hardcore, age range, comparable titles they
might enjoy.

## Core Mechanics
<!-- essential -->
The primary gameplay systems. For each mechanic:
- What the player does (input)
- What happens (system response)
- Why it's fun (feedback loop)

## Game Loop
<!-- essential -->
The moment-to-moment, session, and long-term loops. What does a typical
play session look like from start to finish?

## Progression
<!-- essential -->
How does the player advance? Unlocks, difficulty curves, skill growth,
content gating. What keeps them coming back?

## Scenes & Levels
<!-- optional -->
List of scenes/levels/maps with brief descriptions. Include purpose in
the progression and approximate scope.

## Art Direction
<!-- optional -->
Visual style, color palette, reference images/games. Enough for an artist
or asset search to work from.

## Audio
<!-- optional -->
Music style, key sound effects, audio feedback philosophy.

## UI/UX
<!-- optional -->
Key screens (main menu, HUD, pause, settings). Interaction patterns.
Accessibility considerations.

## Technical Constraints
<!-- optional -->
Performance targets, platform limitations, engine-specific concerns,
third-party dependencies.

## Monetization
<!-- optional -->
Business model, if applicable. Free-to-play, premium, ads, DLC.

## Roadmap
<!-- essential -->
Version milestones with scope. Each version should be a playable increment.
Format: `vX.Y — milestone name — brief scope description`.
```

- [ ] **Step 2: Commit**

```bash
git add skills/scout/templates/game-gdd.md
git commit -m "feat: add game GDD template for scout skill"
```

---

### Task 5: Create Application PRD Template

**Files:**
- Create: `skills/scout/templates/app-prd.md`

- [ ] **Step 1: Write the application PRD template**

```markdown
---
type: application
name: Product Requirements Document
output_suffix: prd
---

## Problem Statement
<!-- essential -->
What problem does this application solve? Who has this problem and how do
they currently deal with it?

## Target Audience
<!-- essential -->
Primary and secondary users. Their technical sophistication, usage context,
and what success looks like for them.

## User Personas
<!-- optional -->
Named archetypes with goals, frustrations, and usage patterns. Only include
if the audience segments are meaningfully different.

## Requirements
<!-- essential -->
Functional requirements grouped by feature area. Each requirement should be
specific and testable. Use "must", "should", "could" priority levels.

## Architecture
<!-- essential -->
High-level system design. Components, their responsibilities, and how they
communicate. Include deployment model (local, cloud, hybrid).

## Data Model
<!-- optional -->
Key entities, their relationships, and storage approach. Include any
external data sources or integrations.

## API Surface
<!-- optional -->
Public interfaces — REST endpoints, CLI commands, SDK methods, or IPC
protocols. Include request/response shapes for critical paths.

## Security & Auth
<!-- optional -->
Authentication method, authorization model, data protection requirements.
Compliance constraints if any.

## Success Metrics
<!-- optional -->
How you'll know this is working. Quantitative metrics preferred.

## Technical Constraints
<!-- optional -->
Language/framework requirements, platform targets, performance budgets,
dependency restrictions.

## Roadmap
<!-- essential -->
Version milestones with scope. Each version should deliver usable
functionality. Format: `vX.Y — milestone name — brief scope description`.
```

- [ ] **Step 2: Commit**

```bash
git add skills/scout/templates/app-prd.md
git commit -m "feat: add application PRD template for scout skill"
```

---

### Task 6: Create Library PRD Template

**Files:**
- Create: `skills/scout/templates/library-prd.md`

- [ ] **Step 1: Write the library PRD template**

```markdown
---
type: library
name: Library/Tool Requirements Document
output_suffix: prd
---

## Purpose
<!-- essential -->
What does this library/tool do? One paragraph covering the problem space,
why existing solutions are insufficient, and what this provides.

## Target Users
<!-- essential -->
Who will use this? Developers, ops teams, end users? What's their skill
level and what ecosystem do they work in?

## API Design
<!-- essential -->
The public interface. For each major function/class/command:
- Signature and parameters
- Return value and side effects
- Usage example

Design for the consumer's ergonomics, not the implementation's convenience.

## Use Cases
<!-- essential -->
Concrete scenarios showing how the library/tool is used end-to-end.
Include the "happy path" and at least one edge case per use case.

## Integration Patterns
<!-- optional -->
How does this fit into a larger system? Import/install method, configuration,
and common composition patterns with other tools.

## Compatibility
<!-- optional -->
Language/runtime versions, OS support, browser targets, dependency
constraints. Breaking change policy.

## Performance Constraints
<!-- optional -->
Latency budgets, memory limits, throughput targets. Benchmarking approach.

## CLI Interface
<!-- optional -->
If the tool has a CLI: commands, flags, output formats. Include examples
of common invocations.

## Error Handling
<!-- optional -->
Error taxonomy, reporting approach (exceptions, result types, exit codes),
and recovery guidance for consumers.

## Roadmap
<!-- essential -->
Version milestones with scope. Each version should be independently
publishable. Format: `vX.Y — milestone name — brief scope description`.
```

- [ ] **Step 2: Commit**

```bash
git add skills/scout/templates/library-prd.md
git commit -m "feat: add library PRD template for scout skill"
```

---

### Task 7: Remove Old Skill Location

**Files:**
- Delete: `~/.claude/skills/playbook-plan-version/SKILL.md`
- Delete: `~/.claude/skills/playbook-plan-version/issue-template.md`
- Delete: `~/.claude/skills/playbook-plan-version/` (directory)

- [ ] **Step 1: Verify the new skill files are committed**

```bash
git log --oneline -5
```

Confirm the gameplan migration commit is present before deleting the old files.

- [ ] **Step 2: Remove the old skill directory**

```bash
rm -rf ~/.claude/skills/playbook-plan-version/
```

- [ ] **Step 3: Verify the plugin skills are discoverable**

Check that `/playbook:scout` and `/playbook:gameplan` appear in the skill list. If the plugin isn't auto-discovered, check that `.claude-plugin/plugin.json` is correctly structured.

---

### Task 8: Verify End-to-End

- [ ] **Step 1: Verify plugin structure**

```bash
ls -la .claude-plugin/
cat .claude-plugin/plugin.json
ls -la skills/scout/
ls -la skills/scout/templates/
ls -la skills/gameplan/
```

Confirm all files exist in the expected locations.

- [ ] **Step 2: Verify template frontmatter**

Read each template and confirm:
- `type`, `name`, and `output_suffix` fields are present in frontmatter
- Sections are annotated with `<!-- essential -->` or `<!-- optional -->`
- All templates have a `## Roadmap` essential section (gameplan depends on this)

- [ ] **Step 3: Verify gameplan content is intact**

Read `skills/gameplan/SKILL.md` and confirm:
- Five-phase flow is complete
- References to `playbook-plan-version` have been updated to `playbook:gameplan`
- Red flags and common mistakes sections are present
- Issue template reference points to the correct relative path

- [ ] **Step 4: Commit any fixes**

If any issues were found and fixed:

```bash
git add -A
git commit -m "fix: address issues found during plugin verification"
```
