# Version-Gated Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add version-gated dispatch so the orchestrator only runs issues from the lowest incomplete version, with bootstrap support and Slack notifications on version completion.

**Architecture:** A `versioning.py` module handles version parsing and active version detection. The orchestrator's `_process_ready_issues` filters issues by active version before dispatching. A new `_check_version_completion` method runs each cycle and notifies via Slack when a version finishes. Config gains a `versioning` section.

**Tech Stack:** Python 3.11+, regex for version parsing, existing GitHub GraphQL/REST client

---

### Task 1: Add Version Parsing Module

**Files:**
- Create: `versioning.py`
- Create: `tests/test_versioning.py`

- [ ] **Step 1: Write failing tests for version parsing**

```python
# tests/test_versioning.py
import pytest
from versioning import parse_version, get_active_version


def test_parse_version_standard():
    assert parse_version("[v0.1] Basic arena scene") == (0, 1)


def test_parse_version_higher():
    assert parse_version("[v1.2] Some feature") == (1, 2)


def test_parse_version_bootstrap():
    assert parse_version("[bootstrap] Project scaffold") == (0, 0)


def test_parse_version_no_tag():
    assert parse_version("Fix bug in player scene") is None


def test_parse_version_malformed():
    assert parse_version("[vX.Y] Bad version") is None


def test_get_active_version_bootstrap_first():
    issues = [
        {"title": "[bootstrap] Setup", "status": "ai-ready"},
        {"title": "[v0.1] Feature A", "status": "ai-ready"},
    ]
    assert get_active_version(issues) == (0, 0)


def test_get_active_version_skips_done():
    issues = [
        {"title": "[v0.1] Feature A", "status": "Done"},
        {"title": "[v0.2] Feature B", "status": "ai-ready"},
    ]
    assert get_active_version(issues) == (0, 2)


def test_get_active_version_blocked_holds_version():
    issues = [
        {"title": "[v0.1] Feature A", "status": "Done"},
        {"title": "[v0.1] Feature B", "status": "ai-blocked"},
        {"title": "[v0.2] Feature C", "status": "ai-ready"},
    ]
    assert get_active_version(issues) == (0, 1)


def test_get_active_version_all_done():
    issues = [
        {"title": "[v0.1] Feature A", "status": "Done"},
        {"title": "[v0.1] Feature B", "status": "Done"},
    ]
    assert get_active_version(issues) is None


def test_get_active_version_no_versioned_issues():
    issues = [
        {"title": "Unversioned task", "status": "ai-ready"},
    ]
    assert get_active_version(issues) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_versioning.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'versioning'`

- [ ] **Step 3: Implement versioning module**

```python
# versioning.py
import re

VERSION_PATTERN = re.compile(r"\[v(\d+)\.(\d+)\]")
BOOTSTRAP_PATTERN = re.compile(r"\[bootstrap\]", re.IGNORECASE)


def parse_version(title: str) -> tuple[int, int] | None:
    """Extract version tuple from issue title. Returns (major, minor) or None."""
    bootstrap_match = BOOTSTRAP_PATTERN.search(title)
    if bootstrap_match:
        return (0, 0)
    version_match = VERSION_PATTERN.search(title)
    if version_match:
        return (int(version_match.group(1)), int(version_match.group(2)))
    return None


def get_active_version(issues: list[dict]) -> tuple[int, int] | None:
    """Determine the lowest incomplete version from a list of issues.

    Each issue dict must have 'title' and 'status' keys.
    Returns the version tuple of the lowest version that has any issue
    not in 'Done' status, or None if all versioned issues are done.
    """
    version_statuses: dict[tuple[int, int], list[str]] = {}
    for issue in issues:
        version = parse_version(issue["title"])
        if version is None:
            continue
        version_statuses.setdefault(version, []).append(issue["status"])

    if not version_statuses:
        return None

    for version in sorted(version_statuses.keys()):
        statuses = version_statuses[version]
        if not all(s == "Done" for s in statuses):
            return version

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_versioning.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add versioning.py tests/test_versioning.py
git commit -m "feat: add version parsing module"
```

---

### Task 2: Add `fetch_all_project_issues` to GitHubClient

**Files:**
- Modify: `github_client.py`
- Modify: `tests/test_github_client.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_github_client.py

def test_fetch_all_project_issues(mock_client):
    mock_client._graphql = MagicMock(return_value={
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
    })
    issues = mock_client.fetch_all_project_issues()
    assert len(issues) == 2
    assert issues[0]["title"] == "[v0.1] Feature A"
    assert issues[0]["status"] == "ai-ready"
    assert issues[1]["status"] == "Done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_github_client.py::test_fetch_all_project_issues -v`
Expected: FAIL — `AttributeError: 'GitHubClient' object has no attribute 'fetch_all_project_issues'`

- [ ] **Step 3: Implement `fetch_all_project_issues`**

Add this method to `GitHubClient` in `github_client.py`, after the existing `fetch_issues_by_status` method:

```python
    def fetch_all_project_issues(self) -> list[dict]:
        """Fetch all issues in the project with their status names.

        Returns a list of dicts with keys: number, title, body, repo, project_item_id, status
        """
        issues = []
        cursor = None

        while True:
            after_clause = f', after: "{cursor}"' if cursor else ""
            data = self._graphql(
                f"""
                query($projectId: ID!) {{
                    node(id: $projectId) {{
                        ... on ProjectV2 {{
                            items(first: 50{after_clause}) {{
                                pageInfo {{
                                    hasNextPage
                                    endCursor
                                }}
                                nodes {{
                                    id
                                    fieldValueByName(name: "Status") {{
                                        ... on ProjectV2ItemFieldSingleSelectValue {{
                                            name
                                        }}
                                    }}
                                    content {{
                                        ... on Issue {{
                                            number
                                            title
                                            body
                                            state
                                            repository {{
                                                nameWithOwner
                                            }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    }}
                }}
                """,
                {"projectId": self._project_id},
            )

            items = data["node"]["items"]
            for node in items["nodes"]:
                content = node.get("content")
                if not content or not content.get("number"):
                    continue
                field_value = node.get("fieldValueByName")
                status_name = field_value.get("name") if field_value else None
                issues.append({
                    "number": content["number"],
                    "title": content["title"],
                    "body": content.get("body", ""),
                    "repo": content["repository"]["nameWithOwner"],
                    "project_item_id": node["id"],
                    "status": status_name,
                })

            if items["pageInfo"]["hasNextPage"]:
                cursor = items["pageInfo"]["endCursor"]
            else:
                break

        return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_github_client.py::test_fetch_all_project_issues -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add github_client.py tests/test_github_client.py
git commit -m "feat: add fetch_all_project_issues method"
```

---

### Task 3: Add Slack Notification for Version Completion

**Files:**
- Modify: `notifications/slack.py`
- Modify: `tests/test_slack.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_slack.py

def test_notify_version_complete(mock_slack):
    mock_slack.notify_version_complete("v0.1", 5)
    mock_slack.send.assert_called_once_with(
        ":tada: Version v0.1 complete — 5 issues merged to ai/dev. Ready for next batch of issues."
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_slack.py::test_notify_version_complete -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement `notify_version_complete`**

Add to the `SlackNotifier` class in `notifications/slack.py`:

```python
    def notify_version_complete(self, version: str, issue_count: int):
        self.send(f":tada: Version {version} complete — {issue_count} issues merged to ai/dev. Ready for next batch of issues.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_slack.py::test_notify_version_complete -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add notifications/slack.py tests/test_slack.py
git commit -m "feat: add Slack notification for version completion"
```

---

### Task 4: Add Versioning Config

**Files:**
- Modify: `config.yaml`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Add versioning section to config.yaml**

Add after the `branches` section:

```yaml
versioning:
  enabled: true
  auto_create_issues: false
  bootstrap_timeout_minutes: 120
  bootstrap_max_budget_usd: 5.0
```

- [ ] **Step 2: Verify config loads**

Run: `python3 -c "from config import load_config; c = load_config('config.yaml'); print(c['versioning'])"`
Expected: `{'enabled': True, 'auto_create_issues': False, 'bootstrap_timeout_minutes': 120, 'bootstrap_max_budget_usd': 5.0}`

- [ ] **Step 3: Commit**

```bash
git add config.yaml
git commit -m "feat: add versioning config section"
```

---

### Task 5: Wire Version Gating into Orchestrator

**Files:**
- Modify: `orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing test for version-filtered dispatch**

```python
# Add to tests/test_orchestrator.py

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

    orch.run()

    # Should only dispatch v0.1 issue, not v0.2
    MockPopen.assert_called_once()
    assert orch.state.agents[0]["issue"] == "owner/repo#1"
```

- [ ] **Step 2: Write failing test for bootstrap concurrency limit**

```python
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

    orch.run()

    # Bootstrap should only dispatch 1 even though max_coding is 3
    MockPopen.assert_called_once()
```

- [ ] **Step 3: Write failing test for version completion notification**

```python
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
    # Simulate that we haven't notified about v0.1 yet
    orch._notified_versions = set()

    orch.run()

    mock_slack.notify_version_complete.assert_called_once_with("v0.1", 2)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_orchestrator.py::test_version_gating_dispatches_only_active_version tests/test_orchestrator.py::test_bootstrap_limits_concurrency_to_one tests/test_orchestrator.py::test_version_completion_sends_slack -v`
Expected: All 3 FAIL

- [ ] **Step 5: Implement version gating in orchestrator**

Modify `orchestrator.py`:

1. Add import at top:
```python
from versioning import parse_version, get_active_version
```

2. Add `_notified_versions` to `__init__`:
```python
        self._notified_versions = set()
```

3. Add `_check_version_completion` method (add after `_check_running_agents`):
```python
    def _check_version_completion(self):
        """Check if the most recently completed version should trigger a notification."""
        if not self.config.get("versioning", {}).get("enabled", False):
            return
        all_issues = self.gh.fetch_all_project_issues()
        # Group by version, find completed versions
        version_issues: dict[tuple[int, int], list[dict]] = {}
        for issue in all_issues:
            version = parse_version(issue["title"])
            if version is not None:
                version_issues.setdefault(version, []).append(issue)

        for version in sorted(version_issues.keys()):
            statuses = [i["status"] for i in version_issues[version]]
            if all(s == "Done" for s in statuses) and version not in self._notified_versions:
                self._notified_versions.add(version)
                version_label = "bootstrap" if version == (0, 0) else f"v{version[0]}.{version[1]}"
                logger.info(f"Version {version_label} complete")
                self.slack.notify_version_complete(version_label, len(statuses))
```

4. Replace `_process_ready_issues` with version-aware version:
```python
    def _process_ready_issues(self):
        """Dispatch coding agents for ai-ready issues, respecting version gating."""
        issues = self.gh.fetch_issues_by_status(self.statuses["ready"])
        versioning_enabled = self.config.get("versioning", {}).get("enabled", False)
        active_version = None
        is_bootstrap = False

        if versioning_enabled:
            all_issues = self.gh.fetch_all_project_issues()
            active_version = get_active_version(all_issues)

        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            if self.state.is_issue_active(issue_key):
                continue

            # Version filter: skip issues not in the active version
            if versioning_enabled:
                issue_version = parse_version(issue["title"])
                if active_version is not None:
                    # Active version exists — only dispatch matching issues
                    if issue_version != active_version:
                        continue
                    is_bootstrap = active_version == (0, 0)
                else:
                    # All versioned work is done — only dispatch unversioned issues
                    if issue_version is not None:
                        continue

            attempt_count = self.gh.get_attempt_count(issue["repo"], issue["number"])
            if attempt_count >= self.config["guardrails"]["max_retry_cycles"]:
                logger.warning(f"Max retries reached for {issue_key}")
                self.gh.update_status(issue["project_item_id"], self.statuses["blocked"])
                self.gh.add_comment(issue["repo"], issue["number"],
                    f"[agent-orchestrator] Max retry cycles ({self.config['guardrails']['max_retry_cycles']}) reached. Marking blocked.")
                self.slack.notify_max_retries(issue_key, self.config["guardrails"]["max_retry_cycles"])
                continue

            # Bootstrap: max 1 concurrent coding agent
            max_coding = 1 if is_bootstrap else self.config["concurrency"]["max_coding"]
            current_coding = len(self.state.get_agents_by_type("coding"))
            if current_coding >= max_coding:
                logger.info(f"Coding concurrency limit reached ({current_coding}/{max_coding}), skipping {issue_key}")
                break

            # Use bootstrap-specific timeout and budget if applicable
            if is_bootstrap:
                timeout = self.config.get("versioning", {}).get("bootstrap_timeout_minutes", 120)
                budget = self.config.get("versioning", {}).get("bootstrap_max_budget_usd", 5.0)
                self._dispatch_coding(issue, attempt_count + 1, timeout_override=timeout, budget_override=budget)
            else:
                self._dispatch_coding(issue, attempt_count + 1)
```

5. Update `_dispatch_coding` to accept overrides:
```python
    def _dispatch_coding(self, issue: dict, attempt: int, timeout_override: int | None = None, budget_override: float | None = None):
        issue_key = f"{issue['repo']}#{issue['number']}"
        logger.info(f"Dispatching coding agent for {issue_key} (attempt {attempt})")

        timeout = timeout_override or self.config["timeouts"]["coding_minutes"]
        integration_branch = self.config.get("branches", {}).get("integration", "ai/dev")
        cmd = self.coding_agent.build_command(
            issue_title=issue["title"],
            issue_body=issue["body"] or "",
            issue_number=issue["number"],
            repo=issue["repo"],
            integration_branch=integration_branch,
            max_budget_usd=budget_override or 1.0,
        )
        log_path = self.state.log_path(issue["repo"], issue["number"])
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        self.gh.update_status(issue["project_item_id"], self.statuses["in_progress"])
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=issue["repo"],
            agent_type="coding",
            timeout_minutes=timeout,
            attempt=attempt,
            project_item_id=issue["project_item_id"],
            log_path=log_path,
        )
```

6. Update `run()` to call `_check_version_completion`:
```python
    def run(self):
        """Single orchestration cycle: check agents, auto-merge, dispatch new work."""
        self._check_running_agents()
        self._process_complete_issues()
        self._check_version_completion()
        self._process_ready_issues()
        self._process_testing_issues()
        self._process_review_issues()
```

- [ ] **Step 6: Run all new tests**

Run: `python3 -m pytest tests/test_orchestrator.py -v`
Expected: All tests PASS (existing + 3 new)

- [ ] **Step 7: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 8: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add version-gated dispatch to orchestrator"
```

---

### Task 6: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Version Gating section**

After the "Integration PR Workflow" section, add:

```markdown
## Version-Gated Dispatch

Issues are dispatched in version order based on `[vX.Y]` tags in issue titles. The orchestrator only runs issues from the lowest incomplete version — all issues in v0.1 must reach `Done` before any v0.2 issue starts.

### Version Tags

- `[bootstrap]` — Runs first, alone (max 1 concurrent agent). Sets up project scaffold.
- `[v0.1]`, `[v0.2]`, etc. — Run in order. All issues within a version run in parallel.
- No tag — Runs after all versioned work is complete.

### Rules

- All issues within a version must be safe to run in parallel (no shared file writes)
- A version is complete when all its issues are `Done`
- Blocked issues hold the version open — resolve or remove them to proceed
- Slack notification is sent when a version completes

### Config

```yaml
versioning:
  enabled: true                    # false to disable version gating
  auto_create_issues: false        # reserved for future use
  bootstrap_timeout_minutes: 120   # extended timeout for bootstrap
  bootstrap_max_budget_usd: 5.0    # extended budget for bootstrap
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add version-gated dispatch section to README"
```
