import pytest
from unittest.mock import MagicMock, patch
from github_client import GitHubClient


@pytest.fixture
def mock_github():
    with patch("github_client.Github") as MockGithub:
        mock_instance = MockGithub.return_value
        yield mock_instance


def _make_mock_issue(number, title, body, label_names):
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.body = body
    labels = []
    for name in label_names:
        label = MagicMock()
        label.name = name
        labels.append(label)
    issue.labels = labels
    issue.repository = MagicMock()
    issue.repository.full_name = "owner/repo"
    return issue


def test_fetch_issues_by_label(mock_github):
    mock_repo = MagicMock()
    mock_github.get_repo.return_value = mock_repo
    mock_issue = _make_mock_issue(42, "Fix bug", "Body text", ["ai-ready"])
    mock_repo.get_issues.return_value = [mock_issue]

    client = GitHubClient.__new__(GitHubClient)
    client.gh = mock_github
    issues = client.fetch_issues_by_label("owner/repo", "ai-ready")

    assert len(issues) == 1
    assert issues[0].number == 42
    mock_repo.get_issues.assert_called_once_with(labels=["ai-ready"], state="open")


def test_swap_label(mock_github):
    mock_repo = MagicMock()
    mock_github.get_repo.return_value = mock_repo
    mock_issue = MagicMock()
    mock_repo.get_issue.return_value = mock_issue

    client = GitHubClient.__new__(GitHubClient)
    client.gh = mock_github
    client.swap_label("owner/repo", 42, old_label="ai-ready", new_label="ai-in-progress")

    mock_issue.remove_from_labels.assert_called_once_with("ai-ready")
    mock_issue.add_to_labels.assert_called_once_with("ai-in-progress")


def test_add_comment(mock_github):
    mock_repo = MagicMock()
    mock_github.get_repo.return_value = mock_repo
    mock_issue = MagicMock()
    mock_repo.get_issue.return_value = mock_issue

    client = GitHubClient.__new__(GitHubClient)
    client.gh = mock_github
    client.add_comment("owner/repo", 42, "Agent blocked: ambiguous requirements")

    mock_issue.create_comment.assert_called_once_with("Agent blocked: ambiguous requirements")


def test_get_issue_attempt_count(mock_github):
    mock_repo = MagicMock()
    mock_github.get_repo.return_value = mock_repo
    mock_issue = MagicMock()
    mock_repo.get_issue.return_value = mock_issue

    comment1 = MagicMock()
    comment1.body = "[agent-orchestrator] Attempt 1 completed"
    comment2 = MagicMock()
    comment2.body = "[agent-orchestrator] Attempt 2 completed"
    comment3 = MagicMock()
    comment3.body = "Some human comment"
    mock_issue.get_comments.return_value = [comment1, comment2, comment3]

    client = GitHubClient.__new__(GitHubClient)
    client.gh = mock_github
    count = client.get_attempt_count("owner/repo", 42)

    assert count == 2
