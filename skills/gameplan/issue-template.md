# Issue Template for Playbook Versions

Use this template for every issue created by the plan-version skill.
Each issue serves as the single source of truth for coding, testing, and review agents.

## Title Format

`[vX.Y] Short description of the feature`

For bootstrap: `[bootstrap] Short description`

## Body Template

~~~
## Overview
Brief description of what this issue delivers and how it fits into the version milestone.

## Relevant GDD Sections
- Section X.Y — [quoted or summarized relevant requirements from the GDD]

## Acceptance Criteria
- [ ] Criterion 1 — specific, testable outcome
- [ ] Criterion 2 — specific, testable outcome
- [ ] Criterion 3 — specific, testable outcome

## Scope
**Files to create or modify:**
- `path/to/file.ext` — orientation context about what exists (if modifying) + what changes
- `path/to/new_file.ext` — new file, purpose and responsibility

**Do NOT touch:**
- `path/to/other.ext` — owned by issue #N in this version (only critical when max_coding > 1)

## Dependencies
- Assumes [vX.previous] work is merged: [brief description of what should already exist]
- If no prior version: "None — this is the first version" or "Assumes bootstrap is complete"

## Testing Criteria
- [ ] Expected behavior: [describe what should happen given specific input]
- [ ] Edge case: [describe boundary condition to test]
- [ ] Integration: [describe how this interacts with existing systems]
- [ ] Negative case: [describe what should NOT happen]

## Review Criteria
- [ ] GDD compliance: [specific GDD requirement to verify against]
- [ ] Architecture: [constraint to verify, e.g., "uses signals not direct references"]
- [ ] Code quality: [specific concern, e.g., "no hardcoded values for configurable settings"]

## Definition of Done
This issue is done when [concise statement tying acceptance criteria to testing validation].

## Notes
Any product-owner context, caveats, or edge-case guidance.
~~~

## Usage Notes

- Every field must be filled in. No "TBD" or "see GDD" without quoting the relevant part.
- The "Do NOT touch" section is only critical when max_coding > 1. Include it anyway for documentation but mark it as advisory when max_coding == 1.
- Testing criteria should be specific enough that the testing agent can write tests from them without re-reading the GDD.
- Review criteria should reference specific GDD sections or architectural decisions the review agent can verify.
- The Definition of Done should be a single sentence that an agent can evaluate as true/false.
