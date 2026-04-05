# orchestrator.py
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone

from config import load_config
from state import StateManager
from github_client import GitHubClient
from agents.coding import CodingAgent
from agents.testing import TestingAgent
from agents.review import ReviewAgent
from notifications.slack import SlackNotifier
from logger import setup_logger

logger = setup_logger()


class Orchestrator:
    def __init__(self, config: dict, state_dir: str | None = None):
        self.config = config
        self.labels = config["labels"]
        self.gh = GitHubClient()
        self.state = StateManager(state_dir or os.path.expanduser("~/.agent-orchestrator"))
        self.slack = SlackNotifier(config["slack"].get("webhook_url"))
        self.coding_agent = CodingAgent()
        self.testing_agent = TestingAgent()
        self.review_agent = ReviewAgent()

    def run(self):
        """Single orchestration cycle: check agents, dispatch new work."""
        self._check_running_agents()
        for repo in self.config["repos"]:
            self._process_ready_issues(repo)
            self._process_testing_issues(repo)
            self._process_review_issues(repo)

    def _check_running_agents(self):
        """Check PIDs, handle timeouts and completions."""
        for agent in list(self.state.agents):
            pid = agent["pid"]
            if self._is_process_alive(pid):
                if self._is_timed_out(agent):
                    self._handle_timeout(agent)
            else:
                self._handle_completion(agent)

    def _is_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _is_timed_out(self, agent: dict) -> bool:
        started = datetime.fromisoformat(agent["started_at"])
        elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 60
        return elapsed > agent["timeout_minutes"]

    def _handle_timeout(self, agent: dict):
        pid = agent["pid"]
        issue = agent["issue"]
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])

        logger.warning(f"Agent timed out: {issue} (pid={pid})")
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        label_map = {
            "coding": self.labels["in_progress"],
            "testing": self.labels["testing"],
            "review": self.labels["review_needed"],
        }
        old_label = label_map.get(agent["type"], self.labels["in_progress"])
        self.gh.swap_label(repo, issue_number, old_label, self.labels["error"])
        self.gh.add_comment(repo, issue_number, f"[agent-orchestrator] Agent timed out after {agent['timeout_minutes']} minutes.")
        self.slack.notify_timeout(issue, agent["timeout_minutes"])
        self.state.remove_agent(pid)

    def _handle_completion(self, agent: dict):
        """Agent process exited — clean up state. Label transitions are handled by the agent itself."""
        pid = agent["pid"]
        issue = agent["issue"]
        logger.info(f"Agent completed: {issue} (pid={pid}, type={agent['type']})")
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])
        self.gh.add_comment(repo, issue_number, f"[agent-orchestrator] Attempt {agent['attempt']} completed ({agent['type']} agent).")
        self.state.remove_agent(pid)

    def _process_ready_issues(self, repo: str):
        """Dispatch coding agents for ai-ready issues."""
        issues = self.gh.fetch_issues_by_label(repo, self.labels["ready"])
        for issue in issues:
            issue_key = f"{repo}#{issue.number}"
            if self.state.is_issue_active(issue_key):
                continue

            attempt_count = self.gh.get_attempt_count(repo, issue.number)
            if attempt_count >= self.config["guardrails"]["max_retry_cycles"]:
                logger.warning(f"Max retries reached for {issue_key}")
                self.gh.swap_label(repo, issue.number, self.labels["ready"], self.labels["blocked"])
                self.gh.add_comment(repo, issue.number, f"[agent-orchestrator] Max retry cycles ({self.config['guardrails']['max_retry_cycles']}) reached. Marking blocked.")
                self.slack.notify_max_retries(issue_key, self.config["guardrails"]["max_retry_cycles"])
                continue

            current_coding = len(self.state.get_agents_by_type("coding"))
            if current_coding >= self.config["concurrency"]["max_coding"]:
                logger.info(f"Coding concurrency limit reached ({current_coding}), skipping {issue_key}")
                break

            self._dispatch_coding(repo, issue, attempt_count + 1)

    def _process_testing_issues(self, repo: str):
        """Dispatch testing agents for ai-testing issues."""
        issues = self.gh.fetch_issues_by_label(repo, self.labels["testing"])
        for issue in issues:
            issue_key = f"{repo}#{issue.number}"
            if self.state.is_issue_active(issue_key):
                continue

            # Guard: skip if issue no longer carries the expected label
            label_names = {lbl.name for lbl in issue.labels}
            if self.labels["testing"] not in label_names:
                continue

            current_testing = len(self.state.get_agents_by_type("testing"))
            if current_testing >= self.config["concurrency"]["max_testing"]:
                break

            self._dispatch_testing(repo, issue)

    def _process_review_issues(self, repo: str):
        """Dispatch review agents for ai-review-needed issues."""
        issues = self.gh.fetch_issues_by_label(repo, self.labels["review_needed"])
        for issue in issues:
            issue_key = f"{repo}#{issue.number}"
            if self.state.is_issue_active(issue_key):
                continue

            # Guard: skip if issue no longer carries the expected label
            label_names = {lbl.name for lbl in issue.labels}
            if self.labels["review_needed"] not in label_names:
                continue

            current_review = len(self.state.get_agents_by_type("review"))
            if current_review >= self.config["concurrency"]["max_review"]:
                break

            self._dispatch_review(repo, issue)

    def _dispatch_coding(self, repo: str, issue, attempt: int):
        issue_key = f"{repo}#{issue.number}"
        logger.info(f"Dispatching coding agent for {issue_key} (attempt {attempt})")

        cmd = self.coding_agent.build_command(
            issue_title=issue.title,
            issue_body=issue.body or "",
            issue_number=issue.number,
            repo=repo,
        )
        log_path = self.state.log_path(repo, issue.number)
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        self.gh.swap_label(repo, issue.number, self.labels["ready"], self.labels["in_progress"])
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=repo,
            agent_type="coding",
            timeout_minutes=self.config["timeouts"]["coding_minutes"],
            attempt=attempt,
        )

    def _dispatch_testing(self, repo: str, issue):
        issue_key = f"{repo}#{issue.number}"
        logger.info(f"Dispatching testing agent for {issue_key}")

        pr_branch = f"ai/issue-{issue.number}"
        cmd = self.testing_agent.build_command(
            issue_title=issue.title,
            issue_body=issue.body or "",
            issue_number=issue.number,
            repo=repo,
            pr_branch=pr_branch,
        )
        log_path = self.state.log_path(repo, issue.number)
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        # No label swap needed — issue is already ai-testing
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=repo,
            agent_type="testing",
            timeout_minutes=self.config["timeouts"]["testing_minutes"],
            attempt=1,
        )

    def _dispatch_review(self, repo: str, issue):
        issue_key = f"{repo}#{issue.number}"
        logger.info(f"Dispatching review agent for {issue_key}")

        pr_number = issue.number  # Assumes PR number matches; can be refined
        cmd = self.review_agent.build_command(
            issue_title=issue.title,
            issue_body=issue.body or "",
            issue_number=issue.number,
            repo=repo,
            pr_number=pr_number,
        )
        log_path = self.state.log_path(repo, issue.number)
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        # No label swap needed — issue is already ai-review-needed
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=repo,
            agent_type="review",
            timeout_minutes=self.config["timeouts"]["review_minutes"],
            attempt=1,
        )


def main():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    config = load_config(config_path)
    orchestrator = Orchestrator(config)
    orchestrator.run()


if __name__ == "__main__":
    main()
