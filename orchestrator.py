# orchestrator.py
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone

from config import load_config
from versioning import parse_version, get_active_version, version_branch_name
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
        self._notified_versions = set()

    def run(self):
        """Single orchestration cycle: check agents, auto-merge, dispatch new work."""
        self._check_running_agents()
        self._process_complete_issues()
        # Fetch all project issues once per cycle if versioning is enabled
        all_issues = None
        if self.config.get("versioning", {}).get("enabled", False):
            all_issues = self.gh.fetch_all_project_issues()
        self._check_version_completion(all_issues)
        self._retry_error_issues()
        self._process_ready_issues(all_issues)
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

    def _check_version_completion(self, all_issues: list[dict] | None = None):
        """Check if the most recently completed version should trigger a notification."""
        if all_issues is None:
            return
        version_issues: dict[tuple[int, int], list[dict]] = {}
        for issue in all_issues:
            version = parse_version(issue["title"])
            if version is not None:
                version_issues.setdefault(version, []).append(issue)

        for version in sorted(version_issues.keys()):
            statuses = [i["status"] for i in version_issues[version]]
            if all(s == "Done" for s in statuses) and version not in self._notified_versions:
                self._notified_versions.add(version)
                version_label = "bootstrap" if version == (0, 0) else f"v{version[0]}.{version[1]}"
                logger.info(f"Version {version_label} complete")
                self.slack.notify_version_complete(version_label, len(statuses))

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
        from prior_attempt import serialize_failure_comment

        pid = agent["pid"]
        issue = agent["issue"]
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])
        project_item_id = agent.get("project_item_id")
        attempt = agent["attempt"]

        logger.warning(f"Agent timed out: {issue} (pid={pid})")
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

        # Take a snapshot, if enabled
        snapshot_ref = None
        wip_ref = None
        snapshot_status = "skipped"
        if self.config.get("guardrails", {}).get("snapshot_on_failure", True):
            snap = self._snapshot_branch(repo, issue_number, attempt)
            snapshot_ref = snap["snapshot_ref"]
            wip_ref = snap["wip_ref"]
            snapshot_status = snap["status"]

        if project_item_id:
            self.gh.update_status(project_item_id, self.statuses["error"])

        if snapshot_status == "skipped":
            # Legacy comment
            self.gh.add_comment(
                repo, issue_number,
                f"[agent-orchestrator] Agent timed out after {agent['timeout_minutes']} minutes."
            )
        else:
            body = serialize_failure_comment(
                attempt=attempt,
                kind="timeout",
                reason=f"Agent timed out after {agent['timeout_minutes']} minutes",
                snapshot_ref=snapshot_ref,
                wip_ref=wip_ref,
                log_path=self.state.logs_dir,
                ts=datetime.now(timezone.utc).isoformat(),
            )
            self.gh.add_comment(repo, issue_number, body)

        self.slack.notify_timeout(issue, agent["timeout_minutes"])
        self.state.remove_agent(pid)

    def _get_integration_branch(self, issue_title: str) -> str:
        """Derive the version-specific integration branch from an issue title."""
        prefix = self.config.get("branches", {}).get("integration", "ai/dev")
        version = parse_version(issue_title)
        if version is None:
            return prefix
        return version_branch_name(version, prefix)

    def _handle_completion(self, agent: dict):
        """Agent process exited — clean up state and advance status."""
        pid = agent["pid"]
        issue = agent["issue"]
        logger.info(f"Agent completed: {issue} (pid={pid}, type={agent['type']})")
        repo = agent["repo"]
        issue_number = int(issue.split("#")[1])
        project_item_id = agent.get("project_item_id")

        # For coding agents, verify a PR was actually created before advancing
        if agent["type"] == "coding":
            from prior_attempt import serialize_failure_comment

            pr_branch = f"ai/issue-{issue_number}"
            pr_number = self.gh.find_pr_for_branch(repo, pr_branch)
            if pr_number is None:
                logger.warning(f"Coding agent exited without creating PR for {issue}")
                attempt = agent["attempt"]

                snapshot_ref = None
                wip_ref = None
                snapshot_status = "skipped"
                if self.config.get("guardrails", {}).get("snapshot_on_failure", True):
                    snap = self._snapshot_branch(repo, issue_number, attempt)
                    snapshot_ref = snap["snapshot_ref"]
                    wip_ref = snap["wip_ref"]
                    snapshot_status = snap["status"]

                if snapshot_status == "skipped":
                    self.gh.add_comment(
                        repo, issue_number,
                        f"[agent-orchestrator] Attempt {attempt} completed (coding agent) "
                        f"but no PR found on branch `{pr_branch}`. Marking as error."
                    )
                else:
                    body = serialize_failure_comment(
                        attempt=attempt,
                        kind="no-pr",
                        reason=f"Coding agent completed but no PR found on branch {pr_branch}",
                        snapshot_ref=snapshot_ref,
                        wip_ref=wip_ref,
                        log_path=self.state.logs_dir,
                        ts=datetime.now(timezone.utc).isoformat(),
                    )
                    self.gh.add_comment(repo, issue_number, body)

                if project_item_id:
                    self.gh.update_status(project_item_id, self.statuses["error"])
                self.slack.notify_error(issue, "Coding agent exited without creating a PR")
                self.state.remove_agent(pid)
                return

        self.gh.add_comment(repo, issue_number, f"[agent-orchestrator] Attempt {agent['attempt']} completed ({agent['type']} agent).")

        # Advance to next status in the pipeline
        next_status = {
            "coding": self.statuses["testing"],
            "testing": self.statuses["review"],
            "review": self.statuses["complete"],
        }
        if project_item_id and agent["type"] in next_status:
            self.gh.update_status(project_item_id, next_status[agent["type"]])
            logger.info(f"Advanced {issue} to {next_status[agent['type']]}")

        self.state.remove_agent(pid)

    def _process_complete_issues(self):
        """Auto-merge PRs for issues in ai-complete status."""
        issues = self.gh.fetch_issues_by_status(self.statuses["complete"])
        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            integration_branch = self._get_integration_branch(issue["title"])
            pr_branch = f"ai/issue-{issue['number']}"
            pr_number = self.gh.find_pr_for_branch(issue["repo"], pr_branch)

            if pr_number is None:
                logger.warning(f"No PR found for {issue_key} branch {pr_branch}, marking error")
                self.gh.update_status(issue["project_item_id"], self.statuses["error"])
                self.gh.add_comment(issue["repo"], issue["number"],
                    f"[agent-orchestrator] No PR found on branch `{pr_branch}` at merge time. Marking as error.")
                continue

            logger.info(f"Auto-merging PR #{pr_number} for {issue_key}")
            try:
                success = self.gh.merge_pr(issue["repo"], pr_number)
                if success:
                    self.gh.update_status(issue["project_item_id"], self.statuses["done"])
                    self.gh.add_comment(issue["repo"], issue["number"],
                        f"[agent-orchestrator] PR #{pr_number} auto-merged into `{integration_branch}`.")
                    self.slack.notify_pr_ready(issue_key, pr_number)
                    # Clean up local feature branch (CWD is the target repo)
                    result = subprocess.run(["git", "branch", "-D", pr_branch], capture_output=True)
                    if result.returncode == 0:
                        logger.info(f"Deleted local branch {pr_branch}")
                    else:
                        logger.debug(f"Local branch {pr_branch} not found, skipping cleanup")
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

    def _retry_error_issues(self):
        """Move ai-error issues back to ai-ready for retry (respects max_retry_cycles)."""
        issues = self.gh.fetch_issues_by_status(self.statuses["error"])
        max_retries = self.config["guardrails"]["max_retry_cycles"]
        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            attempt_count = self.gh.get_attempt_count(issue["repo"], issue["number"])
            if attempt_count >= max_retries:
                logger.info(f"Error issue {issue_key} already at max retries, marking blocked")
                self.gh.update_status(issue["project_item_id"], self.statuses["blocked"])
                self.gh.add_comment(issue["repo"], issue["number"],
                    f"[agent-orchestrator] Max retry cycles ({max_retries}) reached. Marking blocked.")
                self.slack.notify_max_retries(issue_key, max_retries)
            else:
                logger.info(f"Retrying error issue {issue_key} (attempt {attempt_count + 1}/{max_retries})")
                self.gh.update_status(issue["project_item_id"], self.statuses["ready"])

    def _process_ready_issues(self, all_issues: list[dict] | None = None):
        """Dispatch coding agents for ai-ready issues, respecting version gating."""
        issues = self.gh.fetch_issues_by_status(self.statuses["ready"])
        active_version = None
        is_bootstrap = False

        if all_issues is not None:
            active_version = get_active_version(all_issues)

        # Check if any active-version issues are still in the pipeline (not yet merged).
        # If so, block new dispatches to ensure fully sequential execution.
        in_flight_statuses = {
            self.statuses["in_progress"],
            self.statuses["testing"],
            self.statuses["review"],
            self.statuses["complete"],
        }
        if all_issues is not None and active_version is not None:
            for other in all_issues:
                if parse_version(other["title"]) == active_version and other["status"] in in_flight_statuses:
                    logger.info(f"Pipeline busy — {other['title']!r} is in {other['status']}, holding new dispatches")
                    return

        for issue in issues:
            issue_key = f"{issue['repo']}#{issue['number']}"
            if self.state.is_issue_active(issue_key):
                continue

            # Enforce version tag — block unversioned issues
            issue_version = parse_version(issue["title"])
            if issue_version is None:
                logger.warning(f"No version tag in {issue_key}: {issue['title']!r}")
                self.gh.update_status(issue["project_item_id"], self.statuses["blocked"])
                self.gh.add_comment(issue["repo"], issue["number"],
                    "[agent-orchestrator] Issue title missing version tag (e.g. `[v1.0]`). "
                    "Add a version tag and move back to ai-ready to resume.")
                continue

            # Version filter: skip issues not in the active version
            if all_issues is not None:
                if active_version is not None:
                    if issue_version != active_version:
                        continue
                    is_bootstrap = active_version == (0, 0)
                else:
                    if issue_version is not None:
                        continue

            attempt_count = self.gh.get_attempt_count(issue["repo"], issue["number"])
            if attempt_count >= self.config["guardrails"]["max_retry_cycles"]:
                logger.warning(f"Max retries reached for {issue_key}")
                self.gh.update_status(issue["project_item_id"], self.statuses["blocked"])
                self.gh.add_comment(issue["repo"], issue["number"],
                    f"[agent-orchestrator] Max retry cycles ({self.config['guardrails']['max_retry_cycles']}) reached. Marking blocked.")
                self.slack.notify_max_retries(issue_key, self.config["guardrails"]["max_retry_cycles"])
                continue

            # Bootstrap: max 1 concurrent coding agent
            max_coding = 1 if is_bootstrap else self.config["concurrency"]["max_coding"]
            current_coding = len(self.state.get_agents_by_type("coding"))
            if current_coding >= max_coding:
                logger.info(f"Coding concurrency limit reached ({current_coding}/{max_coding}), skipping {issue_key}")
                break

            integration_branch = self._get_integration_branch(issue["title"])
            if is_bootstrap:
                timeout = self.config.get("versioning", {}).get("bootstrap_timeout_minutes", 120)
                budget = self.config.get("versioning", {}).get("bootstrap_max_budget_usd", 5.0)
                self._dispatch_coding(issue, attempt_count + 1, timeout_override=timeout, budget_override=budget, integration_branch=integration_branch)
            else:
                self._dispatch_coding(issue, attempt_count + 1, integration_branch=integration_branch)

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

    def _snapshot_branch(self, repo: str, issue_number: int, attempt: int) -> dict:
        """Best-effort snapshot of the current ai/issue-N branch + dirty state.

        Returns a dict with keys: snapshot_ref, wip_ref, status (ok|partial|unavailable),
        error. Never raises. Steps are independently try/except'd; partial successes
        are reflected in the returned status.
        """
        branch = f"ai/issue-{issue_number}"
        snapshot_ref_name = f"ai/issue-{issue_number}-attempt-{attempt}"
        wip_ref_name = f"ai/issue-{issue_number}-attempt-{attempt}-wip"
        result = {
            "snapshot_ref": None,
            "wip_ref": None,
            "status": "unavailable",
            "error": None,
        }

        # 0. Does the branch even exist locally?
        check = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            capture_output=True, text=True,
        )
        if check.returncode != 0:
            result["error"] = "branch does not exist locally"
            return result

        # 1. Stash dirty state (if any). --include-untracked respects .gitignore.
        stash_msg = f"[playbook] attempt-{attempt} WIP"
        stash = subprocess.run(
            ["git", "stash", "push", "--include-untracked", "--message", stash_msg],
            capture_output=True, text=True,
        )
        stash_created = (
            stash.returncode == 0
            and "No local changes to save" not in stash.stdout
            and "No local changes to save" not in stash.stderr
        )

        stash_sha: str | None = None
        if stash_created:
            sha = subprocess.run(
                ["git", "rev-parse", "stash@{0}"],
                capture_output=True, text=True,
            )
            if sha.returncode == 0:
                stash_sha = sha.stdout.strip()

        # 2. Push the branch as the snapshot ref.
        try:
            push_branch = subprocess.run(
                ["git", "push", "--force", "origin",
                 f"{branch}:refs/heads/{snapshot_ref_name}"],
                capture_output=True, text=True,
            )
            if push_branch.returncode == 0:
                result["snapshot_ref"] = snapshot_ref_name
            else:
                result["error"] = f"branch push failed: {push_branch.stderr.strip()}"
        except Exception as e:
            result["error"] = f"branch push exception: {e}"

        # 3. Push the stash sha as the wip ref (if we have one).
        if stash_sha is not None and result["snapshot_ref"] is not None:
            try:
                push_wip = subprocess.run(
                    ["git", "push", "--force", "origin",
                     f"{stash_sha}:refs/heads/{wip_ref_name}"],
                    capture_output=True, text=True,
                )
                if push_wip.returncode == 0:
                    result["wip_ref"] = wip_ref_name
            except Exception:
                pass  # best-effort — stash is forensic only

        # 4. Drop the local stash (always — don't leave dirty state behind).
        if stash_created:
            subprocess.run(["git", "stash", "drop"], capture_output=True, text=True)

        # 5. Decide overall status.
        if result["snapshot_ref"] is None:
            result["status"] = "unavailable"
        elif stash_sha is not None and result["wip_ref"] is None:
            # We had a stash but couldn't push it
            result["status"] = "partial"
        else:
            result["status"] = "ok"

        return result

    def _dispatch_coding(self, issue: dict, attempt: int, timeout_override: int | None = None, budget_override: float | None = None, integration_branch: str | None = None):
        issue_key = f"{issue['repo']}#{issue['number']}"
        logger.info(f"Dispatching coding agent for {issue_key} (attempt {attempt})")

        timeout = timeout_override if timeout_override is not None else self.config["timeouts"]["coding_minutes"]
        if integration_branch is None:
            integration_branch = self._get_integration_branch(issue["title"])
        cmd = self.coding_agent.build_command(
            issue_title=issue["title"],
            issue_body=issue["body"] or "",
            issue_number=issue["number"],
            repo=issue["repo"],
            integration_branch=integration_branch,
            max_budget_usd=budget_override if budget_override is not None else self.config.get("versioning", {}).get("coding_max_budget_usd", 5.0),
        )
        log_path = self.state.log_path(issue["repo"], issue["number"])
        log_file = open(log_path, "w")
        cwd = None  # Orchestrator runs from within the target repo
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=cwd)

        self.gh.update_status(issue["project_item_id"], self.statuses["in_progress"])
        self.state.add_agent(
            pid=proc.pid,
            issue=issue_key,
            repo=issue["repo"],
            agent_type="coding",
            timeout_minutes=timeout,
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
        cwd = None  # Orchestrator runs from within the target repo
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=cwd)

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
        cwd = None  # Orchestrator runs from within the target repo
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT, cwd=cwd)

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
    config = load_config()  # Reads playbook.yaml from CWD, merges with defaults.yaml
    orchestrator = Orchestrator(config)
    orchestrator.run()


if __name__ == "__main__":
    main()
