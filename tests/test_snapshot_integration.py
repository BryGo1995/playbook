"""Integration test for _snapshot_branch using real git in a temp repo (no GitHub)."""
import os
import subprocess
import pytest
from unittest.mock import MagicMock, patch
from orchestrator import Orchestrator


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def real_git_repo(tmp_path):
    """Create a temp repo + a 'remote' (also temp) so push works."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "checkout", "-b", "ai/dev")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    _git(repo, "push", "-u", "origin", "ai/dev")

    # Set up the feature branch with one commit + a dirty working tree
    _git(repo, "checkout", "-b", "ai/issue-7")
    (repo / "feature.py").write_text("print('hi')\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-m", "feature commit")
    # Leave a dirty file (uncommitted)
    (repo / "dirty.py").write_text("dirty\n")

    return repo


@pytest.fixture
def config():
    return {
        "repo": "owner/repo",
        "project": {"owner": "owner", "number": 1, "status_field_id": "PVTSSF_x"},
        "concurrency": {"max_coding": 1, "max_testing": 1, "max_review": 1},
        "timeouts": {"coding_minutes": 60, "testing_minutes": 30, "review_minutes": 30},
        "guardrails": {"max_files_changed": 10, "max_retry_cycles": 3, "snapshot_on_failure": True},
        "branches": {"integration": "ai/dev"},
        "slack": {"webhook_url": None},
        "statuses": {
            "backlog": "Backlog", "ready": "ai-ready", "in_progress": "ai-in-progress",
            "testing": "ai-testing", "review": "ai-review", "complete": "ai-complete",
            "done": "Done", "blocked": "ai-blocked", "error": "ai-error",
        },
    }


def test_snapshot_branch_with_real_git(real_git_repo, config, tmp_path, monkeypatch):
    monkeypatch.chdir(real_git_repo)
    with patch("orchestrator.GitHubClient"):
        orch = Orchestrator(config, state_dir=str(tmp_path / "state"))

    result = orch._snapshot_branch("owner/repo", 7, attempt=1)

    assert result["status"] == "ok"
    assert result["snapshot_ref"] == "ai/issue-7-attempt-1"
    assert result["wip_ref"] == "ai/issue-7-attempt-1-wip"

    # Snapshot ref points at the same SHA as ai/issue-7
    snap = subprocess.run(
        ["git", "ls-remote", "origin", "ai/issue-7-attempt-1"],
        cwd=real_git_repo, capture_output=True, text=True,
    )
    assert "refs/heads/ai/issue-7-attempt-1" in snap.stdout

    # Wip ref exists
    wip = subprocess.run(
        ["git", "ls-remote", "origin", "ai/issue-7-attempt-1-wip"],
        cwd=real_git_repo, capture_output=True, text=True,
    )
    assert "refs/heads/ai/issue-7-attempt-1-wip" in wip.stdout

    # Working tree is clean (stash dropped, untracked file is gone via stash + drop)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=real_git_repo, capture_output=True, text=True,
    )
    assert status.stdout == ""
