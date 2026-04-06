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
        self.statuses = config["statuses"]
        self.gh = GitHubClient()
        self.gh.load_project_metadata(
            owner=config["project"]["owner"],
            project_number=config["project"]["number"],
            status_field_id=config["project"]["status_field_id"],
        )
        self.state = StateManager(state_dir or os.path.expanduser("~/.agent-orchestrator"))
        self.slack = SlackNotifier(config["slack"].get("webhook_url"))
        self.coding_agent = CodingAgent()
        self.testing_agent = TestingAgent()
        self.review_agent = ReviewAgent()

    def run(self):
        """Single orchestration cycle: check agents, auto-merge, dispatch new work."""
        self._check_running_agents()
        self._process_complete_issues()
        self._process_ready_issues()
        self._process_testing_issues()
        self._process_review_issues()

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
        project_item_id = agent.get("project_item_id")

        logger.warning(f"Agent timed out: {issue} (pid={pid})")
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        if project_item_id:
            self.gh.update_status(project_item_id, self.statuses["error"])
        self.gh.add_comment(repo, issue_number, f"[agent-orchestrator] Agent timed out after {agent['timeout_minutes']} minutes.")
        self.slack.notify_timeout(issue, agent["timeout_minutes"])
        self.state.remove_agent(pid)

    def _handle_completion(self, agent: dict):
        """Agent process exited — clean up state."""
        pid = agent["pid"]
        issue = agent["issue"]
        logger.info(f"Agent completed: {issue} (pid={pid}, type={agent['type']})")
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])
        self.gh.add_comment(repo, issue_number, f"[agent-orchestrator] Attempt {agent['attempt']} completed ({agent['type']} agent).")
        self.state.remove_agent(pid)

    def _process_complete_issues(self):
        """Auto-merge PRs for issues in ai-complete status."""
        issues = self.gh.fetch_issues_by_status(self.statuses["complete"])
        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            pr_branch = f"ai/issue-{issue['number']}"
            pr_number = self.gh.find_pr_for_branch(issue["repo"], pr_branch)

            if pr_number is None:
                logger.warning(f"No PR found for {issue_key} branch {pr_branch}")
                continue

            logger.info(f"Auto-merging PR #{pr_number} for {issue_key}")
            try:
                success = self.gh.merge_pr(issue["repo"], pr_number)
                if success:
                    self.gh.update_status(issue["project_item_id"], self.statuses["done"])
                    self.gh.close_issue(issue["repo"], issue["number"])
                    self.gh.add_comment(issue["repo"], issue["number"],
                        f"[agent-orchestrator] PR #{pr_number} auto-merged into {self.config['branches']['integration']}. Issue closed.")
                    self.slack.notify_pr_ready(issue_key, pr_number)
                else:
                    logger.warning(f"Merge failed for PR #{pr_number} ({issue_key})")
                    self.gh.update_status(issue["project_item_id"], self.statuses["blocked"])
                    self.gh.add_comment(issue["repo"], issue["number"],
                        f"[agent-orchestrator] PR #{pr_number} could not be merged (conflict or not mergeable). Marking blocked.")
                    self.slack.notify_blocked(issue_key, f"PR #{pr_number} merge conflict")
            except Exception as e:
                logger.error(f"Merge error for PR #{pr_number} ({issue_key}): {e}")
                self.gh.update_status(issue["project_item_id"], self.statuses["error"])
                self.slack.notify_error(issue_key, f"Merge failed: {e}")

    def _process_ready_issues(self):
        """Dispatch coding agents for ai-ready issues."""
        issues = self.gh.fetch_issues_by_status(self.statuses["ready"])
        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            if self.state.is_issue_active(issue_key):
                continue

            attempt_count = self.gh.get_attempt_count(issue["repo"], issue["number"])
            if attempt_count >= self.config["guardrails"]["max_retry_cycles"]:
                logger.warning(f"Max retries reached for {issue_key}")
                self.gh.update_status(issue["project_item_id"], self.statuses["blocked"])
                self.gh.add_comment(issue["repo"], issue["number"],
                    f"[agent-orchestrator] Max retry cycles ({self.config['guardrails']['max_retry_cycles']}) reached. Marking blocked.")
                self.slack.notify_max_retries(issue_key, self.config["guardrails"]["max_retry_cycles"])
                continue

            current_coding = len(self.state.get_agents_by_type("coding"))
            if current_coding >= self.config["concurrency"]["max_coding"]:
                logger.info(f"Coding concurrency limit reached ({current_coding}), skipping {issue_key}")
                break

            self._dispatch_coding(issue, attempt_count + 1)

    def _process_testing_issues(self):
        """Dispatch testing agents for ai-testing issues."""
        issues = self.gh.fetch_issues_by_status(self.statuses["testing"])
        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            if self.state.is_issue_active(issue_key):
                continue

            current_testing = len(self.state.get_agents_by_type("testing"))
            if current_testing >= self.config["concurrency"]["max_testing"]:
                break

            self._dispatch_testing(issue)

    def _process_review_issues(self):
        """Dispatch review agents for ai-review issues."""
        issues = self.gh.fetch_issues_by_status(self.statuses["review"])
        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            if self.state.is_issue_active(issue_key):
                continue

            current_review = len(self.state.get_agents_by_type("review"))
            if current_review >= self.config["concurrency"]["max_review"]:
                break

            self._dispatch_review(issue)

    def _dispatch_coding(self, issue: dict, attempt: int):
        issue_key = f"{issue['repo']}#{issue['number']}"
        logger.info(f"Dispatching coding agent for {issue_key} (attempt {attempt})")

        integration_branch = self.config.get("branches", {}).get("integration", "ai/dev")
        cmd = self.coding_agent.build_command(
            issue_title=issue["title"],
            issue_body=issue["body"] or "",
            issue_number=issue["number"],
            repo=issue["repo"],
            integration_branch=integration_branch,
        )
        log_path = self.state.log_path(issue["repo"], issue["number"])
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        self.gh.update_status(issue["project_item_id"], self.statuses["in_progress"])
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=issue["repo"],
            agent_type="coding",
            timeout_minutes=self.config["timeouts"]["coding_minutes"],
            attempt=attempt,
            project_item_id=issue["project_item_id"],
        )

    def _dispatch_testing(self, issue: dict):
        issue_key = f"{issue['repo']}#{issue['number']}"
        logger.info(f"Dispatching testing agent for {issue_key}")

        pr_branch = f"ai/issue-{issue['number']}"
        cmd = self.testing_agent.build_command(
            issue_title=issue["title"],
            issue_body=issue["body"] or "",
            issue_number=issue["number"],
            repo=issue["repo"],
            pr_branch=pr_branch,
        )
        log_path = self.state.log_path(issue["repo"], issue["number"])
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=issue["repo"],
            agent_type="testing",
            timeout_minutes=self.config["timeouts"]["testing_minutes"],
            attempt=1,
            project_item_id=issue["project_item_id"],
        )

    def _dispatch_review(self, issue: dict):
        issue_key = f"{issue['repo']}#{issue['number']}"
        logger.info(f"Dispatching review agent for {issue_key}")

        pr_number = issue["number"]  # Can be refined to look up actual PR
        cmd = self.review_agent.build_command(
            issue_title=issue["title"],
            issue_body=issue["body"] or "",
            issue_number=issue["number"],
            repo=issue["repo"],
            pr_number=pr_number,
        )
        log_path = self.state.log_path(issue["repo"], issue["number"])
        log_file = open(log_path, "w")
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)

        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=issue["repo"],
            agent_type="review",
            timeout_minutes=self.config["timeouts"]["review_minutes"],
            attempt=1,
            project_item_id=issue["project_item_id"],
        )


def main():
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    config = load_config(config_path)
    orchestrator = Orchestrator(config)
    orchestrator.run()


if __name__ == "__main__":
    main()
