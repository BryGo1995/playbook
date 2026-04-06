# tests/test_summary.py
import json
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from summary import (
    categorize_issues,
    format_summary,
    group_by_theme,
    load_last_run,
    save_last_run,
    parse_since,
    generate_summary,
)


LABELS = {
    "ready": "ai-ready",
    "in_progress": "ai-in-progress",
    "testing": "ai-testing",
    "review_needed": "ai-review-needed",
    "pr_ready": "ai-pr-ready",
    "merged": "ai-merged",
    "blocked": "ai-blocked",
    "error": "ai-error",
}


def _mock_issue(number, title, label_names):
    issue = MagicMock()
    issue.number = number
    issue.title = title
    labels = []
    for name in label_names:
        lbl = MagicMock()
        lbl.name = name
        labels.append(lbl)
    issue.labels = labels
    return issue


def test_categorize_issues():
    issues = [
        _mock_issue(1, "Fix bug", ["ai-merged"]),
        _mock_issue(2, "Add feature", ["ai-in-progress"]),
        _mock_issue(3, "Blocked task", ["ai-blocked"]),
        _mock_issue(4, "Review PR", ["ai-review-needed"]),
    ]
    cats = categorize_issues(issues, LABELS)
    assert len(cats["merged"]) == 1
    assert cats["merged"][0].number == 1
    assert len(cats["in_progress"]) == 1
    assert len(cats["blocked"]) == 1
    assert len(cats["review_needed"]) == 1
    assert len(cats["error"]) == 0


def test_group_by_theme_short_list():
    issues = [
        _mock_issue(1, "Fix login", []),
        _mock_issue(2, "Fix signup", []),
    ]
    result = group_by_theme(issues)
    assert len(result) == 2
    assert "#1 Fix login" in result[0]
    assert "#2 Fix signup" in result[1]


def test_group_by_theme_long_list_groups():
    issues = [
        _mock_issue(1, "Fix login flow", []),
        _mock_issue(2, "Fix signup flow", []),
        _mock_issue(3, "Fix password reset", []),
        _mock_issue(4, "Add user endpoint", []),
        _mock_issue(5, "Add admin endpoint", []),
    ]
    result = group_by_theme(issues)
    # "Fix" issues should be grouped, "Add" issues should be grouped
    assert len(result) < 5  # grouped
    fix_lines = [r for r in result if "Fix" in r]
    assert len(fix_lines) >= 1


def test_format_summary_with_activity():
    categories = {
        "merged": [_mock_issue(1, "Fix bug", []), _mock_issue(2, "Add tests", [])],
        "in_progress": [_mock_issue(3, "New feature", [])],
        "testing": [],
        "review_needed": [_mock_issue(4, "Refactor", [])],
        "pr_ready": [],
        "blocked": [_mock_issue(5, "Migration", [])],
        "error": [],
    }
    since = datetime(2026, 4, 5, 20, 0, tzinfo=timezone.utc)
    now = datetime(2026, 4, 6, 8, 0, tzinfo=timezone.utc)

    result = format_summary("owner/repo", categories, since, now, "ai/dev")

    assert "owner/repo" in result
    assert "2 merged" in result
    assert "2 in progress" in result  # 1 coding + 1 review
    assert "1 blocked" in result
    assert "#1 Fix bug" in result
    assert "coding" in result  # issue 3 status
    assert "in review" in result  # issue 4 status
    assert "github.com/owner/repo/compare/main...ai/dev" in result


def test_format_summary_no_activity():
    categories = {
        "merged": [],
        "in_progress": [],
        "testing": [],
        "review_needed": [],
        "pr_ready": [],
        "blocked": [],
        "error": [],
    }
    since = datetime(2026, 4, 5, 20, 0, tzinfo=timezone.utc)
    now = datetime(2026, 4, 6, 8, 0, tzinfo=timezone.utc)

    result = format_summary("owner/repo", categories, since, now, "ai/dev")
    assert "No agent activity" in result


def test_save_and_load_last_run(tmp_path):
    state_file = str(tmp_path / "summary_state.json")
    ts = datetime(2026, 4, 6, 8, 0, tzinfo=timezone.utc)

    with patch("summary.STATE_FILE", state_file):
        save_last_run(ts)
        loaded = load_last_run()
        assert loaded == ts


def test_load_last_run_default_when_missing(tmp_path):
    state_file = str(tmp_path / "nonexistent.json")
    with patch("summary.STATE_FILE", state_file):
        result = load_last_run()
        # Should default to ~12 hours ago
        expected_approx = datetime.now(timezone.utc) - timedelta(hours=12)
        assert abs((result - expected_approx).total_seconds()) < 5


def test_parse_since_hours():
    delta = parse_since("12h")
    assert delta == timedelta(hours=12)


def test_parse_since_minutes():
    delta = parse_since("30m")
    assert delta == timedelta(minutes=30)


def test_parse_since_invalid():
    with pytest.raises(ValueError):
        parse_since("abc")


@patch("summary.GitHubClient")
def test_generate_summary_posts_to_slack(MockGH):
    mock_gh = MockGH.return_value
    mock_gh.fetch_issues_by_label.return_value = [
        _mock_issue(1, "Fix bug", ["ai-merged"]),
    ]

    config = {
        "repos": ["owner/repo"],
        "branches": {"integration": "ai/dev"},
        "slack": {"webhook_url": "https://hooks.slack.com/test"},
        "labels": LABELS,
    }

    with patch("summary.SlackNotifier") as MockSlack:
        mock_slack = MockSlack.return_value
        with patch("summary.save_last_run"):
            generate_summary(config, since=datetime(2026, 4, 5, tzinfo=timezone.utc))

        mock_slack.send.assert_called_once()
        message = mock_slack.send.call_args[0][0]
        assert "owner/repo" in message
        assert "1 merged" in message
