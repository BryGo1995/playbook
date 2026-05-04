#!/bin/bash
# Playbook — Run orchestrator for all configured projects
# Each project must have a playbook.yaml in its root.
#
# Configure your projects by editing the PROJECTS array below, e.g.:
#
#   PROJECTS=(
#       "$HOME/code/my-project"
#       "$HOME/code/another-project"
#   )

PLAYBOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$PLAYBOOK_DIR"
export PATH="$HOME/.local/bin:$PATH"

PROJECTS=(
    # Add absolute paths to your project directories here.
)

if [ ${#PROJECTS[@]} -eq 0 ]; then
    echo "[playbook] No projects configured. Edit PROJECTS in $0 to add project directories." >&2
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
