from prior_attempt import (
    STOP_TAG_PREFIX,
    render_prior_attempt_context,
    serialize_failure_comment,
    parse_failure_comment,
)


# ---- render_prior_attempt_context ----

def test_render_returns_empty_on_first_attempt():
    """No context block on attempt 1 — keeps the original prompt clean."""
    result = render_prior_attempt_context(
        history=[],
        latest_diff_stat="",
        snapshot_ref=None,
        wip_ref=None,
        stop_comment=None,
        attempt=1,
        integration_branch="ai/dev",
    )
    assert result == ""


def test_render_with_one_prior_failure_and_snapshot():
    history = [{"attempt": 1, "kind": "no-pr", "reason": "no PR opened"}]
    diff_stat = " src/foo.py | 2 ++\n 1 file changed, 2 insertions(+)"
    result = render_prior_attempt_context(
        history=history,
        latest_diff_stat=diff_stat,
        snapshot_ref="ai/issue-42-attempt-1",
        wip_ref="ai/issue-42-attempt-1-wip",
        stop_comment="Stopping: needs clarification",
        attempt=2,
        integration_branch="ai/dev",
    )
    assert "## Prior Attempt Context" in result
    assert "This is your attempt 2" in result
    assert "1 previous attempt" in result
    assert "Attempt 1: no-pr" in result
    assert "Stopping: needs clarification" in result
    assert "ai/issue-42-attempt-1" in result
    assert "ai/issue-42-attempt-1-wip" in result
    assert "src/foo.py | 2 ++" in result
    assert "git diff origin/ai/dev...origin/ai/issue-42-attempt-1" in result
    assert "input, not truth" in result


def test_render_with_multiple_failures_shows_all_in_history_but_only_latest_diff():
    history = [
        {"attempt": 1, "kind": "timeout", "reason": "timed out at 60min"},
        {"attempt": 2, "kind": "no-pr", "reason": "no PR opened"},
    ]
    result = render_prior_attempt_context(
        history=history,
        latest_diff_stat=" src/foo.py | 5 +",
        snapshot_ref="ai/issue-42-attempt-2",
        wip_ref=None,
        stop_comment=None,
        attempt=3,
        integration_branch="ai/dev",
    )
    assert "Attempt 1: timeout" in result
    assert "Attempt 2: no-pr" in result
    assert "ai/issue-42-attempt-2" in result
    # Only the latest snapshot's diff is rendered — earlier are not embedded
    assert result.count("Files changed") == 1


def test_render_snapshot_unavailable():
    history = [{"attempt": 1, "kind": "timeout", "reason": "timed out"}]
    result = render_prior_attempt_context(
        history=history,
        latest_diff_stat="",
        snapshot_ref=None,
        wip_ref=None,
        stop_comment=None,
        attempt=2,
        integration_branch="ai/dev",
    )
    assert "no snapshot" in result.lower()
    assert "feedback only" in result.lower()
    assert "Files changed" not in result


def test_render_omits_reasoning_subsection_when_no_stop_comment():
    history = [{"attempt": 1, "kind": "timeout", "reason": "timed out"}]
    result = render_prior_attempt_context(
        history=history,
        latest_diff_stat=" src/foo.py | 1 +",
        snapshot_ref="ai/issue-42-attempt-1",
        wip_ref=None,
        stop_comment=None,
        attempt=2,
        integration_branch="ai/dev",
    )
    assert "Latest attempt's reasoning" not in result


# ---- serialize_failure_comment ----

def test_serialize_failure_comment_human_readable_and_json():
    body = serialize_failure_comment(
        attempt=2,
        kind="timeout",
        reason="Agent timed out after 60 minutes",
        snapshot_ref="ai/issue-42-attempt-2",
        wip_ref="ai/issue-42-attempt-2-wip",
        log_path=".playbook/logs/foo.json",
        ts="2026-05-01T12:00:00Z",
    )
    # Human-readable surface
    assert body.startswith("[agent-orchestrator]")
    assert "Attempt 2" in body
    assert "timeout" in body
    assert "ai/issue-42-attempt-2" in body
    # JSON block exists and is parseable
    assert "<details>" in body
    assert "```json" in body
    parsed = parse_failure_comment(body)
    assert parsed is not None
    assert parsed["attempt"] == 2
    assert parsed["kind"] == "timeout"
    assert parsed["snapshot_ref"] == "ai/issue-42-attempt-2"


def test_serialize_with_unavailable_snapshot_uses_null_refs():
    body = serialize_failure_comment(
        attempt=2,
        kind="no-pr",
        reason="agent exited without PR",
        snapshot_ref=None,
        wip_ref=None,
        log_path=".playbook/logs/bar.json",
        ts="2026-05-01T12:00:00Z",
    )
    assert "snapshot unavailable" in body.lower()
    parsed = parse_failure_comment(body)
    assert parsed["snapshot_ref"] is None
    assert parsed["wip_ref"] is None


# ---- parse_failure_comment ----

def test_parse_returns_none_for_comment_without_json_block():
    assert parse_failure_comment("Just a regular human comment") is None
    assert parse_failure_comment("[agent-orchestrator] Attempt 1 completed (coding agent).") is None


def test_parse_returns_none_for_malformed_json():
    body = "[agent-orchestrator] Attempt 2 failed.\n\n<details>\n\n```json\n{not valid json\n```\n\n</details>"
    assert parse_failure_comment(body) is None


def test_parse_returns_dict_for_valid_json_block():
    body = (
        "[agent-orchestrator] Attempt 2 failed: timeout.\n\n"
        "<details><summary>diagnostic</summary>\n\n"
        "```json\n"
        '{"attempt": 2, "kind": "timeout", "reason": "timed out", '
        '"snapshot_ref": "ai/issue-42-attempt-2", "wip_ref": null, '
        '"log_path": ".playbook/logs/x.json", "ts": "2026-05-01T00:00:00Z"}\n'
        "```\n\n"
        "</details>"
    )
    result = parse_failure_comment(body)
    assert result is not None
    assert result["attempt"] == 2
    assert result["kind"] == "timeout"
    assert result["wip_ref"] is None


# ---- STOP_TAG_PREFIX ----

def test_stop_tag_prefix_format():
    """Tag includes 'attempt=' so it can be extended with the number."""
    assert STOP_TAG_PREFIX == "[ai-coding-agent: stop attempt="
