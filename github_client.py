import os
from github import Github


ORCHESTRATOR_TAG = "[agent-orchestrator]"


class GitHubClient:
    """Wraps PyGithub for issue label management and comments."""

    def __init__(self, token: str | None = None):
        self.gh = Github(token or os.environ["GITHUB_TOKEN"])

    def fetch_issues_by_label(self, repo_name: str, label: str) -> list:
        repo = self.gh.get_repo(repo_name)
        return list(repo.get_issues(labels=[label], state="open"))

    def swap_label(self, repo_name: str, issue_number: int, old_label: str, new_label: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.remove_from_labels(old_label)
        issue.add_to_labels(new_label)

    def add_label(self, repo_name: str, issue_number: int, label: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.add_to_labels(label)

    def remove_label(self, repo_name: str, issue_number: int, label: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.remove_from_labels(label)

    def add_comment(self, repo_name: str, issue_number: int, body: str):
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        issue.create_comment(body)

    def merge_pr(self, repo_name: str, pr_number: int, merge_method: str = "squash") -> bool:
        """Merge a pull request. Returns True on success, False on failure."""
        repo = self.gh.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        if not pr.mergeable:
            return False
        pr.merge(merge_method=merge_method)
        return True

    def find_pr_for_branch(self, repo_name: str, branch: str) -> int | None:
        """Find the PR number for a given branch. Returns None if not found."""
        repo = self.gh.get_repo(repo_name)
        pulls = repo.get_pulls(state="open", head=f"{repo_name.split('/')[0]}:{branch}")
        for pr in pulls:
            return pr.number
        return None

    def get_attempt_count(self, repo_name: str, issue_number: int) -> int:
        repo = self.gh.get_repo(repo_name)
        issue = repo.get_issue(issue_number)
        comments = issue.get_comments()
        return sum(
            1
            for c in comments
            if c.body.startswith(ORCHESTRATOR_TAG) and "Attempt" in c.body and "completed" in c.body
        )
