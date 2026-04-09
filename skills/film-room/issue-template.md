# Issue Template for Film Room Sessions

Use this template when creating the tracking issue in Phase 1.
The issue body grows during the session as the user identifies fixes.

## Title Format

`[vX.Y] Film Room: Post-Agent Review`

For bootstrap: `[bootstrap] Film Room: Post-Agent Review`

## Body Template

~~~
## Film Room: vX.Y Post-Agent Review

**Branch:** `film-room/vX.Y`
**Version branch:** `ai/dev-vX.Y`

## Fixes
(items added during session)

## Notes
~~~

## Usage Notes

- The "Fixes" section starts empty. Items are appended as the user identifies
  problems during the working session.
- Each fix is a checklist item: `- [ ] Description` when identified,
  `- [x] Description` when committed.
- The "Notes" section captures any context added during the session — edge
  cases discovered, decisions made, things deferred.
- The full issue body is maintained in conversation context and pushed to
  GitHub via `gh issue edit --body` on each update.
