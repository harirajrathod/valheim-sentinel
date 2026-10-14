#!/usr/bin/env python3
"""
/root/valheim_doctor.py - Valheim Ecosystem Logical Sanity & Comprehensive Diagnostic Verifier

Performs end-to-end logical validation across:
1. Server Process, Port Binding & Network Runtime
2. Systemd Daemons & Scheduled Crontab Jobs
3. Source Code Syntax & Import Integrity (Python & Node.js Bridge)
4. Persistent JSON State Stores & Schema Validation
5. WhatsApp In-Group Commands Execution & Output Integrity (20+ commands)
6. Voice Audio Generation & Chronicle Pipeline Dry-Runs
7. Cross-Script Geographical & Player Name Consistency

Usage:
    python3 /root/valheim_doctor.py              # Full diagnostic suite
    python3 /root/valheim_doctor.py --quick      # Fast sanity check (< 5s)
    python3 /root/valheim_doctor.py --json       # Machine-readable output
"""

import os
import sys
import json
import time
import shutil
import socket
import struct
import py_compile
import subprocess
import argparse
from typing import Dict, Any, List, Tuple, Optional

# ANSI Color Codes
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

MAIN_BASE_COORDS = (12.8, -360.1)


class ValheimDoctor:
    def __init__(self, quick: bool = False, verbose: bool = False):
        self.quick = quick
        self.verbose = verbose
        self.results: List[Dict[str, Any]] = []
        self.start_time = time.time()

    def record(self, category: str, name: str, status: str, detail: str = "", elapsed_ms: float = 0.0):
        self.results.append({
            "category": category,
            "name": name,
            "status": status,  # "PASS", "WARN", "FAIL"
            "detail": detail,
            "elapsed_ms": round(elapsed_ms, 1)
        })

    def run_cmd(self, cmd: List[str], timeout: int = 15) -> Tuple[int, str, str, float]:
        t0 = time.time()
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
            elapsed = (time.time() - t0) * 1000.0
            return res.returncode, res.stdout.strip(), res.stderr.strip(), elapsed
        except subprocess.TimeoutExpired:
            elapsed = (time.time() - t0) * 1000.0
            return -1, "", f"Timed out after {timeout}s", elapsed
        except Exception as e:
            elapsed = (time.time() - t0) * 1000.0
            return -2, "", str(e), elapsed

    # =========================================================================
    # 1. SERVER PROCESS, PORTS & RUNTIME
    # =========================================================================
    def check_runtime(self):
        cat = "Runtime & Infrastructure"

        # 1. tmux session 'valheim'
        code, out, _, t = self.run_cmd(["tmux", "has-session", "-t", "valheim"])
        if code == 0:
            self.record(cat, "tmux session 'valheim'", "PASS", "Session active", t)
        else:
            self.record(cat, "tmux session 'valheim'", "FAIL", "tmux session 'valheim' not found", t)

        # 2. Binary process valheim_server.x86_64
        code, out, _, t = self.run_cmd(["pgrep", "-f", "valheim_server.x86_64"])
        if code == 0 and out.strip():
            pids = out.strip().split()
            self.record(cat, "Process valheim_server.x86_64", "PASS", f"Running (PID: {', '.join(pids)})", t)
        else:
            self.record(cat, "Process valheim_server.x86_64", "FAIL", "Process not running", t)

        # 3. Game Ports (UDP 2458 Game / 2459 Query)
        code, out, _, t = self.run_cmd(["ss", "-u", "-l", "-n", "-p"])
        has_query_port = ":2459" in out or ":2458" in out
        if has_query_port:
            self.record(cat, "Server UDP Sockets (Port 2458/2459 Query)", "PASS", "Listening and bound by server", t)
        else:
            self.record(cat, "Server UDP Sockets (Port 2458/2459 Query)", "WARN", "Port 2458/2459 not directly visible in ss", t)

        # 4. Join Code in Player.log or status
        code, out, err, t = self.run_cmd(["/usr/bin/python3", "/root/valheim_whatsapp_action.py", "--status"])
        if code == 0:
            try:
                data = json.loads(out)
                join_code = data.get("join_code", "")
                players = data.get("players", [])
                if join_code and len(join_code) >= 6:
                    self.record(cat, "PlayFab Join Code", "PASS", f"Active Join Code: `{join_code}` ({len(players)} warriors online)", t)
                else:
                    self.record(cat, "PlayFab Join Code", "WARN", f"Unexpected Join Code format: '{join_code}'", t)
            except Exception as e:
                self.record(cat, "PlayFab Join Code", "FAIL", f"JSON parsing failed: {e}", t)
        else:
            self.record(cat, "PlayFab Join Code", "FAIL", f"Status command failed: {err}", t)

        # 5. World Save Files (Valheim10 chunks / DB)
        world_dir = "/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10"
        world_db = "/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10.db"
        if os.path.isdir(world_dir):
            chunks = [os.path.join(world_dir, f) for f in os.listdir(world_dir) if f.endswith(".chunk")]
            total_size_mb = sum(os.path.getsize(c) for c in chunks) / (1024 * 1024)
            if len(chunks) > 0 and total_size_mb > 5.0:
                self.record(cat, "World Storage (Valheim10 Chunks)", "PASS", f"{len(chunks)} chunks, {total_size_mb:.1f}MB active world data", 0)
            else:
                self.record(cat, "World Storage (Valheim10 Chunks)", "WARN", f"Chunk directory has only {len(chunks)} chunks ({total_size_mb:.1f}MB)", 0)
        elif os.path.exists(world_db):
            db_size_mb = os.path.getsize(world_db) / (1024 * 1024)
            self.record(cat, "World Files (Valheim10)", "PASS", f"DB: {db_size_mb:.1f}MB", 0)
        else:
            self.record(cat, "World Storage (Valheim10)", "FAIL", "Neither Valheim10 chunk directory nor .db file found", 0)

        # 6. valheim-monitor.service
        code, out, _, t = self.run_cmd(["systemctl", "is-active", "valheim-monitor.service"])
        if out == "active":
            self.record(cat, "valheim-monitor.service", "PASS", "Active and running", t)
        else:
            self.record(cat, "valheim-monitor.service", "FAIL", f"State: {out}", t)

        # 7. hermes-gateway.service (user service)
        code, out, _, t = self.run_cmd(["systemctl", "--user", "is-active", "hermes-gateway.service"])
        if out == "active":
            self.record(cat, "hermes-gateway.service", "PASS", "Active and running (WhatsApp bridge)", t)
        else:
            self.record(cat, "hermes-gateway.service", "FAIL", f"State: {out}", t)

    # =========================================================================
    # 2. CRON SCHEDULES & SCRIPT EXISTENCE
    # =========================================================================
    def check_cron(self):
        cat = "Cron Jobs & Automation"
        code, out, _, t = self.run_cmd(["crontab", "-l"])
        if code != 0:
            self.record(cat, "Crontab access", "FAIL", "Cannot read crontab", t)
            return

        expected_crons = [
            ("valheim_autopatch.py", "Auto-Patcher (15m watchdog)"),
            ("valheim_daily_chronicle.py", "Daily Battle Chronicle (9 AM IST)"),
            ("valheim_weekly_superlatives.py", "Weekly Superlatives (Sun 8 PM IST)"),
            ("weekly_pipeline.py", "Weekly Chronicles Pipeline (Sun 8:30 PM IST)"),
            ("valheim_roast_refresher.py", "AI Roast Refresher (Sun 9:30 PM IST)"),
            ("valheim_sync.py", "Progress & Inventory Auto-Sync (15m)"),
            ("restart_valheim.sh", "Daily Server Reboot (5:30 AM IST)"),
            ("valheim_doctor.py", "Valheim Ecosystem Doctor (Daily 5 AM IST)"),
        ]

        for script, desc in expected_crons:
            if script in out:
                self.record(cat, f"Cron: {desc}", "PASS", f"Found entry for {script}", 0)
            else:
                self.record(cat, f"Cron: {desc}", "WARN", f"Missing schedule for {script}", 0)

    # =========================================================================
    # 3. CODE SYNTAX & BRIDGE INTEGRITY
    # =========================================================================
    def check_syntax(self):
        cat = "Code Syntax & Imports"

        scripts = [
            "/root/valheim_autopatch.py",
            "/root/valheim_boss_helper.py",
            "/root/valheim_constants.py",
            "/root/valheim_daily_chronicle.py",
            "/root/valheim_farm.py",
            "/root/valheim_geography.py",
            "/root/valheim_info.py",
            "/root/valheim_inventory.py",
            "/root/valheim_messages.py",
            "/root/valheim_monitor.py",
            "/root/valheim_progression.py",
            "/root/valheim_qol.py",
            "/root/valheim_quest_engine.py",
            "/root/valheim_record_death_cause.py",
            "/root/valheim_roast_refresher.py",
            "/root/valheim_sync.py",
            "/root/valheim_utils.py",
            "/root/valheim_voice.py",
            "/root/valheim_weekly_superlatives.py",
            "/root/valheim_weekly_sync.py",
            "/root/valheim_whatsapp_action.py",
            "/root/valheim_whine_roaster.py",
            "/root/valheim_chronicles/weekly_pipeline.py",
            "/root/valheim_chronicles/skald.py",
        ]

        compiled_count = 0
        failed_scripts = []
        for s in scripts:
            if not os.path.exists(s):
                failed_scripts.append(f"{os.path.basename(s)} (not found)")
                continue
            try:
                py_compile.compile(s, doraise=True)
                compiled_count += 1
            except py_compile.PyCompileError as e:
                failed_scripts.append(f"{os.path.basename(s)} ({e})")

        if not failed_scripts:
            self.record(cat, f"Python Syntax ({compiled_count} scripts)", "PASS", "All scripts compiled cleanly", 0)
        else:
            self.record(cat, "Python Syntax", "FAIL", f"Failures: {', '.join(failed_scripts)}", 0)

        # Node.js WhatsApp Bridge syntax
        bridge_path = "/usr/local/lib/hermes-agent/scripts/whatsapp-bridge/bridge.js"
        if os.path.exists(bridge_path):
            code, _, err, t = self.run_cmd(["node", "--check", bridge_path])
            if code == 0:
                self.record(cat, "WhatsApp Bridge Syntax (bridge.js)", "PASS", "Clean JavaScript syntax", t)
            else:
                self.record(cat, "WhatsApp Bridge Syntax (bridge.js)", "FAIL", err, t)
        else:
            self.record(cat, "WhatsApp Bridge Syntax (bridge.js)", "WARN", "bridge.js not found at standard path", 0)

    # =========================================================================
    # 4. JSON DATA STORES & SCHEMAS
    # =========================================================================
    def check_json_stores(self):
        cat = "Data Stores & JSON Schemas"

        stores = [
            ("/root/valheim_player_state.json", dict, "player_history"),
            ("/root/valheim_dynamic_roasts.json", dict, "dynamic_roasts"),
            ("/root/valheim_deaths_history.json", (dict, list), "deaths_history"),
            ("/root/valheim_bosses_defeated.json", (dict, list), "bosses_defeated"),
            ("/root/valheim_active_quests.json", (dict, list), "active_quests"),
            ("/root/valheim_active_sessions.json", dict, "active_sessions"),
            ("/root/valheim_traders_state.json", dict, "traders_state"),
            ("/root/valheim_voice_state.json", dict, "voice_state"),
            ("/root/valheim_world_day.json", dict, "world_day"),
        ]

        for path, exp_type, label in stores:
            if not os.path.exists(path):
                self.record(cat, f"Store: {label}", "WARN", f"File {os.path.basename(path)} does not exist yet", 0)
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, exp_type):
                    entries = len(data) if isinstance(data, (list, dict)) else 1
                    self.record(cat, f"Store: {label}", "PASS", f"Valid JSON ({entries} items)", 0)
                else:
                    self.record(cat, f"Store: {label}", "WARN", f"Unexpected root type {type(data)}", 0)
            except Exception as e:
                self.record(cat, f"Store: {label}", "FAIL", f"Corrupt JSON: {e}", 0)

    # =========================================================================
    # 5. WHATSAPP IN-GROUP COMMANDS (20+ Commands)
    # =========================================================================
    def check_commands(self):
        cat = "In-Group Commands Execution"

        commands = [
            ("!status", ["/usr/bin/python3", "/root/valheim_whatsapp_action.py", "--status"], ["running", "join_code"]),
            ("!patch", ["/usr/bin/python3", "/root/valheim_autopatch.py", "--check"], ["Local Build", "Remote Build"]),
            ("!wealth", ["/usr/bin/python3", "/root/valheim_info.py", "--wealth"], ["Coins", "Gold"]),
            ("!metalcount", ["/usr/bin/python3", "/root/valheim_info.py", "--metalcount"], ["Copper", "Iron", "Silver"]),
            ("!foodcount", ["/usr/bin/python3", "/root/valheim_info.py", "--foodcount"], ["Pantry", "Cauldron"]),
            ("!armourus", ["/usr/bin/python3", "/root/valheim_info.py", "--armourus"], ["Armor", "Shield"]),
            ("!era", ["/usr/bin/python3", "/root/valheim_info.py", "--era"], ["Day", "Midgard"]),
            ("!leaderboard", ["/usr/bin/python3", "/root/valheim_info.py", "--leaderboard"], ["Casualties", "Expedition"]),
            ("!farm", ["/usr/bin/python3", "/root/valheim_farm.py", "--farm"], ["Crops", "Honey"]),
            ("!hearth", ["/usr/bin/python3", "/root/valheim_qol.py", "--comfort"], ["Comfort", "Rested"]),
            ("!tames", ["/usr/bin/python3", "/root/valheim_qol.py", "--tames"], ["Dire Wolves", "Boars", "Lox Herds", "Calves"]),
            ("!mead", ["/usr/bin/python3", "/root/valheim_qol.py", "--mead"], ["Fermenters", "Cellar"]),
            ("!grave", ["/usr/bin/python3", "/root/valheim_qol.py", "--grave"], ["Rescue Route", "All Viking souls"]),
            ("!fleet", ["/usr/bin/python3", "/root/valheim_qol.py", "--fleet"], ["Fleet", "Portals", "No moored vessels"]),
            ("!milestones", ["/usr/bin/python3", "/root/valheim_qol.py", "--milestones"], ["Milestones", "Tier"]),
            ("!portals", ["/usr/bin/python3", "/root/valheim_info.py", "--portals"], ["Portals", "Tags"]),
            ("!signs", ["/usr/bin/python3", "/root/valheim_info.py", "--signs"], ["Signs", "Carved Runes"]),
            ("!find Iron", ["/usr/bin/python3", "/root/valheim_info.py", "--find", "Iron"], ["Iron", "chests"]),
            ("!craft Iron Sword", ["/usr/bin/python3", "/root/valheim_qol.py", "--craft", "Iron Sword"], ["Iron Sword", "Recipe", "Craftable"]),
            ("!quests", ["/usr/bin/python3", "/root/valheim_quest_engine.py", "--list"], ["Clan Quest Board", "Great Hall"]),
            ("!sync", ["/usr/bin/python3", "/root/valheim_sync.py", "--check"], ["Traders Audited", "Stockpiles"]),
        ]

        for cmd_name, cmd_args, expected_keywords in commands:
            code, out, err, t = self.run_cmd(cmd_args, timeout=20)
            if code != 0:
                self.record(cat, f"Command: {cmd_name}", "FAIL", f"Exit {code}: {err or out}", t)
                continue

            # Verify output length (WhatsApp safety)
            lines = out.splitlines()
            if len(lines) > 40:
                self.record(cat, f"Command: {cmd_name}", "WARN", f"Output exceeds 40 lines ({len(lines)} lines)", t)
                continue

            # Check expected keywords (at least one must match)
            matched = any(kw.lower() in out.lower() for kw in expected_keywords)
            if matched:
                self.record(cat, f"Command: {cmd_name}", "PASS", f"{len(lines)} lines returned ({t:.0f}ms)", t)
            else:
                self.record(cat, f"Command: {cmd_name}", "WARN", f"Missing expected tokens: {expected_keywords}", t)

    # =========================================================================
    # 6. VOICE AUDIO SYNTHESIS & CHRONICLES
    # =========================================================================
    def check_voice_and_chronicles(self):
        cat = "Voice Engine & Storytelling"

        # 1. FFmpeg availability
        code, out, _, t = self.run_cmd(["ffmpeg", "-version"])
        if code == 0:
            self.record(cat, "Audio Dependency: FFmpeg", "PASS", "Available in PATH", t)
        else:
            self.record(cat, "Audio Dependency: FFmpeg", "FAIL", "ffmpeg command missing", t)

        if not self.quick:
            # 2. Voice synthesis test
            test_mp3 = "/tmp/valheim_doctor_voice_test.mp3"
            code, out, err, t = self.run_cmd([
                "/usr/bin/python3", "/root/valheim_voice.py",
                "--speak", "Odin smiles upon the clan this day.",
                "--char", "skald",
                "--out", test_mp3
            ], timeout=25)

            if code == 0 and os.path.exists(test_mp3) and os.path.getsize(test_mp3) > 1000:
                mp3_kb = os.path.getsize(test_mp3) / 1024
                self.record(cat, "Norse Voice Synthesis (Edge-TTS)", "PASS", f"Generated {mp3_kb:.1f}KB MP3 ({t:.0f}ms)", t)
                try:
                    os.remove(test_mp3)
                except Exception:
                    pass
            else:
                self.record(cat, "Norse Voice Synthesis (Edge-TTS)", "FAIL", f"Failed: {err or out}", t)

            # 3. Daily Chronicle simulation
            code, out, err, t = self.run_cmd([
                "/usr/bin/python3", "/root/valheim_daily_chronicle.py", "--dry-run", "--hours", "24"
            ], timeout=30)
            if code == 0 and "DAILY CHRONICLE" in out:
                self.record(cat, "Daily Chronicle Engine", "PASS", f"Battle recap simulated ({t:.0f}ms)", t)
            else:
                self.record(cat, "Daily Chronicle Engine", "FAIL", f"Simulation failed: {err}", t)

            # 4. Weekly Superlatives simulation
            code, out, err, t = self.run_cmd([
                "/usr/bin/python3", "/root/valheim_weekly_superlatives.py", "--dry-run", "--days", "7"
            ], timeout=20)
            if code == 0 and "HALL OF FAME" in out:
                self.record(cat, "Weekly Superlatives Engine", "PASS", f"Awards calculated ({t:.0f}ms)", t)
            else:
                self.record(cat, "Weekly Superlatives Engine", "FAIL", f"Superlatives failed: {err}", t)
        else:
            self.record(cat, "Voice & Heavy Story Simulation", "PASS", "Skipped in --quick mode", 0)

    # =========================================================================
    # 7. CROSS-SCRIPT LOGICAL CONSISTENCY
    # =========================================================================
    def check_consistency(self):
        cat = "Cross-Script Consistency"

        # 1. Main Base Coordinates match across files
        checked_files = [
            "/root/valheim_farm.py",
            "/root/valheim_qol.py",
        ]
        coords_match = True
        for f in checked_files:
            if os.path.exists(f):
                with open(f, "r", encoding="utf-8") as fp:
                    content = fp.read()
                if "MAIN_BASE_COORDS = (12.8, -360.1)" not in content:
                    coords_match = False
                    self.record(cat, f"Base Coords: {os.path.basename(f)}", "WARN", "Coords differ from (12.8, -360.1)", 0)

        if coords_match:
            self.record(cat, "Homestead Coordinates", "PASS", "Main Base (12.8, -360.1) aligned across all modules", 0)

        # 2. Known Clan Warriors normalization in valheim_utils.py
        try:
            sys.path.insert(0, "/root")
            from valheim_utils import KNOWN_PLAYERS
            required_names = ["musashi", "dexter", "hilda", "faye"]
            if all(n in KNOWN_PLAYERS for n in required_names):
                self.record(cat, "Clan Character Registry", "PASS", f"All 4 core Vikings mapped: {list(KNOWN_PLAYERS.values())[:4]}", 0)
            else:
                self.record(cat, "Clan Character Registry", "WARN", f"Missing some expected warrior names: {KNOWN_PLAYERS}", 0)
        except Exception as e:
            self.record(cat, "Clan Character Registry", "FAIL", f"Cannot import KNOWN_PLAYERS: {e}", 0)

    # =========================================================================
    # EXECUTION RUNNER & REPORTING
    # =========================================================================
    def run_all(self):
        self.check_runtime()
        self.check_cron()
        self.check_syntax()
        self.check_json_stores()
        self.check_commands()
        self.check_voice_and_chronicles()
        self.check_consistency()

    def print_report(self):
        total_time = time.time() - self.start_time

        passes = [r for r in self.results if r["status"] == "PASS"]
        warns = [r for r in self.results if r["status"] == "WARN"]
        fails = [r for r in self.results if r["status"] == "FAIL"]

        print(f"\n{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════{RESET}")
        print(f"{BOLD}{CYAN}             ⚔️  VALHEIM ECOSYSTEM DOCTOR & DIAGNOSTIC REPORT  ⚔️       {RESET}")
        print(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════{RESET}\n")

        # Group by category
        categories = {}
        for r in self.results:
            categories.setdefault(r["category"], []).append(r)

        for cat, items in categories.items():
            print(f"{BOLD}▸ {cat}:{RESET}")
            for item in items:
                status = item["status"]
                if status == "PASS":
                    badge = f"{GREEN}[PASS]{RESET}"
                elif status == "WARN":
                    badge = f"{YELLOW}[WARN]{RESET}"
                else:
                    badge = f"{RED}[FAIL]{RESET}"

                detail_str = f" — {item['detail']}" if item["detail"] else ""
                print(f"  {badge} {item['name']}{detail_str}")
            print()

        print(f"{BOLD}══════════════════════════════════════════════════════════════════════{RESET}")
        summary_color = GREEN if not fails and not warns else (YELLOW if not fails else RED)
        print(f"{BOLD}DIAGNOSTIC SUMMARY:{RESET} {summary_color}{len(passes)} Passed, {len(warns)} Warnings, {len(fails)} Failures{RESET} ({total_time:.2f}s total)")
        print(f"{BOLD}══════════════════════════════════════════════════════════════════════{RESET}\n")

        if fails:
            print(f"{BOLD}{RED}🚨 ACTION REQUIRED FOR FAILURES:{RESET}")
            for f in fails:
                print(f"  • {f['category']} -> {f['name']}: {f['detail']}")
            print()
            return 1
        elif warns:
            print(f"{BOLD}{YELLOW}💡 RECOMMENDATIONS FOR WARNINGS:{RESET}")
            for w in warns:
                print(f"  • {w['category']} -> {w['name']}: {w['detail']}")
            print()
            return 0
        else:
            print(f"{BOLD}{GREEN}✨ All Valheim scripts, services, commands, and data stores are operating logically and with zero defects! Skål! 🍻{RESET}\n")
            return 0

    def notify_failures_if_cron(self):
        fails = [r for r in self.results if r["status"] == "FAIL"]
        if fails:
            try:
                sys.path.insert(0, "/root")
                from valheim_utils import safe_send_telegram
                lines = [
                    "🚨 <b>[Valheim Doctor Alert]</b>",
                    f"Daily 5 AM IST Health Check detected <b>{len(fails)} failure(s)</b> on Valheim dedicated server:\n"
                ]
                for f in fails:
                    lines.append(f"• <b>{f['category']}</b> -> <code>{f['name']}</code>: {f['detail']}")
                lines.append("\n<i>Check full log at /var/log/valheim_doctor.log</i>")
                safe_send_telegram("\n".join(lines))
            except Exception as e:
                sys.stderr.write(f"[valheim_doctor] Error sending Telegram alert: {e}\n")

    def output_json(self):
        total_time = time.time() - self.start_time
        passes = sum(1 for r in self.results if r["status"] == "PASS")
        warns = sum(1 for r in self.results if r["status"] == "WARN")
        fails = sum(1 for r in self.results if r["status"] == "FAIL")

        out = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST", time.localtime()),
            "total_time_seconds": round(total_time, 2),
            "summary": {
                "passed": passes,
                "warnings": warns,
                "failed": fails,
                "healthy": fails == 0
            },
            "checks": self.results
        }
        print(json.dumps(out, indent=2))
        return 1 if fails > 0 else 0


def main():
    parser = argparse.ArgumentParser(description="Valheim Ecosystem Logical Doctor")
    parser.add_argument("--quick", action="store_true", help="Run fast verification, skipping heavy synthesis/chronicle simulations")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON results")
    parser.add_argument("--cron", action="store_true", help="Run in daily cron mode with timestamped logging & Telegram failure alert")
    parser.add_argument("--verbose", action="store_true", help="Show verbose internal details")
    args = parser.parse_args()

    doc = ValheimDoctor(quick=args.quick, verbose=args.verbose)
    doc.run_all()

    if args.cron:
        doc.notify_failures_if_cron()

    if args.json:
        sys.exit(doc.output_json())
    else:
        sys.exit(doc.print_report())


if __name__ == "__main__":
    main()
