#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Agent Orchestrator Setup ==="

# Install Python dependencies
cd "$SCRIPT_DIR"
python3 -m pip install -r requirements.txt
echo "Installed Python dependencies"

echo "Note: per-project runtime state lives in <project_dir>/.playbook/ (created on first run)."

# Check for required env vars
if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "WARNING: GITHUB_TOKEN not set. Export it before running the orchestrator."
    echo "  export GITHUB_TOKEN=ghp_your_token_here"
fi

if [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
    echo "WARNING: SLACK_WEBHOOK_URL not set. Slack notifications will be disabled."
    echo "  export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/..."
fi

# Show cron entries to add
echo ""
echo "Add these to your crontab (crontab -e):"
echo ""
echo "GITHUB_TOKEN=\$GITHUB_TOKEN"
echo "SLACK_WEBHOOK_URL=\$SLACK_WEBHOOK_URL"
echo ""
echo "# Orchestrator: dispatch agents every 10 minutes for all configured projects"
echo "# (edit PROJECTS in $SCRIPT_DIR/run-all.sh first)"
echo "*/10 * * * * $SCRIPT_DIR/run-all.sh >> /var/log/playbook.log 2>&1"
echo ""
echo "# Morning / evening Slack summaries (one line per project)"
echo "0 8,20 * * * cd /path/to/your-project && PYTHONPATH=$SCRIPT_DIR python3 -c 'from summary import main; main()' >> /var/log/playbook.log 2>&1"
echo ""
echo "Setup complete."
