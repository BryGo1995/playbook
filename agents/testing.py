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
