# tests/test_config.py
import os
import pytest
from config import load_config


def test_load_config_returns_all_sections(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
repos:
  - owner/repo-a
concurrency:
  max_coding: 2
  max_testing: 1
  max_review: 1
timeouts:
  coding_minutes: 60
  testing_minutes: 30
  review_minutes: 30
guardrails:
  max_files_changed: 10
  max_retry_cycles: 3
slack:
  webhook_url: "https://hooks.slack.com/test"
labels:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review_needed: "ai-review-needed"
  pr_ready: "ai-pr-ready"
  blocked: "ai-blocked"
  error: "ai-error"
""")
    cfg = load_config(str(config_file))
    assert cfg["repos"] == ["owner/repo-a"]
    assert cfg["concurrency"]["max_coding"] == 2
    assert cfg["timeouts"]["coding_minutes"] == 60
    assert cfg["guardrails"]["max_retry_cycles"] == 3
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/test"
    assert cfg["labels"]["ready"] == "ai-ready"


def test_load_config_resolves_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/from-env")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
repos:
  - owner/repo-a
concurrency:
  max_coding: 1
  max_testing: 1
  max_review: 1
timeouts:
  coding_minutes: 60
  testing_minutes: 30
  review_minutes: 30
guardrails:
  max_files_changed: 10
  max_retry_cycles: 3
slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
labels:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review_needed: "ai-review-needed"
  pr_ready: "ai-pr-ready"
  blocked: "ai-blocked"
  error: "ai-error"
""")
    cfg = load_config(str(config_file))
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/from-env"


def test_gdd_path_missing_returns_none(tmp_path):
    """When gdd_path is not in the YAML, dict.get returns None."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("repos:\n  - owner/repo-a\n")
    cfg = load_config(str(config_file))
    assert cfg.get("gdd_path") is None


def test_gdd_path_explicit_value(tmp_path):
    """When gdd_path is set, it is accessible from the loaded config."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        'repos:\n  - owner/repo-a\ngdd_path: "docs/my-game-gdd.md"\n'
    )
    cfg = load_config(str(config_file))
    assert cfg["gdd_path"] == "docs/my-game-gdd.md"


def test_load_config_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")
