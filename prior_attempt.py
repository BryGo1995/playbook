# prior_attempt.py
"""Format and render prior-attempt context for retried coding agents.

Three responsibilities, kept in one module so the failure-comment format has a
single source of truth:
  - render_prior_attempt_context: build the prompt block fed to a retry agent
  - serialize_failure_comment: produce the human + JSON failure comment body
  - parse_failure_comment: extract the JSON dict from a comment body (or None)
"""
import json
import re

STOP_TAG_PREFIX = "[ai-coding-agent: stop attempt="
ORCHESTRATOR_TAG = "[agent-orchestrator]"

# Failure-kind discriminator stored in the diagnostic JSON block. Existing kinds
# in the wild: "no-pr", "timeout". "budget-cap" is new in the tiered-retry
# work — it means a prior attempt hit the per-attempt USD cap before committing,
# which changes how the next attempt should be prompted (resume aggressively
# rather than re-explore).
KIND_BUDGET_CAP = "budget-cap"

# Match a fenced ```json ... ``` block inside the comment. DOTALL so newlines match.
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def render_prior_attempt_context(
    history: list[dict],
    latest_diff_stat: str,
    snapshot_ref: str | None,
    wip_ref: str | None,
    stop_comment: str | None,
    attempt: int,
    integration_branch: str,
) -> str:
    """Render the PRIOR_ATTEMPT_CONTEXT block. Returns empty string on attempt 1."""
    if attempt <= 1 or not history:
        return ""

    lines: list[str] = []
    lines.append("## Prior Attempt Context")
    lines.append("")
    prior_count = attempt - 1
    plural = "attempts" if prior_count != 1 else "attempt"
    lines.append(
        f"This is your attempt {attempt}. "
        f"{prior_count} previous {plural} did not complete."
    )
    lines.append("")

    # Budget-cap retry preamble. When the most recent prior failure is a
    # budget-cap exhaustion, the prior attempt produced real WIP that was killed
    # mid-work — re-exploring the codebase wastes budget and is the exact thing
    # that just blew up. Promote "resume" from a suggestion (the generic
    # "How to use this" block below) to a directive.
    latest = max(history, key=lambda e: e.get("attempt", 0))
    if latest.get("kind") == KIND_BUDGET_CAP:
        lines.append("### ⚠️ MANDATORY: Resume from the snapshot")
        lines.append("")
        lines.append(
            "The previous attempt hit the per-attempt USD budget cap before "
            "it could commit and push. Do NOT start from scratch on this retry."
        )
        lines.append("")
        lines.append("On this attempt you MUST:")
        lines.append(
            "1. Check out the snapshot ref below directly as your starting point. "
            "Do not branch from the integration branch."
        )
        lines.append(
            "2. Use the diff-stat below as your map of what the prior attempt "
            "already changed. Do NOT re-read those files unless you must verify "
            "a specific line — every re-read costs budget."
        )
        lines.append(
            "3. Prioritize committing and pushing forward progress over verifying "
            "perfection. A PR with imperfect tests but working code is rescuable; "
            "an uncommitted working tree is not."
        )
        lines.append(
            "4. Commit incrementally as you go — do not save all commits for the "
            "end. If the cap hits again, what's pushed is what survives."
        )
        lines.append("")

    # Failure history — one line per past attempt
    lines.append("### Failure history")
    for entry in sorted(history, key=lambda e: e["attempt"]):
        lines.append(f"- Attempt {entry['attempt']}: {entry['kind']} — {entry['reason']}")
    lines.append("")

    # Stop comment (only if present)
    if stop_comment:
        lines.append("### Latest attempt's reasoning")
        for line in stop_comment.strip().splitlines():
            lines.append(f"> {line}")
        lines.append("")

    # Code state
    lines.append("### Latest attempt's code state")
    if snapshot_ref is None:
        lines.append("No snapshot available — prior attempt produced no recoverable code state.")
        lines.append("Continue based on failure history and reasoning above (feedback only).")
    else:
        lines.append(f"Snapshot ref: {snapshot_ref}  (committed only)")
        if wip_ref:
            lines.append(f"WIP ref:      {wip_ref}  (uncommitted/untracked)")
        lines.append("")
        lines.append(f"Files changed (vs {integration_branch}):")
        lines.append(latest_diff_stat.rstrip())
        lines.append("")
        lines.append("To inspect the full diff:")
        lines.append(
            f"  git fetch origin && git diff "
            f"origin/{integration_branch}...origin/{snapshot_ref}"
        )
    lines.append("")

    # How-to-use
    lines.append("### How to use this")
    lines.append(
        "A previous attempt produced the work above. Treat it as input, not truth.\n"
        "If the approach is wrong, discard it and start over. Resuming is a means,\n"
        "not a goal. You are NOT obligated to keep any of the prior code."
    )
    lines.append("")
    return "\n".join(lines)


def serialize_failure_comment(
    attempt: int,
    kind: str,
    reason: str,
    snapshot_ref: str | None,
    wip_ref: str | None,
    log_path: str,
    ts: str,
) -> str:
    """Build the failure comment body — human-readable surface + JSON in <details>."""
    if snapshot_ref is None:
        snapshot_line = "Snapshot unavailable"
    else:
        wip_part = f" (with WIP ref {wip_ref})" if wip_ref else ""
        snapshot_line = f"Snapshot: {snapshot_ref}{wip_part}"

    payload = {
        "attempt": attempt,
        "kind": kind,
        "reason": reason,
        "snapshot_ref": snapshot_ref,
        "wip_ref": wip_ref,
        "log_path": log_path,
        "ts": ts,
    }
    json_block = json.dumps(payload, sort_keys=True)

    return (
        f"{ORCHESTRATOR_TAG} Attempt {attempt} failed: {kind}.\n"
        f"Reason: {reason}\n"
        f"{snapshot_line}\n"
        f"Log: {log_path}\n"
        f"\n"
        f"<details><summary>diagnostic</summary>\n"
        f"\n"
        f"```json\n"
        f"{json_block}\n"
        f"```\n"
        f"\n"
        f"</details>"
    )


def parse_failure_comment(body: str) -> dict | None:
    """Extract the diagnostic JSON dict from a failure comment, or return None."""
    match = _JSON_BLOCK_RE.search(body)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
