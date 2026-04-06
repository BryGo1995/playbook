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


def categorize_issues(issues: list, labels: dict) -> dict:
    """Categorize issues by their current label state."""
    categories = {
        "merged": [],
        "pr_ready": [],
        "review_needed": [],
        "testing": [],
        "in_progress": [],
        "blocked": [],
        "error": [],
    }
    label_to_category = {
        labels["merged"]: "merged",
        labels["pr_ready"]: "pr_ready",
        labels["review_needed"]: "review_needed",
        labels["testing"]: "testing",
        labels["in_progress"]: "in_progress",
        labels["blocked"]: "blocked",
        labels["error"]: "error",
    }
    for issue in issues:
        issue_labels = {lbl.name for lbl in issue.labels}
        for label_name, category in label_to_category.items():
            if label_name in issue_labels:
                categories[category].append(issue)
                break
    return categories


def group_by_theme(issues: list) -> list[str]:
    """Group issues into short theme descriptions by common title prefixes/keywords."""
    if len(issues) <= 3:
        return [f"#{i.number} {i.title}" for i in issues]

    # Group by first word in title (e.g., "Fix", "Add", "Update")
    groups = {}
    for issue in issues:
        words = issue.title.strip().split()
        key = words[0] if words else "Other"
        if key not in groups:
            groups[key] = []
        groups[key].append(issue)

    lines = []
    for theme, group_issues in groups.items():
        if len(group_issues) == 1:
            lines.append(f"#{group_issues[0].number} {group_issues[0].title}")
        else:
            numbers = ", ".join(f"#{i.number}" for i in group_issues)
            lines.append(f"{theme}: {numbers}")
    return lines


def format_summary(repo: str, categories: dict, since: datetime, now: datetime, integration_branch: str) -> str:
    """Format the summary as a compact Slack message."""
    since_str = since.strftime("%b %d %I:%M%p").replace(" 0", " ")
    now_str = now.strftime("%b %d %I:%M%p").replace(" 0", " ")

    merged = categories["merged"]
    in_progress = categories["in_progress"]
    testing = categories["testing"]
    review = categories["review_needed"]
    pr_ready = categories["pr_ready"]
    blocked = categories["blocked"]
    errors = categories["error"]

    total_active = len(in_progress) + len(testing) + len(review) + len(pr_ready)

    lines = []
    lines.append(f":clipboard: *Summary: {repo}* ({since_str} → {now_str})")
    lines.append("━" * 35)

    # Status counts line
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

    # Merged details
    if merged:
        lines.append("*Merged:*")
        for item in group_by_theme(merged):
            lines.append(f"  • {item}")

    # In progress breakdown
    active_issues = in_progress + testing + review + pr_ready
    if active_issues:
        lines.append("*Active:*")
        for issue in in_progress:
            lines.append(f"  • #{issue.number} {issue.title} — coding")
        for issue in testing:
            lines.append(f"  • #{issue.number} {issue.title} — testing")
        for issue in review:
            lines.append(f"  • #{issue.number} {issue.title} — in review")
        for issue in pr_ready:
            lines.append(f"  • #{issue.number} {issue.title} — PR ready")

    # Blocked
    if blocked:
        lines.append("*Blocked:*")
        for issue in blocked:
            lines.append(f"  • #{issue.number} {issue.title}")

    # Errors
    if errors:
        lines.append("*Errors:*")
        for issue in errors:
            lines.append(f"  • #{issue.number} {issue.title}")

    lines.append("")
    lines.append(f"<https://github.com/{repo}/compare/main...{integration_branch}|View {integration_branch} → main diff>")

    return "\n".join(lines)


def generate_summary(config: dict, since: datetime | None = None):
    """Generate and post summaries for all configured repos."""
    now = datetime.now(timezone.utc)
    if since is None:
        since = load_last_run()

    gh = GitHubClient()
    slack = SlackNotifier(config["slack"].get("webhook_url"))
    labels = config["labels"]
    integration_branch = config.get("branches", {}).get("integration", "ai/dev")

    all_ai_labels = list(labels.values())

    for repo in config["repos"]:
        logger.info(f"Generating summary for {repo} since {since.isoformat()}")

        # Fetch all issues that have any ai-* label (both open and closed for merged)
        all_issues = []
        seen = set()
        for label in all_ai_labels:
            for issue in gh.fetch_issues_by_label(repo, label):
                if issue.number not in seen:
                    seen.add(issue.number)
                    all_issues.append(issue)

        if not all_issues:
            logger.info(f"No agent-tracked issues for {repo}")
            continue

        categories = categorize_issues(all_issues, labels)
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
