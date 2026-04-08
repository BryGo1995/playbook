# agents/base.py


def build_claude_command(
    prompt: str,
    allowed_tools: list[str],
    output_format: str = "stream-json",
    max_budget_usd: float | None = None,
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
    if max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(max_budget_usd)])
    cmd.append(prompt)
    return cmd
