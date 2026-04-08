# tests/test_config.py
import os
import pytest
from config import load_config


def test_load_config_returns_all_sections(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/repo-a
gdd_path: "docs/gdd.md"
project:
  owner: owner
  number: 1
  status_field_id: "test"
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
statuses:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
  testing: "ai-testing"
  review: "ai-review"
  complete: "ai-complete"
  done: "Done"
  blocked: "ai-blocked"
  error: "ai-error"
""")
    # No defaults file — project config is self-contained
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg["repo"] == "owner/repo-a"
    assert cfg["concurrency"]["max_coding"] == 2
    assert cfg["timeouts"]["coding_minutes"] == 60
    assert cfg["guardrails"]["max_retry_cycles"] == 3
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/test"
    assert cfg["statuses"]["ready"] == "ai-ready"


def test_load_config_resolves_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/from-env")
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/repo-a
slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
""")
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/from-env"


def test_gdd_path_missing_returns_none(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("repo: owner/repo-a\n")
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg.get("gdd_path") is None


def test_gdd_path_explicit_value(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text(
        'repo: owner/repo-a\ngdd_path: "docs/my-game-gdd.md"\n'
    )
    cfg = load_config(project_dir=str(project_dir), defaults_path=str(tmp_path / "nonexistent.yaml"))
    assert cfg["gdd_path"] == "docs/my-game-gdd.md"


def test_load_config_missing_playbook_yaml_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="playbook.yaml"):
        load_config(project_dir=str(tmp_path), defaults_path=str(tmp_path / "nonexistent.yaml"))


def test_load_config_merges_defaults_and_project(tmp_path, monkeypatch):
    """Project playbook.yaml overrides defaults.yaml values."""
    defaults = tmp_path / "playbook"
    defaults.mkdir()
    (defaults / "defaults.yaml").write_text("""
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
statuses:
  ready: "ai-ready"
  in_progress: "ai-in-progress"
slack:
  webhook_url: "default"
""")

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("""
repo: owner/my-project
gdd_path: "docs/my-gdd.md"
project:
  owner: owner
  number: 5
  status_field_id: "PVTSSF_test"
concurrency:
  max_coding: 2
""")

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults / "defaults.yaml"))
    # Project-specific values
    assert cfg["repo"] == "owner/my-project"
    assert cfg["gdd_path"] == "docs/my-gdd.md"
    assert cfg["project"]["number"] == 5
    # Override from project
    assert cfg["concurrency"]["max_coding"] == 2
    # Inherited from defaults
    assert cfg["concurrency"]["max_testing"] == 1
    assert cfg["timeouts"]["coding_minutes"] == 60
    assert cfg["statuses"]["ready"] == "ai-ready"


def test_load_config_no_playbook_yaml_raises(tmp_path):
    """Error when playbook.yaml is not found in the project directory."""
    with pytest.raises(FileNotFoundError, match="playbook.yaml"):
        load_config(project_dir=str(tmp_path), defaults_path="/nonexistent/defaults.yaml")


def test_load_config_env_vars_resolved_in_merged_config(tmp_path, monkeypatch):
    """Env vars are resolved after merging."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/merged")
    defaults_dir = tmp_path / "playbook"
    defaults_dir.mkdir()
    (defaults_dir / "defaults.yaml").write_text('slack:\n  webhook_url: "${SLACK_WEBHOOK_URL}"\n')

    project_dir = tmp_path / "my-project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text('repo: owner/proj\nproject:\n  owner: owner\n  number: 1\n  status_field_id: "test"\n')

    cfg = load_config(project_dir=str(project_dir), defaults_path=str(defaults_dir / "defaults.yaml"))
    assert cfg["slack"]["webhook_url"] == "https://hooks.slack.com/merged"
