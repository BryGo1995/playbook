#!/usr/bin/env python3
"""Validate the playbook plugin layout.

Checks plugin.json, marketplace.json, skill frontmatter, and agent prompt
references. Exits non-zero on any hard failure; warnings do not affect exit.

Usage:
    python scripts/validate_plugin.py [--root PATH]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


@dataclass
class Report:
    passes: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok(self, msg: str) -> None:
        self.passes.append(msg)

    def fail(self, msg: str) -> None:
        self.failures.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def print(self) -> None:
        for m in self.passes:
            print(f"✓ {m}")
        for m in self.warnings:
            print(f"⚠ {m}")
        for m in self.failures:
            print(f"✗ {m}")

    @property
    def exit_code(self) -> int:
        return 1 if self.failures else 0


def validate(root: Path) -> Report:
    report = Report()
    _check_plugin_manifests(root, report)
    _check_skills(root, report)
    _check_agent_prompts(root, report)
    return report


def _check_plugin_manifests(root: Path, report: Report) -> None:
    plugin_path = root / ".claude-plugin" / "plugin.json"
    marketplace_path = root / ".claude-plugin" / "marketplace.json"

    if not plugin_path.exists():
        report.fail(f"{plugin_path.relative_to(root)} missing")
        return
    if not marketplace_path.exists():
        report.fail(f"{marketplace_path.relative_to(root)} missing")
        return

    try:
        plugin = json.loads(plugin_path.read_text())
    except json.JSONDecodeError as e:
        report.fail(f"plugin.json invalid JSON: {e}")
        return
    try:
        marketplace = json.loads(marketplace_path.read_text())
    except json.JSONDecodeError as e:
        report.fail(f"marketplace.json invalid JSON: {e}")
        return

    required_missing = [f for f in ("name", "version") if f not in plugin]
    for f in required_missing:
        report.fail(f"plugin.json missing required field '{f}'")
    if required_missing:
        return

    plugin_version = plugin.get("version")
    market_metadata_version = marketplace.get("metadata", {}).get("version")
    market_plugins = marketplace.get("plugins", [])
    market_plugin_version = market_plugins[0].get("version") if market_plugins else None

    versions = {
        "plugin.json": plugin_version,
        "marketplace.json metadata.version": market_metadata_version,
        "marketplace.json plugins[0].version": market_plugin_version,
    }
    distinct = {v for v in versions.values() if v is not None}
    if len(distinct) > 1:
        report.fail(f"version mismatch across manifests: {versions}")
    else:
        report.ok(f"plugin.json + marketplace.json (version {plugin_version})")


def _check_skills(root: Path, report: Report) -> None:
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            report.fail(f"{skill_md.relative_to(root)} missing")
            continue
        text = skill_md.read_text()
        m = re.match(r"^---\n(.*?)\n---\s*\n?", text, re.DOTALL)
        if not m:
            report.fail(f"{skill_md.relative_to(root)}: missing YAML frontmatter")
            continue
        try:
            front = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            report.fail(f"{skill_md.relative_to(root)}: frontmatter YAML error: {e}")
            continue
        for required in ("name", "description"):
            if not front.get(required):
                report.fail(f"{skill_md.relative_to(root)}: missing required field '{required}'")
        expected_name = f"playbook:{skill_dir.name}"
        if front.get("name") and front["name"] != expected_name:
            report.fail(
                f"{skill_md.relative_to(root)}: name '{front['name']}' "
                f"does not match expected '{expected_name}'"
            )
        if front.get("name") == expected_name and front.get("description"):
            report.ok(f"{skill_md.relative_to(root)}")


def _check_agent_prompts(root: Path, report: Report) -> None:
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return
    pattern = re.compile(
        r'os\.path\.join\(\s*os\.path\.dirname\(__file__\)\s*,\s*["\']prompts["\']\s*,\s*["\']([^"\']+)["\']'
    )
    for py in sorted(agents_dir.glob("*.py")):
        text = py.read_text()
        for match in pattern.finditer(text):
            prompt_name = match.group(1)
            prompt_path = agents_dir / "prompts" / prompt_name
            if not prompt_path.exists():
                report.fail(
                    f"{py.relative_to(root)} references missing prompt "
                    f"{prompt_path.relative_to(root)}"
                )
            else:
                report.ok(f"{py.relative_to(root)} → prompts/{prompt_name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(),
                        help="Plugin root (default: cwd)")
    args = parser.parse_args(argv)
    report = validate(args.root.resolve())
    report.print()
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
