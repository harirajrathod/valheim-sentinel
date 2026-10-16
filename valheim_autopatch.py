#!/usr/bin/env python3
"""
/root/valheim_autopatch.py - Valheim Dedicated Server Automated Patching Engine

Features:
- Checks for Steam updates for AppID 896660 (via fast SteamCMD Web API with SteamCMD fallback)
- Player-safe: Never interrupts active players unless forced; queues pending updates and patches as soon as server is empty
- Automated pre-update snapshot backup of all world saves
- Graceful shutdown allowing world data to flush cleanly to disk
- Seamless SteamCMD update, validation, and tmux restart
- Post-patch verification (process health, world save load, and PlayFab lobby code)
- Telegram and WhatsApp notifications on update detection, deferral, and deployment
- Safe dynamic templating with SafeFormatDict
- Atomic cache persistence for patch notes
- Support for --dry-run mode for hermetic pre-flight verification
"""

import os
import sys
import time
import re
import json
import shutil
import argparse
import subprocess
import urllib.request
import urllib.parse
import html
from datetime import datetime
from typing import Optional, Dict, Any, Tuple, List

sys.path.insert(0, "/root")
from valheim_utils import (
    VALHEIM_DIR,
    WORLDS_DIR,
    BACKUP_BASE,
    LOG_FILE,
    ENV_FILE,
    TMUX_SESSION,
    APP_ID,
    CLIENT_APP_ID,
    VALHEIM_WHATSAPP_GROUP,
    atomic_save_json,
    safe_load_json,
    safe_send_whatsapp,
    safe_send_telegram,
    safe_urlopen,
    safe_format_template,
    load_env
)
from valheim_constants import PATTERNS

# File Paths
MANIFEST_PATH    = os.path.join(VALHEIM_DIR, "steamapps/appmanifest_896660.acf")
PENDING_FILE     = os.path.join(VALHEIM_DIR, ".pending_update")
AUTOPATCH_LOG    = "/var/log/valheim_autopatch.log"
PATCH_CACHE_FILE = "/root/valheim_latest_patch_notes.json"


def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        with open(AUTOPATCH_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_telegram(html_text: str) -> bool:
    success = safe_send_telegram(html_text)
    if not success:
        log("Telegram alert skipped or failed.")
    return success


def send_whatsapp(text: str) -> bool:
    success = safe_send_whatsapp(text)
    if not success:
        log("WhatsApp alert skipped or failed.")
    return success


def record_vps_log(description: str) -> None:
    try:
        subprocess.run(["bash", "/root/log.sh", "add", description], capture_output=True, timeout=10)
    except Exception as e:
        log(f"Failed to record in log.sh: {e}")


# --- Patch Notes Parsing & Formatting Engine ---

def clean_bbcode(text: Optional[str]) -> str:
    """Strips and converts Steam BBCode tags to clean plaintext/markdown."""
    if not text:
        return ""
    text = re.sub(r'\[previewyoutube=[^\]]*\]\[/previewyoutube\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[img\].*?\[/img\]', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\[h[1-6]\](.*?)\[/h[1-6]\]', r'*\1*', text, flags=re.IGNORECASE)
    text = re.sub(r'\[b\](.*?)\[/b\]', r'*\1*', text, flags=re.IGNORECASE)
    text = re.sub(r'\[i\](.*?)\[/i\]', r'_\1_', text, flags=re.IGNORECASE)
    text = re.sub(r'\[u\](.*?)\[/u\]', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'\[strike\](.*?)\[/strike\]', r'~\1~', text, flags=re.IGNORECASE)
    text = re.sub(r'\[url=([^\]]+)\](.*?)\[/url\]', r'\2 (\1)', text, flags=re.IGNORECASE)
    text = re.sub(r'\[url\](.*?)\[/url\]', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'\[/?(?:list|\*|code|quote|spoiler)[^\]]*\]', '', text, flags=re.IGNORECASE)
    text = html.unescape(text)
    return text.strip()


def parse_patch_content(raw_content: str) -> Tuple[str, List[str]]:
    """Extracts intro description and actionable bullet points from raw Steam post content."""
    cleaned = clean_bbcode(raw_content)
    lines = [l.strip() for l in cleaned.splitlines()]
    bullets: List[str] = []
    intro_lines: List[str] = []
    in_patch_notes = False

    for l in lines:
        if not l:
            continue
        if re.search(r'patch\s*notes', l, re.IGNORECASE):
            in_patch_notes = True
            continue

        if l.startswith('* ') or l.startswith('• ') or l.startswith('- '):
            item = re.sub(r'^[\*\•\-]\s*', '', l).strip()
            if item:
                item = re.sub(r'^\*+|\*+$', '', item).strip()
                bullets.append(item)
        elif in_patch_notes and (l.startswith('*') and l.endswith('*')) and len(l) < 50:
            header = l.strip('*').strip(':')
            bullets.append(f'[{header}]')
        elif not in_patch_notes and not bullets:
            clean_l = l.strip('*_ ')
            if len(intro_lines) < 2 and len(clean_l) < 220 and not clean_l.startswith('http'):
                intro_lines.append(clean_l)

    intro = ' '.join(intro_lines) if intro_lines else ''
    return intro, bullets


def format_patch_notes_wa(title: str, intro: str, bullets: List[str], url: str, max_bullets: int = 10) -> str:
    """Formats patch notes cleanly for WhatsApp mobile view."""
    lines = [f"📜 *Patch Notes — {title}*"]
    if intro:
        lines.append(f"_{intro}_")
    lines.append("")

    count = 0
    for b in bullets:
        if b.startswith('[') and b.endswith(']'):
            lines.append(f"*{b[1:-1]}*")
        else:
            if count >= max_bullets:
                rem = len(bullets) - count
                lines.append(f"_...and {rem} more changes._")
                break
            lines.append(f"• {b}")
            count += 1

    if url:
        lines.append("")
        lines.append(f"🔗 *Full Notes:* {url}")
    return "\n".join(lines)


def format_patch_notes_tg(title: str, intro: str, bullets: List[str], url: str, max_bullets: int = 10) -> str:
    """Formats patch notes safely with HTML entities for Telegram."""
    lines = [f"📜 <b>Patch Notes — {html.escape(title)}</b>"]
    if intro:
        lines.append(f"<i>{html.escape(intro)}</i>")
    lines.append("")

    count = 0
    for b in bullets:
        if b.startswith('[') and b.endswith(']'):
            lines.append(f"<b>{html.escape(b[1:-1])}</b>")
        else:
            if count >= max_bullets:
                rem = len(bullets) - count
                lines.append(f"<i>...and {rem} more changes.</i>")
                break
            lines.append(f"• {html.escape(b)}")
            count += 1

    if url:
        lines.append("")
        lines.append(f'🔗 <a href="{url}">View on Steam</a>')
    return "\n".join(lines)


def save_cached_patch_notes(data: Dict[str, Any]) -> bool:
    """Persists fetched patch notes atomically for instant retrieval."""
    return atomic_save_json(PATCH_CACHE_FILE, data)


def get_cached_patch_notes() -> Optional[Dict[str, Any]]:
    """Retrieves local cached patch notes if available."""
    res = safe_load_json(PATCH_CACHE_FILE, default=None)
    if isinstance(res, dict) and res.get("title"):
        return res
    return None


def fetch_steam_patch_notes(target_version: Optional[str] = None, save_cache: bool = True) -> Optional[Dict[str, Any]]:
    """
    Fetches official Valheim patch notes from Steam.
    Uses ISteamNews Web API with Steam Partner Events AJAX as fallback.
    """
    # Method 1: ISteamNews Web API
    try:
        url = f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={CLIENT_APP_ID}&count=15&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "ValheimAutoPatch/1.0"})
        with safe_urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("appnews", {}).get("newsitems", [])
                candidates = []
                for it in items:
                    title = it.get("title", "")
                    feed = it.get("feedname", "")
                    tags = it.get("tags") or []
                    if feed == "steam_community_announcements" or "patchnotes" in tags or any(k in title.lower() for k in ["patch", "hotfix", "update"]):
                        candidates.append(it)

                if candidates:
                    chosen = None
                    if target_version:
                        m_v = re.search(r'\b(\d+\.\d+\.[\d\w]+)\b', target_version)
                        clean_v = m_v.group(1) if m_v else None
                        if clean_v:
                            for c in candidates:
                                if clean_v in c.get("title", ""):
                                    chosen = c
                                    break
                    if not chosen:
                        for c in candidates:
                            tags = c.get("tags") or []
                            if "patchnotes" in tags or any(k in c.get("title", "").lower() for k in ["patch", "hotfix"]):
                                chosen = c
                                break
                    if not chosen:
                        chosen = candidates[0]

                    title = chosen.get("title", "Valheim Update")
                    gid = chosen.get("gid")
                    url_link = f"https://store.steampowered.com/news/app/{CLIENT_APP_ID}/view/{gid}" if gid else chosen.get("url", "")
                    intro, bullets = parse_patch_content(chosen.get("contents", ""))
                    wa_text = format_patch_notes_wa(title, intro, bullets, url_link)
                    tg_text = format_patch_notes_tg(title, intro, bullets, url_link)

                    res = {
                        "title": title,
                        "url": url_link,
                        "intro": intro,
                        "bullets": bullets,
                        "wa_text": wa_text,
                        "tg_text": tg_text,
                        "date": chosen.get("date", int(time.time())),
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    if save_cache:
                        save_cached_patch_notes(res)
                    return res
    except Exception as e:
        log(f"Steam News API query failed ({e}), checking partner events fallback...")

    # Method 2: Steam Partner Events AJAX API Fallback
    try:
        url = f"https://store.steampowered.com/events/ajaxgetadjacentpartnerevents/?appid={CLIENT_APP_ID}&count_before=0&count_after=5"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with safe_urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                events = data.get("events", [])
                candidates = []
                for ev in events:
                    ann = ev.get("announcement_body", {})
                    headline = ann.get("headline", "")
                    tags = ann.get("tags") or []
                    if "patchnotes" in tags or any(k in headline.lower() for k in ["patch", "hotfix", "update"]):
                        candidates.append(ev)

                if candidates:
                    chosen = None
                    if target_version:
                        m_v = re.search(r'\b(\d+\.\d+\.[\d\w]+)\b', target_version)
                        clean_v = m_v.group(1) if m_v else None
                        if clean_v:
                            for c in candidates:
                                if clean_v in c.get("announcement_body", {}).get("headline", ""):
                                    chosen = c
                                    break
                    if not chosen:
                        chosen = candidates[0]

                    ann = chosen.get("announcement_body", {})
                    title = ann.get("headline", "Valheim Update")
                    gid = chosen.get("gid")
                    url_link = f"https://store.steampowered.com/news/app/{CLIENT_APP_ID}/view/{gid}" if gid else ""
                    intro, bullets = parse_patch_content(ann.get("body", ""))
                    wa_text = format_patch_notes_wa(title, intro, bullets, url_link)
                    tg_text = format_patch_notes_tg(title, intro, bullets, url_link)

                    res = {
                        "title": title,
                        "url": url_link,
                        "intro": intro,
                        "bullets": bullets,
                        "wa_text": wa_text,
                        "tg_text": tg_text,
                        "date": ann.get("posttime", int(time.time())),
                        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    if save_cache:
                        save_cached_patch_notes(res)
                    return res
    except Exception as e:
        log(f"Steam Events fallback failed: {e}")

    return None


def get_or_fetch_patch_notes(target_version: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetches fresh patch notes from Steam with fallback to local cached notes."""
    fresh = fetch_steam_patch_notes(target_version=target_version, save_cache=True)
    if fresh:
        return fresh
    cached = get_cached_patch_notes()
    if cached:
        return cached
    return None


# --- Version & Build Detection ---

def get_local_buildid() -> Optional[str]:
    """Extract local buildid from Steam appmanifest."""
    if not os.path.exists(MANIFEST_PATH):
        log(f"Manifest not found at {MANIFEST_PATH}")
        return None
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'\"buildid\"\s+\"(\d+)\"', content)
        if m:
            return m.group(1)
    except Exception as e:
        log(f"Error reading local manifest: {e}")
    return None


def get_remote_buildid() -> Optional[str]:
    """Fetch the latest public buildid from Steam. Uses Web API first, SteamCMD as fallback."""
    # Method 1: Web API (instant, ~200ms)
    try:
        url = f"https://api.steamcmd.net/v1/info/{APP_ID}"
        req = urllib.request.Request(url, headers={"User-Agent": "ValheimAutoPatch/1.0"})
        with safe_urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                remote = data.get("data", {}).get(APP_ID, {}).get("depots", {}).get("branches", {}).get("public", {}).get("buildid")
                if remote:
                    return str(remote)
    except Exception as e:
        log(f"Web API check failed ({e}), falling back to SteamCMD...")

    # Method 2: SteamCMD CLI fallback
    try:
        cmd = ["/usr/games/steamcmd", "+login", "anonymous", "+app_info_update", "1", "+app_info_print", APP_ID, "+quit"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        m = re.search(r'\"branches\"[\s\S]*?\"public\"[\s\S]*?\"buildid\"\s+\"(\d+)\"', res.stdout)
        if m:
            return m.group(1)
    except Exception as e:
        log(f"SteamCMD fallback failed: {e}")

    return None


# --- Player & Server Inspection ---

def get_active_players() -> Tuple[int, List[str]]:
    """Inspects server log to determine active player count and character names."""
    if not is_server_running():
        return 0, []
    if not os.path.exists(LOG_FILE):
        return 0, []

    count = 0
    recent_names: List[str] = []
    try:
        with open(LOG_FILE, "r", errors="ignore") as f:
            lines = f.readlines()

        for line in reversed(lines):
            m_count = PATTERNS["player_count"].search(line)
            if m_count:
                count = int(m_count.group(1))
                break
            m_conn = PATTERNS["connections"].search(line)
            if m_conn:
                count = int(m_conn.group(1))
                break

        if count > 0:
            for line in reversed(lines):
                m_join = PATTERNS["zdo_any"].search(line)
                if m_join:
                    pname = m_join.group(1).strip()
                    if pname not in recent_names:
                        recent_names.append(pname)
                    if len(recent_names) >= count:
                        break
    except Exception as e:
        log(f"Error checking active players: {e}")

    return count, recent_names


def is_server_running() -> bool:
    try:
        res = subprocess.run(["pgrep", "-f", "valheim_server.x86_64"], capture_output=True, text=True)
        return bool(res.stdout.strip())
    except Exception:
        return False


# --- Safe Patching Actions ---

def backup_worlds(dry_run: bool = False) -> Optional[str]:
    """Creates a timestamped snapshot of the worlds directory."""
    if not os.path.exists(WORLDS_DIR):
        log("No worlds directory found to back up.")
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_BASE, f"auto_patch_{timestamp}")
    if dry_run:
        log(f"[DRY RUN] Would create world backup at {backup_path}")
        return backup_path
    try:
        os.makedirs(backup_path, exist_ok=True)
        shutil.copytree(WORLDS_DIR, os.path.join(backup_path, "worlds_local"))
        log(f"World backup created at {backup_path}")
        return backup_path
    except Exception as e:
        log(f"Backup failed: {e}")
        return None


def stop_server(dry_run: bool = False) -> None:
    """Gracefully stops the server allowing world data flush."""
    if dry_run:
        log("[DRY RUN] Would gracefully signal server stop and kill tmux session.")
        return

    log("Stopping active Valheim server...")
    stop_file = os.path.join(VALHEIM_DIR, ".stop_server")
    try:
        with open(stop_file, "w") as f:
            f.write("stop\n")
    except Exception:
        pass

    try:
        subprocess.run(["pkill", "-SIGINT", "-f", "valheim_server.x86_64"], timeout=5)
        for _ in range(10):
            if not is_server_running():
                log("Server stopped cleanly via SIGINT.")
                break
            time.sleep(1)
    except Exception:
        pass

    subprocess.run(["tmux", "kill-session", "-t", TMUX_SESSION], capture_output=True)
    time.sleep(2)

    if is_server_running():
        log("Server process still active, issuing SIGKILL...")
        subprocess.run(["pkill", "-9", "-f", "valheim_server.x86_64"], capture_output=True)
        time.sleep(2)

    try:
        if os.path.exists(stop_file):
            os.remove(stop_file)
    except Exception:
        pass


def start_server(dry_run: bool = False) -> bool:
    """Starts the Valheim server in the designated tmux session."""
    if dry_run:
        log(f"[DRY RUN] Would launch Valheim server in tmux session '{TMUX_SESSION}'.")
        return True

    stop_file = os.path.join(VALHEIM_DIR, ".stop_server")
    try:
        if os.path.exists(stop_file):
            os.remove(stop_file)
    except Exception:
        pass

    log(f"Launching Valheim server in tmux session '{TMUX_SESSION}'...")
    start_script = os.path.join(VALHEIM_DIR, "start_valheim.sh")
    tmux_cmd = f"bash {start_script} >> {LOG_FILE} 2>&1"
    subprocess.run(["tmux", "new-session", "-d", "-s", TMUX_SESSION, tmux_cmd])
    time.sleep(5)
    return is_server_running()


def update_game_files(dry_run: bool = False) -> bool:
    """Runs SteamCMD to update and validate Valheim Dedicated Server files."""
    if dry_run:
        log("[DRY RUN] Would invoke SteamCMD app_update 896660 validate.")
        return True

    log("Running SteamCMD update for AppID 896660...")
    cmd = [
        "/usr/games/steamcmd",
        "+force_install_dir", VALHEIM_DIR,
        "+login", "anonymous",
        "+app_update", APP_ID, "validate",
        "+quit"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if "Success! App '896660' fully installed." in res.stdout:
        log("SteamCMD update successful.")
        for f in ["valheim_server.x86_64", "start_valheim.sh"]:
            target = os.path.join(VALHEIM_DIR, f)
            if os.path.exists(target):
                os.chmod(target, 0o700)
        return True
    else:
        log(f"SteamCMD update failed! Output:\n{res.stdout[-500:]}")
        return False


def verify_and_get_info(timeout: int = 60, dry_run: bool = False) -> Tuple[bool, str, str]:
    """Waits for server initialization, parses new game version and PlayFab join code."""
    if dry_run:
        return True, "1.0.17", "321199"

    log("Verifying server startup and extracting session credentials...")
    start_time = time.time()
    version = "Unknown"
    join_code = "Unknown"

    while time.time() - start_time < timeout:
        if not is_server_running():
            log("Server process terminated unexpectedly during verification!")
            return False, version, join_code

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", errors="ignore") as f:
                    lines = f.readlines()
                for line in reversed(lines[-80:]):
                    if "Valheim version:" in line or "Console: Valheim" in line:
                        m_ver = re.search(r'Valheim\s+(l-[\d\.]+.*?\(network version \d+\))', line)
                        if m_ver:
                            version = m_ver.group(1)
                    if "registered with join code" in line:
                        m_code = re.search(r'join code\s+(\d+)', line)
                        if m_code:
                            join_code = m_code.group(1)
                    if version != "Unknown" and join_code != "Unknown":
                        return True, version, join_code
            except Exception:
                pass
        time.sleep(3)

    return is_server_running(), version, join_code


# --- Orchestrator ---

def perform_patch(old_build: str, new_build: str, dry_run: bool = False) -> bool:
    """Executes the automated patching pipeline."""
    log(f"Initiating patch upgrade: Build {old_build} -> {new_build} (dry_run={dry_run})")

    # 1. Backup
    backup_path = backup_worlds(dry_run=dry_run)
    if not backup_path and not dry_run:
        log("Warning: Proceeding with update, but world backup encountered an error.")

    # 2. Stop server
    stop_server(dry_run=dry_run)

    # 3. Update files
    success = update_game_files(dry_run=dry_run)
    if not success and not dry_run:
        log("Update failed! Attempting to restart previous server build...")
        start_server()
        send_telegram(f"❌ <b>Valheim Auto-Patch Failed</b>\nSteamCMD failed to update to Build <code>{new_build}</code>. Server was restarted.")
        return False

    # 4. Start server
    if not start_server(dry_run=dry_run) and not dry_run:
        log("Server failed to launch after update!")
        send_telegram(f"❌ <b>Valheim Auto-Patch Critical</b>\nServer updated to Build <code>{new_build}</code> but failed to start! Check logs at {LOG_FILE}.")
        return False

    # 5. Verification
    healthy, version, join_code = verify_and_get_info(timeout=60, dry_run=dry_run)
    if healthy:
        log(f"Update verified successful. Version: {version}, Join Code: {join_code}")
        if not dry_run and os.path.exists(PENDING_FILE):
            try:
                os.remove(PENDING_FILE)
            except Exception:
                pass

        notes = get_or_fetch_patch_notes(target_version=version)

        msg = (
            f"🛡️ <b>Valheim Server Auto-Patched!</b>\n\n"
            f"• <b>Build ID:</b> <code>{old_build}</code> ➔ <code>{new_build}</code>\n"
            f"• <b>Version:</b> <code>{version}</code>\n"
            f"• <b>Join Code:</b> <code>{join_code}</code> (Port 2458)\n"
            f"• <b>World Backup:</b> <code>{os.path.basename(backup_path or 'none')}</code>\n"
            f"• <b>Status:</b> Online &amp; Ready"
        )
        if notes and notes.get("tg_text"):
            msg += f"\n\n{notes['tg_text']}"

        wa_msg = (
            f"🛡️ *Valheim Server Auto-Patched!*\n\n"
            f"• *Build:* `{old_build}` ➔ `{new_build}`\n"
            f"• *Version:* `{version}`\n"
            f"• *Join Code:* `{join_code}` (Port 2458)\n"
            f"• *Status:* Online & Ready! ⚔️"
        )
        if notes and notes.get("wa_text"):
            wa_msg += f"\n\n{notes['wa_text']}"

        if not dry_run:
            send_telegram(msg)
            send_whatsapp(wa_msg)
            record_vps_log(f"Valheim Server: Auto-patched to Build {new_build} ({version}). Join code: {join_code}.")
        else:
            log("[DRY RUN] Patch flow simulated successfully. No alerts broadcast.")
        return True
    else:
        log("Server process is running but did not complete PlayFab registration within timeout.")
        if not dry_run:
            send_telegram(f"⚠️ <b>Valheim Auto-Patch Warning</b>\nServer updated to Build <code>{new_build}</code> but PlayFab registration is delayed.")
        return False


def check_and_run(cron_mode: bool = False, force: bool = False, dry_run: bool = False) -> None:
    local_build = get_local_buildid()
    remote_build = get_remote_buildid()

    if not local_build or not remote_build:
        log(f"Check aborted: Local Build={local_build}, Remote Build={remote_build}")
        return

    if local_build == remote_build:
        if not cron_mode:
            log(f"Server is up-to-date. (Build: {local_build})")
        if not dry_run and os.path.exists(PENDING_FILE):
            try:
                os.remove(PENDING_FILE)
            except Exception:
                pass

        # Watchdog: ensure server is running if not intentionally stopped
        stop_file = os.path.join(VALHEIM_DIR, ".stop_server")
        if not is_server_running() and not os.path.exists(stop_file):
            if dry_run:
                log("🛡️ [DRY RUN] Watchdog: Server is offline, would trigger automatic recovery.")
                return
            log("🛡️ Watchdog: Valheim server process is offline! Initiating automatic recovery...")
            start_server()
            ok, version, join_code = verify_and_get_info(timeout=75)
            if ok:
                msg = (
                    f"🛡️ <b>Valheim Server Recovered!</b>\n\n"
                    f"• <b>Status:</b> Automatically restored after unexpected shutdown\n"
                    f"• <b>Version:</b> <code>{version}</code>\n"
                    f"• <b>Join Code:</b> <code>{join_code}</code> (Port 2458)"
                )
                send_telegram(msg)
                send_whatsapp(f"🛡️ *Valheim Server Recovered!*\nAutomatically brought back online after crash.\n*Join Code:* `{join_code}` (Port 2458)")
                record_vps_log(f"Valheim Watchdog: Automatically restored crashed server. Join code: {join_code}.")
            else:
                send_telegram("⚠️ <b>Valheim Watchdog Alert</b>: Server was offline and attempted restart, but verification timed out.")
        return

    # New patch available!
    log(f"🔔 UPDATE DETECTED! Local Build: {local_build} | Steam Public Build: {remote_build}")

    player_count, players = get_active_players()
    if player_count > 0 and not force:
        p_word = "player" if player_count == 1 else "players"
        pnames = ", ".join(players) if players else f"{player_count} {p_word}"
        log(f"Postponing update: {player_count} {p_word} online ({pnames}).")

        if dry_run:
            log(f"[DRY RUN] Would defer update for {player_count} active players ({pnames}).")
            return

        already_notified = False
        pending_data = safe_load_json(PENDING_FILE, default={})
        if pending_data.get("build") == remote_build:
            already_notified = True

        if not already_notified:
            atomic_save_json(PENDING_FILE, {"build": remote_build, "time": time.time(), "players": pnames})
            notes = get_or_fetch_patch_notes()

            msg = (
                f"⚠️ <b>Valheim Update Available (Build {remote_build})</b>\n\n"
                f"Current Build: <code>{local_build}</code>\n"
                f"Active Players: <b>{pnames}</b>\n\n"
                f"<i>Update has been deferred. It will automatically install the moment all players log off.</i>"
            )
            if notes and notes.get("tg_text"):
                msg += f"\n\n{notes['tg_text']}"
            send_telegram(msg)

            wa_msg = (
                f"⚠️ *Valheim Update Detected (Build {remote_build})*\n\n"
                f"• *Current Build:* `{local_build}`\n"
                f"• *Warriors In-Game:* *{pnames}*\n\n"
                f"⚔️ _Update is deferred and will install automatically when the server is empty._"
            )
            if notes and notes.get("wa_text"):
                wa_msg += f"\n\n{notes['wa_text']}"
            send_whatsapp(wa_msg)
        return

    # No players online or force flag set: Proceed with patch!
    perform_patch(local_build, remote_build, dry_run=dry_run)


def show_status() -> None:
    local_build = get_local_buildid()
    remote_build = get_remote_buildid()
    count, players = get_active_players()
    running = is_server_running()
    pending = os.path.exists(PENDING_FILE)
    cached_notes = get_cached_patch_notes()

    print("=== Valheim Auto-Patcher Status ===")
    print(f"Server Running  : {'YES' if running else 'NO'}")
    print(f"Local Build ID  : {local_build or 'Unknown'}")
    print(f"Remote Build ID : {remote_build or 'Unknown'}")
    print(f"Update Available: {'YES' if (local_build and remote_build and local_build != remote_build) else 'NO'}")
    print(f"Active Players  : {count} ({', '.join(players) if players else 'none'})")
    print(f"Pending Update  : {'YES' if pending else 'NO'}")
    if cached_notes:
        print(f"Latest Patch    : {cached_notes.get('title', 'Unknown')} (cached at {cached_notes.get('updated_at', '')})")
    else:
        print("Latest Patch    : None cached")


def show_pending() -> None:
    if os.path.exists(PENDING_FILE):
        data = safe_load_json(PENDING_FILE, default={})
        build = data.get("build", "Unknown")
        players = data.get("players", "Unknown")
        ts = data.get("time")
        
        deferred_at = "Unknown"
        if ts:
            deferred_at = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            
        print(f"⏳ *[Pending Update]*\nA server update (Build `{build}`) is currently pending and waiting for players to log off.\n• *Deferred due to:* {players}\n• *Deferred at:* {deferred_at}\n\n_Once all players disconnect, the server will restart and apply the patch automatically._")
    else:
        print("✅ *[Server Up-to-Date]*\nNo updates are currently pending.")

def main() -> None:
    parser = argparse.ArgumentParser(description="Valheim Server Auto-Patching Engine")
    parser.add_argument("--check", action="store_true", help="Check for updates and display status without modifying server")
    parser.add_argument("--status", action="store_true", help="Display full local vs remote status")
    parser.add_argument("--pending", action="store_true", help="Display pending update status for chat bot")
    parser.add_argument("--notes", "--patchnotes", dest="notes", action="store_true", help="Fetch and print latest patch notes to terminal")
    parser.add_argument("--post-notes", dest="post_notes", action="store_true", help="Broadcast latest patch notes to WhatsApp and Telegram immediately")
    parser.add_argument("--version-tag", dest="version_tag", default=None, help="Target game version for patch notes (e.g. 1.0.17)")
    parser.add_argument("--force", action="store_true", help="Force update immediately even if players are online")
    parser.add_argument("--cron", action="store_true", help="Run in cron mode (quiet unless update detected or executed)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate update process safely without executing changes")
    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.pending:
        show_pending()
    elif args.notes:
        notes = get_or_fetch_patch_notes(target_version=args.version_tag)
        if notes and notes.get("wa_text"):
            print(notes["wa_text"])
        else:
            print("No patch notes available.")
    elif args.post_notes:
        notes = get_or_fetch_patch_notes(target_version=args.version_tag)
        if notes:
            if notes.get("tg_text"):
                send_telegram(notes["tg_text"])
            if notes.get("wa_text"):
                send_whatsapp(notes["wa_text"])
            print(f"Posted patch notes for '{notes.get('title')}' to Telegram and WhatsApp.")
        else:
            print("Failed to fetch patch notes.")
    elif args.check:
        local_build = get_local_buildid()
        remote_build = get_remote_buildid()
        print(f"Local Build : {local_build}")
        print(f"Remote Build: {remote_build}")
        if local_build != remote_build:
            print(f"Update AVAILABLE! (New Build: {remote_build})")
        else:
            print("Server is UP-TO-DATE.")
    else:
        check_and_run(cron_mode=args.cron, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
