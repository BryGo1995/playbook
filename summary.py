# summary.py
"""
Generates a summary of agent activity and posts it to Slack.
Run via cron at 8am and 8pm, or manually.

Usage:
    python3 summary.py                  # summarize since last run
    python3 summary.py --since 2h       # summarize last 2 hours
    python3 summary.py --since 12h      # summarize last 12 hours
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone, timedelta

from config import load_config
from github_client import GitHubClient
from notifications.slack import SlackNotifier
from logger import setup_logger

logger = setup_logger("summary")

STATE_FILE = os.path.expanduser("~/.agent-orchestrator/summary_state.json")


def load_last_run() -> datetime:
    """Load the timestamp of the last summary run."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            data = json.load(f)
        return datetime.fromisoformat(data["last_run"])
    # Default to 12 hours ago if no prior run
    return datetime.now(timezone.utc) - timedelta(hours=12)


def save_last_run(timestamp: datetime):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"last_run": timestamp.isoformat()}, f)


def parse_since(since_str: str) -> timedelta:
    """Parse a duration string like '2h', '12h', '30m' into a timedelta."""
    match = re.match(r"^(\d+)([hm])$", since_str)
    if not match:
        raise ValueError(f"Invalid duration format: {since_str}. Use e.g. '2h' or '30m'.")
    value, unit = int(match.group(1)), match.group(2)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(minutes=value)


def categorize_issues(issues_by_status: dict[str, list[dict]], statuses: dict) -> dict:
    """Categorize issues from status queries into summary categories."""
    return {
        "complete": issues_by_status.get(statuses["complete"], []),
        "done": issues_by_status.get(statuses["done"], []),
        "in_progress": issues_by_status.get(statuses["in_progress"], []),
        "testing": issues_by_status.get(statuses["testing"], []),
        "review": issues_by_status.get(statuses["review"], []),
        "blocked": issues_by_status.get(statuses["blocked"], []),
        "error": issues_by_status.get(statuses["error"], []),
    }


def group_by_theme(issues: list[dict]) -> list[str]:
    """Group issues into short theme descriptions by common title prefixes."""
    if len(issues) <= 3:
        return [f"#{i['number']} {i['title']}" for i in issues]

    groups = {}
    for issue in issues:
        words = issue["title"].strip().split()
        key = words[0] if words else "Other"
        if key not in groups:
            groups[key] = []
        groups[key].append(issue)

    lines = []
    for theme, group_issues in groups.items():
        if len(group_issues) == 1:
            lines.append(f"#{group_issues[0]['number']} {group_issues[0]['title']}")
        else:
            numbers = ", ".join(f"#{i['number']}" for i in group_issues)
            lines.append(f"{theme}: {numbers}")
    return lines


def format_summary(repo: str, categories: dict, since: datetime, now: datetime, integration_branch: str) -> str:
    """Format the summary as a compact Slack message."""
    since_str = since.strftime("%b %d %I:%M%p").replace(" 0", " ")
    now_str = now.strftime("%b %d %I:%M%p").replace(" 0", " ")

    merged = categories["complete"] + categories["done"]
    in_progress = categories["in_progress"]
    testing = categories["testing"]
    review = categories["review"]
    blocked = categories["blocked"]
    errors = categories["error"]

    total_active = len(in_progress) + len(testing) + len(review)

    lines = []
    lines.append(f":clipboard: *Summary: {repo}* ({since_str} → {now_str})")
    lines.append("━" * 35)

    counts = []
    if merged:
        counts.append(f":white_check_mark: {len(merged)} merged")
    if total_active:
        counts.append(f":arrows_counterclockwise: {total_active} in progress")
    if blocked:
        counts.append(f":no_entry_sign: {len(blocked)} blocked")
    if errors:
        counts.append(f":x: {len(errors)} errors")

    if counts:
        lines.append("  |  ".join(counts))
    else:
        lines.append("No agent activity in this period.")
        return "\n".join(lines)

    lines.append("")

    if merged:
        lines.append("*Merged:*")
        for item in group_by_theme(merged):
            lines.append(f"  • {item}")

    active_issues = in_progress + testing + review
    if active_issues:
        lines.append("*Active:*")
        for issue in in_progress:
            lines.append(f"  • #{issue['number']} {issue['title']} — coding")
        for issue in testing:
            lines.append(f"  • #{issue['number']} {issue['title']} — testing")
        for issue in review:
            lines.append(f"  • #{issue['number']} {issue['title']} — in review")

    if blocked:
        lines.append("*Blocked:*")
        for issue in blocked:
            lines.append(f"  • #{issue['number']} {issue['title']}")

    if errors:
        lines.append("*Errors:*")
        for issue in errors:
            lines.append(f"  • #{issue['number']} {issue['title']}")

    lines.append("")
    lines.append(f"<https://github.com/{repo}/compare/main...{integration_branch}|View {integration_branch} → main diff>")

    return "\n".join(lines)


def generate_summary(config: dict, since: datetime | None = None):
    """Generate and post summaries for all configured repos."""
    now = datetime.now(timezone.utc)
    if since is None:
        since = load_last_run()

    gh = GitHubClient()
    gh.load_project_metadata(
        owner=config["project"]["owner"],
        project_number=config["project"]["number"],
        status_field_id=config["project"]["status_field_id"],
    )
    slack = SlackNotifier(config["slack"].get("webhook_url"))
    statuses = config["statuses"]
    integration_branch = config.get("branches", {}).get("integration", "ai/dev")

    active_statuses = [
        statuses["complete"], statuses["done"],
        statuses["in_progress"], statuses["testing"], statuses["review"],
        statuses["blocked"], statuses["error"],
    ]
    issues_by_status = {}
    for status_name in active_statuses:
        issues = gh.fetch_issues_by_status(status_name)
        if issues:
            issues_by_status[status_name] = issues

    if not issues_by_status:
        logger.info("No agent-tracked issues found")
        save_last_run(now)
        return

    categories = categorize_issues(issues_by_status, statuses)
    repo = config["repos"][0]
    message = format_summary(repo, categories, since, now, integration_branch)
    slack.send(message)
    logger.info(f"Summary posted for {repo}")

    save_last_run(now)


def main():
    parser = argparse.ArgumentParser(description="Generate agent activity summary")
    parser.add_argument("--since", type=str, help="Duration to look back (e.g. '12h', '2h', '30m')")
    args = parser.parse_args()

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    config = load_config(config_path)

    since = None
    if args.since:
        delta = parse_since(args.since)
        since = datetime.now(timezone.utc) - delta

    generate_summary(config, since=since)


if __name__ == "__main__":
    main()
