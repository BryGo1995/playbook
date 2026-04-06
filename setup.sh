#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Agent Orchestrator Setup ==="

# Create runtime directories
mkdir -p ~/.agent-orchestrator/logs
echo "Created ~/.agent-orchestrator/logs"

# Install Python dependencies
cd "$SCRIPT_DIR"
python3 -m pip install -r requirements.txt
echo "Installed Python dependencies"

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
echo "# Orchestrator: dispatch agents every 10 minutes"
echo "*/10 * * * * cd $SCRIPT_DIR && python3 orchestrator.py >> /var/log/agent-orchestrator.log 2>&1"
echo ""
echo "# Morning summary: 8am"
echo "0 8 * * * cd $SCRIPT_DIR && python3 summary.py >> /var/log/agent-orchestrator.log 2>&1"
echo ""
echo "# Evening summary: 8pm"
echo "0 20 * * * cd $SCRIPT_DIR && python3 summary.py >> /var/log/agent-orchestrator.log 2>&1"
echo ""
echo "Setup complete."
