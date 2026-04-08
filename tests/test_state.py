# tests/test_state.py
import json
import os
import pytest
from state import StateManager


@pytest.fixture
def state_dir(tmp_path):
    return str(tmp_path)


def test_load_empty_state(state_dir):
    sm = StateManager(state_dir)
    assert sm.agents == []


def test_add_agent_and_persist(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(
        pid=12345,
        issue="owner/repo#42",
        repo="owner/repo",
        agent_type="coding",
        timeout_minutes=60,
        attempt=1,
    )
    assert len(sm.agents) == 1
    assert sm.agents[0]["pid"] == 12345
    assert sm.agents[0]["issue"] == "owner/repo#42"

    # Verify persistence
    sm2 = StateManager(state_dir)
    assert len(sm2.agents) == 1
    assert sm2.agents[0]["pid"] == 12345


def test_remove_agent(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(
        pid=12345,
        issue="owner/repo#42",
        repo="owner/repo",
        agent_type="coding",
        timeout_minutes=60,
        attempt=1,
    )
    sm.remove_agent(12345)
    assert sm.agents == []

    sm2 = StateManager(state_dir)
    assert sm2.agents == []


def test_get_agents_by_type(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(pid=1, issue="o/r#1", repo="o/r", agent_type="coding", timeout_minutes=60, attempt=1)
    sm.add_agent(pid=2, issue="o/r#2", repo="o/r", agent_type="review", timeout_minutes=30, attempt=1)
    sm.add_agent(pid=3, issue="o/r#3", repo="o/r", agent_type="coding", timeout_minutes=60, attempt=1)
    assert len(sm.get_agents_by_type("coding")) == 2
    assert len(sm.get_agents_by_type("review")) == 1
    assert len(sm.get_agents_by_type("testing")) == 0


def test_is_issue_active(state_dir):
    sm = StateManager(state_dir)
    sm.add_agent(pid=1, issue="o/r#1", repo="o/r", agent_type="coding", timeout_minutes=60, attempt=1)
    assert sm.is_issue_active("o/r#1") is True
    assert sm.is_issue_active("o/r#99") is False


def test_logs_directory_created(state_dir):
    StateManager(state_dir)
    assert os.path.isdir(os.path.join(state_dir, "logs"))


def test_default_base_dir_is_cwd_playbook(tmp_path, monkeypatch):
    """StateManager defaults to .playbook/ in the current working directory."""
    monkeypatch.chdir(tmp_path)
    sm = StateManager()
    expected = os.path.join(str(tmp_path), ".playbook")
    assert sm.base_dir == expected
    assert os.path.isdir(os.path.join(expected, "logs"))
