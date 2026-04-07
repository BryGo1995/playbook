import logging
import requests

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Sends notifications to Slack via incoming webhook."""

    def __init__(self, webhook_url: str | None):
        self.webhook_url = webhook_url

    def send(self, message: str):
        if not self.webhook_url:
            logger.debug("No Slack webhook configured, skipping notification")
            return
        try:
            requests.post(
                self.webhook_url,
                json={"text": message},
                timeout=10,
            )
        except requests.RequestException as e:
            logger.error(f"Slack notification failed: {e}")

    def notify_blocked(self, issue: str, reason: str):
        self.send(f":warning: Issue {issue} blocked: {reason}")

    def notify_error(self, issue: str, error: str):
        self.send(f":x: Agent failed on {issue}: {error}")

    def notify_pr_ready(self, issue: str, pr_number: int):
        self.send(f":white_check_mark: Draft PR #{pr_number} ready for review ({issue})")

    def notify_timeout(self, issue: str, timeout_minutes: int):
        self.send(f":clock1: Agent on {issue} killed after {timeout_minutes}min timeout")

    def notify_max_retries(self, issue: str, max_cycles: int):
        self.send(f":rotating_light: Issue {issue} hit {max_cycles} cycles — marked blocked")

    def notify_review_rejected(self, issue: str, attempt: int, max_cycles: int):
        self.send(f":leftwards_arrow_with_hook: Review agent sent {issue} back for rework (attempt {attempt}/{max_cycles})")

    def notify_version_complete(self, version: str, issue_count: int):
        self.send(f":tada: Version {version} complete \u2014 {issue_count} issues merged to ai/dev. Ready for next batch of issues.")
