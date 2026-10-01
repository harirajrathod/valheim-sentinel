"""
core/config.py - Unified Configuration & Environment Management for Valheim Sentinel
"""

import os
import sys
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

class SafeFormatDict(dict):
    """Guards against string formatting crashes on missing template keys."""
    def __missing__(self, key: str) -> str:
        return ""

def load_dotenv(env_path: Optional[str] = None) -> Dict[str, str]:
    """Lightweight built-in .env parser without external dependencies."""
    loaded = {}
    if not env_path:
        # Search current working dir, repo root, or script dir
        candidates = [
            os.path.join(os.getcwd(), ".env"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        ]
        for c in candidates:
            if os.path.exists(c):
                env_path = c
                break

    if env_path and os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'").strip('"')
                    # Do not override existing environment variables
                    if key not in os.environ:
                        os.environ[key] = val
                    loaded[key] = val
        except Exception:
            pass
    return loaded

# Load .env on module import
load_dotenv()

# --- Server & Filesystem Paths ---
DEFAULT_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VALHEIM_SERVER_DIR = os.environ.get("VALHEIM_SERVER_DIR", os.path.join(DEFAULT_BASE, "valheim_server"))
VALHEIM_WORLDS_DIR = os.environ.get(
    "VALHEIM_WORLDS_DIR",
    os.path.expanduser("~/.config/unity3d/IronGate/Valheim/worlds_local")
)
VALHEIM_BACKUP_DIR = os.environ.get("VALHEIM_BACKUP_DIR", os.path.join(DEFAULT_BASE, "backups"))
VALHEIM_LOG_FILE = os.environ.get("VALHEIM_LOG_FILE", os.path.join(VALHEIM_SERVER_DIR, "current_run.log"))

# --- Server Lifecycle & Game Properties ---
VALHEIM_SERVER_NAME = os.environ.get("VALHEIM_SERVER_NAME", "Valheim Dedicated")
VALHEIM_WORLD_NAME = os.environ.get("VALHEIM_WORLD_NAME", "Dedicated")
VALHEIM_SERVER_PASSWORD = os.environ.get("VALHEIM_SERVER_PASSWORD", "secret")
VALHEIM_SERVER_PORT = int(os.environ.get("VALHEIM_SERVER_PORT", "2458"))
VALHEIM_PUBLIC = int(os.environ.get("VALHEIM_PUBLIC", "1"))
VALHEIM_CROSSPLAY = int(os.environ.get("VALHEIM_CROSSPLAY", "1"))
TMUX_SESSION = os.environ.get("VALHEIM_TMUX_SESSION", "valheim")

# --- Timezone Configuration ---
def get_timezone() -> timezone:
    try:
        offset_hours = float(os.environ.get("TIMEZONE_OFFSET_HOURS", "0.0"))
        return timezone(timedelta(hours=offset_hours))
    except Exception:
        return timezone.utc

CURRENT_TZ = get_timezone()

# --- Notification Endpoints ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
WHATSAPP_BRIDGE_URL = os.environ.get("WHATSAPP_BRIDGE_URL", "").strip()
WHATSAPP_GROUP_ID = os.environ.get("WHATSAPP_GROUP_ID", "").strip()

# --- AI Skald Engine ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash").strip()
