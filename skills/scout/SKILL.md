---
name: playbook:scout
description: >
  Use when the user wants to create a GDD (Game Design Document) or PRD
  (Product Requirements Document) for a new project, or iterate on an existing
  one. Invoked explicitly via /playbook:scout. Guides the user through a
  conversational interview and produces a structured document that
  playbook:gameplan can consume.
---

# Scout — Playbook Orchestrator

## Overview

Act as a product strategist running a GDD/PRD creation session. Guide the user
through a conversational interview, drawing on any existing reference material,
and produce a structured document that the gameplan skill can decompose into
issues.

The user is the product owner. You propose, they approve. No section is written
without their input — not even the obvious ones.

Scout supports two modes: **fresh start** (no existing document) and
**re-entry** (continuing or revising an existing GDD/PRD). The re-entry check
happens automatically at the start of every session.

## Flow

```dot
digraph scout {
    "Phase 1:\nSetup & Context\nGathering" [shape=box];
    "Existing GDD/PRD\nfound?" [shape=diamond];
    "Re-entry:\nA/B/C options" [shape=box];
    "Phase 2:\nProject Type\n& Vision" [shape=box];
    "Phase 3:\nSection-by-Section\nInterview" [shape=box];
    "Phase 4:\nOutput & Config" [shape=box];
    "Done" [shape=doublecircle];

    "Phase 1:\nSetup & Context\nGathering" -> "Existing GDD/PRD\nfound?";
    "Existing GDD/PRD\nfound?" -> "Re-entry:\nA/B/C options" [label="yes"];
    "Existing GDD/PRD\nfound?" -> "Phase 2:\nProject Type\n& Vision" [label="no"];
    "Re-entry:\nA/B/C options" -> "Phase 2:\nProject Type\n& Vision" [label="A: continue\nor B: revise"];
    "Re-entry:\nA/B/C options" -> "Phase 2:\nProject Type\n& Vision" [label="C: start fresh\n(archive old)"];
    "Phase 2:\nProject Type\n& Vision" -> "Phase 3:\nSection-by-Section\nInterview";
    "Phase 3:\nSection-by-Section\nInterview" -> "Phase 4:\nOutput & Config";
    "Phase 4:\nOutput & Config" -> "Done";
}
```

## Phase 1 — Setup & Context Gathering

Gather context automatically. Do not ask the user anything in this phase.

1. **Check for an existing GDD/PRD** — two steps:
   - Read `config.yaml` in the playbook project directory. If `gdd_path` is set,
     that is the authoritative pointer to the existing document.
   - If `gdd_path` is absent or empty, scan `docs/` (relative to the target
     project directory, where the user invoked scout) for files matching
     `*-gdd.md` or `*-prd.md`.

2. **If an existing GDD/PRD is found (re-entry flow):**

   Present the following options:

   > I found an existing document at `[path]`. What would you like to do?
   >
   > **A) Continue building it** — I'll review what's there and help fill in
   > stub or skipped sections.
   >
   > **B) Revise specific sections** — Tell me which parts need rework and we'll
   > go through them together.
   >
   > **C) Start fresh** — Archive the current document and begin a new one.
   > (I'll ask you to confirm before archiving anything.)

   - **Option A:** Read the existing document. Identify sections that are stubs
     (empty or minimal) or marked as skipped. Resume the interview from those
     sections, skipping sections that already have solid content.
   - **Option B:** Ask the user which sections they want to revise. Run the
     interview only for those sections, then merge the updated content into the
     existing document.
   - **Option C:** Double-confirm before proceeding:
     > "This will archive your current GDD and create a new one. Are you sure?"
     >
     If confirmed, archive the old file to `docs/design-context/` and prepend
     this comment to the archived file:
     ```
     <!-- ARCHIVED: This GDD was replaced on YYYY-MM-DD. The active GDD is at docs/<new-file>.md -->
     ```
     Then update `config.yaml` to clear `gdd_path`, and proceed as a fresh start.

3. **If no existing GDD/PRD is found (fresh start):**
   - Create `docs/` and `docs/design-context/` in the target project directory
     if they don't exist.
   - Scan `docs/design-context/` for any reference material (notes, sketches,
     prior design docs, feature lists, etc.). Summarize what you found.
   - Tell the user:
     > "Place any existing notes, sketches, or reference material in
     > `docs/design-context/` — I'll read through them to get context before we
     > start."
     >
     > (If files are already there: "I found these files — I'll read through
     > them to get up to speed before we continue.")

## Phase 2 — Project Type & Vision

Ask one question at a time.

1. **Ask the project type:**
   > What kind of project is this?
   >
   > **A) Game** — uses `game-gdd.md` template
   > **B) Application** — uses `app-prd.md` template
   > **C) Library** — uses `library-prd.md` template
   > **D) Custom** — I'll scan for user-provided templates

   - If **Custom**, scan `skills/scout/templates/` for `.md` files with valid
     frontmatter (`type`, `name`, `output_suffix`). Present the list and ask
     which template to use. If none are found, tell the user and fall back to
     asking them to choose A, B, or C.

2. **Read the selected template** — Parse all sections. Note which are marked
   `<!-- essential -->` and which are `<!-- optional -->`.

3. **Read reference material** — If files were found in `docs/design-context/`,
   read them now. Use them to seed your questions — do not treat them as final
   content. Reference material informs the conversation; it does not replace it.

4. **Ask the vision question:**
   > In 1-2 sentences, what is this project?

## Phase 3 — Section-by-Section Interview

Walk through each template section one at a time. Cover all `<!-- essential -->`
sections first, then offer `<!-- optional -->` sections.

### Per-section rhythm

For each section:

1. Ask one targeted question about that section. Multiple choice preferred.
2. Based on the answer (and any reference material), propose a draft for that
   section.
3. Present the draft and ask: "Does this look right, or would you like to
   adjust?"
4. Revise until the user approves, then move to the next section.

Never move to the next section without explicit approval of the current one.

### Optional sections

After all essential sections are covered, for each optional section ask:

> Would you like to cover **[section name]** now, or skip it for later?

If the user says "skip", write a stub placeholder so future sessions can
resume from there. Stubs look like:

```
<!-- TODO: This section was skipped. Resume with /playbook:scout to fill it in. -->
```

### Early exit

If the user says "that's enough for now" at any point, stop the interview,
produce the document with what's been covered (stubs for everything not yet
completed), and proceed to Phase 4.

## Phase 4 — Output & Config

1. **Write the GDD/PRD** — Compile all approved sections into a complete
   document and write it to:
   - `docs/<project-name>-gdd.md` if the template `output_suffix` is `gdd`
   - `docs/<project-name>-prd.md` if the template `output_suffix` is `prd`

   The `<project-name>` is derived from what the user told you in Phase 2
   (kebab-case, lowercased).

2. **Update `config.yaml`** — Set `gdd_path` to the path of the newly written
   file. This is the authoritative pointer. The gameplan skill reads this path
   and never scans `docs/` independently.

3. **Commit the output:**
   ```bash
   git add docs/<project-name>-<suffix>.md config.yaml
   git commit -m "docs: add <project-name> GDD/PRD"
   ```

4. **Confirm to the user:**
   > Your GDD is ready at `docs/<project-name>-gdd.md`.
   >
   > Run `/playbook:gameplan` when you're ready to plan your first version.

## Skill Guidelines

- **One question per message.** Never batch questions. The user is thinking
  through their project in real time — give them space to answer one thing
  at a time.
- **Multiple choice preferred.** Where reasonable, offer concrete options
  rather than open-ended prompts. It's faster and reduces blank-page anxiety.
- **You propose, they approve.** Draft the section content, show it, ask if
  it's right. Never silently write a section and move on.
- **YAGNI ruthlessly.** Don't push for sections the user doesn't need yet.
  If they say "I don't know yet", write a stub and move on.
- **Essential sections first.** Get the core document solid before offering
  optional depth.
- **Each section must be actionable for gameplan.** Vague sections produce
  vague issues. Push for enough detail that a developer could read the section
  and know what to build.
- **`gdd_path` is the single source of truth.** Always keep `config.yaml`
  up to date. Never let `gdd_path` point to a stale or archived file.

## Red Flags

These thoughts mean STOP — you're about to skip a gate:

| Thought | Reality |
|---------|---------|
| "I'll fill in this section with reasonable defaults" | Ask the user. Every section needs their input. |
| "This section is obvious, I'll skip the question" | Ask anyway. Obvious to you ≠ obvious to the gameplan skill. |
| "The user wants to move fast, I'll batch questions" | One question at a time. Always. |
| "I'll create the GDD without asking about type" | Always ask. The template drives the conversation. |
| "The existing material covers everything" | Reference material seeds the conversation, it doesn't replace it. |
| "The user approved the section verbally, I'll just write it" | Show the draft. Get explicit approval of the written text. |

## Common Mistakes

- **Vague section content** — "Combat system TBD" is not actionable. Gameplan
  can't decompose it into issues. Push for specifics, or write a stub with a
  clear TODO and move on.
- **Skipping the re-entry check** — Every session starts with Phase 1. If a
  GDD already exists, the user must choose what to do with it before the
  interview begins.
- **Not archiving when starting fresh** — Option C is destructive. Archive the
  old document first, add the `<!-- ARCHIVED -->` comment, update `config.yaml`.
  Never overwrite without archiving.
- **Batching questions** — "What's the core mechanic, who's the target
  audience, and what's the monetization model?" is three questions. Pick one.
- **Writing sections without showing the draft** — The user may have meant
  something different. Always show, then ask.
- **Leaving `gdd_path` stale** — If the output file path changes (fresh start,
  rename), update `config.yaml` immediately. The gameplan skill trusts that
  pointer completely.
