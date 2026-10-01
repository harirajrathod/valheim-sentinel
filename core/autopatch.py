"""
core/autopatch.py - Autonomous, Player-Safe SteamCMD Auto-Patcher & Watchdog
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
from datetime import datetime
from typing import Tuple, List, Optional

from . import config
from . import notifier

APP_ID = "896660"
MANIFEST_PATH = os.path.join(config.VALHEIM_SERVER_DIR, "steamapps/appmanifest_896660.acf")
PENDING_FILE = os.path.join(config.VALHEIM_SERVER_DIR, ".pending_update")
MAX_BACKUPS = 10

def log(msg: str):
    timestamp = datetime.now(config.CURRENT_TZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [AutoPatch] {msg}")

def get_local_buildid() -> Optional[str]:
    """Extract local buildid from Steam appmanifest."""
    if not os.path.exists(MANIFEST_PATH):
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
    """Fetch latest public buildid from Steam via Web API with SteamCMD fallback."""
    try:
        url = f"https://api.steamcmd.net/v1/info/{APP_ID}"
        req = urllib.request.Request(url, headers={"User-Agent": "ValheimSentinel/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                remote = data.get("data", {}).get(APP_ID, {}).get("depots", {}).get("branches", {}).get("public", {}).get("buildid")
                if remote:
                    return str(remote)
    except Exception as e:
        log(f"Web API check failed ({e}), falling back to SteamCMD...")

    # Fallback to local steamcmd binary
    steamcmd_bins = ["/usr/games/steamcmd", "steamcmd"]
    for sc in steamcmd_bins:
        try:
            cmd = [sc, "+login", "anonymous", "+app_info_update", "1", "+app_info_print", APP_ID, "+quit"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            m = re.search(r'\"branches\"[\s\S]*?\"public\"[\s\S]*?\"buildid\"\s+\"(\d+)\"', res.stdout)
            if m:
                return m.group(1)
        except Exception:
            continue
    return None

def get_active_players() -> Tuple[int, List[str]]:
    """Inspects server log to determine active player count and character names."""
    if not os.path.exists(config.VALHEIM_LOG_FILE):
        return 0, []

    count = 0
    recent_names = []
    try:
        with open(config.VALHEIM_LOG_FILE, "r", errors="ignore") as f:
            lines = f.readlines()

        for line in reversed(lines):
            m_count = re.search(r'now (\d+) player\(s\)', line)
            if m_count:
                count = int(m_count.group(1))
                break
            m_conn = re.search(r'Connections (\d+) ZDOS', line)
            if m_conn:
                count = int(m_conn.group(1))
                break

        if count > 0:
            for line in reversed(lines):
                m_join = re.search(r'Got character ZDOID from ([^:]+) :', line)
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

def backup_worlds() -> Optional[str]:
    """Creates a timestamped snapshot of the worlds directory."""
    if not os.path.exists(config.VALHEIM_WORLDS_DIR):
        log("No worlds directory found to back up.")
        return None
    timestamp = datetime.now(config.CURRENT_TZ).strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(config.VALHEIM_BACKUP_DIR, f"auto_patch_{timestamp}")
    try:
        os.makedirs(backup_path, exist_ok=True)
        shutil.copytree(config.VALHEIM_WORLDS_DIR, os.path.join(backup_path, "worlds_local"))
        log(f"World backup created at {backup_path}")
        # Prune old backups beyond MAX_BACKUPS
        try:
            existing = sorted(
                [d for d in os.listdir(config.VALHEIM_BACKUP_DIR)
                 if d.startswith("auto_patch_") and os.path.isdir(os.path.join(config.VALHEIM_BACKUP_DIR, d))],
                reverse=True
            )
            for old in existing[MAX_BACKUPS:]:
                old_path = os.path.join(config.VALHEIM_BACKUP_DIR, old)
                shutil.rmtree(old_path, ignore_errors=True)
                log(f"Pruned old backup: {old}")
        except Exception as e:
            log(f"Backup pruning warning: {e}")
        return backup_path
    except Exception as e:
        log(f"Backup failed: {e}")
        return None

def stop_server():
    """Gracefully stops the server allowing world data flush."""
    log("Stopping active Valheim server...")
    stop_file = os.path.join(config.VALHEIM_SERVER_DIR, ".stop_server")
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

    subprocess.run(["tmux", "kill-session", "-t", config.TMUX_SESSION], capture_output=True)
    time.sleep(2)

    if is_server_running():
        log("Server process still active, issuing SIGKILL...")
        subprocess.run(["pkill", "-9", "-f", "valheim_server.x86_64"], capture_output=True)
        time.sleep(2)

    if os.path.exists(stop_file):
        try:
            os.remove(stop_file)
        except Exception:
            pass

def start_server() -> bool:
    """Starts the Valheim server in the designated tmux session."""
    stop_file = os.path.join(config.VALHEIM_SERVER_DIR, ".stop_server")
    if os.path.exists(stop_file):
        try:
            os.remove(stop_file)
        except Exception:
            pass

    start_script = os.path.join(config.VALHEIM_SERVER_DIR, "start_valheim.sh")
    if not os.path.exists(start_script):
        # Fallback to direct binary launch or generic runner
        start_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "start_server.sh")

    log(f"Launching Valheim server in tmux session '{config.TMUX_SESSION}'...")
    tmux_cmd = f"bash {start_script} >> {config.VALHEIM_LOG_FILE} 2>&1"
    subprocess.run(["tmux", "new-session", "-d", "-s", config.TMUX_SESSION, tmux_cmd])
    time.sleep(5)
    return is_server_running()

def update_game_files() -> bool:
    """Runs SteamCMD to update and validate Valheim Dedicated Server files."""
    log("Running SteamCMD update for AppID 896660...")
    cmd = [
        "steamcmd",
        "+force_install_dir", config.VALHEIM_SERVER_DIR,
        "+login", "anonymous",
        "+app_update", APP_ID, "validate",
        "+quit"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if "Success! App '896660' fully installed." in res.stdout:
            log("SteamCMD update successful.")
            for f in ["valheim_server.x86_64", "start_valheim.sh"]:
                target = os.path.join(config.VALHEIM_SERVER_DIR, f)
                if os.path.exists(target):
                    os.chmod(target, 0o755)
            return True
        else:
            log(f"SteamCMD update failed! Output:\n{res.stdout[-300:]}")
            return False
    except Exception as e:
        log(f"SteamCMD execution error: {e}")
        return False

def verify_and_get_info(timeout=60) -> Tuple[bool, str, str]:
    """Waits for server initialization, parses new game version and PlayFab join code."""
    log("Verifying server startup and extracting session credentials...")
    start_time = time.time()
    version = "Unknown"
    join_code = "Unknown"

    while time.time() - start_time < timeout:
        if not is_server_running():
            log("Server process terminated unexpectedly during verification!")
            return False, version, join_code

        if os.path.exists(config.VALHEIM_LOG_FILE):
            try:
                with open(config.VALHEIM_LOG_FILE, "r", errors="ignore") as f:
                    content = f.read()
                m_ver = re.search(r'Valheim version:\s*([\d\.]+)', content)
                if m_ver:
                    version = m_ver.group(1)
                m_code = re.search(r'Session \"[^\"]+\" with join code\s+([A-Za-z0-9]+)\s+and IP', content)
                if m_code:
                    join_code = m_code.group(1)
                    log(f"Server operational: Version {version}, Join Code: {join_code}")
                    return True, version, join_code
            except Exception:
                pass
        time.sleep(3)

    return is_server_running(), version, join_code

def run_patch_pipeline(force: bool = False) -> bool:
    """Executes the full automated patch and restart cycle."""
    player_count, players = get_active_players()
    if player_count > 0 and not force:
        log(f"Update deferred: {player_count} player(s) online ({', '.join(players)}). Setting pending flag.")
        with open(PENDING_FILE, "w") as f:
            f.write(f"{datetime.now(config.CURRENT_TZ).isoformat()}|{player_count}\n")
        notifier.broadcast(
            f"⚔️ **Valheim Update Detected!**\n"
            f"An official update is available, but deferred because **{player_count} warrior(s)** are currently in-game ({', '.join(players)}).\n"
            f"The server will patch automatically as soon as the realm is empty!"
        )
        return False

    log("Starting autonomous patch deployment...")
    backup_path = backup_worlds()
    stop_server()

    if not update_game_files():
        log("Patch failed! Attempting recovery restart...")
        start_server()
        notifier.broadcast("⚠️ **Valheim Patch Alert**: SteamCMD update failed. Server has been restored to previous build.")
        return False

    if not start_server():
        log("Failed to restart server after update!")
        notifier.broadcast("🚨 **Valheim Critical Alert**: Server failed to restart after update! Manual intervention required.")
        return False

    success, version, join_code = verify_and_get_info()
    if os.path.exists(PENDING_FILE):
        try:
            os.remove(PENDING_FILE)
        except Exception:
            pass

    msg = (
        f"🛡️ **Valheim Server Updated & Online!** ⚡\n\n"
        f"• **Version:** `{version}`\n"
        f"• **Join Code:** `{join_code}`\n"
        f"• **Port:** `{config.VALHEIM_SERVER_PORT}`\n"
        f"• **Backup:** Snapshot created successfully."
    )
    notifier.broadcast(msg)
    log("Patch pipeline completed successfully.")
    return True

def main():
    parser = argparse.ArgumentParser(description="Valheim Sentinel Autonomous Auto-Patcher")
    parser.add_argument("--check", action="store_true", help="Check local vs remote buildid")
    parser.add_argument("--force", action="store_true", help="Force update immediately regardless of active players")
    parser.add_argument("--cron", action="store_true", help="Cron check mode (updates if empty or pending)")
    parser.add_argument("--status", action="store_true", help="Show current server and player status")
    parser.add_argument("--restart", action="store_true", help="Unconditionally restart the server (graceful stop + start)")
    args = parser.parse_args()

    local_id = get_local_buildid()
    remote_id = get_remote_buildid()

    if args.status:
        running = is_server_running()
        count, players = get_active_players()
        print(json.dumps({
            "running": running,
            "local_buildid": local_id,
            "remote_buildid": remote_id,
            "active_players": count,
            "player_names": players
        }, indent=2))
        return

    if args.check:
        print(f"Local BuildID:  {local_id}")
        print(f"Remote BuildID: {remote_id}")
        if local_id and remote_id and local_id != remote_id:
            print("Status: UPDATE AVAILABLE")
        else:
            print("Status: UP TO DATE")
        return

    if args.restart:
        log("Manual restart requested.")
        stop_server()
        if not start_server():
            log("Failed to restart server!")
            notifier.broadcast("🚨 **Valheim Alert**: Manual restart failed! Server did not come back online.")
            sys.exit(1)
        success, version, join_code = verify_and_get_info()
        notifier.broadcast(
            f"🛡️ **Valheim Server Restarted!** ⚡\n\n"
            f"• **Version:** `{version}`\n"
            f"• **Join Code:** `{join_code}`\n"
            f"• **Port:** `{config.VALHEIM_SERVER_PORT}`"
        )
        return

    # In cron or force mode
    if args.force:
        run_patch_pipeline(force=True)
    elif args.cron:
        has_pending = os.path.exists(PENDING_FILE)
        update_available = (local_id and remote_id and local_id != remote_id)
        if update_available or has_pending:
            run_patch_pipeline(force=False)
        else:
            # Watchdog health check: if server unexpectedly offline, revive it
            if not is_server_running():
                log("Watchdog detected server process offline! Rebooting...")
                start_server()
                _, version, join_code = verify_and_get_info()
                notifier.broadcast(f"🛡️ **Valheim Watchdog**: Server recovered from crash and is back online! Join Code: `{join_code}`")

if __name__ == "__main__":
    main()
