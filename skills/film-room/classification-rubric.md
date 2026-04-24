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
