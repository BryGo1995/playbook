import pytest
from unittest.mock import patch, MagicMock
from notifications.slack import SlackNotifier


def test_send_message_posts_to_webhook():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.send("Test message")

        mock_post.assert_called_once_with(
            "https://hooks.slack.com/test",
            json={"text": "Test message"},
            timeout=10,
        )


def test_send_does_nothing_when_no_webhook():
    notifier = SlackNotifier(webhook_url=None)
    # Should not raise
    notifier.send("Test message")


def test_notify_blocked():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_blocked("owner/repo#42", "ambiguous requirements")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "owner/repo#42" in payload["text"]
        assert "blocked" in payload["text"].lower()


def test_notify_pr_ready():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_pr_ready("owner/repo#42", pr_number=15)

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "#15" in payload["text"]
        assert "review" in payload["text"].lower()


def test_notify_error():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_error("owner/repo#42", "exit code 1")

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "owner/repo#42" in payload["text"]
        assert "exit code 1" in payload["text"]


def test_notify_timeout():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_timeout("owner/repo#42", timeout_minutes=60)

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "60" in payload["text"]
        assert "timeout" in payload["text"].lower()


def test_notify_max_retries():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_max_retries("owner/repo#42", max_cycles=3)

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert "3" in payload["text"]
        assert "owner/repo#42" in payload["text"]


def test_notify_version_complete():
    with patch("notifications.slack.requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notifier = SlackNotifier("https://hooks.slack.com/test")
        notifier.notify_version_complete("v0.1", 5)

        call_args = mock_post.call_args
        payload = call_args[1]["json"] if "json" in call_args[1] else call_args[0][1]
        assert payload["text"] == ":tada: Version v0.1 complete \u2014 5 issues merged to ai/dev. Ready for next batch of issues."
