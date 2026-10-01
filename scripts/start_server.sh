#!/usr/bin/env bash
# scripts/start_server.sh - Auto-recovering Valheim server runner
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
VALHEIM_SERVER_NAME="${VALHEIM_SERVER_NAME:-Valheim Dedicated}"
VALHEIM_WORLD_NAME="${VALHEIM_WORLD_NAME:-Dedicated}"
VALHEIM_SERVER_PASSWORD="${VALHEIM_SERVER_PASSWORD:-secret}"
VALHEIM_SERVER_PORT="${VALHEIM_SERVER_PORT:-2458}"
VALHEIM_PUBLIC="${VALHEIM_PUBLIC:-1}"
VALHEIM_CROSSPLAY="${VALHEIM_CROSSPLAY:-1}"

cd "$VALHEIM_SERVER_DIR"

export templdpath=$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=.:./linux64:$LD_LIBRARY_PATH
export SteamAppId=892970

mkdir -p "$HOME/.steam/sdk64/" 2>/dev/null || true
ln -sf "$VALHEIM_SERVER_DIR/linux64/steamclient.so" "$HOME/.steam/sdk64/steamclient.so" 2>/dev/null || true

STOP_FILE="$VALHEIM_SERVER_DIR/.stop_server"
rm -f "$STOP_FILE" 2>/dev/null || true

CROSSPLAY_FLAG=""
if [ "$VALHEIM_CROSSPLAY" = "1" ]; then
    CROSSPLAY_FLAG="-crossplay"
fi

while true; do
    if [ -f "$STOP_FILE" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stop signal detected ($STOP_FILE). Exiting server loop."
        rm -f "$STOP_FILE" 2>/dev/null || true
        break
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Valheim Dedicated Server [$VALHEIM_SERVER_NAME | $VALHEIM_WORLD_NAME]..."

    ./valheim_server.x86_64 \
        -name "$VALHEIM_SERVER_NAME" \
        -port "$VALHEIM_SERVER_PORT" \
        -world "$VALHEIM_WORLD_NAME" \
        -password "$VALHEIM_SERVER_PASSWORD" \
        -public "$VALHEIM_PUBLIC" \
        $CROSSPLAY_FLAG \
        -saveinterval 1800
    EXIT_CODE=$?

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Valheim process exited with code $EXIT_CODE."

    if [ -f "$STOP_FILE" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Clean shutdown requested. Exiting loop."
        rm -f "$STOP_FILE" 2>/dev/null || true
        break
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Crash or unexpected exit detected. Auto-restarting in 5 seconds..."
    sleep 5
done

export LD_LIBRARY_PATH=$templdpath
