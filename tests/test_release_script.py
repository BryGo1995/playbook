import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release.sh"


def _init_git_repo(tmp_path: Path, with_plugin_files: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    if with_plugin_files:
        (repo / ".claude-plugin").mkdir()
        (repo / ".claude-plugin" / "plugin.json").write_text(
            '{\n  "name": "p",\n  "version": "0.1.0"\n}\n'
        )
        (repo / ".claude-plugin" / "marketplace.json").write_text(
            '{\n  "name": "p",\n'
            '  "metadata": { "version": "0.1.0" },\n'
            '  "plugins": [{ "name": "p", "version": "0.1.0" }]\n}\n'
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return repo


def _run_script(repo: Path, version: str, *, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PLAYBOOK_RELEASE_SKIP_PUSH"] = "1"  # script honors this for tests
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT), version],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def test_aborts_when_not_on_main(tmp_path):
    repo = _init_git_repo(tmp_path)
    subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=repo, check=True)
    result = _run_script(repo, "1.0.0")
    assert result.returncode != 0
    assert "main" in (result.stdout + result.stderr).lower()


def test_aborts_when_working_tree_dirty(tmp_path):
    repo = _init_git_repo(tmp_path)
    (repo / "dirty.txt").write_text("uncommitted")
    result = _run_script(repo, "1.0.0")
    assert result.returncode != 0
    assert "clean" in (result.stdout + result.stderr).lower() or "dirty" in (result.stdout + result.stderr).lower()


def test_happy_path_bumps_versions_commits_and_tags(tmp_path):
    repo = _init_git_repo(tmp_path)
    # Fake an origin so the "in sync with origin" check has something to look at.
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)

    result = _run_script(repo, "1.0.0")
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    plugin = (repo / ".claude-plugin" / "plugin.json").read_text()
    market = (repo / ".claude-plugin" / "marketplace.json").read_text()
    assert '"version": "1.0.0"' in plugin
    assert plugin.count('"version": "1.0.0"') >= 1
    assert market.count('"version": "1.0.0"') >= 2  # metadata + plugins[0]

    tags = subprocess.run(
        ["git", "tag", "--list"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "v1.0.0" in tags

    last_msg = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert last_msg == "chore: release v1.0.0"


def test_aborts_on_invalid_semver(tmp_path):
    repo = _init_git_repo(tmp_path)
    result = _run_script(repo, "not-a-version")
    assert result.returncode == 2
    assert "semver" in (result.stdout + result.stderr).lower()
