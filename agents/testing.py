# agents/testing.py
import os
from agents.base import build_claude_command, BASE_BASH_DENY

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "testing.md")
with open(_PROMPT_PATH) as _f:
    TESTING_PROMPT = _f.read()

ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Bash", "Write"]
DISALLOWED_TOOLS = list(BASE_BASH_DENY)


class TestingAgent:
    def build_prompt(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        pr_branch: str,
        project_addendum: str = "",
    ) -> str:
        addn = f"\n{project_addendum}" if project_addendum else ""
        return TESTING_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
            pr_branch=pr_branch,
            project_addendum=addn,
        )

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
