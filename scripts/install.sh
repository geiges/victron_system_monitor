#!/bin/bash
# Install the startup hook on Venus OS so the logger and API start at boot.
#
# Venus OS persists /data/rc.local across firmware updates.
# This script appends a launch line to /data/rc.local (creating it if absent).
#
# Usage (run on the Venus OS device):
#   ./deploy/install.sh [project_dir]

RC_LOCAL="/data/rc.local"
PROJECT_DIR="${1:-/data/python/victron_system_monitor}"
LAUNCH_CMD="$PROJECT_DIR/deploy/start.sh '$PROJECT_DIR'"
MARKER="# victron_system_monitor startup"

if grep -qF "$MARKER" "$RC_LOCAL" 2>/dev/null; then
    echo "Startup hook already present in $RC_LOCAL — nothing to do."
    exit 0
fi

# Create rc.local with correct shebang if it does not exist yet
if [ ! -f "$RC_LOCAL" ]; then
    echo "#!/bin/bash" > "$RC_LOCAL"
    chmod +x "$RC_LOCAL"
    echo "Created $RC_LOCAL"
fi

cat >> "$RC_LOCAL" <<EOF

$MARKER
$LAUNCH_CMD
EOF

echo "Installed startup hook in $RC_LOCAL"
echo "The logger and API will start automatically on next boot."
echo "To start now without rebooting, run:"
echo "  $LAUNCH_CMD"
