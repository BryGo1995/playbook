# Model Tiering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configurable per-role model (`claude -p --model <id>`) for the coding/testing/review agents, with pinned full model IDs defaulting to Sonnet 4.6 for coding, Haiku 4.5 for testing, Opus 4.7 for review.

**Architecture:** Add a `models:` block to `defaults.yaml`. Thread an optional `model: str | None` parameter through `build_claude_command` → each `<Role>Agent.build_command`. The orchestrator's three `_dispatch_*` methods read `self.config["models"]["<role>"]` (with `.get` fallback to `None`) and pass it down. Backward-compatible: a missing `models` block produces `model=None` which omits the CLI flag and preserves today's "use CLI default" behavior.

**Tech Stack:** Python 3 (no new deps), pytest with `unittest.mock` (existing pattern), `subprocess.Popen` mocked at the orchestrator boundary.

**Spec:** `docs/specs/2026-05-14-model-tiering-and-bench-design.md`

---

## File Structure

**Modified files:**
- `defaults.yaml` — add `models:` block at the top level.
- `agents/base.py` — `build_claude_command` gains `model: str | None = None` kwarg; emits `["--model", model]` after `--max-budget-usd` when non-None.
- `agents/coding.py` — `CodingAgent.build_command` gains `model: str | None = None` kwarg; passed to `build_claude_command`.
- `agents/testing.py` — same shape.
- `agents/review.py` — same shape.
- `orchestrator.py` — each of `_dispatch_coding`, `_dispatch_testing`, `_dispatch_review` reads `self.config.get("models", {}).get("<role>")` and passes it to the agent's `build_command`.

**Modified tests:**
- `tests/test_agents.py` — new tests on `build_claude_command` `--model` flag + per-agent pass-through.
- `tests/test_orchestrator.py` — new tests asserting argv `--model <id>` per role + backward-compat with missing `models:`.
- `tests/test_config.py` — new test asserting `defaults.yaml` exposes the three model IDs after `load_config`.

---

## Task 1: Add `--model` flag to `build_claude_command`

**Files:**
- Modify: `agents/base.py:37-59`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_agents.py` (after `test_build_claude_command_omits_disallowed_when_none_or_empty`):

```python
def test_build_claude_command_includes_model_when_provided():
    cmd = build_claude_command(
        prompt="x",
        allowed_tools=["Bash"],
        max_budget_usd=1.0,
        model="claude-sonnet-4-6",
    )
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"


def test_build_claude_command_omits_model_when_none():
    cmd = build_claude_command(
        prompt="x",
        allowed_tools=["Bash"],
        max_budget_usd=1.0,
        model=None,
    )
    assert "--model" not in cmd


def test_build_claude_command_model_appears_after_max_budget():
    """Argv ordering: --max-budget-usd <val> --model <id> ... <prompt>."""
    cmd = build_claude_command(
        prompt="x",
        allowed_tools=["Bash"],
        max_budget_usd=1.0,
        model="claude-opus-4-7",
    )
    budget_idx = cmd.index("--max-budget-usd")
    model_idx = cmd.index("--model")
    assert model_idx > budget_idx
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents.py -k model -v`
Expected: 3 failures — `TypeError: build_claude_command() got an unexpected keyword argument 'model'`.

- [ ] **Step 3: Implement**

In `agents/base.py`, change `build_claude_command` signature and body:

```python
def build_claude_command(
    prompt: str,
    allowed_tools: list[str],
    output_format: str = "stream-json",
    max_budget_usd: float | None = None,
    disallowed_tools: list[str] | None = None,
    model: str | None = None,
) -> list[str]:
    """Build the claude -p command line."""
    cmd = [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        output_format,
        "--allowedTools",
        ",".join(allowed_tools),
    ]
    if disallowed_tools:
        cmd.extend(["--disallowedTools", ",".join(disallowed_tools)])
    if max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(max_budget_usd)])
    if model is not None:
        cmd.extend(["--model", model])
    cmd.append(prompt)
    return cmd
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_agents.py -k model -v`
Expected: 3 passes.

- [ ] **Step 5: Commit**

```bash
git add agents/base.py tests/test_agents.py
git commit -m "feat(agents): add --model flag to build_claude_command"
```

---

## Task 2: Thread `model` through `CodingAgent.build_command`

**Files:**
- Modify: `agents/coding.py:43-66`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_agents.py`:

```python
def test_coding_agent_passes_model_to_build_claude_command():
    cmd = CodingAgent().build_command(
        issue_title="t",
        issue_body="b",
        issue_number=1,
        repo="o/r",
        model="claude-sonnet-4-6",
    )
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-4-6"


def test_coding_agent_omits_model_when_not_provided():
    cmd = CodingAgent().build_command(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
    )
    assert "--model" not in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents.py -k coding_agent_passes_model -v`
Expected: FAIL — `TypeError: build_command() got an unexpected keyword argument 'model'`.

- [ ] **Step 3: Implement**

In `agents/coding.py`, change `build_command` signature and body:

```python
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
    project_addendum: str = "",
    model: str | None = None,
) -> list[str]:
    prompt = self.build_prompt(
        issue_title, issue_body, issue_number, repo, integration_branch,
        attempt=attempt, prior_attempt_context=prior_attempt_context,
        project_addendum=project_addendum,
    )
    return build_claude_command(
        prompt=prompt,
        allowed_tools=ALLOWED_TOOLS,
        disallowed_tools=DISALLOWED_TOOLS,
        max_budget_usd=max_budget_usd,
        model=model,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_agents.py -k coding_agent -v`
Expected: all coding tests pass (including the existing ones).

- [ ] **Step 5: Commit**

```bash
git add agents/coding.py tests/test_agents.py
git commit -m "feat(agents/coding): pass model kwarg through to build_claude_command"
```

---

## Task 3: Thread `model` through `TestingAgent.build_command`

**Files:**
- Modify: `agents/testing.py:33-52`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_agents.py`:

```python
def test_testing_agent_passes_model_to_build_claude_command():
    cmd = TestingAgent().build_command(
        issue_title="t",
        issue_body="b",
        issue_number=1,
        repo="o/r",
        pr_branch="ai/issue-1",
        model="claude-haiku-4-5",
    )
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-4-5"


def test_testing_agent_omits_model_when_not_provided():
    cmd = TestingAgent().build_command(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        pr_branch="ai/issue-1",
    )
    assert "--model" not in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents.py -k testing_agent_passes_model -v`
Expected: FAIL — unexpected kwarg `model`.

- [ ] **Step 3: Implement**

In `agents/testing.py`, change `build_command` signature and body:

```python
def build_command(
    self,
    issue_title: str,
    issue_body: str,
    issue_number: int,
    repo: str,
    pr_branch: str,
    max_budget_usd: float = 0.50,
    project_addendum: str = "",
    model: str | None = None,
) -> list[str]:
    prompt = self.build_prompt(
        issue_title, issue_body, issue_number, repo, pr_branch,
        project_addendum=project_addendum,
    )
    return build_claude_command(
        prompt=prompt,
        allowed_tools=ALLOWED_TOOLS,
        disallowed_tools=DISALLOWED_TOOLS,
        max_budget_usd=max_budget_usd,
        model=model,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_agents.py -k testing_agent -v`
Expected: all testing tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/testing.py tests/test_agents.py
git commit -m "feat(agents/testing): pass model kwarg through to build_claude_command"
```

---

## Task 4: Thread `model` through `ReviewAgent.build_command`

**Files:**
- Modify: `agents/review.py:41-60`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_agents.py`:

```python
def test_review_agent_passes_model_to_build_claude_command():
    cmd = ReviewAgent().build_command(
        issue_title="t",
        issue_body="b",
        issue_number=1,
        repo="o/r",
        pr_number=1,
        model="claude-opus-4-7",
    )
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "claude-opus-4-7"


def test_review_agent_omits_model_when_not_provided():
    cmd = ReviewAgent().build_command(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        pr_number=1,
    )
    assert "--model" not in cmd
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agents.py -k review_agent_passes_model -v`
Expected: FAIL — unexpected kwarg `model`.

- [ ] **Step 3: Implement**

In `agents/review.py`, change `build_command` signature and body:

```python
def build_command(
    self,
    issue_title: str,
    issue_body: str,
    issue_number: int,
    repo: str,
    pr_number: int,
    max_budget_usd: float = 0.50,
    project_addendum: str = "",
    model: str | None = None,
) -> list[str]:
    prompt = self.build_prompt(
        issue_title, issue_body, issue_number, repo, pr_number,
        project_addendum=project_addendum,
    )
    return build_claude_command(
        prompt=prompt,
        allowed_tools=ALLOWED_TOOLS,
        disallowed_tools=DISALLOWED_TOOLS,
        max_budget_usd=max_budget_usd,
        model=model,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_agents.py -k review_agent -v`
Expected: all review tests pass.

- [ ] **Step 5: Commit**

```bash
git add agents/review.py tests/test_agents.py
git commit -m "feat(agents/review): pass model kwarg through to build_claude_command"
```

---

## Task 5: Add `models:` block to `defaults.yaml`

**Files:**
- Modify: `defaults.yaml`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_config.py`:

```python
def test_models_defaults_loaded(tmp_path):
    """defaults.yaml exposes per-role pinned model IDs."""
    import shutil
    defaults_dir = tmp_path / "playbook"
    defaults_dir.mkdir()
    real_defaults = os.path.join(os.path.dirname(os.path.dirname(__file__)), "defaults.yaml")
    shutil.copy(real_defaults, defaults_dir / "defaults.yaml")

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("repo: owner/my-project\n")

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults_dir / "defaults.yaml"))
    assert cfg["models"]["coding"] == "claude-sonnet-4-6"
    assert cfg["models"]["testing"] == "claude-haiku-4-5"
    assert cfg["models"]["review"] == "claude-opus-4-7"


def test_models_project_overrides_defaults(tmp_path):
    """Project playbook.yaml can override a subset of model IDs."""
    defaults_dir = tmp_path / "playbook"
    defaults_dir.mkdir()
    (defaults_dir / "defaults.yaml").write_text("""
models:
  coding: claude-sonnet-4-6
  testing: claude-haiku-4-5
  review: claude-opus-4-7
""")

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/my-project
models:
  coding: claude-opus-4-7
""")

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults_dir / "defaults.yaml"))
    assert cfg["models"]["coding"] == "claude-opus-4-7"   # overridden
    assert cfg["models"]["testing"] == "claude-haiku-4-5"  # inherited
    assert cfg["models"]["review"] == "claude-opus-4-7"    # inherited
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -k models -v`
Expected: 2 failures — `KeyError: 'models'`.

- [ ] **Step 3: Implement**

In `defaults.yaml`, add a `models:` block at the top level (after the existing `versioning:` block, before `statuses:`):

```yaml
# Per-role model selection. Pinned full model IDs (not aliases) so benchmark
# baselines stay stable when Anthropic releases new minors. Override any
# subset in a project's playbook.yaml.
models:
  coding: claude-sonnet-4-6
  testing: claude-haiku-4-5
  review: claude-opus-4-7
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_config.py -k models -v`
Expected: 2 passes.

- [ ] **Step 5: Commit**

```bash
git add defaults.yaml tests/test_config.py
git commit -m "feat(config): add models block to defaults.yaml (sonnet/haiku/opus per role)"
```

---

## Task 6: Orchestrator passes per-role model from config

**Files:**
- Modify: `orchestrator.py` — three dispatch methods (`_dispatch_coding`, `_dispatch_testing`, `_dispatch_review`)
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_orchestrator.py`:

```python
@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_coding_uses_models_config(MockGH, MockPopen, config, state_dir):
    """Coding dispatch passes models.coding from config to build_command."""
    config["models"] = {
        "coding": "claude-sonnet-4-6",
        "testing": "claude-haiku-4-5",
        "review": "claude-opus-4-7",
    }
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

    MockPopen.assert_called_once()
    argv = MockPopen.call_args[0][0]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_testing_uses_models_config(MockGH, MockPopen, config, state_dir):
    """Testing dispatch passes models.testing from config."""
    config["models"] = {
        "coding": "claude-sonnet-4-6",
        "testing": "claude-haiku-4-5",
        "review": "claude-opus-4-7",
    }
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "[v0.1] Fix bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-testing" else []

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

    MockPopen.assert_called_once()
    argv = MockPopen.call_args[0][0]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5"


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_review_uses_models_config(MockGH, MockPopen, config, state_dir):
    """Review dispatch passes models.review from config."""
    config["models"] = {
        "coding": "claude-sonnet-4-6",
        "testing": "claude-haiku-4-5",
        "review": "claude-opus-4-7",
    }
    mock_gh = MockGH.return_value
    mock_issue = _mock_issue(42, "[v0.1] Fix bug", "Body")
    mock_gh.fetch_issues_by_status.side_effect = lambda s: [mock_issue] if s == "ai-review" else []

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

    MockPopen.assert_called_once()
    argv = MockPopen.call_args[0][0]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == "claude-opus-4-7"


@patch("orchestrator.subprocess.Popen")
@patch("orchestrator.GitHubClient")
def test_dispatch_omits_model_when_block_missing(MockGH, MockPopen, config, state_dir):
    """Missing 'models' block in config → no --model flag, no exception."""
    # NOTE: config fixture deliberately omits 'models'
    assert "models" not in config
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

    MockPopen.assert_called_once()
    argv = MockPopen.call_args[0][0]
    assert "--model" not in argv
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_orchestrator.py -k "uses_models_config or omits_model" -v`
Expected: 4 failures — the dispatches don't yet read from `config["models"]`, so `--model` is not in argv.

- [ ] **Step 3: Implement**

In `orchestrator.py`, modify the three dispatch methods.

For `_dispatch_coding` (around line 665), update the `build_command` call to include `model`:

```python
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
    project_addendum=_load_project_addendum("coding"),
    model=self.config.get("models", {}).get("coding"),
)
```

For `_dispatch_testing` (around line 699), update:

```python
cmd = self.testing_agent.build_command(
    issue_title=issue["title"],
    issue_body=issue["body"] or "",
    issue_number=issue["number"],
    repo=issue["repo"],
    pr_branch=pr_branch,
    project_addendum=_load_project_addendum("testing"),
    model=self.config.get("models", {}).get("testing"),
)
```

For `_dispatch_review` (around line 727), update:

```python
cmd = self.review_agent.build_command(
    issue_title=issue["title"],
    issue_body=issue["body"] or "",
    issue_number=issue["number"],
    repo=issue["repo"],
    pr_number=pr_number,
    project_addendum=_load_project_addendum("review"),
    model=self.config.get("models", {}).get("review"),
)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_orchestrator.py -k "uses_models_config or omits_model" -v`
Expected: 4 passes.

- [ ] **Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: all pre-existing tests still pass; total count = existing + 14 new tests from this plan.

- [ ] **Step 6: Commit**

```bash
git add orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): dispatch per-role model from config.models"
```

---

## Final verification

- [ ] **Step 1: Confirm full suite green**

Run: `pytest tests/ -v 2>&1 | tail -20`
Expected: `passed` count on the final line, no `failed`, no `error`.

- [ ] **Step 2: Lint passes**

Run: `ruff check .`
Expected: no errors (or only pre-existing warnings unrelated to this change).

- [ ] **Step 3: Smoke test — config inspection**

From the playbook repo root:

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from config import load_config
import os, tempfile
with tempfile.TemporaryDirectory() as td:
    with open(os.path.join(td, 'playbook.yaml'), 'w') as f:
        f.write('repo: owner/test\n')
    cfg = load_config(project_dir=td, defaults_path='./defaults.yaml')
    print('coding  ->', cfg['models']['coding'])
    print('testing ->', cfg['models']['testing'])
    print('review  ->', cfg['models']['review'])
"
```

Expected output:
```
coding  -> claude-sonnet-4-6
testing -> claude-haiku-4-5
review  -> claude-opus-4-7
```

- [ ] **Step 4: Open PR**

```bash
git push -u origin <current-branch>
gh pr create --title "feat: per-role model tiering (sonnet coding / haiku testing / opus review)" \
  --body "Implements docs/specs/2026-05-14-model-tiering-and-bench-design.md PR 1.

Adds a \`models:\` block to defaults.yaml with pinned full model IDs, threads
an optional \`model\` kwarg through \`build_claude_command\` and each
\`<Role>Agent.build_command\`, and has the orchestrator pass
\`config[\"models\"][\"<role>\"]\` to each dispatch. Backward compatible: a
config missing the \`models\` block emits no \`--model\` flag.

Test coverage: 14 new tests covering the flag emission, per-agent
pass-through, per-role dispatch, defaults.yaml load, project override,
and the missing-block fallback."
```
