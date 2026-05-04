# agents/review.py
import os
from agents.base import build_claude_command

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "review.md")
with open(_PROMPT_PATH) as _f:
    REVIEW_PROMPT = _f.read()

ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Bash"]


class ReviewAgent:
    def build_prompt(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        pr_number: int,
        project_addendum: str = "",
    ) -> str:
        addn = f"\n{project_addendum}" if project_addendum else ""
        return REVIEW_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
            pr_number=pr_number,
            project_addendum=addn,
        )

    def build_command(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        pr_number: int,
        max_budget_usd: float = 0.50,
        project_addendum: str = "",
    ) -> list[str]:
        prompt = self.build_prompt(
            issue_title, issue_body, issue_number, repo, pr_number,
            project_addendum=project_addendum,
        )
        return build_claude_command(
            prompt=prompt,
            allowed_tools=ALLOWED_TOOLS,
            max_budget_usd=max_budget_usd,
        )
