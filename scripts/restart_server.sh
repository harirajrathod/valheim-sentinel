#!/usr/bin/env bash
# scripts/restart_server.sh - Safe shutdown and restart script
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Requesting safe server restart..."
python3 -m core.autopatch --restart
