"""Tests for run-all.sh project-discovery behavior.

The distribution-clean script ships with PROJECTS=() empty; user project
paths come from `${XDG_CONFIG_HOME:-$HOME/.config}/playbook/projects.sh`,
which the script sources at startup. These tests pin that contract so
future commits can't quietly regress it (e.g., re-leaking maintainer
paths into the tracked script).
"""
import os
import subprocess
import textwrap

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_RUN_ALL = os.path.join(_PROJECT_ROOT, "run-all.sh")


def _run(home, env_extra=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", _RUN_ALL],
        capture_output=True, text=True, env=env, timeout=10,
    )


def test_no_config_exits_zero_with_friendly_message(tmp_path):
    """With no config file present, the script must exit 0 and tell the
    user where to put their project list — not silently do nothing."""
    proc = _run(tmp_path)
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert "No projects configured" in combined
    assert "playbook/projects.sh" in combined, (
        f"empty-config message must point at the XDG config path; got:\n{combined}"
    )


def test_sources_xdg_projects_config(tmp_path):
    """When ~/.config/playbook/projects.sh sets PROJECTS=(...), the script
    must iterate those entries (proven here by the SKIP message for
    directories that lack a playbook.yaml)."""
    config_dir = tmp_path / ".config" / "playbook"
    config_dir.mkdir(parents=True)
    fake_a = tmp_path / "fake_a"
    fake_b = tmp_path / "fake_b"
    fake_a.mkdir()
    fake_b.mkdir()
    (config_dir / "projects.sh").write_text(textwrap.dedent(f"""\
        PROJECTS=(
            "{fake_a}"
            "{fake_b}"
        )
    """))
    proc = _run(tmp_path)
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert "No projects configured" not in combined
    assert f"SKIP {fake_a}" in combined
    assert f"SKIP {fake_b}" in combined


def test_honors_xdg_config_home_override(tmp_path):
    """When XDG_CONFIG_HOME is set, the script reads the projects file
    from there rather than $HOME/.config — standard XDG behavior."""
    custom_xdg = tmp_path / "custom-config"
    config_dir = custom_xdg / "playbook"
    config_dir.mkdir(parents=True)
    fake = tmp_path / "fake_proj"
    fake.mkdir()
    (config_dir / "projects.sh").write_text(f'PROJECTS=("{fake}")\n')
    proc = _run(tmp_path, env_extra={"XDG_CONFIG_HOME": str(custom_xdg)})
    assert proc.returncode == 0
    assert f"SKIP {fake}" in (proc.stdout + proc.stderr)
