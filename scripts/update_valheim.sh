#!/bin/bash
# /root/update_valheim.sh - Safely updates the Valheim Dedicated Server via SteamCMD
# Preserves worlds, stops the running server, validates/updates game files, and restarts.

set -e

VALHEIM_DIR="/root/valheim_server"
WORLDS_DIR="/root/.config/unity3d/IronGate/Valheim/worlds_local"
BACKUP_DIR="/root/valheim_server_backups/pre_update_$(date +%Y%m%d_%H%M%S)"
TMUX_SESSION="valheim"
LOG_FILE="$VALHEIM_DIR/current_run.log"

echo "=== [$(date)] Starting Valheim Server Update ==="

# 1. Backup existing worlds
if [ -d "$WORLDS_DIR" ]; then
    echo "Backing up worlds to $BACKUP_DIR..."
    mkdir -p "$BACKUP_DIR"
    cp -r "$WORLDS_DIR" "$BACKUP_DIR/"
    echo "Backup completed successfully."
fi

# 2. Gracefully stop running server
if pgrep -f "valheim_server.x86_64" >/dev/null; then
    echo "Stopping active Valheim server gracefully..."
    touch "$VALHEIM_DIR/.stop_server"
    pkill -SIGINT -f "valheim_server.x86_64" 2>/dev/null || true
    for i in {1..15}; do
        if ! pgrep -f "valheim_server.x86_64" >/dev/null; then
            break
        fi
        sleep 1
    done
    tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
    # Force kill only if still hanging after 15s
    pkill -9 -f "valheim_server.x86_64" 2>/dev/null || true
    rm -f "$VALHEIM_DIR/.stop_server"
    sleep 2
    echo "Server stopped."
fi

# 3. Update via SteamCMD
echo "Running SteamCMD update for AppID 896660..."
/usr/games/steamcmd +force_install_dir "$VALHEIM_DIR" +login anonymous +app_update 896660 validate +quit

# Ensure execute permissions
chmod +x "$VALHEIM_DIR/valheim_server.x86_64" "$VALHEIM_DIR/start_valheim.sh" 2>/dev/null || true

# 4. Restart server in tmux
echo "Starting Valheim server in tmux session '$TMUX_SESSION'..."
tmux new-session -d -s "$TMUX_SESSION" "bash $VALHEIM_DIR/start_valheim.sh >> $LOG_FILE 2>&1"
sleep 5

if pgrep -f "valheim_server.x86_64" >/dev/null; then
    echo "=== [$(date)] Valheim Server update and restart SUCCESSFUL ==="
    source /root/.env 2>/dev/null || true
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
          --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
          --data-urlencode "text=🛡️ <b>Valheim Server</b> updated and restarted successfully." \
          --data-urlencode "parse_mode=HTML" > /dev/null || true
    fi
else
    echo "=== [$(date)] Valheim Server failed to start! Check $LOG_FILE ==="
    exit 1
fi
