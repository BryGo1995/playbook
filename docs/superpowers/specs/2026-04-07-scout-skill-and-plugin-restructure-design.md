# Scout Skill & Plugin Restructure Design

## Overview

Two related changes to the playbook project:

1. **playbook:scout** — A new skill that guides users through creating a GDD (Game Design Document) or PRD (Product Requirements Document) via conversational interview, producing a structured document that the gameplan skill can consume.
2. **Plugin restructure** — Migrate the existing playbook-plan-version skill into a proper `.claude-plugin/` structure alongside scout, unifying both under the `playbook:` namespace with football-themed naming.

## Plugin Structure

The playbook repo becomes a Claude Code plugin. Both skills live in-repo, version-controlled with the codebase:

```
playbook/
├── .claude-plugin/
│   └── plugin.json
├── skills/
│   ├── scout/
│   │   ├── SKILL.md
│   │   └── templates/
│   │       ├── game-gdd.md
│   │       ├── app-prd.md
│   │       └── library-prd.md
│   └── gameplan/
│       ├── SKILL.md
│       └── issue-template.md
├── orchestrator.py
└── ... (rest of existing codebase)
```

### plugin.json

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

### Benefits of in-repo plugin

- **Distribution** — Cloning the repo installs the skills automatically.
- **Versioning** — Skills evolve with the codebase. No drift between orchestrator and its skills.
- **Publishable** — Structure is ready for community distribution.

## Scout Skill

### Invocation

Explicit only via `/playbook:scout`. Not auto-detected or auto-invoked. Creating a GDD/PRD is intentional and not appropriate for every project.

### Input Model (Hybrid)

Scout supports two input modes:

- **Conversational** — Interview the user from scratch, one question at a time.
- **Context-aware** — Read existing material from `docs/design-context/` to seed the conversation with prior thinking.

Both modes can be combined. Scout always checks for existing context before starting the interview.

### Directory Conventions

Scout creates these directories in the working directory if they don't exist:

- `docs/design-context/` — User-provided reference material (notes, sketches, research). Scout reads from here; users place files here before or during sessions.
- `docs/` — Output location for the generated GDD/PRD.

On first invocation, scout tells the user: "Place any existing notes, sketches, or reference material in `docs/design-context/` — I'll read through them to get context before we start."

### Project Types

Scout detects project type via user selection and loads the corresponding template:

| Type | Template | Output file |
|------|----------|-------------|
| Game | `templates/game-gdd.md` | `docs/<project>-gdd.md` |
| Application | `templates/app-prd.md` | `docs/<project>-prd.md` |
| Library/Tool | `templates/library-prd.md` | `docs/<project>-prd.md` |
| Custom | User-provided template in `templates/` | Per template frontmatter |

Each template is first-class for its domain — not a watered-down generic form.

### Custom Templates

Users can add their own templates to `skills/scout/templates/` in the playbook plugin directory. Requirements:

- Must include frontmatter with `type`, `name`, and `output_suffix` fields.
- Must use `## Section Name` headings with `<!-- essential -->` or `<!-- optional -->` annotations.
- Scout validates frontmatter before accepting a custom template.

Scout presents custom templates alongside built-in ones during project type selection.

### Conversation Flow

#### Phase 1 — Setup & Context Gathering (automatic)

1. Check for existing GDD/PRD:
   - Read `gdd_path` from `config.yaml` if it exists.
   - Scan `docs/` for `*-gdd.md` / `*-prd.md` files.
2. **If existing GDD/PRD found (re-entry flow):**
   - Present options:
     - **A) Continue building it** — Review what's there, fill in stub/skipped sections.
     - **B) Revise specific sections** — User specifies which parts need rework.
     - **C) Start fresh** — Archive existing GDD to `docs/design-context/`, create new one.
   - If "Start fresh" selected: double-confirm ("This will archive your current GDD and create a new one. Are you sure?"). On confirm, move old file to `docs/design-context/` with an archival frontmatter note (`<!-- ARCHIVED: This GDD was replaced on YYYY-MM-DD. The active GDD is at docs/<new-file>.md -->`), then update `config.yaml` `gdd_path`.
3. **If no existing GDD/PRD:**
   - Create `docs/design-context/` and `docs/` if they don't exist.
   - Scan `docs/design-context/` for reference material.
   - Summarize what context was found.

#### Phase 2 — Project Type & Vision (conversational)

1. Ask project type: Game / Application / Library / Custom.
   - If Custom, scan `skills/scout/templates/` for user-provided templates.
2. Read the corresponding template to determine sections.
3. If reference material was found in `docs/design-context/`, read through it first: "I found these files — let me read through them to get up to speed before we continue."
4. Ask the core vision question: "In 1-2 sentences, what is this project?"

#### Phase 3 — Section-by-Section Interview (conversational, iterative)

1. Walk through each template section one at a time.
2. For each section:
   - Ask targeted questions (one at a time, multiple choice preferred).
   - Propose draft content for the section.
   - Get user approval before moving on.
3. Cover all essential sections first, then offer optional sections.
4. User can say "skip" on optional sections — they stay as stubs for future sessions.
5. User can say "that's enough for now" to stop early and produce what's been covered.

#### Phase 4 — Output & Config (automatic)

1. Write the GDD/PRD to `docs/<project-name>-gdd.md` or `docs/<project-name>-prd.md`.
2. Auto-update `config.yaml` with `gdd_path` pointing to the new file.
3. Commit the GDD/PRD and config change.
4. Tell the user: "Your GDD is ready. Run `/playbook:gameplan` when you're ready to plan your first version."

### Config as Single Source of Truth

`gdd_path` in `config.yaml` is the authoritative pointer to the active GDD/PRD. Gameplan and any other consumer reads this path — they never independently scan `docs/` for GDD files. This prevents stale references when a GDD is archived and replaced.

### Iterative Design

Scout produces a solid v1 covering essential sections in the first session. Subsequent invocations detect the existing document and offer to continue building it, revise sections, or start fresh. The GDD/PRD grows over time as the project matures. The gameplan skill only needs enough detail to create the next version's issues.

## Template Structure

All templates (built-in and custom) follow this format:

```markdown
---
type: game
name: Game Design Document
output_suffix: gdd
---

## Core Concept
<!-- essential -->
Brief description of the project...

## Target Audience
<!-- essential -->
...

## Core Mechanics
<!-- essential -->
...

## Scenes & Levels
<!-- optional -->
...

## Art Direction
<!-- optional -->
...
```

### Conventions

- **Frontmatter** — `type`, `name`, `output_suffix` fields. Required for scout to identify and use the template.
- **`<!-- essential -->` / `<!-- optional -->`** — Controls interview order. Essential sections first, optional offered after.
- **`##` headings** — Section contract between scout (writing) and gameplan (reading). Consistent heading levels ensure gameplan can parse any GDD/PRD regardless of project type.

### Built-in Templates

| Template | Key Sections |
|----------|-------------|
| **Game GDD** | Core concept, target audience, core mechanics, progression, scenes/levels, art direction, audio, UI/UX, technical constraints |
| **App PRD** | Problem statement, target audience, user personas, requirements, architecture, data model, API surface, success metrics |
| **Library PRD** | Purpose, target users, API design, use cases, integration patterns, compatibility, performance constraints |

## Gameplan Migration

The existing `~/.claude/skills/playbook-plan-version/` moves into the plugin:

1. Copy `SKILL.md` to `skills/gameplan/SKILL.md`.
2. Copy `issue-template.md` to `skills/gameplan/issue-template.md`.
3. Update internal references from `playbook-plan-version` to `playbook:gameplan`.
4. Remove `~/.claude/skills/playbook-plan-version/`.

The five-phase flow, conflict avoidance strategies, and issue template content remain unchanged. Gameplan already reads `gdd_path` from `config.yaml`, which aligns with scout's output. No compatibility changes needed.

## Pipeline

The full playbook pipeline with both skills:

```
/playbook:scout → GDD/PRD → /playbook:gameplan → Issues → Orchestrator → Agents
```

Scout creates the document. Gameplan decomposes it into agent-ready issues. The orchestrator dispatches agents against those issues.
