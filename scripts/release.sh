#!/usr/bin/env bash
# release.sh — one-command playbook release.
#
# Usage: scripts/release.sh <version>
#   e.g. scripts/release.sh 1.0.0
#
# Preconditions enforced:
#   * Current branch is `main`
#   * Working tree is clean
#   * Local `main` matches `origin/main` (if origin is configured)
#
# Side effects:
#   * Bumps version in .claude-plugin/plugin.json (top-level `version`)
#   * Bumps version in .claude-plugin/marketplace.json (metadata.version + plugins[0].version)
#   * Commits "chore: release v<version>"
#   * Tags v<version>
#   * Pushes commit and tag to origin (unless PLAYBOOK_RELEASE_SKIP_PUSH=1)
#
# Environment:
#   PLAYBOOK_RELEASE_SKIP_PUSH=1   Skip git push (used by tests)

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <version>   (e.g. $0 1.0.0)" >&2
    exit 2
fi

VERSION="$1"

# Basic semver shape check (X.Y.Z, optional -rc.N / -beta.N suffix).
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
    echo "ERROR: version '$VERSION' is not a valid semver (e.g. 1.0.0 or 1.0.0-rc.1)" >&2
    exit 2
fi

TAG="v${VERSION}"

# Precondition 1: on main
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo "ERROR: must be on 'main' (currently on '$CURRENT_BRANCH')" >&2
    exit 1
fi

# Precondition 2: clean working tree
if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: working tree is not clean. Commit or stash before releasing." >&2
    git status --short >&2
    exit 1
fi

# Precondition 3: in sync with origin (if origin exists)
if git remote get-url origin >/dev/null 2>&1; then
    git fetch -q origin main
    LOCAL="$(git rev-parse HEAD)"
    REMOTE="$(git rev-parse origin/main)"
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "ERROR: local main ($LOCAL) does not match origin/main ($REMOTE)." >&2
        echo "Pull or push first." >&2
        exit 1
    fi
fi

# Precondition 4: tag must not already exist locally
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: tag '$TAG' already exists locally." >&2
    echo "If a previous push failed, run: git push origin $TAG" >&2
    exit 1
fi

PLUGIN_JSON=".claude-plugin/plugin.json"
MARKETPLACE_JSON=".claude-plugin/marketplace.json"

if [ ! -f "$PLUGIN_JSON" ] || [ ! -f "$MARKETPLACE_JSON" ]; then
    echo "ERROR: expected $PLUGIN_JSON and $MARKETPLACE_JSON to exist." >&2
    exit 1
fi

echo "Releasing v$VERSION..."
echo "  - Updating $PLUGIN_JSON"
echo "  - Updating $MARKETPLACE_JSON"

# Use Python (already a dep) for safe JSON edits — sed on JSON is error-prone.
python3 - "$VERSION" "$PLUGIN_JSON" "$MARKETPLACE_JSON" <<'PY'
import json
import sys
from pathlib import Path

version, plugin_path, marketplace_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])

plugin = json.loads(plugin_path.read_text())
plugin["version"] = version

market = json.loads(marketplace_path.read_text())
meta = market.get("metadata")
if meta is not None and not isinstance(meta, dict):
    sys.exit(f"ERROR: {marketplace_path}: 'metadata' must be a dict, got {type(meta).__name__}")
market.setdefault("metadata", {})["version"] = version
plugins = market.get("plugins") or []
for p in plugins:
    p["version"] = version

plugin_path.write_text(json.dumps(plugin, indent=2) + "\n")
marketplace_path.write_text(json.dumps(market, indent=2) + "\n")
PY

echo "  - Committing"
git add "$PLUGIN_JSON" "$MARKETPLACE_JSON"
git commit -q -m "chore: release $TAG"

echo "  - Tagging $TAG"
git tag "$TAG"

if [ "${PLAYBOOK_RELEASE_SKIP_PUSH:-0}" = "1" ]; then
    echo "  - PLAYBOOK_RELEASE_SKIP_PUSH=1, skipping push"
else
    if git remote get-url origin >/dev/null 2>&1; then
        echo "  - Pushing commit and tag to origin"
        git push origin main
        if ! git push origin "$TAG"; then
            echo "ERROR: commit pushed but tag push failed." >&2
            echo "Re-run: git push origin $TAG" >&2
            exit 1
        fi
    else
        echo "  - No origin configured, skipping push"
    fi
fi

echo "Done. Release $TAG ready."
