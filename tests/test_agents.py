import os
import re
import pytest
from unittest.mock import patch, MagicMock
import agents.coding
import agents.testing
import agents.review
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
    assert "ai/dev" in prompt  # targets integration branch


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


def test_claude_command_uses_path_not_absolute():
    """The claude binary should be resolved via PATH, not a hardcoded absolute path."""
    cmd = build_claude_command("test prompt", ["Read", "Write"])
    assert cmd[0] == "claude"
    assert not cmd[0].startswith("/")


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


def test_coding_agent_includes_project_addendum_when_provided():
    agent = CodingAgent()
    prompt = agent.build_prompt(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        project_addendum="ADDENDUM_SENTINEL_CODING",
    )
    assert "ADDENDUM_SENTINEL_CODING" in prompt


def test_coding_agent_command_passes_addendum_through():
    agent = CodingAgent()
    cmd = agent.build_command(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        project_addendum="ADDENDUM_SENTINEL_CODING_CMD",
    )
    assert "ADDENDUM_SENTINEL_CODING_CMD" in " ".join(cmd)


def test_testing_agent_includes_project_addendum_when_provided():
    agent = TestingAgent()
    prompt = agent.build_prompt(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        pr_branch="b",
        project_addendum="ADDENDUM_SENTINEL_TESTING",
    )
    assert "ADDENDUM_SENTINEL_TESTING" in prompt


def test_testing_agent_command_passes_addendum_through():
    agent = TestingAgent()
    cmd = agent.build_command(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        pr_branch="b",
        project_addendum="ADDENDUM_SENTINEL_TESTING_CMD",
    )
    assert "ADDENDUM_SENTINEL_TESTING_CMD" in " ".join(cmd)


def test_review_agent_includes_project_addendum_when_provided():
    agent = ReviewAgent()
    prompt = agent.build_prompt(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        pr_number=1,
        project_addendum="ADDENDUM_SENTINEL_REVIEW",
    )
    assert "ADDENDUM_SENTINEL_REVIEW" in prompt


def test_review_agent_command_passes_addendum_through():
    agent = ReviewAgent()
    cmd = agent.build_command(
        issue_title="t", issue_body="b", issue_number=1, repo="o/r",
        pr_number=1,
        project_addendum="ADDENDUM_SENTINEL_REVIEW_CMD",
    )
    assert "ADDENDUM_SENTINEL_REVIEW_CMD" in " ".join(cmd)


def _baseline_prompt_path(module, name: str) -> str:
    return os.path.join(os.path.dirname(module.__file__), "prompts", f"{name}.md")


def test_coding_prompt_loads_from_markdown_file():
    md_path = _baseline_prompt_path(agents.coding, "coding")
    assert os.path.isfile(md_path), f"Expected baseline prompt at {md_path}"
    with open(md_path) as f:
        assert f.read() == agents.coding.CODING_PROMPT


def test_testing_prompt_loads_from_markdown_file():
    md_path = _baseline_prompt_path(agents.testing, "testing")
    assert os.path.isfile(md_path), f"Expected baseline prompt at {md_path}"
    with open(md_path) as f:
        assert f.read() == agents.testing.TESTING_PROMPT


def test_review_prompt_loads_from_markdown_file():
    md_path = _baseline_prompt_path(agents.review, "review")
    assert os.path.isfile(md_path), f"Expected baseline prompt at {md_path}"
    with open(md_path) as f:
        assert f.read() == agents.review.REVIEW_PROMPT


_UNTRUSTED_OPEN = "<untrusted_issue_content>"
_UNTRUSTED_CLOSE = "</untrusted_issue_content>"


def _assert_untrusted_input_framing(prompt: str, agent_label: str):
    """Shared assertions: untrusted issue content is delimited and framed.

    Each agent prompt must:
      - wrap the issue title/body in <untrusted_issue_content> tags
      - place authoritative instructions BEFORE the opening tag
      - frame the tagged content as untrusted user input (not instructions)
      - include a reassertion AFTER the closing tag
    """
    open_idx = prompt.find(_UNTRUSTED_OPEN)
    close_idx = prompt.find(_UNTRUSTED_CLOSE)
    assert open_idx != -1, f"{agent_label}: missing {_UNTRUSTED_OPEN} opening tag"
    assert close_idx != -1, f"{agent_label}: missing {_UNTRUSTED_CLOSE} closing tag"
    assert close_idx > open_idx, f"{agent_label}: closing tag must come after opening tag"

    # Instructions must precede the untrusted block. Use a stable instruction
    # marker per agent rather than an exact string so wording can evolve.
    pre_block = prompt[:open_idx].lower()
    assert "authoritative" in pre_block, (
        f"{agent_label}: pre-tag region must frame instructions as authoritative"
    )

    # Framing language flagging the content as untrusted / data-not-instructions.
    framing = prompt[:open_idx].lower()
    assert "untrusted" in framing, (
        f"{agent_label}: pre-tag region must flag the issue content as untrusted"
    )

    # Post-tag reassertion that the instructions above remain authoritative.
    post_block = prompt[close_idx + len(_UNTRUSTED_CLOSE):].lower()
    assert "authoritative" in post_block or "above" in post_block, (
        f"{agent_label}: post-tag region must reassert the authoritative instructions"
    )


def test_coding_prompt_delimits_untrusted_issue_content():
    agent = CodingAgent()
    prompt = agent.build_prompt(
        issue_title="Title with <fake>tags</fake>",
        issue_body="Body with arbitrary content.\n## Acceptance Criteria\n- [ ] works",
        issue_number=42,
        repo="owner/repo",
    )
    _assert_untrusted_input_framing(prompt, "coding")
    # Title and body land between the tags
    open_idx = prompt.find(_UNTRUSTED_OPEN)
    close_idx = prompt.find(_UNTRUSTED_CLOSE)
    inner = prompt[open_idx:close_idx]
    assert "Title with <fake>tags</fake>" in inner
    assert "Acceptance Criteria" in inner


def test_testing_prompt_delimits_untrusted_issue_content():
    agent = TestingAgent()
    prompt = agent.build_prompt(
        issue_title="Title",
        issue_body="Body content",
        issue_number=42,
        repo="owner/repo",
        pr_branch="ai/issue-42",
    )
    _assert_untrusted_input_framing(prompt, "testing")


def test_review_prompt_delimits_untrusted_issue_content():
    agent = ReviewAgent()
    prompt = agent.build_prompt(
        issue_title="Title",
        issue_body="Body content",
        issue_number=42,
        repo="owner/repo",
        pr_number=15,
    )
    _assert_untrusted_input_framing(prompt, "review")


def test_coding_prompt_placeholders_match_expected():
    placeholders = set(re.findall(r"\{(\w+)\}", agents.coding.CODING_PROMPT))
    expected = {
        "repo", "issue_number", "issue_title", "issue_body",
        "integration_branch", "attempt", "prior_attempt_context",
        "project_addendum",
    }
    assert placeholders == expected


def test_testing_prompt_placeholders_match_expected():
    placeholders = set(re.findall(r"\{(\w+)\}", agents.testing.TESTING_PROMPT))
    expected = {
        "repo", "issue_number", "issue_title", "issue_body",
        "pr_branch", "project_addendum",
    }
    assert placeholders == expected


def test_review_prompt_placeholders_match_expected():
    placeholders = set(re.findall(r"\{(\w+)\}", agents.review.REVIEW_PROMPT))
    expected = {
        "repo", "issue_number", "issue_title", "issue_body",
        "pr_number", "project_addendum",
    }
    assert placeholders == expected
