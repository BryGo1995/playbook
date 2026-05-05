# agents/coding.py
import os
from agents.base import build_claude_command, BASE_BASH_DENY

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "coding.md")
with open(_PROMPT_PATH) as _f:
    CODING_PROMPT = _f.read()

ALLOWED_TOOLS = ["Edit", "Write", "Bash", "Read", "Glob", "Grep"]
DISALLOWED_TOOLS = list(BASE_BASH_DENY)


class CodingAgent:
    def build_prompt(
        self,
        issue_title: str,
        issue_body: str,
        issue_number: int,
        repo: str,
        integration_branch: str = "ai/dev",
        attempt: int = 1,
        prior_attempt_context: str = "",
        project_addendum: str = "",
    ) -> str:
        # Newline-pad the context block so it sits cleanly between body and instructions
        ctx = f"\n{prior_attempt_context}" if prior_attempt_context else ""
        addn = f"\n{project_addendum}" if project_addendum else ""
        return CODING_PROMPT.format(
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_body=issue_body,
            integration_branch=integration_branch,
            attempt=attempt,
            prior_attempt_context=ctx,
            project_addendum=addn,
        )

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
        )
