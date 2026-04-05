import json
import os
import pytest
from unittest.mock import patch, MagicMock, call
from orchestrator import Orchestrator


@pytest.fixture
def config():
    return {
        "repos": ["owner/repo"],
        "concurrency": {"max_coding": 2, "max_testing": 1, "max_review": 1},
        "timeouts": {"coding_minutes": 60, "testing_minutes": 30, "review_minutes": 30},
        "guardrails": {"max_files_changed": 10, "max_retry_cycles": 3},
        "slack": {"webhook_url": None},
        "labels": {
            "ready": "ai-ready",
            "in_progress": "ai-in-progress",
            "testing": "ai-testing",
            "review_needed": "ai-review-needed",
            "pr_ready": "ai-pr-ready",
            "blocked": "ai-blocked",
            "error": "ai-error",
        },
    }


@pytest.fixture
def state_dir(tmp_path):
    return str(tmp_path)


def _mock_issue(number, title, body, labels):
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.body = body
    label_objs = []
    for name in labels:
        l = MagicMock()
        l.name = name
        label_objs.append(l)
    issue.labels = label_objs
    issue.repository = MagicMock()
    issue.repository.full_name = "owner/repo"
    issue.pull_request = None
    return issue


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_coding_agent(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body\n## Acceptance Criteria\n- [ ] works", ["ai-ready"])
    mock_gh.fetch_issues_by_label.return_value = [mock_issue]
    mock_gh.get_attempt_count.return_value = 0

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    MockPopen.return_value = mock_proc

    orch = Orchestrator(config, state_dir=state_dir)
    orch.run()

    mock_gh.swap_label.assert_called_with("owner/repo", 42, "ai-ready", "ai-in-progress")
    MockPopen.assert_called_once()
    assert len(orch.state.agents) == 1
    assert orch.state.agents[0]["pid"] == 99999
    assert orch.state.agents[0]["type"] == "coding"


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_skip_already_active_issue(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body", ["ai-ready"])
    mock_gh.fetch_issues_by_label.return_value = [mock_issue]

    orch = Orchestrator(config, state_dir=state_dir)
    orch.state.add_agent(pid=11111, issue="owner/repo#42", repo="owner/repo", agent_type="coding", timeout_minutes=60, attempt=1)

    with patch.object(orch, "_is_process_alive", return_value=True):
        orch.run()

    MockPopen.assert_not_called()


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_respects_concurrency_limit(MockGH, MockPopen, config, state_dir):
    config["concurrency"]["max_coding"] = 1
    mock_gh = MockGH.return_value
    mock_issue1 = _mock_issue(1, "T1", "B", ["ai-ready"])
    mock_issue2 = _mock_issue(2, "T2", "B", ["ai-ready"])
    mock_gh.fetch_issues_by_label.return_value = [mock_issue1, mock_issue2]
    mock_gh.get_attempt_count.return_value = 0

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    MockPopen.return_value = mock_proc

    orch = Orchestrator(config, state_dir=state_dir)
    orch.state.add_agent(pid=11111, issue="owner/repo#99", repo="owner/repo", agent_type="coding", timeout_minutes=60, attempt=1)

    with patch.object(orch, "_is_process_alive", return_value=True):
        orch.run()

    MockPopen.assert_not_called()


@patch("orchestrator.GitHubClient")
def test_handles_timed_out_agent(MockGH, config, state_dir):
    mock_gh = MockGH.return_value

    orch = Orchestrator(config, state_dir=state_dir)
    orch.state.add_agent(
        pid=11111, issue="owner/repo#42", repo="owner/repo",
        agent_type="coding", timeout_minutes=60, attempt=1,
    )
    orch.state.agents[0]["started_at"] = "2020-01-01T00:00:00+00:00"
    orch.state._save()

    with patch("orchestrator.os.kill") as mock_kill:
        with patch("orchestrator.subprocess.Popen"):
            mock_gh.fetch_issues_by_label.return_value = []
            mock_gh.get_attempt_count.return_value = 0
            orch.run()

    mock_kill.assert_called()
    mock_gh.swap_label.assert_called_with("owner/repo", 42, "ai-in-progress", "ai-error")


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_max_retries_labels_blocked(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body", ["ai-ready"])
    mock_gh.fetch_issues_by_label.return_value = [mock_issue]
    mock_gh.get_attempt_count.return_value = 3

    orch = Orchestrator(config, state_dir=state_dir)
    orch.run()

    mock_gh.swap_label.assert_called_with("owner/repo", 42, "ai-ready", "ai-blocked")
    MockPopen.assert_not_called()
