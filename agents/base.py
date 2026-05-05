# agents/base.py


# Bash patterns denied for every agent. Best-effort defense-in-depth on top of
# the prompt-level untrusted-input framing — pattern matching is fragile (extra
# whitespace, `bash -c "..."` wrappers, and flag aliasing can bypass), so do
# not rely on this list as a sole control.
BASE_BASH_DENY: list[str] = [
    # No force-pushing — agent must work via PRs to the integration branch
    "Bash(git push --force*)",
    "Bash(git push * --force*)",
    "Bash(git push -f)",
    "Bash(git push -f *)",
    "Bash(git push * -f)",
    "Bash(git push * -f *)",
    # No pushing directly to main or master, in any of the common shapes
    "Bash(git push * main)",
    "Bash(git push * main:*)",
    "Bash(git push * *:main)",
    "Bash(git push * master)",
    "Bash(git push * master:*)",
    "Bash(git push * *:master)",
    # No deleting remote branches via push
    "Bash(git push * --delete*)",
    "Bash(git push --delete*)",
    # The orchestrator merges PRs; the agent never should
    "Bash(gh pr merge*)",
    # No destructive gh commands
    "Bash(gh repo delete*)",
    "Bash(gh release delete*)",
    # Block raw GitHub API destructive calls
    "Bash(gh api * -X DELETE*)",
    "Bash(gh api * --method DELETE*)",
]


def build_claude_command(
    prompt: str,
    allowed_tools: list[str],
    output_format: str = "stream-json",
    max_budget_usd: float | None = None,
    disallowed_tools: list[str] | None = None,
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
    cmd.append(prompt)
    return cmd
