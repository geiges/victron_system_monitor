#!/bin/bash
# Start the Victron System Monitor logger and REST API in a persistent tmux session.
# This script is idempotent: re-running it when the session already exists is a no-op.
#
# Usage:
#   ./deploy/start.sh [project_dir]
#
# Default project_dir is /data/python/victron_system_monitor (Venus OS path).
# Pass a different path when running from a different location, e.g. for local dev.

SESSION="victron"
PROJECT_DIR="${1:-/data/python/victron_system_monitor}"

if ! command -v tmux &>/dev/null; then
    echo "ERROR: tmux is not installed." >&2
    exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session '$SESSION' already running — nothing to do."
    exit 0
fi

# Create detached session with the data logger in the first window
tmux new-session -d -s "$SESSION" -n "logger" \
    "cd '$PROJECT_DIR' && uv run dbus_logger.py; read -p 'Press enter to close'"

# Add the REST API in a second window
tmux new-window -t "$SESSION" -n "api" \
    "cd '$PROJECT_DIR' && uv run rest_api_app.py; read -p 'Press enter to close'"

echo "Started tmux session '$SESSION' with windows: logger, api"
echo "  Attach with: tmux attach -t $SESSION"
