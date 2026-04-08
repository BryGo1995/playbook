# config.py
import os
import re
import yaml


def _resolve_env_vars(value):
    """Replace ${VAR_NAME} patterns with environment variable values."""
    if isinstance(value, str):
        return re.sub(
            r"\$\{(\w+)\}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            value,
        )
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override wins for scalars and lists."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(project_dir: str | None = None, defaults_path: str | None = None) -> dict:
    """Load defaults.yaml from playbook repo, merge with playbook.yaml from project dir."""
    if project_dir is None:
        project_dir = os.getcwd()

    if defaults_path is None:
        defaults_path = os.path.join(os.path.dirname(__file__), "defaults.yaml")

    # Load project config (required)
    project_config_path = os.path.join(project_dir, "playbook.yaml")
    if not os.path.exists(project_config_path):
        raise FileNotFoundError(
            f"No playbook.yaml found in {project_dir}. "
            "Create a playbook.yaml with your project-specific settings."
        )
    with open(project_config_path) as f:
        project = yaml.safe_load(f) or {}

    # Load defaults (optional — works without it, just uses project config only)
    defaults = {}
    if os.path.exists(defaults_path):
        with open(defaults_path) as f:
            defaults = yaml.safe_load(f) or {}

    merged = _deep_merge(defaults, project)
    return _resolve_env_vars(merged)
