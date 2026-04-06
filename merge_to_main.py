# merge_to_main.py
"""
Creates a PR from ai/dev → main with all completed issues listed as "Closes #N".
When merged, GitHub auto-closes those issues.

Usage:
    python3 merge_to_main.py              # create PR
    python3 merge_to_main.py --dry-run    # show what would be created without creating it
"""
import argparse
import os
import sys

from config import load_config
from github_client import GitHubClient
from logger import setup_logger

logger = setup_logger("merge_to_main")


def get_completed_issues(gh: GitHubClient, statuses: dict) -> list[dict]:
    """Get all open issues in ai-complete or Done status."""
    completed = gh.fetch_issues_by_status(statuses["complete"])
    done = gh.fetch_issues_by_status(statuses["done"])
    return completed + done


def build_pr_body(issues: list[dict], integration_branch: str) -> str:
    """Build PR body with Closes references and summary."""
    lines = []
    lines.append(f"## Merge `{integration_branch}` → `main`")
    lines.append("")

    if issues:
        lines.append(f"### Completed Issues ({len(issues)})")
        lines.append("")
        for issue in sorted(issues, key=lambda i: i["number"]):
            lines.append(f"- Closes #{issue['number']} — {issue['title']}")
        lines.append("")
    else:
        lines.append("No completed issues found in the project.")
        lines.append("")

    lines.append("---")
    lines.append("*Created by [Playbook](https://github.com/BryGo1995/playbook)*")

    return "\n".join(lines)


def create_merge_pr(config: dict, dry_run: bool = False):
    """Create the ai/dev → main PR."""
    gh = GitHubClient()
    gh.load_project_metadata(
        owner=config["project"]["owner"],
        project_number=config["project"]["number"],
        status_field_id=config["project"]["status_field_id"],
    )

    integration_branch = config.get("branches", {}).get("integration", "ai/dev")
    repo = config["repos"][0]
    statuses = config["statuses"]

    # Get completed issues
    issues = get_completed_issues(gh, statuses)
    logger.info(f"Found {len(issues)} completed issues")

    # Build PR
    title = f"Merge {integration_branch} → main ({len(issues)} issues)"
    body = build_pr_body(issues, integration_branch)

    if dry_run:
        print(f"\n=== DRY RUN ===\n")
        print(f"Repo: {repo}")
        print(f"Branch: {integration_branch} → main")
        print(f"Title: {title}")
        print(f"\nBody:\n{body}")
        return

    # Create PR via REST API
    owner, repo_name = repo.split("/")
    pr_data = gh._rest_post(f"/repos/{owner}/{repo_name}/pulls", {
        "title": title,
        "body": body,
        "head": integration_branch,
        "base": "main",
    })

    pr_url = pr_data.get("html_url", pr_data.get("url"))
    pr_number = pr_data.get("number")
    print(f"PR #{pr_number} created: {pr_url}")
    logger.info(f"Created PR #{pr_number} for {repo}: {integration_branch} → main")


def main():
    parser = argparse.ArgumentParser(description="Create ai/dev → main merge PR")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be created without creating it")
    args = parser.parse_args()

    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    config = load_config(config_path)

    create_merge_pr(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
