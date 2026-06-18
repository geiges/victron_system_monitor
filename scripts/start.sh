#!/bin/bash
# Start the Victron System Monitor components in a persistent tmux session.
#
# Usage:
#   ./scripts/start.sh [--restart] [project_dir]
#
#   --restart   git pull, kill the existing session, then start fresh.
#               Without this flag the script is a no-op if the session exists.
#
# Default project_dir is /data/python/victron_system_monitor (Venus OS path).

SESSION="victron"
RESTART=0

# Parse flags
for arg in "$@"; do
    case "$arg" in
        --restart) RESTART=1 ;;
        -*) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done
# Remaining positional arg is the project dir
PROJECT_DIR="$(for arg in "$@"; do [[ "$arg" != --* ]] && echo "$arg" && break; done)"
PROJECT_DIR="${PROJECT_DIR:-/data/python/victron_system_monitor}"

if ! command -v tmux &>/dev/null; then
    echo "ERROR: tmux is not installed." >&2
    exit 1
fi

if [ "$RESTART" -eq 1 ]; then
    echo "--- git pull ---"
    git -C "$PROJECT_DIR" pull || { echo "ERROR: git pull failed." >&2; exit 1; }

    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "Killing session '$SESSION'..."
        tmux kill-session -t "$SESSION"
    fi
else
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "Session '$SESSION' already running — nothing to do."
        exit 0
    fi
fi

# Create detached session with the data logger in the first window
tmux new-session -d -s "$SESSION" -n "logger" \
    "cd '$PROJECT_DIR' && uv run dbus_logger.py; read -p 'Press enter to close'"

# Add the REST API in a second window
tmux new-window -t "$SESSION" -n "api" \
    "cd '$PROJECT_DIR' && uv run rest_api_app.py; read -p 'Press enter to close'"

# Add the auxiliary logger in a third window
tmux new-window -t "$SESSION" -n "aux_logger" \
    "cd '$PROJECT_DIR' && uv run aux_logger.py; read -p 'Press enter to close'"

# Add the battery control runner in a fourth window
tmux new-window -t "$SESSION" -n "control" \
    "cd '$PROJECT_DIR' && uv run control_runner.py; read -p 'Press enter to close'"

echo "Started tmux session '$SESSION' with windows: logger, api, aux_logger, control"
echo "  Attach with: tmux attach -t $SESSION"
