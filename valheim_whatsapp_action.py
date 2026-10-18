#!/usr/bin/env python3
"""
/root/valheim_whatsapp_action.py - Safe Valheim actions for WhatsApp integration.

Provides:
  --status    : Returns clean JSON with running state, active players, and join code
  --restart   : Gracefully flushes world save, restarts server in tmux, verifies PlayFab lobby, returns JSON
  --dry-run   : Simulates actions safely without modifying server state

All diagnostic messages are directed to stderr so stdout is ALWAYS valid JSON.
"""

import os
import sys
import time
import re
import json
import base64
import subprocess
import argparse
from datetime import datetime, timezone
from typing import Dict, Any, List

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
if "/root" not in sys.path:
    sys.path.append("/root")
from valheim_utils import (
    VALHEIM_DIR,
    LOG_FILE,
    TMUX_SESSION,
    IST,
    format_player_name
)
from valheim_constants import PATTERNS


def log_debug(msg: str) -> None:
    """Logs diagnostic info to stderr to keep stdout strictly JSON."""
    sys.stderr.write(f"[valheim_action] {msg}\n")


def is_server_running() -> bool:
    """Checks whether the valheim_server.x86_64 process is active."""
    try:
        res = subprocess.run(["pgrep", "-f", "valheim_server.x86_64"], capture_output=True, text=True)
        return bool(res.stdout.strip())
    except Exception as e:
        log_debug(f"Process check error: {e}")
        return False


def wait_for_ports_free(timeout: int = 15) -> bool:
    """Waits for Valheim UDP ports 2458/2459 to be released after process exit."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            res = subprocess.run(["ss", "-u", "-a", "-n"], capture_output=True, text=True)
            if ":2458" not in res.stdout and ":2459" not in res.stdout:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


class PingCache:
    """Caches round-trip ping to the Azure PlayFab Relay with 60s TTL."""
    def __init__(self, ttl_seconds: int = 60) -> None:
        self.ttl = ttl_seconds
        self.last_time: float = 0
        self.cached_info: Dict[str, Any] = {"ping_ms": None, "region": "UAE North (PlayFab Azure)"}

    def measure(self, host_or_ip: str = "20.74.234.90", timeout_sec: float = 0.8) -> Dict[str, Any]:
        now = time.time()
        if (now - self.last_time < self.ttl) and self.cached_info.get("ping_ms") is not None:
            return self.cached_info

        try:
            res = subprocess.run(
                ["ping", "-c", "1", "-W", "1", str(host_or_ip)],
                capture_output=True,
                text=True,
                timeout=timeout_sec + 0.2
            )
            if res.returncode == 0:
                m = re.search(r'time=([\d\.]+)\s*ms', res.stdout)
                if m:
                    self.cached_info["ping_ms"] = round(float(m.group(1)), 1)
                    self.last_time = now
        except Exception:
            pass
        return self.cached_info


_PING_CACHE = PingCache(ttl_seconds=60)


def measure_relay_ping(host_or_ip: str = "20.74.234.90", timeout_sec: float = 0.8) -> Dict[str, Any]:
    return _PING_CACHE.measure(host_or_ip, timeout_sec)


def is_crossplay_configured() -> bool:
    """Checks whether -crossplay is present in start_valheim.sh."""
    try:
        start_script = os.path.join(VALHEIM_DIR, "start_valheim.sh")
        if os.path.exists(start_script):
            with open(start_script, "r", encoding="utf-8", errors="ignore") as f:
                return "-crossplay" in f.read()
    except Exception:
        pass
    return False


def is_crossplay_active() -> bool:
    """Checks whether the currently running Valheim server was launched with -crossplay."""
    try:
        res = subprocess.run(["pgrep", "-f", "valheim_server.x86_64"], capture_output=True, text=True)
        pids = res.stdout.strip().split()
        if pids:
            with open(f"/proc/{pids[0]}/cmdline", "rb") as f:
                cmd = f.read().decode('latin1', errors='ignore')
                return "-crossplay" in cmd
    except Exception:
        pass
    return is_crossplay_configured()


def get_server_info() -> Dict[str, Any]:
    """
    Parses the active Valheim log to determine current status, players,
    session duration, and Azure relay connection.
    """
    running = is_server_running()
    crossplay_on = is_crossplay_active() if running else is_crossplay_configured()
    join_code = "Unknown" if crossplay_on else "Disabled (Direct IP: 72.62.227.29:2458)"
    version = "1.0.12"
    active_players: Dict[str, str] = {}  # owner -> name
    sid_to_name: Dict[str, str] = {}
    player_load_times: Dict[str, datetime] = {}  # name -> datetime
    relay_host = "20.74.234.90" if crossplay_on else "Direct"
    relay_region = "UAE North (PlayFab Azure)" if crossplay_on else "Direct Steam Sockets"

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", errors="ignore") as f:
                last_sid = None
                for line in f:
                    if "Starting Valheim" in line or "Opened Steam server" in line:
                        active_players.clear()
                        sid_to_name.clear()
                        player_load_times.clear()
                        last_sid = None
                        if not crossplay_on:
                            join_code = "Disabled (Direct IP: 72.62.227.29:2458)"
                            relay_host = "Direct"
                            relay_region = "Direct Steam Sockets"

                    if crossplay_on:
                        m_code = PATTERNS["join_code"].search(line) or PATTERNS["join_code_loose"].search(line)
                        if m_code:
                            join_code = m_code.group(1)
                    if "Valheim" in line and "network version" in line:
                        m_ver = PATTERNS["version"].search(line)
                        if m_ver:
                            version = m_ver.group(1)
                    if "Lobby " in line and "and network " in line:
                        m_net = re.search(r'and network [^\|]+\|([A-Za-z0-9+/=]+)', line)
                        if m_net:
                            try:
                                decoded = base64.b64decode(m_net.group(1)).decode('latin1', errors='ignore')
                                m_h = re.search(r'(dns[a-zA-Z0-9-]+[a-zA-Z0-9\.-]+\.cloudapp\.azure\.com)', decoded)
                                if m_h:
                                    relay_host = m_h.group(1)
                                    if "uaenorth" in relay_host:
                                        relay_region = "UAE North (PlayFab Azure)"
                                    elif "india" in relay_host:
                                        relay_region = "India (PlayFab Azure)"
                                    elif "westeurope" in relay_host:
                                        relay_region = "West Europe (PlayFab Azure)"
                            except Exception:
                                pass
                    m_hs = PATTERNS["handshake"].search(line)
                    if m_hs:
                        last_sid = m_hs.group(1).rstrip(",")
                    if "Connections 0 ZDOS" in line or "now 0 player(s)" in line:
                        active_players.clear()
                        sid_to_name.clear()
                        player_load_times.clear()
                        continue
                    m_join = PATTERNS["zdo_join"].search(line)
                    if m_join:
                        raw_name = m_join.group(1).strip()
                        name = format_player_name(raw_name)
                        owner = m_join.group(2).strip()
                        if owner != "0":
                            active_players[owner] = name
                            if last_sid:
                                sid_to_name[last_sid] = name
                            if name not in player_load_times:
                                m_ts = PATTERNS["ts_plain"].search(line)
                                if m_ts:
                                    try:
                                        dt_utc = datetime.strptime(m_ts.group(1), '%m/%d/%Y %H:%M:%S').replace(tzinfo=timezone.utc)
                                        player_load_times[name] = dt_utc
                                    except Exception:
                                        pass
                        last_sid = None
                        continue
                    m_dest = PATTERNS["destroy_zdo"].search(line)
                    if m_dest:
                        owner = m_dest.group(1).strip()
                        pname = active_players.pop(owner, None)
                        if pname and pname not in active_players.values():
                            player_load_times.pop(pname, None)
                    m_sock = PATTERNS["socket_close"].search(line)
                    if m_sock:
                        sid = m_sock.group(1).rstrip(",")
                        pname = sid_to_name.pop(sid, None)
                        if pname:
                            for o, n in list(active_players.items()):
                                if n == pname:
                                    active_players.pop(o, None)
                            if pname not in active_players.values():
                                player_load_times.pop(pname, None)
        except Exception as e:
            log_debug(f"Error parsing log file: {e}")

    players = sorted(list(set(active_players.values())))
    name_to_owner = {n: o for o, n in active_players.items()}

    # Calculate player session durations and determine Primary Zone Owner
    player_sessions: List[Dict[str, Any]] = []
    primary_zone_host = None
    now_utc = datetime.now(timezone.utc)

    active_load_times = {p: dt for p, dt in player_load_times.items() if p in players}
    sorted_players = sorted(active_load_times.items(), key=lambda x: x[1])

    for idx, (pname, dt_utc) in enumerate(sorted_players):
        dur_mins = max(0, int((now_utc - dt_utc).total_seconds() // 60))
        is_host = (idx == 0)
        if is_host:
            primary_zone_host = pname
        dt_ist = dt_utc.astimezone(IST)
        player_sessions.append({
            "name": pname,
            "load_time": dt_ist.strftime("%H:%M IST"),
            "duration_mins": dur_mins,
            "is_primary_host": is_host
        })

    for p in players:
        if p not in [s["name"] for s in player_sessions]:
            is_host = (len(player_sessions) == 0)
            if is_host:
                primary_zone_host = p
            player_sessions.append({
                "name": p,
                "load_time": "Unknown",
                "duration_mins": 0,
                "is_primary_host": is_host
            })

    server_relay_ping_ms = None
    if running and crossplay_on:
        relay_ping_data = measure_relay_ping(relay_host)
        server_relay_ping_ms = relay_ping_data.get("ping_ms")
    elif not running:
        players = []
        active_players = {}
        name_to_owner = {}
        player_sessions = []
        primary_zone_host = None

    # Fetch Drive Backup metadata safely
    drive_backup = {
        "save_id": None,
        "timestamp": None,
        "status": "UNKNOWN",
        "is_synced": False
    }
    try:
        from valheim_backup_drive import load_drive_backup_state, get_active_save_info
        b_state = load_drive_backup_state()
        b_info = get_active_save_info()
        drive_backup["save_id"] = b_state.get("last_save_id")
        drive_backup["timestamp"] = b_state.get("last_backup_time")
        drive_backup["status"] = b_state.get("last_status", "UNKNOWN")
        drive_backup["is_synced"] = (
            b_state.get("last_status") == "SUCCESS"
            and b_state.get("last_save_id") is not None
            and b_state.get("last_save_id") == b_info.get("save_id")
        )
    except Exception as e:
        log_debug(f"Error fetching drive backup state: {e}")

    return {
        "running": running,
        "crossplay": crossplay_on,
        "version": version,
        "join_code": join_code if crossplay_on else "Disabled (Direct IP: 72.62.227.29:2458)",
        "player_count": len(players),
        "players": players,
        "owner_to_name": active_players,
        "name_to_owner": name_to_owner,
        "port": 2458,
        "player_sessions": player_sessions,
        "primary_zone_host": primary_zone_host,
        "server_relay_ping_ms": server_relay_ping_ms,
        "relay_host": relay_host if crossplay_on else "Direct",
        "relay_region": relay_region if crossplay_on else "Direct Steam Sockets",
        "drive_backup": drive_backup
    }


def graceful_restart(timeout: int = 90, dry_run: bool = False) -> Dict[str, Any]:
    """
    Safely flushes world save, terminates server cleanly, and reboots in tmux.
    If dry_run is True, performs a hermetic test without stopping the server.
    """
    if dry_run:
        running = is_server_running()
        info = get_server_info()
        return {
            "success": True,
            "dry_run": True,
            "simulated": True,
            "current_running": running,
            "crossplay": info.get("crossplay", True),
            "join_code": info.get("join_code", "Unknown"),
            "version": info.get("version", "Unknown"),
            "port": 2458,
            "duration_seconds": 0.0,
            "note": "Dry-run completed successfully. Server state untouched."
        }

    start_time = time.time()
    crossplay_will_run = is_crossplay_configured()
    stop_file = os.path.join(VALHEIM_DIR, ".stop_server")
    try:
        with open(stop_file, "w") as f:
            f.write("stop\n")
    except Exception as e:
        log_debug(f"Warning creating stop file: {e}")

    # Send SIGINT to allow Unity world flush
    if is_server_running():
        try:
            subprocess.run(["pkill", "-SIGINT", "-f", "valheim_server.x86_64"], timeout=5)
            for _ in range(12):
                if not is_server_running():
                    break
                time.sleep(1)
        except Exception:
            pass

    # Kill tmux session
    subprocess.run(["tmux", "kill-session", "-t", TMUX_SESSION], capture_output=True)
    time.sleep(2)

    # Force kill if still hanging
    if is_server_running():
        subprocess.run(["pkill", "-9", "-f", "valheim_server.x86_64"], capture_output=True)
        time.sleep(2)

    try:
        if os.path.exists(stop_file):
            os.remove(stop_file)
    except Exception:
        pass

    # Ensure UDP ports 2458 and 2459 are released
    wait_for_ports_free(timeout=10)
    time.sleep(3)

    # Launch new tmux session
    start_script = os.path.join(VALHEIM_DIR, "start_valheim.sh")
    tmux_cmd = f"bash {start_script} >> {LOG_FILE} 2>&1"
    subprocess.run(["tmux", "new-session", "-d", "-s", TMUX_SESSION, tmux_cmd])
    try:
        # Decouple process from caller cgroup
        res_pid = subprocess.run(["pgrep", "-f", "valheim_server.x86_64"], capture_output=True, text=True)
        for p in res_pid.stdout.strip().split():
            if p:
                with open("/sys/fs/cgroup/cgroup.procs", "w") as cg_f:
                    cg_f.write(p + "\n")
    except Exception:
        pass
    time.sleep(5)

    if not is_server_running():
        return {"success": False, "error": "Server process failed to start."}

    # Wait for server initialization
    join_code = "Unknown"
    version = "Unknown"
    server_connected = False
    while time.time() - start_time < timeout:
        if not is_server_running():
            return {"success": False, "error": "Server crashed during startup verification."}

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", errors="ignore") as f:
                    lines = f.readlines()
                for line in reversed(lines[-80:]):
                    if "registered with join code" in line:
                        m_code = re.search(r'join code\s+(\d+)', line)
                        if m_code:
                            join_code = m_code.group(1)
                    if "Valheim version:" in line:
                        m_ver = re.search(r'Valheim version:\s+(.*)', line)
                        if m_ver:
                            version = m_ver.group(1)
                    elif "Console: Valheim" in line and version == "Unknown":
                        m_ver = re.search(r'Valheim\s+(l-[\d\.]+.*?\(network version \d+\))', line)
                        if m_ver:
                            version = m_ver.group(1)
                    if "Game server connected" in line:
                        server_connected = True

                if crossplay_will_run:
                    if join_code != "Unknown":
                        if not dry_run:
                            try:
                                from valheim_utils import safe_load_json, atomic_save_json, state_path
                                pf_file = state_path("valheim_playfab_state.json")
                                pf_state = safe_load_json(pf_file, default={})
                                pf_state["desync_pending"] = False
                                pf_state["last_restart_time"] = time.time()
                                atomic_save_json(pf_file, pf_state)
                            except Exception as ex_pf:
                                log_debug(f"Warning updating playfab state on restart: {ex_pf}")

                        return {
                            "success": True,
                            "crossplay": True,
                            "join_code": join_code,
                            "version": version,
                            "port": 2458,
                            "duration_seconds": round(time.time() - start_time, 1)
                        }
                else:
                    if server_connected:
                        if not dry_run:
                            try:
                                from valheim_utils import safe_load_json, atomic_save_json, state_path
                                pf_file = state_path("valheim_playfab_state.json")
                                pf_state = safe_load_json(pf_file, default={})
                                pf_state["desync_pending"] = False
                                pf_state["last_restart_time"] = time.time()
                                atomic_save_json(pf_file, pf_state)
                            except Exception as ex_pf:
                                log_debug(f"Warning updating playfab state on restart: {ex_pf}")

                        return {
                            "success": True,
                            "crossplay": False,
                            "join_code": "Disabled (Direct IP: 72.62.227.29:2458)",
                            "version": version,
                            "port": 2458,
                            "duration_seconds": round(time.time() - start_time, 1)
                        }
            except Exception:
                pass
        time.sleep(3)

    srv_ok = is_server_running()
    if srv_ok and not dry_run:
        try:
            from valheim_utils import safe_load_json, atomic_save_json, state_path
            pf_file = state_path("valheim_playfab_state.json")
            pf_state = safe_load_json(pf_file, default={})
            pf_state["desync_pending"] = False
            pf_state["last_restart_time"] = time.time()
            atomic_save_json(pf_file, pf_state)
        except Exception as ex_pf:
            log_debug(f"Warning updating playfab state on restart: {ex_pf}")

    return {
        "success": srv_ok,
        "crossplay": crossplay_will_run,
        "join_code": join_code if crossplay_will_run else "Disabled (Direct IP: 72.62.227.29:2458)",
        "version": version,
        "port": 2458,
        "note": "Direct Steam Server running." if not crossplay_will_run else "PlayFab lobby registration took longer than expected but server is running."
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safe Valheim actions for WhatsApp integration")
    parser.add_argument("--status", action="store_true", help="Return current server status as JSON")
    parser.add_argument("--restart", action="store_true", help="Gracefully restart the server")
    parser.add_argument("--dry-run", action="store_true", help="Perform inspection without mutating server state")
    args = parser.parse_args()

    if args.restart:
        result = graceful_restart(dry_run=args.dry_run)
    else:
        result = get_server_info()

    # Print STRICTLY clean JSON to stdout
    print(json.dumps(result, indent=2))
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    sys.exit(main())
