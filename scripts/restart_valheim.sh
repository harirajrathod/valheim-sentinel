#!/bin/bash
# /root/restart_valheim.sh - Safe restart script for Valheim server
# Scheduled via cron to run daily at 05:30 IST (00:00 UTC)

LOG_FILE="/root/valheim_server/current_run.log"

# Check if an update is pending or available during daily restart window
if [ -f "/root/valheim_server/.pending_update" ] || python3 /root/valheim_autopatch.py --check | grep -q "AVAILABLE"; then
    echo "[$(date)] Update detected during scheduled daily restart. Running valheim_autopatch.py..." >> $LOG_FILE
    python3 /root/valheim_autopatch.py --force >> /var/log/valheim_autopatch.log 2>&1
    exit 0
fi

# Check if players are currently online - skip restart if so
PLAYER_COUNT=$(python3 -c "from valheim_utils import get_valheim_player_count; print(get_valheim_player_count())" 2>/dev/null || echo "0")
PLAYER_COUNT=${PLAYER_COUNT:-0}

if [ "$PLAYER_COUNT" -gt 0 ] 2>/dev/null; then
    echo "[$(date)] Skipping restart: $PLAYER_COUNT players online" >> $LOG_FILE
    exit 0
fi

echo "[$(date)] Initiating safe Valheim restart (0 players online)..." >> $LOG_FILE

RESTART_OUT=$(/usr/bin/python3 /root/valheim_whatsapp_action.py --restart)
echo "[$(date)] Restart result: $RESTART_OUT" >> $LOG_FILE

IS_SUCCESS=$(echo "$RESTART_OUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('success', False))" 2>/dev/null)

if [ "$IS_SUCCESS" = "True" ]; then
    JOIN_CODE=$(echo "$RESTART_OUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('join_code', 'Unknown'))" 2>/dev/null)
    IS_CROSSPLAY=$(echo "$RESTART_OUT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('crossplay', True))" 2>/dev/null)
    echo "[$(date)] Valheim restart successful. Join code: $JOIN_CODE (Crossplay: $IS_CROSSPLAY)" >> $LOG_FILE
    # Synchronize world save and create restart snapshot on Google Drive
    /usr/bin/python3 /root/valheim_backup_drive.py --trigger restart --snapshot >> /var/log/valheim_drive_backup.log 2>&1 || true
    source /root/.env
    if [ "$IS_CROSSPLAY" = "False" ]; then
        TG_MSG="🛡️ <b>Valheim</b>: Scheduled daily restart completed. Mode: <b>Direct Steam Sockets</b> (<code>72.62.227.29:2458</code>)"
        WA_MSG="🛡️ *Valheim Server Restarted!* (Daily Scheduled Maintenance)\n\n• *Network Mode:* Direct Steam Sockets 🚀\n• *Direct IP:* \`72.62.227.29:2458\`\n• *Status:* Online & Ready! ⚔️"
    else
        TG_MSG="🛡️ <b>Valheim</b>: Scheduled daily restart completed. Join Code: <code>${JOIN_CODE}</code>"
        WA_MSG="🛡️ *Valheim Server Restarted!* (Daily Scheduled Maintenance)\n\n• *Join Code:* \`${JOIN_CODE}\`\n• *Port:* \`2458\`\n• *Status:* Online & Ready! ⚔️"
    fi
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
          --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
          --data-urlencode "text=${TG_MSG}" \
          --data-urlencode "parse_mode=HTML" > /dev/null
    fi
    # Notify WhatsApp Group
    curl -s -X POST "http://127.0.0.1:3000/send" \
      -H "Content-Type: application/json" \
      -d "{\"chatId\": \"120363426206773037@g.us\", \"message\": \"${WA_MSG}\"}" > /dev/null
else
    echo "[$(date)] Valheim restart FAILED." >> $LOG_FILE
fi
