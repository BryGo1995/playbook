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
