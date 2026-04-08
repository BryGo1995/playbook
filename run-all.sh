#!/bin/bash
# Playbook — Run orchestrator for all configured projects
# Each project must have a playbook.yaml in its root.
# Add/remove project directories below as needed.

PLAYBOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$PLAYBOOK_DIR"

PROJECTS=(
    "/home/bryang/Dev_Space/bee_gee_games/godot/paint-ballas-auto"
)

for dir in "${PROJECTS[@]}"; do
    if [ ! -f "$dir/playbook.yaml" ]; then
        echo "[playbook] SKIP $dir — no playbook.yaml found" >&2
        continue
    fi
    echo "[playbook] Running orchestrator in $dir"
    (cd "$dir" && python3 -c "from orchestrator import main; main()") &
done

wait
