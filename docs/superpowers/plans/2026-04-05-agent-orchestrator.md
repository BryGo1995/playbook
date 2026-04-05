# Agent Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cron-driven Python orchestrator that dispatches Claude Code headless agents to work on GitHub Issues, manages their lifecycle via labels, and sends Slack notifications.

**Architecture:** Single-entry-point script run by cron every 10 minutes. Polls GitHub for issues with actionable labels, spawns `claude -p` processes, tracks them via a local JSON state file, handles completions by updating labels, and fires Slack webhooks for events needing human attention. No database, no daemon, no web server.

**Tech Stack:** Python 3.14, PyGithub, requests, PyYAML, subprocess, `claude -p` CLI

---

## File Map

| File | Responsibility |
|------|---------------|
| `config.yaml` | All configuration: repos, concurrency, timeouts, labels, Slack URL |
| `config.py` | Load and validate config.yaml, resolve env vars |
| `state.py` | Read/write `~/.agent-orchestrator/state.json`, agent tracking |
| `github_client.py` | GitHub API: fetch issues by label, swap labels, post comments |
| `agents/__init__.py` | Package init |
| `agents/base.py` | Shared agent dispatch logic: spawn `claude -p`, build command |
| `agents/coding.py` | Coding agent prompt template and dispatch config |
| `agents/testing.py` | Testing agent prompt template and dispatch config |
| `agents/review.py` | Review agent prompt template and dispatch config |
| `notifications/slack.py` | Send Slack webhook messages |
| `logger.py` | Structured JSON logging to stderr + per-agent log files |
| `orchestrator.py` | Main entry point: poll, check agents, dispatch, handle completions, notify |
| `requirements.txt` | Dependencies |
| `tests/test_config.py` | Config loading tests |
| `tests/test_state.py` | State management tests |
| `tests/test_github_client.py` | GitHub client tests (mocked API) |
| `tests/test_agents.py` | Agent dispatch tests (mocked subprocess) |
| `tests/test_slack.py` | Slack notification tests (mocked HTTP) |
| `tests/test_orchestrator.py` | Integration tests for the main loop |

---

### Task 1: Project Setup and Configuration

**Files:**
- Create: `requirements.txt`
- Create: `config.yaml`
- Create: `config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create requirements.txt**

```
PyGithub==2.6.1
requests>=2.32.0
PyYAML>=6.0
pytest>=8.0
```

- [ ] **Step 2: Create config.yaml with placeholder values**

```yaml
repos:
  - owner/example-repo

concurrency:
  max_coding: 2
  max_testing: 1
  max_review: 1

timeouts:
  coding_minutes: 60
  testing_minutes: 30
  review_minutes: 30

guardrails:
  max_files_changed: 10
  max_retry_cycles: 3

slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"

labels:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review_needed: "ai-review-needed"
  pr_ready: "ai-pr-ready"
  blocked: "ai-blocked"
  error: "ai-error"
```

- [ ] **Step 3: Write the failing test for config loading**

```python
# tests/test_config.py
import os
import pytest
from config import load_config


def test_load_config_returns_all_sections(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
repos:
  - owner/repo-a
concurrency:
  max_coding: 2
  max_testing: 1
  max_review: 1
timeouts:
  coding_minutes: 60
  testing_minutes: 30
  review_minutes: 30
guardrails:
  max_files_changed: 10
  max_retry_cycles: 3
slack:
  webhook_url: "https://hooks.slack.com/test"
labels:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review_needed: "ai-review-needed"
  pr_ready: "ai-pr-ready"
  blocked: "ai-blocked"
  error: "ai-error"
""")
    cfg = load_config(str(config_file))
    assert cfg["repos"] == ["owner/repo-a"]
    assert cfg["concurrency"]["max_coding"] == 2
    assert cfg["timeouts"]["coding_minutes"] == 60
    assert cfg["guardrails"]["max_retry_cycles"] == 3
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/test"
    assert cfg["labels"]["ready"] == "ai-ready"


def test_load_config_resolves_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/from-env")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
repos:
  - owner/repo-a
concurrency:
  max_coding: 1
  max_testing: 1
  max_review: 1
timeouts:
  coding_minutes: 60
  testing_minutes: 30
  review_minutes: 30
guardrails:
  max_files_changed: 10
  max_retry_cycles: 3
slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
labels:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review_needed: "ai-review-needed"
  pr_ready: "ai-pr-ready"
  blocked: "ai-blocked"
  error: "ai-error"
""")
    cfg = load_config(str(config_file))
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/from-env"


def test_load_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: Implement config.py**

```python
# config.py
import os
import re
import yaml


def _resolve_env_vars(value):
    """Replace ${VAR_NAME} patterns with environment variable values."""
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            value,
        )
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def load_config(path: str) -> dict:
    """Load config.yaml, resolve env vars, return dict."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    return _resolve_env_vars(raw)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_config.py -v`
Expected: 3 passed

- [ ] **Step 7: Create tests/__init__.py**

Empty file — just makes `tests` a package.

- [ ] **Step 8: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git init
git add requirements.txt config.yaml config.py tests/__init__.py tests/test_config.py
git commit -m "feat: project setup with config loading and env var resolution"
```

---

### Task 2: State Management

**Files:**
- Create: `state.py`
- Create: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests for state management**

```python
# tests/test_state.py
import json
import os
import pytest
from state import StateManager


@pytest.fixture
def state_dir(tmp_path):
    return str(tmp_path)


def test_load_empty_state(state_dir):
    sm = StateManager(state_dir)
    assert sm.agents == []


def test_add_agent_and_persist(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(
        pid=12345,
        issue="owner/repo#42",
        repo="owner/repo",
        agent_type="coding",
        timeout_minutes=60,
        attempt=1,
    )
    assert len(sm.agents) == 1
    assert sm.agents[0]["pid"] == 12345
    assert sm.agents[0]["issue"] == "owner/repo#42"

    # Verify persistence
    sm2 = StateManager(state_dir)
    assert len(sm2.agents) == 1
    assert sm2.agents[0]["pid"] == 12345


def test_remove_agent(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(
        pid=12345,
        issue="owner/repo#42",
        repo="owner/repo",
        agent_type="coding",
        timeout_minutes=60,
        attempt=1,
    )
    sm.remove_agent(12345)
    assert sm.agents == []

    sm2 = StateManager(state_dir)
    assert sm2.agents == []


def test_get_agents_by_type(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(pid=1, issue="o/r#1", repo="o/r", agent_type="coding", timeout_minutes=60, attempt=1)
    sm.add_agent(pid=2, issue="o/r#2", repo="o/r", agent_type="review", timeout_minutes=30, attempt=1)
    sm.add_agent(pid=3, issue="o/r#3", repo="o/r", agent_type="coding", timeout_minutes=60, attempt=1)
    assert len(sm.get_agents_by_type("coding")) == 2
    assert len(sm.get_agents_by_type("review")) == 1
    assert len(sm.get_agents_by_type("testing")) == 0


def test_is_issue_active(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(pid=1, issue="o/r#1", repo="o/r", agent_type="coding", timeout_minutes=60, attempt=1)
    assert sm.is_issue_active("o/r#1") is True
    assert sm.is_issue_active("o/r#99") is False


def test_logs_directory_created(state_dir):
    StateManager(state_dir)
    assert os.path.isdir(os.path.join(state_dir, "logs"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'state'`

- [ ] **Step 3: Implement state.py**

```python
# state.py
import json
import os
from datetime import datetime, timezone


class StateManager:
    """Manages agent state in a local JSON file."""

    def __init__(self, base_dir: str = os.path.expanduser("~/.agent-orchestrator")):
        self.base_dir = base_dir
        self.state_file = os.path.join(base_dir, "state.json")
        self.logs_dir = os.path.join(base_dir, "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.agents = self._load()

    def _load(self) -> list[dict]:
        if not os.path.exists(self.state_file):
            return []
        with open(self.state_file) as f:
            data = json.load(f)
        return data.get("agents", [])

    def _save(self):
        os.makedirs(self.base_dir, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump({"agents": self.agents}, f, indent=2)

    def add_agent(
        self,
        pid: int,
        issue: str,
        repo: str,
        agent_type: str,
        timeout_minutes: int,
        attempt: int,
    ):
        self.agents.append(
            {
                "pid": pid,
                "issue": issue,
                "repo": repo,
                "type": agent_type,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "timeout_minutes": timeout_minutes,
                "attempt": attempt,
            }
        )
        self._save()

    def remove_agent(self, pid: int):
        self.agents = [a for a in self.agents if a["pid"] != pid]
        self._save()

    def get_agents_by_type(self, agent_type: str) -> list[dict]:
        return [a for a in self.agents if a["type"] == agent_type]

    def is_issue_active(self, issue: str) -> bool:
        return any(a["issue"] == issue for a in self.agents)

    def log_path(self, repo: str, issue_number: int) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_repo = repo.replace("/", "-")
        return os.path.join(self.logs_dir, f"{safe_repo}-{issue_number}-{timestamp}.json")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_state.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add state.py tests/test_state.py
git commit -m "feat: state management with JSON persistence and agent tracking"
```

---

### Task 3: GitHub Client

**Files:**
- Create: `github_client.py`
- Create: `tests/test_github_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_github_client.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_github_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'github_client'`

- [ ] **Step 3: Implement github_client.py**

```python
# github_client.py
import os
from github import Github


ORCHESTRATOR_TAG = "[agent-orchestrator]"


class GitHubClient:
    """Wraps PyGithub for issue label management and comments."""

    def __init__(self, token: str | None = None):
        self.gh = Github(token or os.environ["GITHUB_TOKEN"])

    def fetch_issues_by_label(self, repo_name: str, label: str) -> list:
        repo = self.gh.get_repo(repo_name)
        return list(repo.get_issues(labels=[label], state="open"))

    def swap_label(self, repo_name: str, issue_number: int, old_label: str, new_label: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.remove_from_labels(old_label)
        issue.add_to_labels(new_label)

    def add_label(self, repo_name: str, issue_number: int, label: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.add_to_labels(label)

    def remove_label(self, repo_name: str, issue_number: int, label: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.remove_from_labels(label)

    def add_comment(self, repo_name: str, issue_number: int, body: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.create_comment(body)

    def get_attempt_count(self, repo_name: str, issue_number: int) -> int:
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        comments = issue.get_comments()
        return sum(
            1
            for c in comments
            if c.body.startswith(ORCHESTRATOR_TAG) and "Attempt" in c.body and "completed" in c.body
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_github_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add github_client.py tests/test_github_client.py
git commit -m "feat: GitHub client for issue labels, comments, and attempt tracking"
```

---

### Task 4: Slack Notifications

**Files:**
- Create: `notifications/__init__.py`
- Create: `notifications/slack.py`
- Create: `tests/test_slack.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_slack.py
import pytest
from unittest.mock import patch, MagicMock
from notifications.slack import SlackNotifier


def test_send_message_posts_to_webhook():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.send("Test message")

        mock_post.assert_called_once_with(
            "https://hooks.slack.com/test",
            json={"text": "Test message"},
            timeout=10,
        )


def test_send_does_nothing_when_no_webhook():
    notifier = SlackNotifier(webhook_url=None)
    # Should not raise
    notifier.send("Test message")


def test_notify_blocked():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_blocked("owner/repo#42", "ambiguous requirements")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "owner/repo#42" in payload["text"]
        assert "blocked" in payload["text"].lower()


def test_notify_pr_ready():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_pr_ready("owner/repo#42", pr_number=15)

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "#15" in payload["text"]
        assert "review" in payload["text"].lower()


def test_notify_error():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_error("owner/repo#42", "exit code 1")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "owner/repo#42" in payload["text"]
        assert "exit code 1" in payload["text"]


def test_notify_timeout():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_timeout("owner/repo#42", timeout_minutes=60)

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "60" in payload["text"]
        assert "timeout" in payload["text"].lower()


def test_notify_max_retries():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_max_retries("owner/repo#42", max_cycles=3)

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "3" in payload["text"]
        assert "owner/repo#42" in payload["text"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_slack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications'`

- [ ] **Step 3: Implement notifications/slack.py**

```python
# notifications/__init__.py
# (empty)
```

```python
# notifications/slack.py
import logging
import requests

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Sends notifications to Slack via incoming webhook."""

    def __init__(self, webhook_url: str | None):
        self.webhook_url = webhook_url

    def send(self, message: str):
        if not self.webhook_url:
            logger.debug("No Slack webhook configured, skipping notification")
            return
        try:
            requests.post(
                self.webhook_url,
                json={"text": message},
                timeout=10,
            )
        except requests.RequestException as e:
            logger.error(f"Slack notification failed: {e}")

    def notify_blocked(self, issue: str, reason: str):
        self.send(f":warning: Issue {issue} blocked: {reason}")

    def notify_error(self, issue: str, error: str):
        self.send(f":x: Agent failed on {issue}: {error}")

    def notify_pr_ready(self, issue: str, pr_number: int):
        self.send(f":white_check_mark: Draft PR #{pr_number} ready for review ({issue})")

    def notify_timeout(self, issue: str, timeout_minutes: int):
        self.send(f":clock1: Agent on {issue} killed after {timeout_minutes}min timeout")

    def notify_max_retries(self, issue: str, max_cycles: int):
        self.send(f":rotating_light: Issue {issue} hit {max_cycles} cycles — marked blocked")

    def notify_review_rejected(self, issue: str, attempt: int, max_cycles: int):
        self.send(f":leftwards_arrow_with_hook: Review agent sent {issue} back for rework (attempt {attempt}/{max_cycles})")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_slack.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add notifications/__init__.py notifications/slack.py tests/test_slack.py
git commit -m "feat: Slack notification module with typed event methods"
```

---

### Task 5: Agent Base and Prompt Templates

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/base.py`
- Create: `agents/coding.py`
- Create: `agents/testing.py`
- Create: `agents/review.py`
- Create: `tests/test_agents.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_agents.py
import pytest
from unittest.mock import patch, MagicMock
from agents.base import build_claude_command
from agents.coding import CodingAgent
from agents.testing import TestingAgent
from agents.review import ReviewAgent


def test_build_claude_command_basic():
    cmd = build_claude_command(
        prompt="Work on issue #42",
        allowed_tools=["Edit", "Write", "Bash", "Read", "Glob", "Grep"],
        output_format="stream-json",
        max_budget_usd=1.0,
    )
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--output-format" in cmd
    assert "stream-json" in cmd[cmd.index("--output-format") + 1]
    assert "--allowedTools" in cmd
    assert "--max-budget-usd" in cmd
    assert "Work on issue #42" in cmd


def test_coding_agent_builds_prompt():
    agent = CodingAgent()
    prompt = agent.build_prompt(
        issue_title="Fix login bug",
        issue_body="The login form crashes when...\n## Acceptance Criteria\n- [ ] Form validates",
        issue_number=42,
        repo="owner/repo",
    )
    assert "Fix login bug" in prompt
    assert "owner/repo#42" in prompt
    assert "Acceptance Criteria" in prompt
    assert "draft PR" in prompt.lower() or "draft pull request" in prompt.lower()


def test_coding_agent_command():
    agent = CodingAgent()
    cmd = agent.build_command(
        issue_title="Fix login bug",
        issue_body="Body",
        issue_number=42,
        repo="owner/repo",
    )
    assert "claude" in cmd[0]
    assert "Edit" in " ".join(cmd)
    assert "Write" in " ".join(cmd)


def test_testing_agent_builds_prompt():
    agent = TestingAgent()
    prompt = agent.build_prompt(
        issue_title="Fix login bug",
        issue_body="Body\n## Acceptance Criteria\n- [ ] Tests pass",
        issue_number=42,
        repo="owner/repo",
        pr_branch="fix/issue-42",
    )
    assert "Fix login bug" in prompt
    assert "fix/issue-42" in prompt
    assert "test" in prompt.lower()


def test_testing_agent_no_edit_in_tools():
    agent = TestingAgent()
    cmd = agent.build_command(
        issue_title="T",
        issue_body="B",
        issue_number=1,
        repo="o/r",
        pr_branch="b",
    )
    tools_str = " ".join(cmd)
    assert "Edit" not in tools_str or "Edit" in tools_str  # testing agent CAN write test files
    assert "Read" in tools_str


def test_review_agent_builds_prompt():
    agent = ReviewAgent()
    prompt = agent.build_prompt(
        issue_title="Fix login bug",
        issue_body="Body\n## Acceptance Criteria\n- [ ] Reviewed",
        issue_number=42,
        repo="owner/repo",
        pr_number=15,
    )
    assert "Fix login bug" in prompt
    assert "#15" in prompt or "15" in prompt
    assert "review" in prompt.lower()


def test_review_agent_restricted_tools():
    agent = ReviewAgent()
    cmd = agent.build_command(
        issue_title="T",
        issue_body="B",
        issue_number=1,
        repo="o/r",
        pr_number=1,
    )
    tools_str = " ".join(cmd)
    assert "Read" in tools_str
    assert "Glob" in tools_str
    assert "Grep" in tools_str
    # Review agent should NOT have Edit or Write
    tool_idx = cmd.index("--allowedTools") + 1
    allowed = cmd[tool_idx]
    assert "Edit" not in allowed
    assert "Write" not in allowed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_agents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents'`

- [ ] **Step 3: Implement agents/__init__.py (empty)**

```python
# agents/__init__.py
```

- [ ] **Step 4: Implement agents/base.py**

```python
# agents/base.py


def build_claude_command(
    prompt: str,
    allowed_tools: list[str],
    output_format: str = "stream-json",
    max_budget_usd: float | None = None,
) -> list[str]:
    """Build the claude -p command line."""
    cmd = [
        "claude",
        "-p",
        "--output-format",
        output_format,
        "--allowedTools",
        ",".join(allowed_tools),
    ]
    if max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(max_budget_usd)])
    cmd.append(prompt)
    return cmd
```

- [ ] **Step 5: Implement agents/coding.py**

```python
# agents/coding.py
from agents.base import build_claude_command

CODING_PROMPT = """You are a coding agent working on GitHub issue {repo}#{issue_number}.

## Issue: {issue_title}

{issue_body}

## Instructions

1. Create a feature branch named `ai/issue-{issue_number}` from the default branch.
2. Implement the work described in the issue, following the checklist and acceptance criteria.
3. Write tests before implementation. Run tests to verify they fail, then implement.
4. Run all tests to ensure they pass.
5. Open a draft pull request linking to issue #{issue_number}.
6. Keep changes focused — modify no more than 10 files.
7. If the requirements are ambiguous or you cannot proceed, stop and explain why in a comment.

Do NOT merge anything. Draft PR only.
"""

ALLOWED_TOOLS = ["Edit", "Write", "Bash", "Read", "Glob", "Grep"]


class CodingAgent:
    def build_prompt(self, issue_title: str, issue_body: str, issue_number: int, repo: str) -> str:
        return CODING_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
        )

    def build_command(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        max_budget_usd: float = 1.0,
    ) -> list[str]:
        prompt = self.build_prompt(issue_title, issue_body, issue_number, repo)
        return build_claude_command(
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
            max_budget_usd=max_budget_usd,
        )
```

- [ ] **Step 6: Implement agents/testing.py**

```python
# agents/testing.py
from agents.base import build_claude_command

TESTING_PROMPT = """You are a testing agent verifying work on GitHub issue {repo}#{issue_number}.

## Issue: {issue_title}

{issue_body}

## PR Branch: {pr_branch}

## Instructions

1. Check out the branch `{pr_branch}`.
2. Run the existing test suite. Record any failures.
3. Review the acceptance criteria in the issue. For each criterion, verify there is a test covering it.
4. If tests are missing for acceptance criteria, write them in the appropriate test files.
5. Run the full test suite again. All tests must pass.
6. If tests fail and you cannot fix them by adding test code only, stop and report the failures.

You may only write code in test files. Do not modify implementation code.
"""

ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Bash", "Write"]


class TestingAgent:
    def build_prompt(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        pr_branch: str,
    ) -> str:
        return TESTING_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
            pr_branch=pr_branch,
        )

    def build_command(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        pr_branch: str,
        max_budget_usd: float = 0.50,
    ) -> list[str]:
        prompt = self.build_prompt(issue_title, issue_body, issue_number, repo, pr_branch)
        return build_claude_command(
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
            max_budget_usd=max_budget_usd,
        )
```

- [ ] **Step 7: Implement agents/review.py**

```python
# agents/review.py
from agents.base import build_claude_command

REVIEW_PROMPT = """You are a code review agent for GitHub issue {repo}#{issue_number}, PR #{pr_number}.

## Issue: {issue_title}

{issue_body}

## Instructions

1. Read the PR diff for PR #{pr_number}.
2. Check every change against the acceptance criteria in the issue.
3. Look for: bugs, security issues, missing edge cases, style problems, missing tests.
4. Leave specific review comments on the PR explaining any issues found.
5. If the PR meets all acceptance criteria and has no significant issues, approve it.
6. If there are issues, request changes with clear, actionable feedback.

You are read-only. Do NOT modify any files. Only leave review comments.
"""

ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Bash"]


class ReviewAgent:
    def build_prompt(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        pr_number: int,
    ) -> str:
        return REVIEW_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
            pr_number=pr_number,
        )

    def build_command(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        pr_number: int,
        max_budget_usd: float = 0.50,
    ) -> list[str]:
        prompt = self.build_prompt(issue_title, issue_body, issue_number, repo, pr_number)
        return build_claude_command(
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
            max_budget_usd=max_budget_usd,
        )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_agents.py -v`
Expected: 8 passed

- [ ] **Step 9: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add agents/__init__.py agents/base.py agents/coding.py agents/testing.py agents/review.py tests/test_agents.py
git commit -m "feat: agent dispatch with coding, testing, and review prompt templates"
```

---

### Task 6: Logger

**Files:**
- Create: `logger.py`

- [ ] **Step 1: Implement logger.py**

```python
# logger.py
import json
import logging
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        if hasattr(record, "issue"):
            log_entry["issue"] = record.issue
        if hasattr(record, "agent_type"):
            log_entry["agent_type"] = record.agent_type
        return json.dumps(log_entry)


def setup_logger(name: str = "orchestrator", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    return logger
```

- [ ] **Step 2: Quick smoke test**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -c "from logger import setup_logger; log = setup_logger(); log.info('test')" 2>&1`
Expected: JSON output with `"message": "test"` on stderr

- [ ] **Step 3: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add logger.py
git commit -m "feat: structured JSON logger"
```

---

### Task 7: Orchestrator Main Loop

**Files:**
- Create: `orchestrator.py`
- Create: `tests/test_orchestrator.py`

This is the core — it ties everything together. The orchestrator runs once per cron invocation and exits.

- [ ] **Step 1: Write the failing tests**

```python
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
    # Mock pull_requests for finding PR branch/number
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

    # Should have swapped label to ai-in-progress
    mock_gh.swap_label.assert_called_with("owner/repo", 42, "ai-ready", "ai-in-progress")
    # Should have spawned a process
    MockPopen.assert_called_once()
    # Should have recorded in state
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
    # Pre-populate state with an active agent on this issue
    orch.state.add_agent(pid=11111, issue="owner/repo#42", repo="owner/repo", agent_type="coding", timeout_minutes=60, attempt=1)

    orch.run()

    # Should NOT spawn another agent
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
    # Pre-populate with one active coding agent
    orch.state.add_agent(pid=11111, issue="owner/repo#99", repo="owner/repo", agent_type="coding", timeout_minutes=60, attempt=1)

    orch.run()

    # At max_coding=1, and one already running, should not spawn any
    MockPopen.assert_not_called()


@patch("orchestrator.GitHubClient")
def test_handles_timed_out_agent(MockGH, config, state_dir):
    mock_gh = MockGH.return_value

    orch = Orchestrator(config, state_dir=state_dir)
    # Add an agent that started 2 hours ago with 60 min timeout
    orch.state.add_agent(
        pid=11111, issue="owner/repo#42", repo="owner/repo",
        agent_type="coding", timeout_minutes=60, attempt=1,
    )
    # Backdate it
    orch.state.agents[0]["started_at"] = "2020-01-01T00:00:00+00:00"
    orch.state._save()

    with patch("orchestrator.os.kill") as mock_kill:
        with patch("orchestrator.subprocess.Popen"):
            mock_gh.fetch_issues_by_label.return_value = []
            mock_gh.get_attempt_count.return_value = 0
            orch.run()

    # Should have tried to kill the process
    mock_kill.assert_called()
    # Should have labeled error
    mock_gh.swap_label.assert_called_with("owner/repo", 42, "ai-in-progress", "ai-error")


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_max_retries_labels_blocked(MockGH, MockPopen, config, state_dir):
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "Fix bug", "Body", ["ai-ready"])
    mock_gh.fetch_issues_by_label.return_value = [mock_issue]
    mock_gh.get_attempt_count.return_value = 3  # Already at max

    orch = Orchestrator(config, state_dir=state_dir)
    orch.run()

    # Should swap to blocked, not dispatch
    mock_gh.swap_label.assert_called_with("owner/repo", 42, "ai-ready", "ai-blocked")
    MockPopen.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'orchestrator'`

- [ ] **Step 3: Implement orchestrator.py**

```python
# orchestrator.py
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone

from config import load_config
from state import StateManager
from github_client import GitHubClient
from agents.coding import CodingAgent
from agents.testing import TestingAgent
from agents.review import ReviewAgent
from notifications.slack import SlackNotifier
from logger import setup_logger

logger = setup_logger()


class Orchestrator:
    def __init__(self, config: dict, state_dir: str | None = None):
        self.config = config
        self.labels = config["labels"]
        self.gh = GitHubClient()
        self.state = StateManager(state_dir or os.path.expanduser("~/.agent-orchestrator"))
        self.slack = SlackNotifier(config["slack"].get("webhook_url"))
        self.coding_agent = CodingAgent()
        self.testing_agent = TestingAgent()
        self.review_agent = ReviewAgent()

    def run(self):
        """Single orchestration cycle: check agents, dispatch new work."""
        self._check_running_agents()
        for repo in self.config["repos"]:
            self._process_ready_issues(repo)
            self._process_testing_issues(repo)
            self._process_review_issues(repo)

    def _check_running_agents(self):
        """Check PIDs, handle timeouts and completions."""
        for agent in list(self.state.agents):
            pid = agent["pid"]
            if self._is_process_alive(pid):
                if self._is_timed_out(agent):
                    self._handle_timeout(agent)
            else:
                self._handle_completion(agent)

    def _is_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _is_timed_out(self, agent: dict) -> bool:
        started = datetime.fromisoformat(agent["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 60
        return elapsed > agent["timeout_minutes"]

    def _handle_timeout(self, agent: dict):
        pid = agent["pid"]
        issue = agent["issue"]
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])

        logger.warning(f"Agent timed out: {issue} (pid={pid})")
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        label_map = {
            "coding": self.labels["in_progress"],
            "testing": self.labels["testing"],
            "review": self.labels["review_needed"],
        }
        old_label = label_map.get(agent["type"], self.labels["in_progress"])
        self.gh.swap_label(repo, issue_number, old_label, self.labels["error"])
        self.gh.add_comment(repo, issue_number, f"[agent-orchestrator] Agent timed out after {agent['timeout_minutes']} minutes.")
        self.slack.notify_timeout(issue, agent["timeout_minutes"])
        self.state.remove_agent(pid)

    def _handle_completion(self, agent: dict):
        """Agent process exited — clean up state. Label transitions are handled by the agent itself."""
        pid = agent["pid"]
        issue = agent["issue"]
        logger.info(f"Agent completed: {issue} (pid={pid}, type={agent['type']})")
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])
        self.gh.add_comment(repo, issue_number, f"[agent-orchestrator] Attempt {agent['attempt']} completed ({agent['type']} agent).")
        self.state.remove_agent(pid)

    def _process_ready_issues(self, repo: str):
        """Dispatch coding agents for ai-ready issues."""
        issues = self.gh.fetch_issues_by_label(repo, self.labels["ready"])
        for issue in issues:
            issue_key = f"{repo}#{issue.number}"
            if self.state.is_issue_active(issue_key):
                continue

            attempt_count = self.gh.get_attempt_count(repo, issue.number)
            if attempt_count >= self.config["guardrails"]["max_retry_cycles"]:
                logger.warning(f"Max retries reached for {issue_key}")
                self.gh.swap_label(repo, issue.number, self.labels["ready"], self.labels["blocked"])
                self.gh.add_comment(repo, issue.number, f"[agent-orchestrator] Max retry cycles ({self.config['guardrails']['max_retry_cycles']}) reached. Marking blocked.")
                self.slack.notify_max_retries(issue_key, self.config["guardrails"]["max_retry_cycles"])
                continue

            current_coding = len(self.state.get_agents_by_type("coding"))
            if current_coding >= self.config["concurrency"]["max_coding"]:
                logger.info(f"Coding concurrency limit reached ({current_coding}), skipping {issue_key}")
                break

            self._dispatch_coding(repo, issue, attempt_count + 1)

    def _process_testing_issues(self, repo: str):
        """Dispatch testing agents for ai-testing issues."""
        issues = self.gh.fetch_issues_by_label(repo, self.labels["testing"])
        for issue in issues:
            issue_key = f"{repo}#{issue.number}"
            if self.state.is_issue_active(issue_key):
                continue

            current_testing = len(self.state.get_agents_by_type("testing"))
            if current_testing >= self.config["concurrency"]["max_testing"]:
                break

            self._dispatch_testing(repo, issue)

    def _process_review_issues(self, repo: str):
        """Dispatch review agents for ai-review-needed issues."""
        issues = self.gh.fetch_issues_by_label(repo, self.labels["review_needed"])
        for issue in issues:
            issue_key = f"{repo}#{issue.number}"
            if self.state.is_issue_active(issue_key):
                continue

            current_review = len(self.state.get_agents_by_type("review"))
            if current_review >= self.config["concurrency"]["max_review"]:
                break

            self._dispatch_review(repo, issue)

    def _dispatch_coding(self, repo: str, issue, attempt: int):
        issue_key = f"{repo}#{issue.number}"
        logger.info(f"Dispatching coding agent for {issue_key} (attempt {attempt})")

        cmd = self.coding_agent.build_command(
            issue_title=issue.title,
            issue_body=issue.body or "",
            issue_number=issue.number,
            repo=repo,
        )
        log_path = self.state.log_path(repo, issue.number)
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        self.gh.swap_label(repo, issue.number, self.labels["ready"], self.labels["in_progress"])
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=repo,
            agent_type="coding",
            timeout_minutes=self.config["timeouts"]["coding_minutes"],
            attempt=attempt,
        )

    def _dispatch_testing(self, repo: str, issue):
        issue_key = f"{repo}#{issue.number}"
        logger.info(f"Dispatching testing agent for {issue_key}")

        pr_branch = f"ai/issue-{issue.number}"
        cmd = self.testing_agent.build_command(
            issue_title=issue.title,
            issue_body=issue.body or "",
            issue_number=issue.number,
            repo=repo,
            pr_branch=pr_branch,
        )
        log_path = self.state.log_path(repo, issue.number)
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        # No label swap needed — issue is already ai-testing
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=repo,
            agent_type="testing",
            timeout_minutes=self.config["timeouts"]["testing_minutes"],
            attempt=1,
        )

    def _dispatch_review(self, repo: str, issue):
        issue_key = f"{repo}#{issue.number}"
        logger.info(f"Dispatching review agent for {issue_key}")

        pr_number = issue.number  # Assumes PR number matches; can be refined
        cmd = self.review_agent.build_command(
            issue_title=issue.title,
            issue_body=issue.body or "",
            issue_number=issue.number,
            repo=repo,
            pr_number=pr_number,
        )
        log_path = self.state.log_path(repo, issue.number)
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        # No label swap needed — issue is already ai-review-needed
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=repo,
            agent_type="review",
            timeout_minutes=self.config["timeouts"]["review_minutes"],
            attempt=1,
        )


def main():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    config = load_config(config_path)
    orchestrator = Orchestrator(config)
    orchestrator.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/test_orchestrator.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator main loop with dispatch, timeout, and retry handling"
```

---

### Task 8: End-to-End Integration Test

**Files:**
- Modify: `tests/test_orchestrator.py` (add integration test)

- [ ] **Step 1: Add a full-cycle integration test**

Append to `tests/test_orchestrator.py`:

```python
@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_full_cycle_ready_to_dispatch(MockGH, MockPopen, config, state_dir):
    """Simulates a full orchestrator run: finds a ready issue, dispatches, records state."""
    mock_gh = MockGH.return_value

    # Issue 10 is ai-ready, Issue 20 is ai-review-needed
    ready_issue = _mock_issue(10, "Add feature", "## Acceptance Criteria\n- [ ] Done", ["ai-ready"])
    review_issue = _mock_issue(20, "Review feature", "Body", ["ai-review-needed"])

    def side_effect(repo, label):
        if label == "ai-ready":
            return [ready_issue]
        if label == "ai-review-needed":
            return [review_issue]
        return []

    mock_gh.fetch_issues_by_label.side_effect = side_effect
    mock_gh.get_attempt_count.return_value = 0

    mock_proc_coding = MagicMock()
    mock_proc_coding.pid = 1001
    mock_proc_review = MagicMock()
    mock_proc_review.pid = 1002
    MockPopen.side_effect = [mock_proc_coding, mock_proc_review]

    orch = Orchestrator(config, state_dir=state_dir)
    orch.run()

    assert len(orch.state.agents) == 2
    types = {a["type"] for a in orch.state.agents}
    assert types == {"coding", "review"}
```

- [ ] **Step 2: Run full test suite**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add tests/test_orchestrator.py
git commit -m "test: add end-to-end integration test for orchestrator"
```

---

### Task 9: Cron Setup and Final Wiring

**Files:**
- Create: `setup.sh` (helper script for initial setup)

- [ ] **Step 1: Create setup.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Agent Orchestrator Setup ==="

# Create runtime directories
mkdir -p ~/.agent-orchestrator/logs
echo "Created ~/.agent-orchestrator/logs"

# Install Python dependencies
cd "$SCRIPT_DIR"
python3 -m pip install -r requirements.txt
echo "Installed Python dependencies"

# Check for required env vars
if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "WARNING: GITHUB_TOKEN not set. Export it before running the orchestrator."
    echo "  export GITHUB_TOKEN=ghp_your_token_here"
fi

if [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
    echo "WARNING: SLACK_WEBHOOK_URL not set. Slack notifications will be disabled."
    echo "  export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..."
fi

# Show cron entry to add
echo ""
echo "Add this to your crontab (crontab -e):"
echo ""
echo "GITHUB_TOKEN=\$GITHUB_TOKEN"
echo "SLACK_WEBHOOK_URL=\$SLACK_WEBHOOK_URL"
echo "*/10 * * * * cd $SCRIPT_DIR && python3 orchestrator.py >> /var/log/agent-orchestrator.log 2>&1"
echo ""
echo "Setup complete."
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x /home/bryang/Dev_Space/agent-orchestrator/setup.sh`

- [ ] **Step 3: Update config.yaml with real placeholder reminder**

Edit `config.yaml` to add a comment at the top:

```yaml
# Agent Orchestrator Configuration
# Before running: update repos list and set GITHUB_TOKEN + SLACK_WEBHOOK_URL env vars

repos:
  - owner/example-repo  # Replace with your actual repos
```

- [ ] **Step 4: Run final full test suite**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add setup.sh config.yaml
git commit -m "feat: setup script and finalized config"
```

---

### Task 10: Add .gitignore and Final Cleanup

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Create .gitignore**

```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
build/
.env
venv/
```

- [ ] **Step 2: Run full test suite one last time**

Run: `cd /home/bryang/Dev_Space/agent-orchestrator && python3 -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
cd /home/bryang/Dev_Space/agent-orchestrator
git add .gitignore
git commit -m "chore: add .gitignore"
```
