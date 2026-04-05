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
