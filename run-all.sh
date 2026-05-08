#!/bin/bash
# Playbook — Run orchestrator for all configured projects
# Each project must have a playbook.yaml in its root.
#
# Configure your project list outside this repo, in
# ${XDG_CONFIG_HOME:-$HOME/.config}/playbook/projects.sh:
#
#   PROJECTS=(
#       "$HOME/code/my-project"
#       "$HOME/code/another-project"
#   )
#
# The file is sourced as bash, so $HOME and other env vars expand normally.

PLAYBOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$PLAYBOOK_DIR"
export PATH="$HOME/.local/bin:$PATH"

PROJECTS=()

PROJECTS_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/playbook/projects.sh"
if [ -f "$PROJECTS_CONFIG" ]; then
    # shellcheck disable=SC1090
    source "$PROJECTS_CONFIG"
fi

if [ ${#PROJECTS[@]} -eq 0 ]; then
    echo "[playbook] No projects configured. Create $PROJECTS_CONFIG with a PROJECTS=(...) array of project directories." >&2
    exit 0
fi

for dir in "${PROJECTS[@]}"; do
    if [ ! -f "$dir/playbook.yaml" ]; then
        echo "[playbook] SKIP $dir — no playbook.yaml found" >&2
        continue
    fi
    echo "[playbook] Running orchestrator in $dir"
    (cd "$dir" && python3 -c "from orchestrator import main; main()") &
done

wait
