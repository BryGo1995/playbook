# tests/test_learning_config.py
from config import load_config


def test_defaults_provide_learning_block(tmp_path):
    """defaults.yaml ships a learning block enabled by default."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text("repo: owner/repo\n")

    cfg = load_config(project_dir=str(project_dir))

    assert cfg["learning"]["enabled"] is True
    assert cfg["learning"]["project_distiller"] is True
    assert cfg["learning"]["agent_craft_distiller"] is True
    assert cfg["learning"]["playbook_repo"] == "BryGo1995/playbook"


def test_project_can_disable_learning(tmp_path):
    """playbook.yaml override can disable the whole feature."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text(
        "repo: owner/repo\n"
        "learning:\n"
        "  enabled: false\n"
    )

    cfg = load_config(project_dir=str(project_dir))

    assert cfg["learning"]["enabled"] is False
    # other learning fields still inherit from defaults
    assert cfg["learning"]["project_distiller"] is True


def test_project_can_disable_one_distiller(tmp_path):
    """Distillers can be toggled independently."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "playbook.yaml").write_text(
        "repo: owner/repo\n"
        "learning:\n"
        "  agent_craft_distiller: false\n"
    )

    cfg = load_config(project_dir=str(project_dir))

    assert cfg["learning"]["enabled"] is True
    assert cfg["learning"]["project_distiller"] is True
    assert cfg["learning"]["agent_craft_distiller"] is False
