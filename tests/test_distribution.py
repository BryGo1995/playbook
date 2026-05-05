"""Distribution-readiness smoke tests.

Catches the class of bug that breaks first-install for downstream users
without exercising any runtime behavior — pure structural checks on the
files that ship to the marketplace and to project repos.
"""
import json
import os
import re

import yaml

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_PLUGIN_JSON = os.path.join(_PROJECT_ROOT, ".claude-plugin", "plugin.json")
_MARKETPLACE_JSON = os.path.join(_PROJECT_ROOT, ".claude-plugin", "marketplace.json")
_INTEGRATION_PR_TEMPLATE = os.path.join(_PROJECT_ROOT, "templates", "integration-pr-caller.yml")


def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def test_plugin_json_is_valid_and_has_required_fields():
    data = _load_json(_PLUGIN_JSON)
    for field in ("name", "description", "version"):
        assert field in data, f"plugin.json missing required field: {field}"
    assert data["name"] == "playbook"


def test_marketplace_json_is_valid_and_has_required_fields():
    data = _load_json(_MARKETPLACE_JSON)
    for field in ("name", "owner", "metadata", "plugins"):
        assert field in data, f"marketplace.json missing required field: {field}"
    assert data["name"] == "playbook"
    assert "version" in data["metadata"]
    assert isinstance(data["plugins"], list) and len(data["plugins"]) >= 1
    assert "version" in data["plugins"][0]


def test_plugin_and_marketplace_versions_agree():
    """plugin.json version, marketplace.json metadata.version, and the
    marketplace's plugins[0].version must all match — drift is the C3
    class of bug we shipped 1.4.0 with."""
    plugin = _load_json(_PLUGIN_JSON)
    marketplace = _load_json(_MARKETPLACE_JSON)
    plugin_version = plugin["version"]
    marketplace_metadata_version = marketplace["metadata"]["version"]
    marketplace_plugin_version = marketplace["plugins"][0]["version"]
    assert plugin_version == marketplace_metadata_version, (
        f"plugin.json {plugin_version} != marketplace.json metadata {marketplace_metadata_version}"
    )
    assert plugin_version == marketplace_plugin_version, (
        f"plugin.json {plugin_version} != marketplace.json plugins[0] {marketplace_plugin_version}"
    )


def test_integration_pr_caller_template_is_valid_yaml():
    with open(_INTEGRATION_PR_TEMPLATE) as f:
        data = yaml.safe_load(f)
    assert "jobs" in data
    assert "integration-pr" in data["jobs"]


def test_integration_pr_caller_template_pins_to_plugin_version():
    """The `uses:` line must reference @v{plugin.json version}, not @main.
    Downstream users who install playbook v1.4.0 should get a workflow
    that pins to v1.4.0 — not whatever is on the playbook repo's main
    branch when their action triggers."""
    plugin_version = _load_json(_PLUGIN_JSON)["version"]
    with open(_INTEGRATION_PR_TEMPLATE) as f:
        content = f.read()
    # Find the `uses:` line for the playbook workflow
    match = re.search(r"uses:\s*BryGo1995/playbook/[^@]+@(\S+)", content)
    assert match is not None, "no `uses: BryGo1995/playbook/...@<ref>` line found"
    ref = match.group(1)
    assert ref != "main", (
        "template still references @main; pin to a tag like @v{version} so "
        "downstream installs don't track playbook's development branch"
    )
    expected_ref = f"v{plugin_version}"
    assert ref == expected_ref, (
        f"template ref @{ref} does not match plugin.json version (expected @{expected_ref})"
    )
