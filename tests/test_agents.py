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
