# Resume Coding-Agent Progress on Failure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a coding agent fails (timeout or exit-without-PR), preserve its in-progress work as remote git refs and feed structured prior-attempt context into the next attempt's prompt.

**Architecture:** A new `prior_attempt.py` module owns the failure-comment format (serialize + parse) and the prompt-context renderer. The orchestrator gains `_snapshot_branch` (best-effort git push of WIP-stash + branch as `ai/issue-N-attempt-K[/-wip]` refs) called from both the timeout and no-PR paths. `_dispatch_coding` becomes retry-aware: on `attempt > 1` it queries `git ls-remote` for the latest snapshot, fetches structured failure history + the matching agent stop comment, and renders a context block injected into the existing `CODING_PROMPT` template. A feature flag `guardrails.snapshot_on_failure` provides a kill switch.

**Tech Stack:** Python 3 (no new deps), pytest with `unittest.mock` (existing pattern), `subprocess.run` for git operations, GitHub REST API via the existing `_rest_get`/`_rest_post` helpers.

**Spec:** `docs/specs/2026-05-01-resume-on-failure-design.md`

**Tracking issue:** [#12](https://github.com/BryGo1995/playbook/issues/12)

---

## File Structure

**New files:**
- `prior_attempt.py` (project root) — owns the failure-comment format and prompt-context renderer. Three module-level functions: `render_prior_attempt_context`, `serialize_failure_comment`, `parse_failure_comment`. Plus the `STOP_TAG_PREFIX` constant. Pure functions, no I/O.
- `tests/test_prior_attempt.py` — full coverage for the three functions.

**Modified files:**
- `defaults.yaml` — add `guardrails.snapshot_on_failure: true`.
- `github_client.py` — add `get_attempt_failure_history` and `get_latest_agent_stop_comment`; fix `get_attempt_count` to count new structured failures.
- `agents/coding.py` — add `{prior_attempt_context}` placeholder to `CODING_PROMPT`; add `attempt` and `prior_attempt_context` parameters to `build_prompt`/`build_command`; add the stop-tag instruction.
- `orchestrator.py` — add `_snapshot_branch` method; wire snapshots into `_handle_timeout` and `_handle_completion`'s no-PR branch; make `_dispatch_coding` retry-aware; add snapshot-ref cleanup to `_process_complete_issues`.
- `tests/test_github_client.py` — extend with new helpers and the `get_attempt_count` correctness test.
- `tests/test_agents.py` — extend with prompt-template tests.
- `tests/test_orchestrator.py` — extend with `_snapshot_branch` and dispatch-retry tests.
- `README.md` — operational note about the `ai/issue-*-attempt-*` ref namespace and the kill switch.

**No changes to:** `state.py`, `versioning.py`, `summary.py`, `agents/testing.py`, `agents/review.py`, `agents/base.py`.

---

## Task 1: Add `snapshot_on_failure` config flag

**Files:**
- Modify: `defaults.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_snapshot_on_failure_default(tmp_path):
    """guardrails.snapshot_on_failure defaults to True."""
    import shutil, os
    defaults_dir = tmp_path / "playbook"
    defaults_dir.mkdir()
    real_defaults = os.path.join(os.path.dirname(os.path.dirname(__file__)), "defaults.yaml")
    shutil.copy(real_defaults, defaults_dir / "defaults.yaml")

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("repo: owner/my-project\n")

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults_dir / "defaults.yaml"))
    assert cfg["guardrails"]["snapshot_on_failure"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_snapshot_on_failure_default -v`
Expected: FAIL — KeyError or AssertionError on `snapshot_on_failure`.

- [ ] **Step 3: Add the flag to `defaults.yaml`**

In `defaults.yaml`, modify the `guardrails:` section to:

```yaml
guardrails:
  max_files_changed: 10
  max_retry_cycles: 3
  snapshot_on_failure: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_snapshot_on_failure_default -v`
Expected: PASS.

- [ ] **Step 5: Run full config test suite to confirm no regression**

Run: `pytest tests/test_config.py -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add defaults.yaml tests/test_config.py
git commit -m "feat(config): add guardrails.snapshot_on_failure feature flag (#12)"
```

---

## Task 2: Create `prior_attempt.py` — pure renderer + serializer + parser (TDD)

**Files:**
- Create: `prior_attempt.py`
- Create: `tests/test_prior_attempt.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prior_attempt.py`:

```python
import json
import pytest
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_prior_attempt.py -v`
Expected: All tests FAIL with `ModuleNotFoundError: No module named 'prior_attempt'`.

- [ ] **Step 3: Implement `prior_attempt.py`**

Create `prior_attempt.py` at the project root:

```python
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
        snapshot_line = "Snapshot: unavailable"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_prior_attempt.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add prior_attempt.py tests/test_prior_attempt.py
git commit -m "feat: add prior_attempt module — context renderer + failure-comment format (#12)"
```

---

## Task 3: GitHub client — `get_attempt_failure_history` (TDD)

**Files:**
- Modify: `github_client.py` (add new helper; place near `get_attempt_count` around line 285)
- Test: `tests/test_github_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_github_client.py`:

```python
def test_get_attempt_failure_history_parses_structured_comments(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": (
            "[agent-orchestrator] Attempt 1 failed: timeout.\n\n"
            "<details><summary>diagnostic</summary>\n\n"
            "```json\n"
            '{"attempt": 1, "kind": "timeout", "reason": "timed out", '
            '"snapshot_ref": "ai/issue-42-attempt-1", "wip_ref": null, '
            '"log_path": ".playbook/logs/a.json", "ts": "2026-05-01T01:00:00Z"}\n'
            "```\n\n</details>"
        )},
        {"body": "Just a human comment"},
        {"body": (
            "[agent-orchestrator] Attempt 2 failed: no-pr.\n\n"
            "<details><summary>diagnostic</summary>\n\n"
            "```json\n"
            '{"attempt": 2, "kind": "no-pr", "reason": "no PR", '
            '"snapshot_ref": "ai/issue-42-attempt-2", "wip_ref": "ai/issue-42-attempt-2-wip", '
            '"log_path": ".playbook/logs/b.json", "ts": "2026-05-01T02:00:00Z"}\n'
            "```\n\n</details>"
        )},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    history = client.get_attempt_failure_history("owner/repo", 42)
    assert len(history) == 2
    assert history[0]["attempt"] == 1
    assert history[1]["attempt"] == 2
    assert history[1]["kind"] == "no-pr"


def test_get_attempt_failure_history_drops_malformed_json(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": "[agent-orchestrator] Attempt 1 failed.\n\n```json\n{not valid\n```"},
        {"body": (
            "[agent-orchestrator] Attempt 2 failed.\n\n```json\n"
            '{"attempt": 2, "kind": "timeout", "reason": "x", "snapshot_ref": null, '
            '"wip_ref": null, "log_path": "", "ts": ""}\n```'
        )},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    history = client.get_attempt_failure_history("owner/repo", 42)
    assert len(history) == 1
    assert history[0]["attempt"] == 2


def test_get_attempt_failure_history_empty_for_legacy_only_comments(client):
    """Old-format comments (no JSON block) yield empty history — backward compat."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": "[agent-orchestrator] Attempt 1 completed (coding agent)."},
        {"body": "[agent-orchestrator] Agent timed out after 60 minutes."},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    history = client.get_attempt_failure_history("owner/repo", 42)
    assert history == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_github_client.py -v -k get_attempt_failure_history`
Expected: All three FAIL — `AttributeError: 'GitHubClient' object has no attribute 'get_attempt_failure_history'`.

- [ ] **Step 3: Add the helper to `github_client.py`**

Add to `github_client.py`, right after `get_attempt_count` (around line 295):

```python
    def get_attempt_failure_history(self, repo_name: str, issue_number: int) -> list[dict]:
        """Walk issue comments, return parsed failure-diagnostic dicts sorted by attempt."""
        from prior_attempt import parse_failure_comment, ORCHESTRATOR_TAG

        owner, repo = repo_name.split("/")
        comments = self._rest_get(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")
        entries: list[dict] = []
        for c in comments:
            body = c.get("body", "")
            if not body.startswith(ORCHESTRATOR_TAG):
                continue
            parsed = parse_failure_comment(body)
            if parsed is None:
                continue
            entries.append(parsed)
        entries.sort(key=lambda e: e.get("attempt", 0))
        return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_github_client.py -v -k get_attempt_failure_history`
Expected: All three PASS.

- [ ] **Step 5: Commit**

```bash
git add github_client.py tests/test_github_client.py
git commit -m "feat(gh): add get_attempt_failure_history helper (#12)"
```

---

## Task 4: GitHub client — `get_latest_agent_stop_comment` (TDD)

**Files:**
- Modify: `github_client.py`
- Test: `tests/test_github_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_github_client.py`:

```python
def test_get_latest_agent_stop_comment_filters_by_attempt(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": "[ai-coding-agent: stop attempt=1] First stop reasoning."},
        {"body": "[agent-orchestrator] Attempt 1 failed."},
        {"body": "[ai-coding-agent: stop attempt=2] Second stop reasoning."},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.get_latest_agent_stop_comment("owner/repo", 42, 1) == "First stop reasoning."
    assert client.get_latest_agent_stop_comment("owner/repo", 42, 2) == "Second stop reasoning."


def test_get_latest_agent_stop_comment_returns_none_when_no_match(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": "[ai-coding-agent: stop attempt=1] reasoning."},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.get_latest_agent_stop_comment("owner/repo", 42, 3) is None


def test_get_latest_agent_stop_comment_picks_most_recent_when_duplicates(client):
    """If somehow two stop comments share an attempt, the later one wins."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": "[ai-coding-agent: stop attempt=1] earlier"},
        {"body": "[ai-coding-agent: stop attempt=1] later"},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.get_latest_agent_stop_comment("owner/repo", 42, 1) == "later"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_github_client.py -v -k get_latest_agent_stop_comment`
Expected: All three FAIL — `AttributeError`.

- [ ] **Step 3: Add the helper to `github_client.py`**

Add to `github_client.py`, right after `get_attempt_failure_history`:

```python
    def get_latest_agent_stop_comment(
        self, repo_name: str, issue_number: int, attempt: int
    ) -> str | None:
        """Return the body (minus the tag) of the most recent stop comment for the given attempt."""
        from prior_attempt import STOP_TAG_PREFIX

        owner, repo = repo_name.split("/")
        comments = self._rest_get(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")
        target_prefix = f"{STOP_TAG_PREFIX}{attempt}]"
        match: str | None = None
        for c in comments:
            body = c.get("body", "")
            if body.startswith(target_prefix):
                match = body[len(target_prefix):].lstrip()
        return match
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_github_client.py -v -k get_latest_agent_stop_comment`
Expected: All three PASS.

- [ ] **Step 5: Commit**

```bash
git add github_client.py tests/test_github_client.py
git commit -m "feat(gh): add get_latest_agent_stop_comment helper (#12)"
```

---

## Task 5: Fix `get_attempt_count` to count new structured failures (TDD)

**Files:**
- Modify: `github_client.py:285-294`
- Test: `tests/test_github_client.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_github_client.py`:

```python
def test_get_attempt_count_counts_new_structured_failures(client):
    """Structured timeout/no-pr failures with JSON blocks should be counted."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": (
            "[agent-orchestrator] Attempt 1 failed: timeout.\n\n```json\n"
            '{"attempt": 1, "kind": "timeout", "reason": "x", "snapshot_ref": null, '
            '"wip_ref": null, "log_path": "", "ts": ""}\n```'
        )},
        {"body": "[agent-orchestrator] Attempt 2 completed (coding agent)."},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.get_attempt_count("owner/repo", 42) == 2


def test_get_attempt_count_counts_legacy_format_only(client):
    """Pure legacy comments still count correctly — backward compat."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": "[agent-orchestrator] Attempt 1 completed (coding agent) but no PR found."},
        {"body": "[agent-orchestrator] Attempt 2 completed (coding agent)."},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.get_attempt_count("owner/repo", 42) == 2


def test_get_attempt_count_dedupes_same_attempt_across_formats(client):
    """A single attempt that produced both a structured failure and (somehow) a legacy
    comment should only count once — by attempt number."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": (
            "[agent-orchestrator] Attempt 1 failed: timeout.\n\n```json\n"
            '{"attempt": 1, "kind": "timeout", "reason": "x", "snapshot_ref": null, '
            '"wip_ref": null, "log_path": "", "ts": ""}\n```'
        )},
        {"body": "[agent-orchestrator] Attempt 1 completed (coding agent) but no PR found."},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.get_attempt_count("owner/repo", 42) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_github_client.py -v -k get_attempt_count`
Expected: `test_get_attempt_count_counts_new_structured_failures` FAILS (counts 1, expected 2). `test_get_attempt_count_dedupes_same_attempt_across_formats` likely FAILS (counts 1 — coincidentally right but for the wrong reason; rerun after refactor). Legacy test PASSES.

- [ ] **Step 3: Replace `get_attempt_count` in `github_client.py:285-294`**

Replace the existing `get_attempt_count` method with:

```python
    def get_attempt_count(self, repo_name: str, issue_number: int) -> int:
        """Count distinct coding-agent attempts on an issue.

        Counts by attempt number to avoid double-counting an attempt that left both
        a structured failure JSON block AND a legacy completion comment. Falls back
        to legacy substring matching for comments predating the structured format.
        """
        from prior_attempt import parse_failure_comment

        owner, repo = repo_name.split("/")
        comments = self._rest_get(f"/repos/{owner}/{repo}/issues/{issue_number}/comments")
        attempts: set[int] = set()
        for c in comments:
            body = c.get("body", "")
            if not body.startswith(ORCHESTRATOR_TAG):
                continue
            # Prefer structured JSON when present
            parsed = parse_failure_comment(body)
            if parsed is not None and "attempt" in parsed:
                attempts.add(int(parsed["attempt"]))
                continue
            # Legacy fallback: "Attempt N completed (coding agent)"
            if "Attempt" in body and "completed" in body and "coding agent" in body:
                # Extract the number after "Attempt "
                import re
                m = re.search(r"Attempt\s+(\d+)", body)
                if m:
                    attempts.add(int(m.group(1)))
        return len(attempts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_github_client.py -v -k get_attempt_count`
Expected: All three new tests PASS, plus the original `test_get_attempt_count` (from before this change) still PASSES.

- [ ] **Step 5: Commit**

```bash
git add github_client.py tests/test_github_client.py
git commit -m "fix(gh): count timeout failures in get_attempt_count, dedupe by attempt (#12)"
```

---

## Task 6: Orchestrator — `_snapshot_branch` method (TDD)

**Files:**
- Modify: `orchestrator.py` (add new method)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orchestrator.py`:

```python
def _make_completed_process(returncode=0, stdout="", stderr=""):
    """Helper for mocking subprocess.run results."""
    cp = MagicMock()
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_snapshot_branch_happy_path(MockGH, MockRun, config, state_dir):
    """All git steps succeed → status 'ok', both refs returned."""
    MockGH.return_value = MagicMock()
    # Sequence: rev-parse (branch exists), stash push (created), rev-parse stash sha,
    # push branch, push stash, stash drop
    MockRun.side_effect = [
        _make_completed_process(0),                         # rev-parse --verify ai/issue-42
        _make_completed_process(0, stdout="stashed."),      # git stash push
        _make_completed_process(0, stdout="abc123\n"),      # git rev-parse stash@{0}
        _make_completed_process(0),                         # push branch ref
        _make_completed_process(0),                         # push stash ref
        _make_completed_process(0),                         # stash drop
    ]
    orch = Orchestrator(config, state_dir=state_dir)

    result = orch._snapshot_branch("owner/repo", 42, attempt=1)

    assert result["status"] == "ok"
    assert result["snapshot_ref"] == "ai/issue-42-attempt-1"
    assert result["wip_ref"] == "ai/issue-42-attempt-1-wip"


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_snapshot_branch_no_branch_exists(MockGH, MockRun, config, state_dir):
    """rev-parse fails → branch never existed → status 'unavailable', no pushes attempted."""
    MockGH.return_value = MagicMock()
    MockRun.side_effect = [
        _make_completed_process(returncode=128),  # rev-parse --verify fails
    ]
    orch = Orchestrator(config, state_dir=state_dir)

    result = orch._snapshot_branch("owner/repo", 42, attempt=1)

    assert result["status"] == "unavailable"
    assert result["snapshot_ref"] is None
    assert result["wip_ref"] is None
    # Only one subprocess call (the rev-parse)
    assert MockRun.call_count == 1


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_snapshot_branch_partial_when_stash_push_fails(MockGH, MockRun, config, state_dir):
    """Stash created but stash-ref push fails → status 'partial', base ref populated, no exception."""
    MockGH.return_value = MagicMock()
    MockRun.side_effect = [
        _make_completed_process(0),                         # rev-parse branch
        _make_completed_process(0, stdout="stashed."),      # stash push (created)
        _make_completed_process(0, stdout="abc123\n"),      # rev-parse stash@{0}
        _make_completed_process(0),                         # push branch (success)
        _make_completed_process(returncode=1, stderr="permission denied"),  # push stash (fail)
        _make_completed_process(0),                         # stash drop (still runs)
    ]
    orch = Orchestrator(config, state_dir=state_dir)

    result = orch._snapshot_branch("owner/repo", 42, attempt=2)

    assert result["status"] == "partial"
    assert result["snapshot_ref"] == "ai/issue-42-attempt-2"
    assert result["wip_ref"] is None


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_snapshot_branch_unavailable_when_branch_push_fails(MockGH, MockRun, config, state_dir):
    """Branch push fails entirely → status 'unavailable', stash still dropped."""
    MockGH.return_value = MagicMock()
    MockRun.side_effect = [
        _make_completed_process(0),                                     # rev-parse branch
        _make_completed_process(0, stdout="No local changes to save."), # stash push (no stash)
        _make_completed_process(returncode=1, stderr="auth failed"),    # push branch (fail)
        # No stash to drop
    ]
    orch = Orchestrator(config, state_dir=state_dir)

    result = orch._snapshot_branch("owner/repo", 42, attempt=1)

    assert result["status"] == "unavailable"
    assert result["snapshot_ref"] is None
    assert result["wip_ref"] is None


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_snapshot_branch_no_dirty_state_succeeds_with_no_wip(MockGH, MockRun, config, state_dir):
    """Clean working tree → no stash, only branch ref pushed → status 'ok' with wip_ref=None."""
    MockGH.return_value = MagicMock()
    MockRun.side_effect = [
        _make_completed_process(0),                                     # rev-parse branch
        _make_completed_process(0, stdout="No local changes to save."), # stash push (no stash)
        _make_completed_process(0),                                     # push branch
    ]
    orch = Orchestrator(config, state_dir=state_dir)

    result = orch._snapshot_branch("owner/repo", 42, attempt=1)

    assert result["status"] == "ok"
    assert result["snapshot_ref"] == "ai/issue-42-attempt-1"
    assert result["wip_ref"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v -k snapshot_branch`
Expected: All FAIL — `AttributeError: 'Orchestrator' object has no attribute '_snapshot_branch'`.

- [ ] **Step 3: Add the method to `orchestrator.py`**

Add to the `Orchestrator` class in `orchestrator.py` (place right before `_dispatch_coding`, around line 315):

```python
    def _snapshot_branch(self, repo: str, issue_number: int, attempt: int) -> dict:
        """Best-effort snapshot of the current ai/issue-N branch + dirty state.

        Returns a dict with keys: snapshot_ref, wip_ref, status (ok|partial|unavailable),
        error. Never raises. Steps are independently try/except'd; partial successes
        are reflected in the returned status.
        """
        branch = f"ai/issue-{issue_number}"
        snapshot_ref_name = f"ai/issue-{issue_number}-attempt-{attempt}"
        wip_ref_name = f"ai/issue-{issue_number}-attempt-{attempt}-wip"
        result = {
            "snapshot_ref": None,
            "wip_ref": None,
            "status": "unavailable",
            "error": None,
        }

        # 0. Does the branch even exist locally?
        check = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            capture_output=True, text=True,
        )
        if check.returncode != 0:
            result["error"] = "branch does not exist locally"
            return result

        # 1. Stash dirty state (if any). --include-untracked respects .gitignore.
        stash_msg = f"[playbook] attempt-{attempt} WIP"
        stash = subprocess.run(
            ["git", "stash", "push", "--include-untracked", "--message", stash_msg],
            capture_output=True, text=True,
        )
        stash_created = (
            stash.returncode == 0
            and "No local changes to save" not in stash.stdout
            and "No local changes to save" not in stash.stderr
        )

        stash_sha: str | None = None
        if stash_created:
            sha = subprocess.run(
                ["git", "rev-parse", "stash@{0}"],
                capture_output=True, text=True,
            )
            if sha.returncode == 0:
                stash_sha = sha.stdout.strip()

        # 2. Push the branch as the snapshot ref.
        try:
            push_branch = subprocess.run(
                ["git", "push", "--force", "origin",
                 f"{branch}:refs/heads/{snapshot_ref_name}"],
                capture_output=True, text=True,
            )
            if push_branch.returncode == 0:
                result["snapshot_ref"] = snapshot_ref_name
            else:
                result["error"] = f"branch push failed: {push_branch.stderr.strip()}"
        except Exception as e:
            result["error"] = f"branch push exception: {e}"

        # 3. Push the stash sha as the wip ref (if we have one).
        if stash_sha is not None and result["snapshot_ref"] is not None:
            try:
                push_wip = subprocess.run(
                    ["git", "push", "--force", "origin",
                     f"{stash_sha}:refs/heads/{wip_ref_name}"],
                    capture_output=True, text=True,
                )
                if push_wip.returncode == 0:
                    result["wip_ref"] = wip_ref_name
            except Exception:
                pass  # best-effort — stash is forensic only

        # 4. Drop the local stash (always — don't leave dirty state behind).
        if stash_created:
            subprocess.run(["git", "stash", "drop"], capture_output=True, text=True)

        # 5. Decide overall status.
        if result["snapshot_ref"] is None:
            result["status"] = "unavailable"
        elif stash_sha is not None and result["wip_ref"] is None:
            # We had a stash but couldn't push it
            result["status"] = "partial"
        else:
            result["status"] = "ok"

        return result
```

- [ ] **Step 4: Add the import for `subprocess` at the top of `orchestrator.py` (verify it's already imported)**

Check `orchestrator.py:4`. `subprocess` is already imported. No change needed.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v -k snapshot_branch`
Expected: All five tests PASS.

- [ ] **Step 6: Run the full orchestrator test suite to confirm no regression**

Run: `pytest tests/test_orchestrator.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orch): add _snapshot_branch best-effort failure-state preservation (#12)"
```

---

## Task 7: Wire snapshots into `_handle_timeout` and `_handle_completion` (TDD)

**Files:**
- Modify: `orchestrator.py:92-109` (timeout) and `orchestrator.py:119-155` (completion's no-PR branch)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orchestrator.py`:

```python
@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_handle_timeout_calls_snapshot_and_posts_structured_comment(
    MockGH, MockRun, config, state_dir
):
    mock_gh = MockGH.return_value
    # Snapshot subprocess sequence: rev-parse, stash, push branch (clean tree)
    MockRun.side_effect = [
        _make_completed_process(0),
        _make_completed_process(0, stdout="No local changes to save."),
        _make_completed_process(0),
    ]
    orch = Orchestrator(config, state_dir=state_dir)
    agent = {
        "pid": 99999,
        "issue": "owner/repo#42",
        "repo": "owner/repo",
        "type": "coding",
        "started_at": "2026-05-01T00:00:00+00:00",
        "timeout_minutes": 60,
        "attempt": 1,
        "project_item_id": "item_1",
    }
    orch.state.agents = [agent]

    with patch("os.kill"):
        orch._handle_timeout(agent)

    # The comment posted to the issue must contain the structured failure JSON
    posted_bodies = [c.kwargs.get("body") or c.args[2] for c in mock_gh.add_comment.call_args_list]
    assert any('"kind": "timeout"' in b for b in posted_bodies)
    assert any('"attempt": 1' in b for b in posted_bodies)
    assert any("ai/issue-42-attempt-1" in b for b in posted_bodies)


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_handle_completion_no_pr_calls_snapshot_and_posts_structured_comment(
    MockGH, MockRun, config, state_dir
):
    mock_gh = MockGH.return_value
    mock_gh.find_pr_for_branch.return_value = None  # mode b: no PR
    MockRun.side_effect = [
        _make_completed_process(0),
        _make_completed_process(0, stdout="No local changes to save."),
        _make_completed_process(0),
    ]
    orch = Orchestrator(config, state_dir=state_dir)
    agent = {
        "pid": 99998,
        "issue": "owner/repo#42",
        "repo": "owner/repo",
        "type": "coding",
        "started_at": "2026-05-01T00:00:00+00:00",
        "timeout_minutes": 60,
        "attempt": 2,
        "project_item_id": "item_1",
    }
    orch.state.agents = [agent]

    # _handle_completion checks os.kill via _is_process_alive — bypass via direct call
    orch._handle_completion(agent)

    posted_bodies = [c.kwargs.get("body") or c.args[2] for c in mock_gh.add_comment.call_args_list]
    assert any('"kind": "no-pr"' in b for b in posted_bodies)
    assert any('"attempt": 2' in b for b in posted_bodies)


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_handle_timeout_skips_snapshot_when_feature_flag_disabled(
    MockGH, MockRun, config, state_dir
):
    config["guardrails"]["snapshot_on_failure"] = False
    mock_gh = MockGH.return_value
    orch = Orchestrator(config, state_dir=state_dir)
    agent = {
        "pid": 99997,
        "issue": "owner/repo#42",
        "repo": "owner/repo",
        "type": "coding",
        "started_at": "2026-05-01T00:00:00+00:00",
        "timeout_minutes": 60,
        "attempt": 1,
        "project_item_id": "item_1",
    }
    orch.state.agents = [agent]

    with patch("os.kill"):
        orch._handle_timeout(agent)

    # No subprocess calls (no snapshot attempted)
    assert MockRun.call_count == 0
    # Legacy unstructured comment still posted
    posted_bodies = [c.kwargs.get("body") or c.args[2] for c in mock_gh.add_comment.call_args_list]
    assert any("timed out" in b for b in posted_bodies)
    # No JSON block in any comment
    assert not any("```json" in b for b in posted_bodies)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v -k handle_timeout or test_handle_completion_no_pr`
Expected: FAIL — comments don't contain JSON block (snapshot not yet wired in).

- [ ] **Step 3: Modify `_handle_timeout` in `orchestrator.py:92-109`**

Replace the existing `_handle_timeout` method with:

```python
    def _handle_timeout(self, agent: dict):
        from datetime import datetime, timezone
        from prior_attempt import serialize_failure_comment

        pid = agent["pid"]
        issue = agent["issue"]
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])
        project_item_id = agent.get("project_item_id")
        attempt = agent["attempt"]

        logger.warning(f"Agent timed out: {issue} (pid={pid})")
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        # Take a snapshot, if enabled
        snapshot_ref = None
        wip_ref = None
        snapshot_status = "skipped"
        if self.config.get("guardrails", {}).get("snapshot_on_failure", True):
            snap = self._snapshot_branch(repo, issue_number, attempt)
            snapshot_ref = snap["snapshot_ref"]
            wip_ref = snap["wip_ref"]
            snapshot_status = snap["status"]

        if project_item_id:
            self.gh.update_status(project_item_id, self.statuses["error"])

        if snapshot_status == "skipped":
            # Legacy comment
            self.gh.add_comment(
                repo, issue_number,
                f"[agent-orchestrator] Agent timed out after {agent['timeout_minutes']} minutes."
            )
        else:
            body = serialize_failure_comment(
                attempt=attempt,
                kind="timeout",
                reason=f"Agent timed out after {agent['timeout_minutes']} minutes",
                snapshot_ref=snapshot_ref,
                wip_ref=wip_ref,
                log_path=self.state.logs_dir,
                ts=datetime.now(timezone.utc).isoformat(),
            )
            self.gh.add_comment(repo, issue_number, body)

        self.slack.notify_timeout(issue, agent["timeout_minutes"])
        self.state.remove_agent(pid)
```

- [ ] **Step 4: Modify the no-PR branch of `_handle_completion` in `orchestrator.py:119-141`**

Replace the no-PR check block (the `if pr_number is None:` branch around line 132-141) with:

```python
        # For coding agents, verify a PR was actually created before advancing
        if agent["type"] == "coding":
            from datetime import datetime, timezone
            from prior_attempt import serialize_failure_comment

            pr_branch = f"ai/issue-{issue_number}"
            pr_number = self.gh.find_pr_for_branch(repo, pr_branch)
            if pr_number is None:
                logger.warning(f"Coding agent exited without creating PR for {issue}")
                attempt = agent["attempt"]

                snapshot_ref = None
                wip_ref = None
                snapshot_status = "skipped"
                if self.config.get("guardrails", {}).get("snapshot_on_failure", True):
                    snap = self._snapshot_branch(repo, issue_number, attempt)
                    snapshot_ref = snap["snapshot_ref"]
                    wip_ref = snap["wip_ref"]
                    snapshot_status = snap["status"]

                if snapshot_status == "skipped":
                    self.gh.add_comment(
                        repo, issue_number,
                        f"[agent-orchestrator] Attempt {attempt} completed (coding agent) "
                        f"but no PR found on branch `{pr_branch}`. Marking as error."
                    )
                else:
                    body = serialize_failure_comment(
                        attempt=attempt,
                        kind="no-pr",
                        reason=f"Coding agent completed but no PR found on branch {pr_branch}",
                        snapshot_ref=snapshot_ref,
                        wip_ref=wip_ref,
                        log_path=self.state.logs_dir,
                        ts=datetime.now(timezone.utc).isoformat(),
                    )
                    self.gh.add_comment(repo, issue_number, body)

                if project_item_id:
                    self.gh.update_status(project_item_id, self.statuses["error"])
                self.slack.notify_error(issue, "Coding agent exited without creating a PR")
                self.state.remove_agent(pid)
                return
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v -k handle_timeout or test_handle_completion_no_pr`
Expected: All three new tests PASS.

- [ ] **Step 6: Run full orchestrator test suite**

Run: `pytest tests/test_orchestrator.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orch): wire snapshots into timeout and no-PR failure paths (#12)"
```

---

## Task 8: Update coding-agent prompt template (TDD)

**Files:**
- Modify: `agents/coding.py`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agents.py`:

```python
def test_coding_prompt_first_attempt_has_no_context_block():
    from agents.coding import CodingAgent
    agent = CodingAgent()
    prompt = agent.build_prompt(
        issue_title="Fix bug",
        issue_body="body",
        issue_number=42,
        repo="owner/repo",
        integration_branch="ai/dev",
        attempt=1,
        prior_attempt_context="",
    )
    assert "Prior Attempt Context" not in prompt
    # Stop-tag instruction is rendered with attempt number
    assert "[ai-coding-agent: stop attempt=1]" in prompt


def test_coding_prompt_retry_includes_context_block():
    from agents.coding import CodingAgent
    agent = CodingAgent()
    context = "## Prior Attempt Context\n\nThis is your attempt 2..."
    prompt = agent.build_prompt(
        issue_title="Fix bug",
        issue_body="body",
        issue_number=42,
        repo="owner/repo",
        integration_branch="ai/dev",
        attempt=2,
        prior_attempt_context=context,
    )
    assert "## Prior Attempt Context" in prompt
    assert "[ai-coding-agent: stop attempt=2]" in prompt


def test_coding_prompt_default_attempt_is_1_and_no_context():
    """Backward compat: existing callers pass no attempt/context → attempt 1, empty block."""
    from agents.coding import CodingAgent
    agent = CodingAgent()
    prompt = agent.build_prompt(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
    )
    assert "Prior Attempt Context" not in prompt
    assert "[ai-coding-agent: stop attempt=1]" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents.py -v -k coding_prompt`
Expected: FAIL — `TypeError: build_prompt() got an unexpected keyword argument 'attempt'`.

- [ ] **Step 3: Update `agents/coding.py`**

Replace the contents of `agents/coding.py` with:

```python
# agents/coding.py
from agents.base import build_claude_command

CODING_PROMPT = """You are a coding agent working on GitHub issue {repo}#{issue_number}.

## Issue: {issue_title}

{issue_body}
{prior_attempt_context}
## Instructions

1. Start from a clean state: run `git fetch origin && git checkout {integration_branch} && git reset --hard origin/{integration_branch}`. Delete any existing local branch `ai/issue-{issue_number}` if present (`git branch -D ai/issue-{issue_number}` — ignore errors). Then create a fresh feature branch: `git checkout -b ai/issue-{issue_number}`.
2. Implement the work described in the issue, following the checklist and acceptance criteria.
3. Write tests before implementation. Run tests to verify they fail, then implement.
4. Run all tests to ensure they pass.
5. If the project has a linter configured (e.g., ruff, eslint), run it and fix any issues before proceeding.
6. Open a draft pull request targeting `{integration_branch}`, linking to issue #{issue_number}.
7. Keep changes focused — modify no more than 10 files.
8. If the requirements are ambiguous or you cannot proceed, stop and explain why in a comment. Prefix that comment with `[ai-coding-agent: stop attempt={attempt}]` so future attempts can find your reasoning.

IMPORTANT: Branch from `{integration_branch}`, NOT from `main`. Target the PR to `{integration_branch}`.
Do NOT merge anything. Draft PR only.
"""

ALLOWED_TOOLS = ["Edit", "Write", "Bash", "Read", "Glob", "Grep"]


class CodingAgent:
    def build_prompt(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        integration_branch: str = "ai/dev",
        attempt: int = 1,
        prior_attempt_context: str = "",
    ) -> str:
        # Newline-pad the context block so it sits cleanly between body and instructions
        ctx = f"\n{prior_attempt_context}" if prior_attempt_context else ""
        return CODING_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
            integration_branch=integration_branch,
            attempt=attempt,
            prior_attempt_context=ctx,
        )

    def build_command(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        integration_branch: str = "ai/dev",
        max_budget_usd: float = 3.0,
        attempt: int = 1,
        prior_attempt_context: str = "",
    ) -> list[str]:
        prompt = self.build_prompt(
            issue_title, issue_body, issue_number, repo, integration_branch,
            attempt=attempt, prior_attempt_context=prior_attempt_context,
        )
        return build_claude_command(
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
            max_budget_usd=max_budget_usd,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agents.py -v`
Expected: All pass (new tests + any existing).

- [ ] **Step 5: Commit**

```bash
git add agents/coding.py tests/test_agents.py
git commit -m "feat(agent): add prior_attempt_context placeholder to coding prompt (#12)"
```

---

## Task 9: Wire retry-aware logic into `_dispatch_coding` (TDD)

**Files:**
- Modify: `orchestrator.py:315-344`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_orchestrator.py`:

```python
@patch("orchestrator.subprocess.run")
@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_coding_first_attempt_has_no_context_in_prompt(
    MockGH, MockPopen, MockRun, config, state_dir
):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "[v0.1] Bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-ready" else []
    mock_gh.get_attempt_count.return_value = 0  # first attempt
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    MockPopen.return_value = mock_proc

    orch = Orchestrator(config, state_dir=state_dir)
    orch._process_ready_issues()

    # Inspect the prompt argument passed to claude
    call_args = MockPopen.call_args
    cmd = call_args.args[0]
    prompt = cmd[-1]  # build_claude_command appends prompt last
    assert "Prior Attempt Context" not in prompt
    assert "[ai-coding-agent: stop attempt=1]" in prompt


@patch("orchestrator.subprocess.run")
@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_coding_retry_includes_context_block_with_snapshot_and_history(
    MockGH, MockPopen, MockRun, config, state_dir
):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "[v0.1] Bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-ready" else []
    mock_gh.get_attempt_count.return_value = 1  # this will be attempt 2
    mock_gh.get_attempt_failure_history.return_value = [
        {"attempt": 1, "kind": "timeout", "reason": "timed out at 60min",
         "snapshot_ref": "ai/issue-42-attempt-1", "wip_ref": None,
         "log_path": "x", "ts": "2026-05-01T00:00:00Z"},
    ]
    mock_gh.get_latest_agent_stop_comment.return_value = None

    # ls-remote returns one snapshot ref (and no -wip)
    MockRun.side_effect = [
        _make_completed_process(0, stdout=(
            "abc123\trefs/heads/ai/issue-42-attempt-1\n"
        )),
        # git diff --stat for the snapshot
        _make_completed_process(0, stdout=" src/foo.py | 5 +++++\n 1 file changed, 5 insertions(+)\n"),
    ]

    mock_proc = MagicMock()
    mock_proc.pid = 12346
    MockPopen.return_value = mock_proc

    orch = Orchestrator(config, state_dir=state_dir)
    orch._process_ready_issues()

    cmd = MockPopen.call_args.args[0]
    prompt = cmd[-1]
    assert "## Prior Attempt Context" in prompt
    assert "Attempt 1: timeout" in prompt
    assert "ai/issue-42-attempt-1" in prompt
    assert "src/foo.py | 5" in prompt
    assert "[ai-coding-agent: stop attempt=2]" in prompt


@patch("orchestrator.subprocess.run")
@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_coding_retry_with_no_snapshots_uses_feedback_only_variant(
    MockGH, MockPopen, MockRun, config, state_dir
):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "[v0.1] Bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-ready" else []
    mock_gh.get_attempt_count.return_value = 1
    mock_gh.get_attempt_failure_history.return_value = [
        {"attempt": 1, "kind": "timeout", "reason": "timed out",
         "snapshot_ref": None, "wip_ref": None, "log_path": "", "ts": ""},
    ]
    mock_gh.get_latest_agent_stop_comment.return_value = None

    MockRun.side_effect = [
        _make_completed_process(0, stdout=""),  # ls-remote returns nothing
    ]

    mock_proc = MagicMock(); mock_proc.pid = 12347
    MockPopen.return_value = mock_proc

    orch = Orchestrator(config, state_dir=state_dir)
    orch._process_ready_issues()

    cmd = MockPopen.call_args.args[0]
    prompt = cmd[-1]
    assert "## Prior Attempt Context" in prompt
    assert "no snapshot" in prompt.lower()
    assert "feedback only" in prompt.lower()


@patch("orchestrator.subprocess.run")
@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_coding_retry_picks_highest_attempt_excluding_wip(
    MockGH, MockPopen, MockRun, config, state_dir
):
    """ls-remote returns mixed -wip and base refs; picks highest base K."""
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "[v0.1] Bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-ready" else []
    mock_gh.get_attempt_count.return_value = 2
    mock_gh.get_attempt_failure_history.return_value = []
    mock_gh.get_latest_agent_stop_comment.return_value = None

    MockRun.side_effect = [
        _make_completed_process(0, stdout=(
            "aaa\trefs/heads/ai/issue-42-attempt-1\n"
            "bbb\trefs/heads/ai/issue-42-attempt-2\n"
            "ccc\trefs/heads/ai/issue-42-attempt-2-wip\n"
        )),
        _make_completed_process(0, stdout=" src/foo.py | 1 +"),
    ]

    mock_proc = MagicMock(); mock_proc.pid = 12348
    MockPopen.return_value = mock_proc

    orch = Orchestrator(config, state_dir=state_dir)
    orch._process_ready_issues()

    cmd = MockPopen.call_args.args[0]
    prompt = cmd[-1]
    # Attempt-2 selected, not attempt-2-wip and not attempt-1
    assert "ai/issue-42-attempt-2" in prompt
    assert "git diff origin/ai/dev...origin/ai/issue-42-attempt-2" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v -k dispatch_coding`
Expected: New retry-aware tests FAIL (prompt has no context block yet).

- [ ] **Step 3: Add a private helper to resolve the latest snapshot via `git ls-remote`**

Add to `Orchestrator` in `orchestrator.py` (place right before `_snapshot_branch`):

```python
    def _latest_snapshot_for_issue(self, issue_number: int) -> tuple[str | None, str | None]:
        """Use `git ls-remote` to find the highest attempt-K snapshot for the issue.

        Returns (snapshot_ref, wip_ref). Either may be None. The wip_ref is
        returned only when its K matches the chosen snapshot's K.
        """
        import re

        result = subprocess.run(
            ["git", "ls-remote", "origin", f"ai/issue-{issue_number}-attempt-*"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None, None

        base_re = re.compile(rf"refs/heads/(ai/issue-{issue_number}-attempt-(\d+))$")
        wip_re = re.compile(rf"refs/heads/(ai/issue-{issue_number}-attempt-(\d+)-wip)$")

        bases: dict[int, str] = {}
        wips: dict[int, str] = {}
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            ref = parts[1]
            m = base_re.search(ref)
            if m:
                bases[int(m.group(2))] = m.group(1)
                continue
            m = wip_re.search(ref)
            if m:
                wips[int(m.group(2))] = m.group(1)

        if not bases:
            return None, None
        latest_k = max(bases.keys())
        return bases[latest_k], wips.get(latest_k)
```

- [ ] **Step 4: Modify `_dispatch_coding` in `orchestrator.py:315`**

Replace the existing `_dispatch_coding` with:

```python
    def _dispatch_coding(
        self,
        issue: dict,
        attempt: int,
        timeout_override: int | None = None,
        budget_override: float | None = None,
        integration_branch: str | None = None,
    ):
        from prior_attempt import render_prior_attempt_context

        issue_key = f"{issue['repo']}#{issue['number']}"
        logger.info(f"Dispatching coding agent for {issue_key} (attempt {attempt})")

        timeout = timeout_override if timeout_override is not None else self.config["timeouts"]["coding_minutes"]
        if integration_branch is None:
            integration_branch = self._get_integration_branch(issue["title"])

        # Build prior-attempt context for retries
        prior_attempt_context = ""
        if attempt > 1:
            history = self.gh.get_attempt_failure_history(issue["repo"], issue["number"])
            stop_comment = self.gh.get_latest_agent_stop_comment(
                issue["repo"], issue["number"], attempt - 1
            )
            snapshot_ref, wip_ref = self._latest_snapshot_for_issue(issue["number"])
            diff_stat = ""
            if snapshot_ref:
                diff_proc = subprocess.run(
                    ["git", "diff", "--stat",
                     f"origin/{integration_branch}...origin/{snapshot_ref}"],
                    capture_output=True, text=True,
                )
                if diff_proc.returncode == 0:
                    diff_stat = diff_proc.stdout
            prior_attempt_context = render_prior_attempt_context(
                history=history,
                latest_diff_stat=diff_stat,
                snapshot_ref=snapshot_ref,
                wip_ref=wip_ref,
                stop_comment=stop_comment,
                attempt=attempt,
                integration_branch=integration_branch,
            )

        cmd = self.coding_agent.build_command(
            issue_title=issue["title"],
            issue_body=issue["body"] or "",
            issue_number=issue["number"],
            repo=issue["repo"],
            integration_branch=integration_branch,
            max_budget_usd=budget_override if budget_override is not None
                else self.config.get("versioning", {}).get("coding_max_budget_usd", 5.0),
            attempt=attempt,
            prior_attempt_context=prior_attempt_context,
        )
        log_path = self.state.log_path(issue["repo"], issue["number"])
        log_file = open(log_path, "w")
        cwd = None
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=cwd)

        self.gh.update_status(issue["project_item_id"], self.statuses["in_progress"])
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=issue["repo"],
            agent_type="coding",
            timeout_minutes=timeout,
            attempt=attempt,
            project_item_id=issue["project_item_id"],
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v -k dispatch_coding`
Expected: All four tests PASS, plus any pre-existing dispatch tests still PASS.

- [ ] **Step 6: Run full orchestrator + agents test suites**

Run: `pytest tests/test_orchestrator.py tests/test_agents.py -v`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orch): retry-aware _dispatch_coding injects prior-attempt context (#12)"
```

---

## Task 10: Snapshot-ref cleanup on auto-merge (TDD)

**Files:**
- Modify: `orchestrator.py:182` (cleanup section of `_process_complete_issues`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_orchestrator.py`:

```python
@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_complete_issues_deletes_snapshot_refs_after_merge(
    MockGH, MockRun, config, state_dir
):
    mock_gh = MockGH.return_value
    mock_issue = {
        "number": 42, "title": "[v0.1] Bug", "body": "",
        "repo": "owner/repo", "project_item_id": "item_1", "status": "ai-complete",
    }
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-complete" else []
    mock_gh.find_pr_for_branch.return_value = 100
    mock_gh.merge_pr.return_value = True

    # Subprocess sequence:
    #   1. git branch -D ai/issue-42 (existing local cleanup)
    #   2. git ls-remote for ai/issue-42-attempt-* (new)
    #   3. git push --delete (new)
    MockRun.side_effect = [
        _make_completed_process(0),  # branch -D
        _make_completed_process(0, stdout=(
            "aaa\trefs/heads/ai/issue-42-attempt-1\n"
            "bbb\trefs/heads/ai/issue-42-attempt-1-wip\n"
            "ccc\trefs/heads/ai/issue-42-attempt-2\n"
        )),
        _make_completed_process(0),  # push --delete
    ]

    orch = Orchestrator(config, state_dir=state_dir)
    orch._process_complete_issues()

    # The push --delete call should reference all three refs
    delete_calls = [
        c for c in MockRun.call_args_list
        if "push" in c.args[0] and "--delete" in c.args[0]
    ]
    assert len(delete_calls) == 1
    deleted_args = delete_calls[0].args[0]
    assert "ai/issue-42-attempt-1" in deleted_args
    assert "ai/issue-42-attempt-1-wip" in deleted_args
    assert "ai/issue-42-attempt-2" in deleted_args


@patch("orchestrator.subprocess.run")
@patch("orchestrator.GitHubClient")
def test_complete_issues_tolerates_snapshot_cleanup_failure(
    MockGH, MockRun, config, state_dir
):
    """Cleanup failure must not break the merge flow."""
    mock_gh = MockGH.return_value
    mock_issue = {
        "number": 42, "title": "[v0.1] Bug", "body": "",
        "repo": "owner/repo", "project_item_id": "item_1", "status": "ai-complete",
    }
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-complete" else []
    mock_gh.find_pr_for_branch.return_value = 100
    mock_gh.merge_pr.return_value = True

    MockRun.side_effect = [
        _make_completed_process(0),  # branch -D
        _make_completed_process(returncode=1, stderr="boom"),  # ls-remote fails
    ]

    orch = Orchestrator(config, state_dir=state_dir)
    orch._process_complete_issues()  # Must not raise

    # Issue still advanced to Done
    update_status_calls = mock_gh.update_status.call_args_list
    assert any(call.args[1] == config["statuses"]["done"] for call in update_status_calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -v -k complete_issues`
Expected: First new test FAILS (no `push --delete` call). Second may PASS coincidentally.

- [ ] **Step 3: Modify the cleanup section in `_process_complete_issues`**

In `orchestrator.py`, find the block right after `git branch -D` (around line 182) inside the `if success:` branch and replace its body with:

```python
                if success:
                    self.gh.update_status(issue["project_item_id"], self.statuses["done"])
                    self.gh.add_comment(issue["repo"], issue["number"],
                        f"[agent-orchestrator] PR #{pr_number} auto-merged into `{integration_branch}`.")
                    self.slack.notify_pr_ready(issue_key, pr_number)

                    # Clean up local feature branch
                    result = subprocess.run(["git", "branch", "-D", pr_branch], capture_output=True)
                    if result.returncode == 0:
                        logger.info(f"Deleted local branch {pr_branch}")
                    else:
                        logger.debug(f"Local branch {pr_branch} not found, skipping cleanup")

                    # Best-effort cleanup of snapshot refs for this issue
                    try:
                        ls = subprocess.run(
                            ["git", "ls-remote", "origin",
                             f"ai/issue-{issue['number']}-attempt-*"],
                            capture_output=True, text=True,
                        )
                        if ls.returncode == 0 and ls.stdout.strip():
                            refs_to_delete = []
                            for line in ls.stdout.splitlines():
                                parts = line.split("\t")
                                if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                                    refs_to_delete.append(parts[1][len("refs/heads/"):])
                            if refs_to_delete:
                                subprocess.run(
                                    ["git", "push", "origin", "--delete", *refs_to_delete],
                                    capture_output=True, text=True,
                                )
                    except Exception as e:
                        logger.debug(f"Snapshot ref cleanup failed (non-fatal): {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_orchestrator.py -v -k complete_issues`
Expected: Both new tests PASS, pre-existing complete-issues tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orch): clean up snapshot refs on auto-merge (#12)"
```

---

## Task 11: End-to-end integration test with real git

**Files:**
- Create: `tests/test_snapshot_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_snapshot_integration.py`:

```python
"""Integration test for _snapshot_branch using real git in a temp repo (no GitHub)."""
import os
import subprocess
import pytest
from unittest.mock import MagicMock, patch
from orchestrator import Orchestrator


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def real_git_repo(tmp_path):
    """Create a temp repo + a 'remote' (also temp) so push works."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "checkout", "-b", "ai/dev")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "ai/dev")

    # Set up the feature branch with one commit + a dirty working tree
    _git(repo, "checkout", "-b", "ai/issue-7")
    (repo / "feature.py").write_text("print('hi')\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-m", "feature commit")
    # Leave a dirty file (uncommitted)
    (repo / "dirty.py").write_text("dirty\n")

    return repo


@pytest.fixture
def config():
    return {
        "repo": "owner/repo",
        "project": {"owner": "owner", "number": 1, "status_field_id": "PVTSSF_x"},
        "concurrency": {"max_coding": 1, "max_testing": 1, "max_review": 1},
        "timeouts": {"coding_minutes": 60, "testing_minutes": 30, "review_minutes": 30},
        "guardrails": {"max_files_changed": 10, "max_retry_cycles": 3, "snapshot_on_failure": True},
        "branches": {"integration": "ai/dev"},
        "slack": {"webhook_url": None},
        "statuses": {
            "backlog": "Backlog", "ready": "ai-ready", "in_progress": "ai-in-progress",
            "testing": "ai-testing", "review": "ai-review", "complete": "ai-complete",
            "done": "Done", "blocked": "ai-blocked", "error": "ai-error",
        },
    }


def test_snapshot_branch_with_real_git(real_git_repo, config, tmp_path, monkeypatch):
    monkeypatch.chdir(real_git_repo)
    with patch("orchestrator.GitHubClient"):
        orch = Orchestrator(config, state_dir=str(tmp_path / "state"))

    result = orch._snapshot_branch("owner/repo", 7, attempt=1)

    assert result["status"] == "ok"
    assert result["snapshot_ref"] == "ai/issue-7-attempt-1"
    assert result["wip_ref"] == "ai/issue-7-attempt-1-wip"

    # Snapshot ref points at the same SHA as ai/issue-7
    snap = subprocess.run(
        ["git", "ls-remote", "origin", "ai/issue-7-attempt-1"],
        cwd=real_git_repo, capture_output=True, text=True,
    )
    assert "refs/heads/ai/issue-7-attempt-1" in snap.stdout

    # Wip ref exists
    wip = subprocess.run(
        ["git", "ls-remote", "origin", "ai/issue-7-attempt-1-wip"],
        cwd=real_git_repo, capture_output=True, text=True,
    )
    assert "refs/heads/ai/issue-7-attempt-1-wip" in wip.stdout

    # Working tree is clean (stash dropped, untracked file is back as untracked
    # OR was preserved in the stash — git stash --include-untracked re-adds untracked
    # on apply; we used `stash drop` so untracked files are gone)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=real_git_repo, capture_output=True, text=True,
    )
    assert status.stdout == ""
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/test_snapshot_integration.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_snapshot_integration.py
git commit -m "test: integration test for _snapshot_branch with real git (#12)"
```

---

## Task 12: README operational note

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a section to `README.md`**

Find the existing "Configuration" or "Operations" section in `README.md`. Append (or create a new section near the bottom):

```markdown
### Snapshot refs on coding-agent failure

When a coding agent times out or exits without creating a PR, the orchestrator
pushes a forensic snapshot of the working tree as one or two remote refs:

- `ai/issue-N-attempt-K` — the committed branch state at failure.
- `ai/issue-N-attempt-K-wip` — uncommitted/untracked state captured via stash
  (only present if the working tree was dirty).

Subsequent retries read these refs to feed prior-attempt context into the new
agent's prompt. Successful auto-merge cleans up all `ai/issue-N-attempt-*` refs
for the issue. Issues that hit max retries leave their snapshots in place as
forensic evidence.

**Operational notes:**

- The `ai/issue-*` namespace must remain unprotected (no force-push protection)
  for snapshots to function. If protection blocks the snapshot push, the failure
  is recorded as `snapshot: unavailable` and recovery still proceeds.
- Toggle off via `guardrails.snapshot_on_failure: false` in `defaults.yaml` or
  the project's `playbook.yaml`.
- The first time an existing issue retries after this feature ships, it has no
  prior snapshots — that is expected, not a bug.
```

- [ ] **Step 2: Verify the README renders**

Run: `cat README.md | grep -A 3 "Snapshot refs"`
Expected: The new section appears.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: explain snapshot refs and the snapshot_on_failure flag (#12)"
```

---

## Final verification

After all tasks complete:

- [ ] **Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests pass. No regressions.

- [ ] **Verify the spec is fully covered**

Quick checklist:

- Snapshot refs on timeout: Tasks 6, 7
- Snapshot refs on no-PR: Tasks 6, 7
- Best-effort tolerance (each step independently try/except'd): Task 6
- Structured failure comment with JSON block: Tasks 2, 7
- `STOP_TAG_PREFIX` with attempt number: Tasks 2, 8
- `get_attempt_failure_history`: Task 3
- `get_latest_agent_stop_comment`: Task 4
- `get_attempt_count` correctness fix: Task 5
- `render_prior_attempt_context`: Task 2
- Retry-aware `_dispatch_coding`: Task 9
- Latest-K snapshot resolution excluding `-wip`: Task 9
- Snapshot cleanup on auto-merge: Task 10
- Feature flag `snapshot_on_failure`: Tasks 1, 7
- Backward compatibility (legacy comments): Tasks 3, 5
- Real-git integration test: Task 11
- Operational documentation: Task 12

- [ ] **Manually verify on a sandbox issue**

Pick a low-stakes test issue, intentionally make it fail (e.g. set a 1-minute timeout via config), watch the snapshot ref appear, then move it back to ai-ready and confirm the next attempt's prompt log contains the `## Prior Attempt Context` block.
