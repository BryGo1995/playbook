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
