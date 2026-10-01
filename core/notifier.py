"""
core/notifier.py - Universal Notification Dispatcher (Discord, Telegram, WhatsApp)
"""

import json
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any
from . import config

def send_discord(message: str) -> bool:
    """Sends a message via Discord Webhook."""
    if not config.DISCORD_WEBHOOK_URL:
        return False
    try:
        payload = json.dumps({"content": message}).encode("utf-8")
        req = urllib.request.Request(
            config.DISCORD_WEBHOOK_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ValheimSentinel/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"[Notifier] Discord delivery error: {e}")
        return False

def send_telegram(message: str, parse_mode: str = "HTML") -> bool:
    """Sends a message via Telegram Bot API."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": parse_mode
        }).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Notifier] Telegram delivery error: {e}")
        return False

def send_whatsapp(message: str) -> bool:
    """Sends a message via HTTP WhatsApp Bridge (e.g., Baileys / Hermes)."""
    if not config.WHATSAPP_BRIDGE_URL or not config.WHATSAPP_GROUP_ID:
        return False
    try:
        payload = json.dumps({
            "chatId": config.WHATSAPP_GROUP_ID,
            "message": message
        }).encode("utf-8")
        req = urllib.request.Request(
            config.WHATSAPP_BRIDGE_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Notifier] WhatsApp delivery error: {e}")
        return False

def broadcast(message: str, telegram_html: Optional[str] = None) -> Dict[str, bool]:
    """
    Broadcasts message across all configured notification channels.
    Returns status dict {channel: success}.
    """
    results = {}
    if config.DISCORD_WEBHOOK_URL:
        results["discord"] = send_discord(message)
    if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
        tg_text = telegram_html if telegram_html else message
        results["telegram"] = send_telegram(tg_text)
    if config.WHATSAPP_BRIDGE_URL and config.WHATSAPP_GROUP_ID:
        results["whatsapp"] = send_whatsapp(message)
    return results
