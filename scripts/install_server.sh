#!/usr/bin/env bash
# scripts/install_server.sh - Automated SteamCMD installation for Valheim Dedicated Server
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# Load environment
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    source "$REPO_DIR/.env"
    set +a
fi

VALHEIM_SERVER_DIR="${VALHEIM_SERVER_DIR:-$REPO_DIR/valheim_server}"

echo "=========================================================="
echo "Installing Valheim Dedicated Server (AppID 896660)..."
echo "Target Directory: $VALHEIM_SERVER_DIR"
echo "=========================================================="

mkdir -p "$VALHEIM_SERVER_DIR"

if ! command -v steamcmd &> /dev/null; then
    echo "Error: steamcmd is not installed on this system."
    echo "Please install steamcmd (e.g., 'apt install steamcmd' or via your package manager)."
    exit 1
fi

steamcmd \
    +force_install_dir "$VALHEIM_SERVER_DIR" \
    +login anonymous \
    +app_update 896660 validate \
    +quit

chmod +x "$VALHEIM_SERVER_DIR/valheim_server.x86_64" 2>/dev/null || true
echo "Installation complete! Copy .env.example to .env and launch with 'bash scripts/start_server.sh'"
