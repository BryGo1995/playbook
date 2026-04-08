# tests/test_orchestrator.py
import json
import os
import pytest
from unittest.mock import patch, MagicMock, call
from orchestrator import Orchestrator


@pytest.fixture
def config():
    return {
        "repos": ["owner/repo"],
        "project": {
            "owner": "owner",
            "number": 1,
            "status_field_id": "PVTSSF_test",
        },
        "concurrency": {"max_coding": 2, "max_testing": 1, "max_review": 1},
        "timeouts": {"coding_minutes": 60, "testing_minutes": 30, "review_minutes": 30},
        "guardrails": {"max_files_changed": 10, "max_retry_cycles": 3},
        "branches": {"integration": "ai/dev"},
        "slack": {"webhook_url": None},
        "statuses": {
            "backlog": "Backlog",
            "ready": "ai-ready",
            "in_progress": "ai-in-progress",
            "testing": "ai-testing",
            "review": "ai-review",
            "complete": "ai-complete",
            "done": "Done",
            "blocked": "ai-blocked",
            "error": "ai-error",
        },
    }


@pytest.fixture
def state_dir(tmp_path):
    return str(tmp_path)


def _mock_issue(number, title, body, project_item_id="item_1"):
    return {
        "number": number,
        "title": title,
        "body": body,
        "repo": "owner/repo",
        "project_item_id": project_item_id,
    }


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_coding_agent(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "[v0.1] Fix bug", "Body\n## Acceptance Criteria\n- [ ] works")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-ready" else []
    mock_gh.get_attempt_count.return_value = 0

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    MockPopen.return_value = mock_proc

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()

    orch.run()

    mock_gh.update_status.assert_any_call("item_1", "ai-in-progress")
    MockPopen.assert_called_once()
    assert len(orch.state.agents) == 1
    assert orch.state.agents[0]["pid"] == 99999
    assert orch.state.agents[0]["type"] == "coding"
    assert orch.state.agents[0]["project_item_id"] == "item_1"


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_skip_already_active_issue(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-ready" else []

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()
    orch.state.add_agent(pid=11111, issue="owner/repo#42", repo="owner/repo", agent_type="coding", timeout_minutes=60, attempt=1, project_item_id="item_1")

    with patch.object(orch, "_is_process_alive", return_value=True):
        orch.run()

    MockPopen.assert_not_called()


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_respects_concurrency_limit(MockGH, MockPopen, config, state_dir):
    config["concurrency"]["max_coding"] = 1
    mock_gh = MockGH.return_value
    mock_issue1 = _mock_issue(1, "T1", "B", "item_1")
    mock_issue2 = _mock_issue(2, "T2", "B", "item_2")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue1, mock_issue2] if s == "ai-ready" else []
    mock_gh.get_attempt_count.return_value = 0

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    MockPopen.return_value = mock_proc

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()
    orch.state.add_agent(pid=11111, issue="owner/repo#99", repo="owner/repo", agent_type="coding", timeout_minutes=60, attempt=1, project_item_id="item_99")

    with patch.object(orch, "_is_process_alive", return_value=True):
        orch.run()

    MockPopen.assert_not_called()


@patch("orchestrator.GitHubClient")
def test_handles_timed_out_agent(MockGH, config, state_dir):
    mock_gh = MockGH.return_value
    mock_gh.fetch_issues_by_status.return_value = []

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()
    orch.state.add_agent(
        pid=11111, issue="owner/repo#42", repo="owner/repo",
        agent_type="coding", timeout_minutes=60, attempt=1, project_item_id="item_42",
    )
    orch.state.agents[0]["started_at"] = "2020-01-01T00:00:00+00:00"
    orch.state._save()

    with patch("orchestrator.os.kill") as mock_kill:
        orch.run()

    mock_kill.assert_called()
    mock_gh.update_status.assert_called_with("item_42", "ai-error")


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_max_retries_sets_blocked(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-ready" else []
    mock_gh.get_attempt_count.return_value = 3

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()

    orch.run()

    mock_gh.update_status.assert_called_with("item_1", "ai-blocked")
    MockPopen.assert_not_called()


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_auto_merge_complete(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body", "item_42")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-complete" else []
    mock_gh.find_pr_for_branch.return_value = 15
    mock_gh.merge_pr.return_value = True

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()

    orch.run()

    mock_gh.merge_pr.assert_called_once_with("owner/repo", 15)
    mock_gh.update_status.assert_called_with("item_42", "Done")


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_auto_merge_conflict_sets_blocked(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body", "item_42")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-complete" else []
    mock_gh.find_pr_for_branch.return_value = 15
    mock_gh.merge_pr.return_value = False

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()

    orch.run()

    mock_gh.update_status.assert_called_with("item_42", "ai-blocked")


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_version_gating_dispatches_only_active_version(MockGH, MockPopen, config, state_dir):
    config["versioning"] = {"enabled": True, "auto_create_issues": False, "bootstrap_timeout_minutes": 120, "bootstrap_max_budget_usd": 5.0}
    mock_gh = MockGH.return_value
    v1_issue = _mock_issue(1, "[v0.1] Feature A", "Body", "item_1")
    v2_issue = _mock_issue(2, "[v0.2] Feature B", "Body", "item_2")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [v1_issue, v2_issue] if s == "ai-ready" else []
    mock_gh.fetch_all_project_issues.return_value = [
        {"title": "[v0.1] Feature A", "status": "ai-ready"},
        {"title": "[v0.2] Feature B", "status": "ai-ready"},
    ]
    mock_gh.get_attempt_count.return_value = 0

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    MockPopen.return_value = mock_proc

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()
    orch._notified_versions = set()

    orch.run()

    # Should only dispatch v0.1 issue, not v0.2
    MockPopen.assert_called_once()
    assert orch.state.agents[0]["issue"] == "owner/repo#1"


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_bootstrap_limits_concurrency_to_one(MockGH, MockPopen, config, state_dir):
    config["versioning"] = {"enabled": True, "auto_create_issues": False, "bootstrap_timeout_minutes": 120, "bootstrap_max_budget_usd": 5.0}
    config["concurrency"]["max_coding"] = 3
    mock_gh = MockGH.return_value
    boot1 = _mock_issue(1, "[bootstrap] Setup A", "Body", "item_1")
    boot2 = _mock_issue(2, "[bootstrap] Setup B", "Body", "item_2")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [boot1, boot2] if s == "ai-ready" else []
    mock_gh.fetch_all_project_issues.return_value = [
        {"title": "[bootstrap] Setup A", "status": "ai-ready"},
        {"title": "[bootstrap] Setup B", "status": "ai-ready"},
    ]
    mock_gh.get_attempt_count.return_value = 0

    mock_proc = MagicMock()
    mock_proc.pid = 99999
    MockPopen.return_value = mock_proc

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = __import__("notifications.slack", fromlist=["SlackNotifier"]).SlackNotifier(None)
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()
    orch._notified_versions = set()

    orch.run()

    # Bootstrap should only dispatch 1 even though max_coding is 3
    MockPopen.assert_called_once()


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_version_completion_sends_slack(MockGH, MockPopen, config, state_dir):
    config["versioning"] = {"enabled": True, "auto_create_issues": False, "bootstrap_timeout_minutes": 120, "bootstrap_max_budget_usd": 5.0}
    mock_gh = MockGH.return_value
    mock_gh.fetch_issues_by_status.return_value = []
    mock_gh.fetch_all_project_issues.return_value = [
        {"title": "[v0.1] Feature A", "status": "Done"},
        {"title": "[v0.1] Feature B", "status": "Done"},
        {"title": "[v0.2] Feature C", "status": "ai-ready"},
    ]

    mock_slack = MagicMock()

    orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.statuses = config["statuses"]
    orch.gh = mock_gh
    orch.state = __import__("state").StateManager(state_dir)
    orch.slack = mock_slack
    orch.coding_agent = __import__("agents.coding", fromlist=["CodingAgent"]).CodingAgent()
    orch.testing_agent = __import__("agents.testing", fromlist=["TestingAgent"]).TestingAgent()
    orch.review_agent = __import__("agents.review", fromlist=["ReviewAgent"]).ReviewAgent()
    orch._notified_versions = set()

    orch.run()

    mock_slack.notify_version_complete.assert_called_once_with("v0.1", 2)
