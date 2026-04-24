# Playbook Metrics Implementation Plan

> **For agentic workers:** implement task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a metrics system to playbook that captures root-cause data on film-room fixes and surfaces failure patterns to the plugin maintainer, with zero friction for non-technical distributed users.

**Architecture:** Two skill-level components, both writing to `metrics/` in the project repo. Component 1 (structural spec check) runs inside gameplan during Phase 4 — catches vague acceptance criteria at generation time via one revision pass. Component 2 (LLM classification) runs inside film-room as a new post-merge step, using the same fresh-subagent (`claude -p`) pattern as existing distillers. Both write to a shared per-version YAML-frontmatter markdown file; film-room regenerates `SUMMARY.md` cross-version rollup.

**Tech Stack:** Markdown skill instructions, YAML config, `claude -p` subagent invocations (already used by distillers). One config schema extension in Python (`defaults.yaml` + `config.py` test).

**Deviation from spec to confirm before execution:** The design doc says "Not a separate agent — the film-room skill itself does the pass as a final instruction." While reading film-room's SKILL.md I found the existing distiller pattern at Step 4.5 uses a fresh `claude -p` subagent on a shared input bundle with its own `--max-budget-usd` cap. Using the same pattern for Component 2 is cleaner (budget isolation, context isolation, reproducible) and reuses proven infrastructure. The user-facing behavior is unchanged. **If you disagree, stop and raise before Task 6.**

---

## File Structure

**New files:**
- `skills/gameplan/structural-check-rubric.md` — Component 1 rubric (invoked by gameplan Phase 4)
- `skills/film-room/classification-rubric.md` — Component 2 rubric (consumed by the classifier subagent)
- `skills/film-room/classifier-prompt.md` — the `claude -p` prompt template for the classifier subagent (matches the distiller pattern)
- `docs/metrics-format.md` — authoritative format reference for `metrics/vX.Y.md` and `metrics/SUMMARY.md`

**Modified:**
- `defaults.yaml` — add `metrics:` section with defaults
- `skills/gameplan/SKILL.md` — insert Phase 4 sub-step that runs the structural check before user presentation
- `skills/film-room/SKILL.md` — insert a new Step 4.6 (classification) after distillers; extend Step 4.6 to regenerate `SUMMARY.md`
- `tests/test_config.py` — add test for metrics config defaults

**No changes to:** `agents/*.py`, `orchestrator.py`, `state.py`, `versioning.py`. This is skill-level work; the Python orchestrator is untouched.

---

## Task 1: Add `metrics:` config schema (TDD)

**Files:**
- Modify: `defaults.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append this test to `tests/test_config.py`:

```python
def test_metrics_defaults_loaded(tmp_path):
    """metrics section has documented defaults when project config doesn't override."""
    defaults_dir = tmp_path / "playbook"
    defaults_dir.mkdir()
    # Use the real defaults.yaml — copy it into the tmp path
    import shutil
    real_defaults = os.path.join(os.path.dirname(os.path.dirname(__file__)), "defaults.yaml")
    shutil.copy(real_defaults, defaults_dir / "defaults.yaml")

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("repo: owner/my-project\n")

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults_dir / "defaults.yaml"))
    assert cfg["metrics"]["enabled"] is True
    assert cfg["metrics"]["show_checks"] is False
    assert cfg["metrics"]["classification_budget_usd"] == 0.25


def test_metrics_project_overrides_defaults(tmp_path):
    """Project playbook.yaml can override metrics settings."""
    defaults_dir = tmp_path / "playbook"
    defaults_dir.mkdir()
    (defaults_dir / "defaults.yaml").write_text("""
metrics:
  enabled: true
  show_checks: false
  classification_budget_usd: 0.25
""")

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/my-project
metrics:
  show_checks: true
""")

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults_dir / "defaults.yaml"))
    assert cfg["metrics"]["enabled"] is True  # inherited
    assert cfg["metrics"]["show_checks"] is True  # overridden
    assert cfg["metrics"]["classification_budget_usd"] == 0.25  # inherited
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /home/bryang/Dev_Space/playbook && pytest tests/test_config.py::test_metrics_defaults_loaded -v`
Expected: FAIL with `KeyError: 'metrics'` (no metrics section in defaults yet).

- [ ] **Step 3: Add the `metrics:` section to `defaults.yaml`**

Append to the end of `defaults.yaml` (after the `learning:` block):

```yaml
metrics:
  enabled: true                    # master switch; set false to disable all metrics
  show_checks: false               # echo structural check + classification summaries to user; default false (for distribution)
  classification_budget_usd: 0.25  # per-version cap for the classification subagent
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/bryang/Dev_Space/playbook && pytest tests/test_config.py -v`
Expected: All pass, including the two new metrics tests.

- [ ] **Step 5: Commit**

```bash
git -C /home/bryang/Dev_Space/playbook add defaults.yaml tests/test_config.py
git -C /home/bryang/Dev_Space/playbook commit -m "feat(metrics): add metrics config section with defaults"
```

---

## Task 2: Write the metrics format reference

**Files:**
- Create: `docs/metrics-format.md`

- [ ] **Step 1: Create the format reference document**

Write `docs/metrics-format.md` with this exact content:

````markdown
# Metrics File Format

This is the authoritative reference for the metrics files written by the playbook plugin. Both `skills/gameplan/SKILL.md` (Component 1) and `skills/film-room/SKILL.md` (Component 2) produce these files.

Metrics files live at `metrics/` in the **project repo** (not the playbook repo). They are written and committed by the skills during their normal flow.

## File types

- `metrics/vX.Y.md` — per-version source of truth. One file per version. Bootstrap uses `metrics/bootstrap.md`.
- `metrics/SUMMARY.md` — cross-version rollup. Auto-regenerated at end of every film-room session.

## Per-version file (`metrics/vX.Y.md`)

YAML frontmatter + markdown body.

### Frontmatter schema

```yaml
version: v0.3                   # string — version label, or "bootstrap"
date: 2026-04-24                # ISO date — when the file was last written
issues: 3                       # int — number of issues in this version
first_pass_clean: 1             # int — issues that required zero film-room fixes
fixes_total: 9                  # int — total fixes made in film-room for this version
failures:                       # dict[str, int] — counts per failure tag. Omit tags with zero.
  gameplan-criteria: 4
  coding-misread: 2
  gdd-gap: 1
iterations:                     # dict[str, int] — counts per iteration tag. Omit tags with zero.
  design-change: 2
cost_usd: 4.87                  # float — total agent spend for this version (including classifier)
```

Omit `failures` and `iterations` keys entirely if the version was first-pass clean (`fixes_total: 0`).

### Body sections

Two sections, written by two different skills:

1. `## Structural check (gameplan)` — written by Component 1 during gameplan Phase 4.
2. `## Classification (film-room)` — written by Component 2 as the distiller-peer subagent in film-room.

If a version is first-pass clean, only the structural check section appears and the classification section is replaced with `_No fixes made — classification skipped._`

## Summary file (`metrics/SUMMARY.md`)

No frontmatter. Plain markdown. Auto-regenerated from the frontmatter of all `metrics/v*.md` files at end of every film-room session.

Sections:

1. `# Playbook Metrics` — the title.
2. A markdown table with one row per version: `Version | First-pass | Fixes | Top failure | Cost | Date`. Sort descending by version.
3. `## Current top failure modes (last 3 versions)` — summed failure counts across the most recent 3 versions, ranked.
4. `## Trends` — for each failure tag that appears in at least 2 of the last 3 versions, a line showing `tag: N → N → N (direction-label)`. Direction labels: "improving", "not improving", "steady", "noisy".

## Git handling

Both files are committed to `main` as a separate `chore: record metrics for vX.Y` commit after the fix branch is merged. Metrics commits use only the `metrics/` path; they do not touch other files.

## Versions and completeness

If a version's metrics file is missing (e.g., the user disabled metrics for that version and later re-enabled), SUMMARY.md silently skips it. The plugin does not backfill.
````

- [ ] **Step 2: Commit**

```bash
git -C /home/bryang/Dev_Space/playbook add docs/metrics-format.md
git -C /home/bryang/Dev_Space/playbook commit -m "docs(metrics): add metrics file format reference"
```

---

## Task 3: Write the structural check rubric

**Files:**
- Create: `skills/gameplan/structural-check-rubric.md`

- [ ] **Step 1: Create the rubric**

Write `skills/gameplan/structural-check-rubric.md` with this exact content:

````markdown
# Structural Check Rubric (Component 1)

Used by `gameplan` Phase 4 to assess whether acceptance criteria contain enough structure to be testable. This runs silently after the full issue template is expanded and before the final user presentation.

## Anchors — a criterion must contain at least one

1. **Number** — any numeric value with units or context.
   Examples: "within 5 tiles", "under 100ms", "exactly 3 retries", "at 30% coverage".

2. **Specific state or boolean** — an observable binary/enum condition.
   Examples: "door is locked", "enemy is in pursuit state", "menu is visible", "inventory contains at least one sword".

3. **Named entity from the GDD** — a specific mechanic, system, or value defined elsewhere in the GDD. These should be verifiable by reading the GDD section referenced in the issue's "Relevant GDD Sections" block.
   Examples: "the CoverageController emits `coverage_changed`", "the 'snowball growth' mechanic triggers".

4. **Before/after comparison** — an explicit change over time.
   Examples: "narrows from 60° to 15°", "health drops from 100 to 80", "speed doubles when sprinting".

## Weak phrasing — triggers revision unless criterion is subjective

A criterion is weak if its only action/verb is one of these without an observable anchor:

- "works", "functions", "operates"
- "correctly", "properly", "appropriately", "as expected"
- "handles {X}" without specifying the handling
- "supports {X}" without specifying the behavior
- "provides good UX", "user-friendly"
- "integrates with X" (without specifying what the integration produces)

## Revision procedure

For each weak criterion, attempt exactly **one** revision pass. Use this prompt verbatim (substituting `{criterion}` and `{gdd_excerpt}`):

> The following acceptance criterion lacks a measurable anchor (number, specific state, named entity, or comparison):
>
> "{criterion}"
>
> Relevant GDD excerpt:
> {gdd_excerpt}
>
> Rewrite the criterion to include at least one anchor, drawing concrete values from the GDD where possible. If the criterion is genuinely about subjective feel or aesthetics (e.g., combat feel, visual polish, audio impact), do NOT rewrite — instead return the original criterion prefixed with `[subjective]` to indicate it needs human evaluation.

Accept the returned text as the revised criterion. If the returned text still matches weak phrasing (no anchor and no `[subjective]` prefix), keep the original criterion and log the failure in the metrics file as `revision_failed: true` for that entry.

## Subjective criteria

A criterion is genuinely subjective when its success depends on human judgment that cannot be reduced to a number or state. Examples:

- Game feel: "feels snappy", "satisfying to land", "responsive to input"
- Visual aesthetics: "looks clean", "reads well at a glance", "visually distinct"
- Audio: "sounds impactful", "fits the mood"

Tag these with `[subjective]` and let them pass through unchanged. The `[subjective]` marker flows to film-room so the product owner knows to eval them first.

## Output — written to `metrics/vX.Y.md` structural check section

For each issue, write one block. See `docs/metrics-format.md` for the containing file format.

```markdown
## Structural check (gameplan)

- Issue #15: 5 clean
- Issue #16: 4 clean, 1 sharpened
    · "enemy AI works correctly"
      → "enemies pursue player within 5 tiles, return to patrol 3s after LOS loss"
- Issue #17: 3 clean, 1 sharpened, 1 marked subjective
    · sharpened: "handles input properly"
      → "jump input accepted within 100ms of button press"
    · subjective: "jump feels responsive"
```

If no criteria needed revision, still write the section with each issue line showing "N clean".
````

- [ ] **Step 2: Commit**

```bash
git -C /home/bryang/Dev_Space/playbook add skills/gameplan/structural-check-rubric.md
git -C /home/bryang/Dev_Space/playbook commit -m "feat(gameplan): add structural check rubric"
```

---

## Task 4: Integrate structural check into gameplan Phase 4

**Files:**
- Modify: `skills/gameplan/SKILL.md` (Phase 4, after expansion, before final presentation)

- [ ] **Step 1: Locate the insertion point**

Open `skills/gameplan/SKILL.md`. Find the line that currently reads:

```
After the user reviews and approves the decomposition, expand each issue into the
full template from `issue-template.md`.
```

The structural check is inserted **after** expansion, **before** the "Open the floor for discussion" line that follows this block.

- [ ] **Step 2: Insert the structural check sub-section**

After the line:

```
After the user reviews and approves the decomposition, expand each issue into the
full template from `issue-template.md`.
```

Insert the following new block (exactly — including the `### Structural check` heading):

````markdown

### Structural check (Component 1)

After expanding each issue, run the structural check on every acceptance criterion and every testing criterion. Read the rubric at `skills/gameplan/structural-check-rubric.md` in this plugin's directory.

For each criterion:

1. Evaluate against the anchor list in the rubric.
2. If weak: run exactly one revision pass using the rubric's revision prompt. Replace the criterion with the revised text.
3. If genuinely subjective: prefix with `[subjective]`. Do not revise.
4. If the revision still fails to produce an anchor: keep the original, note it in the output.

**Write the structural check results** to the project repo's `metrics/vX.Y.md` file (use `metrics/bootstrap.md` for bootstrap). Check `metrics.enabled` in the merged config — if false, skip this entire step.

The file does not exist yet at this point (film-room will add the classification section later). Create it with this initial content:

```markdown
---
version: <vX.Y or bootstrap>
date: <today's ISO date>
issues: <count of issues in this version>
first_pass_clean: 0
fixes_total: 0
cost_usd: 0.0
---

## Structural check (gameplan)

<per-issue lines as specified in structural-check-rubric.md>

## Classification (film-room)

_Not yet run — will be written by film-room at end of next session._
```

**Always-written, regardless of `show_checks`.** The file is written whether or not the user sees the summary.

**If `metrics.show_checks` is `true`,** also echo the same structural-check block to the user before the "Open the floor for discussion" prompt, prefixed with:

```
[gameplan] structural check results:
```

**If `metrics.show_checks` is `false`,** write silently to the metrics file and proceed directly to the discussion prompt.

**If `metrics.enabled` is `false`,** skip both the check and the file write entirely.
````

- [ ] **Step 3: Add commit step inside Phase 5**

In Phase 5, find Step 3 ("Confirm creation"). **After** that step and **before** Step 4 ("Register with orchestrator"), insert a new step:

````markdown

4. **Commit the metrics file** — if `metrics.enabled` is true and `metrics/vX.Y.md` was written in Phase 4, commit it:
   ```bash
   git add metrics/vX.Y.md
   git commit -m "chore: record structural check for vX.Y"
   ```

   Substitute `vX.Y` with the actual version label (or `bootstrap`). This keeps the metrics commit atomic and lets git history show when structural-check data was captured.
````

Renumber the existing Step 4 to Step 5 (and any subsequent steps accordingly) so the numbering stays sequential.

- [ ] **Step 4: Manually verify skill file is syntactically valid**

Run: `head -50 skills/gameplan/SKILL.md` and `grep -n "structural check" skills/gameplan/SKILL.md`.
Expected: see the new section cleanly placed after the expansion line and no duplicate headings.

- [ ] **Step 5: Commit**

```bash
git -C /home/bryang/Dev_Space/playbook add skills/gameplan/SKILL.md
git -C /home/bryang/Dev_Space/playbook commit -m "feat(gameplan): integrate Component 1 structural check into Phase 4"
```

---

## Task 5: Write the classification rubric

**Files:**
- Create: `skills/film-room/classification-rubric.md`

- [ ] **Step 1: Create the rubric**

Write `skills/film-room/classification-rubric.md` with this exact content:

````markdown
# Classification Rubric (Component 2)

Used by the classifier subagent (invoked by `film-room` at Step 4.6) to tag each fix by the earliest upstream point where the problem should have been caught.

## Taxonomy

### Failures (count against quality)

| Tag | When to use |
|---|---|
| `gameplan-criteria` | The acceptance criterion was vague, missing, wrong, or ambiguous. The agent did what the criterion said, but the criterion didn't specify the right thing. |
| `gameplan-scope` | The issue's file scope was wrong — the agent touched files it shouldn't have, or the decomposition put related changes in different issues. |
| `coding-misread` | The criterion was clear but the coding agent misinterpreted it. Distinguished from `coding-bug` by the presence of a clear criterion that, if followed correctly, would have prevented the defect. |
| `coding-bug` | A plain implementation bug — logic error, off-by-one, null handling, race condition, etc. Would have occurred even with a perfectly clear criterion. |
| `testing-missed` | Tests exist and passed, but should have caught the defect. The tests themselves were wrong, missing, or insufficient. |
| `review-missed` | The review agent should have flagged this in PR review but did not. Use only when the defect is plainly visible in the diff. |
| `gdd-gap` | The GDD itself was wrong, missing, or internally contradictory. Gameplan had nothing to write a sharp criterion from. This is upstream of gameplan. |

### Expected iteration (do NOT count against quality)

| Tag | When to use |
|---|---|
| `design-change` | The user changed their mind after seeing the output. The original criterion was met correctly; preference shifted. |
| `subjective-eval` | Fix to a criterion that was pre-tagged `[subjective]` in the structural check. Iteration on feel/aesthetics is the expected workflow for these. |

## Primary vs secondary tags

A fix has one **primary** tag and optionally one **secondary**. Primary is the **earliest upstream** point where the problem could have been caught:

```
gdd-gap  >  gameplan-*  >  coding-*  >  testing-missed  >  review-missed
```

If a fix was caused by BOTH a vague criterion AND an independent coding bug, primary is `gameplan-criteria` (earliest upstream) and secondary is `coding-bug`. This optimizes the data toward "where to invest in prompt improvements first."

For iteration tags (`design-change`, `subjective-eval`), there is no secondary — these are not failures and don't cascade.

## Confidence

- `high` — strong signal from user notes + diff + original criterion. You can quote the line that gave it away.
- `medium` — plausible inference but user notes are sparse or the diff is ambiguous.
- `low` — guessing from diff alone with no user reasoning given.

## Input data you will receive

The classifier is invoked as a `claude -p` subagent. It receives a single prompt that bundles:

1. The original version's issues (titles, bodies including acceptance criteria and any `[subjective]` tags).
2. The merged agent PRs (bodies and diffs) — what was originally delivered.
3. The fix branch commits (messages and diffs) — what film-room changed.
4. The tracking issue body — contains the user's fix notes and reasoning.
5. The rubric (this file).

## Output format (JSON — the subagent returns this)

Return a single JSON object, no prose, no code fences:

```json
{
  "fixes": [
    {
      "fix": "<one-line description derived from the commit message or tracking issue>",
      "primary": "<one of the tags above>",
      "secondary": "<one of the failure tags, or null>",
      "confidence": "<high | medium | low>",
      "reasoning": "<one to two sentences citing the specific signal you used>"
    }
  ],
  "summary": {
    "failures": {"gameplan-criteria": 4, "coding-misread": 2, "gdd-gap": 1},
    "iterations": {"design-change": 2},
    "total_fixes": 9,
    "first_pass_clean_issues": 1
  }
}
```

Omit tag keys from `failures` and `iterations` if they have zero counts. Keys must match the taxonomy exactly.

## Edge cases

- **No fixes.** If the fix branch had zero commits, do not run the classifier at all (film-room handles this upstream). This rubric does not apply.
- **Unparseable fix.** If a commit's purpose is unclear, tag with `confidence: low` and use your best guess for the primary tag. Do not omit the fix.
- **Multiple fixes in one commit.** Split into separate entries in the `fixes` array.
````

- [ ] **Step 2: Commit**

```bash
git -C /home/bryang/Dev_Space/playbook add skills/film-room/classification-rubric.md
git -C /home/bryang/Dev_Space/playbook commit -m "feat(film-room): add classification rubric"
```

---

## Task 6: Write the classifier subagent prompt

**Files:**
- Create: `skills/film-room/classifier-prompt.md`

- [ ] **Step 1: Create the prompt file**

This is the prompt that film-room passes to the `claude -p` subagent that does classification. It mirrors the distiller-prompt pattern (the distillers' prompts live at `skills/film-room/distillers/*.md`).

Write `skills/film-room/classifier-prompt.md` with this exact content:

````markdown
# Classifier Subagent Prompt

You are the playbook classifier. Your job is to read a bundle of version data — original issues, merged agent PRs, film-room fix commits, and the tracking issue — and classify each fix in the fix branch by the earliest upstream point where the problem should have been caught.

Read the rubric at `classification-rubric.md` (provided in the same message bundle). Do NOT invent new tags; use only the tags listed there.

## Your task

1. For each commit on the fix branch, extract one or more logical fixes. A commit may contain multiple logical fixes — split them.
2. For each fix, match it to one of the original acceptance criteria when possible. If a fix touches code that doesn't map to any criterion, note that in the reasoning and tag appropriately (often `design-change` or `gdd-gap`).
3. Apply the rubric to assign a primary tag, optional secondary, confidence level, and one-to-two-sentence reasoning.

## Output

Emit ONE JSON object, nothing else. No prose. No code fences. No leading or trailing whitespace. The exact schema is specified in `classification-rubric.md`.

## Budget and failure handling

If you cannot produce a valid JSON object within the budget, emit this literal fallback as your final output:

```json
{"error": "classifier-exceeded-budget-or-failed", "fixes": [], "summary": {"failures": {}, "iterations": {}, "total_fixes": 0, "first_pass_clean_issues": 0}}
```

Film-room treats this fallback as "classification unavailable" and writes a note to the metrics file without blocking the session.

## Input bundle

The invoker will pass you the bundle in this order:

1. `## Rubric` — contents of `classification-rubric.md`.
2. `## Original issues` — titles and bodies, including acceptance criteria with any `[subjective]` tags.
3. `## Merged agent PRs` — titles, bodies, and diffs.
4. `## Fix branch commits` — messages and patches.
5. `## Tracking issue` — the film-room tracking issue body with user fix notes.

Read them all before emitting output.
````

- [ ] **Step 2: Commit**

```bash
git -C /home/bryang/Dev_Space/playbook add skills/film-room/classifier-prompt.md
git -C /home/bryang/Dev_Space/playbook commit -m "feat(film-room): add classifier subagent prompt"
```

---

## Task 7: Integrate the classifier into film-room as Step 4.6

**Files:**
- Modify: `skills/film-room/SKILL.md`

- [ ] **Step 1: Locate the insertion point**

Open `skills/film-room/SKILL.md`. Find the end of `### Step 4.5 — Run distillers` — specifically the line that currently reads:

```
### Step 5 — Clean up
```

(This is the start of the next major step after distillers.)

Step 4.6 goes **between** the end of Step 4.5 and the start of Step 5.

- [ ] **Step 2: Insert Step 4.6 — Classification**

Immediately before `### Step 5 — Clean up`, insert this new section:

````markdown
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

   ```markdown
   # Playbook Metrics

   | Version | First-pass | Fixes | Top failure       | Cost   | Date       |
   |---------|-----------:|------:|-------------------|-------:|------------|
   | <rows — one per metrics file>                                                   |

   ## Current top failure modes (last 3 versions)

   <numbered list — sum of failure counts across the 3 most recent versions, ranked desc, with `(N fixes, M% of failures)` per line>

   ## Trends

   <one line per failure tag that appears in at least 2 of the last 3 versions, showing `tag: N → N → N (direction-label)`>
   ```

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
````

- [ ] **Step 3: Verify insertion**

Run: `grep -n "^### Step 4" skills/film-room/SKILL.md`
Expected: lines for `Step 4 — Execute merge`, `Step 4.5 — Run distillers`, `Step 4.6 — Run the classifier (metrics)`, `Step 4.7 — Regenerate `metrics/SUMMARY.md``. All present, in order.

- [ ] **Step 4: Commit**

```bash
git -C /home/bryang/Dev_Space/playbook add skills/film-room/SKILL.md
git -C /home/bryang/Dev_Space/playbook commit -m "feat(film-room): integrate Component 2 classifier as Step 4.6 and SUMMARY regen as Step 4.7"
```

---

## Task 8: Smoke test end-to-end on a fixture project

**Purpose:** Confirm the full pipeline produces correctly-shaped `metrics/` files. This is a manual verification step — no automated test, because the pipeline involves interactive skills.

- [ ] **Step 1: Pick a real playbook project to test on**

Use one of your active playbook projects (e.g., `paint-ballas-auto` or `snowie`) — whichever has a version in progress or a recently-completed version you can re-run.

If no suitable project exists, skip to Step 4 and verify manually by inspecting the diff in the playbook repo alone.

- [ ] **Step 2: Enable `show_checks` locally for visibility**

In the test project's `playbook.yaml`, add:

```yaml
metrics:
  show_checks: true
```

- [ ] **Step 3: Run gameplan on a fresh version**

Invoke `/playbook:gameplan` as the user normally would. Approve a small version (1-2 issues). Check:

- [ ] The structural check echo appeared before the "does this decomposition look right" prompt.
- [ ] The metrics file `metrics/vX.Y.md` exists in the test project after Phase 5.
- [ ] The metrics file has valid YAML frontmatter.
- [ ] The `## Classification (film-room)` section shows `_Not yet run_`.
- [ ] A `chore: record structural check for vX.Y` commit was made on `main`.

- [ ] **Step 4: Let agents run and then invoke film-room**

Let the orchestrator run the issues through to completion. Then invoke `/playbook:film-room`, make at least one intentional fix, and complete the merge. Check:

- [ ] The classification summary echo appeared at end of session.
- [ ] The metrics file's `## Classification (film-room)` section was populated.
- [ ] Frontmatter `failures`, `iterations`, `fixes_total`, `cost_usd` updated.
- [ ] `metrics/SUMMARY.md` was created and has a row for this version.
- [ ] A `chore: record metrics for vX.Y` commit landed on `main`.

- [ ] **Step 5: Regression check — `metrics.enabled: false`**

Flip `metrics.enabled` to `false` in `playbook.yaml` and run a toy gameplan + film-room flow again. Confirm:

- [ ] No `metrics/` files are written or modified.
- [ ] No metrics commits are made.
- [ ] The skills otherwise behave identically to pre-change behavior.

- [ ] **Step 6: Document findings**

If any step failed, file the specific issue (skill wording ambiguity, command error, formatting bug) and iterate on the affected skill file. If everything passed, write a short confirmation to the user and close out.

---

## Self-Review

### Spec coverage

- [x] Component 1 structural check — Task 3 (rubric), Task 4 (integration)
- [x] Component 2 LLM classification — Task 5 (rubric), Task 6 (prompt), Task 7 (integration as Step 4.6)
- [x] Component 3 storage — Task 2 (format ref), Task 4 (gameplan writes v-file), Task 7 (film-room completes v-file + SUMMARY regen)
- [x] Config schema — Task 1
- [x] `metrics.show_checks` visibility toggle — wired through Tasks 4 and 7
- [x] `metrics.enabled: false` kill switch — wired through Tasks 4 and 7
- [x] Special-case "no fixes made" — covered in Task 7 Step 2
- [x] Classifier error handling — covered in Task 7 Step 2 (subtype check + error payload)
- [x] Git commit pattern — covered in Task 4 Phase 5 and Task 7 Step 4.7
- [x] End-to-end smoke test — Task 8

### Placeholder scan

- No "TBD", "TODO", or vague step language.
- All file paths absolute or rooted at project repo.
- Every code-editing step shows the exact content to write.
- Every command shows the exact invocation.

### Type consistency

- Config keys (`metrics.enabled`, `metrics.show_checks`, `metrics.classification_budget_usd`) used identically in Tasks 1, 4, 7.
- Frontmatter keys (`version`, `date`, `issues`, `first_pass_clean`, `fixes_total`, `failures`, `iterations`, `cost_usd`) match across Tasks 2, 4, 7.
- Tag names match the rubric in all locations.
- File paths consistent: `metrics/vX.Y.md`, `metrics/bootstrap.md`, `metrics/SUMMARY.md`.
