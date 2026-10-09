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
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, "/root")
from valheim_utils import (
    VALHEIM_DIR,
    LOG_FILE,
    TMUX_SESSION,
    IST,
    format_player_name,
    sanitize_network_copy
)


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


def get_server_info() -> Dict[str, Any]:
    """
    Parses the active Valheim log to determine current status, players,
    session duration, and Azure relay connection.
    """
    running = is_server_running()
    join_code = "Unknown"
    version = "1.0.12"
    active_players: Dict[str, str] = {}  # owner -> name
    sid_to_name: Dict[str, str] = {}
    player_load_times: Dict[str, datetime] = {}  # name -> datetime
    relay_host = "20.74.234.90"
    relay_region = "UAE North (PlayFab Azure)"

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", errors="ignore") as f:
                last_sid = None
                for line in f:
                    if "registered with join code" in line or "join code " in line:
                        m_code = re.search(r'join code\s+(\d+)', line)
                        if m_code:
                            join_code = m_code.group(1)
                    if "Valheim " in line and "network version" in line:
                        m_ver = re.search(r'Valheim\s+(l-[\d\.]+.*?\(network version \d+\))', line)
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
                    m_hs = re.search(r'Got handshake from client (\S+)', line)
                    if m_hs:
                        last_sid = m_hs.group(1).rstrip(",")
                    if "Connections 0 ZDOS" in line or "now 0 player(s)" in line:
                        active_players.clear()
                        sid_to_name.clear()
                        player_load_times.clear()
                        continue
                    m_join = re.search(r'Got character ZDOID from ([^:]+) : (-?\d+):(\d+)', line)
                    if m_join:
                        raw_name = m_join.group(1).strip()
                        name = format_player_name(raw_name)
                        owner = m_join.group(2).strip()
                        if owner != "0":
                            active_players[owner] = name
                            if last_sid:
                                sid_to_name[last_sid] = name
                            if name not in player_load_times:
                                m_ts = re.search(r'^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})', line)
                                if m_ts:
                                    try:
                                        dt_utc = datetime.strptime(m_ts.group(1), '%m/%d/%Y %H:%M:%S').replace(tzinfo=timezone.utc)
                                        player_load_times[name] = dt_utc
                                    except Exception:
                                        pass
                        last_sid = None
                        continue
                    m_dest = re.search(r'Destroying abandoned non persistent zdo \S+ owner (-?\d+)', line)
                    if m_dest:
                        owner = m_dest.group(1).strip()
                        pname = active_players.pop(owner, None)
                        if pname and pname not in active_players.values():
                            player_load_times.pop(pname, None)
                    m_sock = re.search(r'Closing socket\s+(\S+)', line)
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
    if running:
        relay_ping_data = measure_relay_ping(relay_host)
        server_relay_ping_ms = relay_ping_data.get("ping_ms")

    return {
        "running": running,
        "version": version,
        "join_code": join_code,
        "player_count": len(players),
        "players": players,
        "owner_to_name": active_players,
        "name_to_owner": name_to_owner,
        "port": 2458,
        "player_sessions": player_sessions,
        "primary_zone_host": primary_zone_host,
        "server_relay_ping_ms": server_relay_ping_ms,
        "relay_host": relay_host,
        "relay_region": relay_region
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
            "join_code": info.get("join_code", "Unknown"),
            "version": info.get("version", "Unknown"),
            "port": 2458,
            "duration_seconds": 0.0,
            "note": "Dry-run completed successfully. Server state untouched."
        }

    start_time = time.time()
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

    # Wait for PlayFab lobby registration & join code
    join_code = "Unknown"
    version = "Unknown"
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
                    if join_code != "Unknown":
                        return {
                            "success": True,
                            "join_code": join_code,
                            "version": version,
                            "port": 2458,
                            "duration_seconds": round(time.time() - start_time, 1)
                        }
            except Exception:
                pass
        time.sleep(3)

    return {
        "success": is_server_running(),
        "join_code": join_code,
        "version": version,
        "port": 2458,
        "note": "PlayFab lobby registration took longer than expected but server is running."
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
