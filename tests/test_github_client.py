# tests/test_github_client.py
import pytest
from unittest.mock import MagicMock, patch
from github_client import GitHubClient


@pytest.fixture
def client():
    """Create a GitHubClient with mocked HTTP."""
    with patch("github_client.requests") as mock_requests:
        c = GitHubClient.__new__(GitHubClient)
        c.token = "fake-token"
        c.headers = {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}
        c._project_id = "PVT_test123"
        c._status_field_id = "PVTSSF_test123"
        c._status_option_ids = {
            "ai-ready": "opt_ready",
            "ai-in-progress": "opt_inprogress",
            "ai-testing": "opt_testing",
            "ai-review": "opt_review",
            "ai-complete": "opt_complete",
            "ai-blocked": "opt_blocked",
            "ai-error": "opt_error",
        }
        c._mock_requests = mock_requests
        yield c


def test_get_status_option_id(client):
    assert client.get_status_option_id("ai-ready") == "opt_ready"
    assert client.get_status_option_id("ai-blocked") == "opt_blocked"


def test_get_status_option_id_unknown(client):
    with pytest.raises(ValueError, match="Unknown status"):
        client.get_status_option_id("nonexistent")


def test_update_status(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "item1"}}}}
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.post.return_value = mock_resp

    client.update_status("item_123", "ai-in-progress")

    client._mock_requests.post.assert_called_once()
    call_args = client._mock_requests.post.call_args
    payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
    assert "opt_inprogress" in str(payload)


def test_add_comment(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"id": 1}
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.post.return_value = mock_resp

    client.add_comment("owner/repo", 42, "Test comment")

    client._mock_requests.post.assert_called_once()
    call_args = client._mock_requests.post.call_args
    assert "/repos/owner/repo/issues/42/comments" in call_args[0][0]
    assert call_args[1]["json"]["body"] == "Test comment"


def test_get_attempt_count(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": "[agent-orchestrator] Attempt 1 completed (coding agent)."},
        {"body": "[agent-orchestrator] Attempt 2 completed (coding agent)."},
        {"body": "Some human comment"},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    count = client.get_attempt_count("owner/repo", 42)
    assert count == 2


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


def test_merge_pr_success(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    client._mock_requests.put.return_value = mock_resp

    assert client.merge_pr("owner/repo", 15) is True


def test_merge_pr_failure(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 405
    client._mock_requests.put.return_value = mock_resp

    assert client.merge_pr("owner/repo", 15) is False


def test_find_pr_for_branch(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [{"number": 15}]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.find_pr_for_branch("owner/repo", "ai/issue-42") == 15


def test_find_pr_for_branch_none(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    assert client.find_pr_for_branch("owner/repo", "ai/issue-99") is None


def test_fetch_all_project_issues(client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {
        "node": {
            "items": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "id": "item_1",
                        "fieldValueByName": {"name": "ai-ready"},
                        "content": {
                            "number": 1,
                            "title": "[v0.1] Feature A",
                            "body": "body",
                            "state": "OPEN",
                            "repository": {"nameWithOwner": "owner/repo"},
                        },
                    },
                    {
                        "id": "item_2",
                        "fieldValueByName": {"name": "Done"},
                        "content": {
                            "number": 2,
                            "title": "[v0.1] Feature B",
                            "body": "body",
                            "state": "OPEN",
                            "repository": {"nameWithOwner": "owner/repo"},
                        },
                    },
                ],
            }
        }
    }}
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.post.return_value = mock_resp

    issues = client.fetch_all_project_issues()
    assert len(issues) == 2
    assert issues[0]["title"] == "[v0.1] Feature A"
    assert issues[0]["status"] == "ai-ready"
    assert issues[1]["status"] == "Done"


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


def _make_resp(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _status_options_payload():
    return {"data": {"node": {"field": {"options": [
        {"id": "opt_ready", "name": "ai-ready"},
        {"id": "opt_done", "name": "Done"},
    ]}}}}


def test_load_project_metadata_resolves_user_owned_project():
    """User-owned Projects v2 resolve via the user branch."""
    with patch("github_client.requests") as mock_requests:
        c = GitHubClient(token="fake")
        user_payload = {"data": {"user": {"projectV2": {"id": "PVT_user_proj"}}}}
        mock_requests.post.side_effect = [
            _make_resp(user_payload),
            _make_resp(_status_options_payload()),
        ]
        c.load_project_metadata("alice", 1, "PVTSSF_x")
        assert c._project_id == "PVT_user_proj"
        assert c._status_field_id == "PVTSSF_x"
        assert c._status_option_ids == {"ai-ready": "opt_ready", "Done": "opt_done"}


def test_load_project_metadata_falls_back_to_organization():
    """When the user query errors (owner is an org), the org branch is used."""
    with patch("github_client.requests") as mock_requests:
        c = GitHubClient(token="fake")
        # First call: user branch errors (owner is an organization)
        user_err_payload = {"errors": [{"message": "Could not resolve to a User"}]}
        org_payload = {"data": {"organization": {"projectV2": {"id": "PVT_org_proj"}}}}
        mock_requests.post.side_effect = [
            _make_resp(user_err_payload),
            _make_resp(org_payload),
            _make_resp(_status_options_payload()),
        ]
        c.load_project_metadata("acme-org", 7, "PVTSSF_y")
        assert c._project_id == "PVT_org_proj"


def test_load_project_metadata_falls_back_when_user_returns_null():
    """When the user query succeeds but returns null (rare), still try org branch."""
    with patch("github_client.requests") as mock_requests:
        c = GitHubClient(token="fake")
        user_null = {"data": {"user": None}}
        org_payload = {"data": {"organization": {"projectV2": {"id": "PVT_org_proj"}}}}
        mock_requests.post.side_effect = [
            _make_resp(user_null),
            _make_resp(org_payload),
            _make_resp(_status_options_payload()),
        ]
        c.load_project_metadata("acme-org", 7, "PVTSSF_y")
        assert c._project_id == "PVT_org_proj"


def test_load_project_metadata_raises_when_neither_kind_has_project():
    """When neither user nor org has the project, raise a clear error."""
    with patch("github_client.requests") as mock_requests:
        c = GitHubClient(token="fake")
        user_err = {"errors": [{"message": "Could not resolve to a User"}]}
        org_err = {"errors": [{"message": "Could not resolve to an Organization"}]}
        mock_requests.post.side_effect = [
            _make_resp(user_err),
            _make_resp(org_err),
        ]
        with pytest.raises(RuntimeError, match="Could not find Projects v2"):
            c.load_project_metadata("nobody", 99, "PVTSSF_z")


def test_get_attempt_count_tolerates_non_numeric_attempt_in_json(client):
    """A malformed JSON block with a non-numeric attempt must not crash the counter."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"body": (
            "[agent-orchestrator] Attempt malformed.\n\n```json\n"
            '{"attempt": "not-a-number", "kind": "timeout", "reason": "x", '
            '"snapshot_ref": null, "wip_ref": null, "log_path": "", "ts": ""}\n```'
        )},
        {"body": "[agent-orchestrator] Attempt 2 completed (coding agent)."},
    ]
    mock_resp.raise_for_status = MagicMock()
    client._mock_requests.get.return_value = mock_resp

    # Bad JSON drops through; legacy match catches "Attempt 2 completed"
    assert client.get_attempt_count("owner/repo", 42) == 1
