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
