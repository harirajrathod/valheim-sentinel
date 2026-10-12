#!/usr/bin/env python3
"""
/root/valheim_utils.py - Core Shared Utilities and Primitives for Valheim Scripts

Features:
- Centralized path constants & timezone definitions
- Safe dynamic string templating (SafeFormatDict) to prevent KeyError crashes
- Atomic, race-condition-free JSON file read & write
- Resilient WhatsApp and Telegram dispatchers with retry logic and timeouts
- Player name canonicalization
- Network copy sanitizer to prevent leaking raw IPs or socket exceptions
"""

import os
import sys
import re
import json
import tempfile
import urllib.request
import urllib.parse
import urllib.error
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple

# --- Central Paths & Configuration ---
VALHEIM_DIR = "/root/valheim_server"
WORLDS_DIR = "/root/.config/unity3d/IronGate/Valheim/worlds_local"
BACKUP_BASE = "/root/valheim_server_backups"
LOG_FILE = os.path.join(VALHEIM_DIR, "current_run.log")
ENV_FILE = "/root/.env"
TMUX_SESSION = "valheim"
APP_ID = "896660"            # Dedicated Server AppID
CLIENT_APP_ID = "892970"     # Valheim Game Client AppID

# WhatsApp & Messaging Configuration
VALHEIM_WHATSAPP_GROUP = "120363426206773037@g.us"
WHATSAPP_BRIDGE_URL = "http://127.0.0.1:3000/send"
IST = timezone(timedelta(hours=5, minutes=30))

# Known Player Name Normalization
KNOWN_PLAYERS = {
    "musashi": "Musashi(Musa Bhai)",
    "musashi(musa bhai)": "Musashi(Musa Bhai)",
    "musa bhai": "Musashi(Musa Bhai)",
    "dexter": "Dexter",
    "hilda": "Hilda",
    "faye": "Faye",
}


def load_env(env_path: str = ENV_FILE) -> Dict[str, str]:
    """Loads key-value pairs from an environment file safely."""
    env = {}
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip().strip('"').strip("'")
        except Exception as e:
            sys.stderr.write(f"[valheim_utils] Warning reading {env_path}: {e}\n")
    return env


# Preload environment
_ENV = load_env()
BOT_TOKEN = _ENV.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = _ENV.get("TELEGRAM_CHAT_ID")


# --- Safe Templating Primitives ---

class SafeFormatDict(dict):
    """
    Dictionary for format_map that returns an empty string for missing keys,
    preventing KeyError crashes on dynamic templates.
    """
    def __missing__(self, key: str) -> str:
        return ""


def safe_format_template(template: str, **kwargs: Any) -> str:
    """
    Safely interpolates kwargs into template string.
    Ensures missing placeholders are cleanly cleared and never crash with KeyError.
    """
    if not template:
        return ""
    try:
        formatted = template.format_map(SafeFormatDict(**kwargs))
    except Exception:
        formatted = template
        for k, v in kwargs.items():
            formatted = formatted.replace(f"{{{k}}}", str(v))
    # Strip any remaining unpopulated {placeholder} tags
    return re.sub(r'\{[a-zA-Z0-9_]+\}', '', formatted)


# --- Atomic JSON File Operations ---

def safe_load_json(file_path: str, default: Any = None) -> Any:
    """
    Safely reads JSON from disk. Returns default if file is missing, empty, or corrupted.
    """
    if default is None:
        default = {}
    if not os.path.exists(file_path):
        return default
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default
            return json.loads(content)
    except Exception as e:
        sys.stderr.write(f"[valheim_utils] Error parsing {file_path}: {e}\n")
        return default


def atomic_save_json(file_path: str, data: Any, indent: int = 2) -> bool:
    """
    Atomically writes data as JSON to file_path using a temporary file and replace,
    guaranteeing zero risk of partial file writes or 0-byte corruptions.
    """
    dir_name = os.path.dirname(os.path.abspath(file_path))
    try:
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp_vh_", dir=dir_name, text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        sys.stderr.write(f"[valheim_utils] Atomic save failed for {file_path}: {e}\n")
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False


# --- Messaging Dispatchers ---

def safe_urlopen(
    url_or_req: Any,
    allowed_schemes: Tuple[str, ...] = ("http", "https"),
    timeout: float = 10,
    **kwargs: Any
) -> Any:
    """
    Safely opens a URL or urllib.request.Request, validating that the scheme
    is in allowed_schemes (defaults to http/https). Prevents file://, ftp://, or
    arbitrary scheme injection (CWE-939 / CWE-22).
    """
    url = url_or_req.full_url if isinstance(url_or_req, urllib.request.Request) else str(url_or_req)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError(f"Disallowed URL scheme '{parsed.scheme}'; expected one of {allowed_schemes}")
    return urllib.request.urlopen(url_or_req, timeout=timeout, **kwargs)  # nosec B310


def safe_send_whatsapp(
    text: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP,
    bridge_url: str = WHATSAPP_BRIDGE_URL,
    timeout: int = 10,
    retries: int = 2
) -> bool:
    """
    Dispatches a WhatsApp message through the local Baileys bridge.
    Guarantees no unhandled exceptions and includes retry attempts.
    """
    if not text or not text.strip():
        return False
    payload = json.dumps({"chatId": chat_id, "message": text}).encode("utf-8")
    req = urllib.request.Request(
        bridge_url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    for attempt in range(1, retries + 1):
        try:
            with safe_urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception as e:
            if attempt >= retries:
                sys.stderr.write(f"[valheim_utils] WhatsApp alert error: {e}\n")
    return False


def safe_send_telegram(
    html_text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    timeout: int = 10
) -> bool:
    """
    Sends an HTML message to the configured Telegram bot and chat.
    Fails safely without raising exceptions.
    """
    tok = token or BOT_TOKEN
    cid = chat_id or CHAT_ID
    if not tok or not cid:
        return False
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": cid,
        "text": html_text,
        "parse_mode": "HTML"
    }).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data)
        with safe_urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        sys.stderr.write(f"[valheim_utils] Telegram send error: {e}\n")
        return False


# --- Name Normalization & Content Sanitation ---

def format_player_name(name: Optional[str]) -> str:
    """
    Standardizes player names and formats clan aliases.
    """
    if not name:
        return ""
    stripped = name.strip()
    lower = stripped.lower()
    return KNOWN_PLAYERS.get(lower, stripped)


def sanitize_network_copy(text: str) -> str:
    """
    Strips raw IP addresses and technical socket errors from text,
    replacing them with friendly error copy.
    """
    if not text:
        return ""
    # Hide VPS or Azure public IP addresses
    sanitized = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', 'Server Host', text)
    sanitized = re.sub(r'ConnectionRefusedError.*', 'Connection is down', sanitized)
    sanitized = re.sub(r'socket\.error.*', 'Network issue', sanitized)
    sanitized = re.sub(r'URLError:.*', 'Network unavailable', sanitized)
    return sanitized

import ctypes

def get_stable_hash(s):
    h1 = ctypes.c_int32(5381).value
    h2 = ctypes.c_int32(5381).value
    for i in range(0, len(s), 2):
        h1 = ctypes.c_int32(((h1 << 5) + h1) ^ ord(s[i])).value
        if i + 1 < len(s):
            h2 = ctypes.c_int32(((h2 << 5) + h2) ^ ord(s[i+1])).value
    return ctypes.c_int32(h1 + ctypes.c_int32(h2 * 1566083941).value).value

import glob

def get_active_chunk_files():
    r"""
    Returns deduplicated list of active chunk file paths.
    Matches r'^(.*__\d+)_(\d+)\.chunk$' to select the highest version
    for each chunk prefix during live save transitions.
    """
    raw_chunks = glob.glob('/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/*.chunk')
    chunks_by_prefix = {}
    for c in raw_chunks:
        m = re.match(r'^(.*__\d+)_(\d+)\.chunk$', c)
        if m:
            prefix = m.group(1)
            version = int(m.group(2))
            if prefix not in chunks_by_prefix or version > chunks_by_prefix[prefix][1]:
                chunks_by_prefix[prefix] = (c, version)
    return [v[0] for v in chunks_by_prefix.values()]


def is_valheim_running() -> bool:
    """Checks if the Valheim dedicated server process is active."""
    try:
        res = subprocess.run(["pgrep", "-f", "valheim_server.x86_64"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except Exception:
        return False


def get_valheim_player_count(log_file: str = LOG_FILE) -> int:
    """
    Returns the real-time active player count on the Valheim server.
    Scans the server log backwards for the latest 'now X player(s)'
    or 'Connections X ZDOS' status line.
    Returns 0 if server is offline or no players connected.
    """
    if not is_valheim_running():
        return 0
    if not os.path.exists(log_file):
        return 0
    try:
        with open(log_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            read_size = min(size, 131072)
            f.seek(-read_size, os.SEEK_END)
            chunk = f.read().decode("latin1", errors="ignore")
            lines = chunk.splitlines()
            for line in reversed(lines):
                m_count = re.search(r'now (\d+) player\(s\)', line)
                if m_count:
                    return int(m_count.group(1))
                m_conn = re.search(r'Connections (\d+) ZDOS', line)
                if m_conn:
                    return int(m_conn.group(1))

            if size > 131072:
                f.seek(0)
                full_chunk = f.read().decode("latin1", errors="ignore")
                for line in reversed(full_chunk.splitlines()):
                    m_count = re.search(r'now (\d+) player\(s\)', line)
                    if m_count:
                        return int(m_count.group(1))
                    m_conn = re.search(r'Connections (\d+) ZDOS', line)
                    if m_conn:
                        return int(m_conn.group(1))
    except Exception:
        pass
    return 0

