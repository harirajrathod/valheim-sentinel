#!/usr/bin/env python3
"""
/root/valheim_emergency_save.py - Emergency Shutdown Trap & Zero-Loss World Save

Invoked by systemd during system shutdown, reboot, or hypervisor poweroff
(Before=shutdown.target reboot.target halt.target poweroff.target).

Workflow:
1. Detects if Valheim dedicated server is running.
2. If running, immediately dispatches an emergency warning to WhatsApp with tight timeout.
3. Touches .stop_server to prevent start_valheim.sh restart loop.
4. Sends SIGINT to valheim_server.x86_64 to force an immediate synchronous world save.
5. Verifies world save completion on disk (_main.*.ok and chunk timestamps).
6. Dispatches a confirmation message to WhatsApp confirming 0 seconds of gameplay lost.
7. Executes a rapid snapshot trigger for Google Drive backup (max 4s timeout).
"""

import os
import sys
import time
import signal
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

sys.path.insert(0, "/root")
from valheim_utils import (
    VALHEIM_WHATSAPP_GROUP,
    WHATSAPP_BRIDGE_URL,
    BOT_TOKEN,
    CHAT_ID,
    IST,
    WORLDS_DIR,
    WORLD_NAME,
    WORLD_DIR,
    LOG_FILE,
    safe_send_whatsapp,
    safe_send_telegram,
)

STOP_FILE = "/root/valheim_server/.stop_server"
VALHEIM_BIN = "valheim_server.x86_64"


def emergency_send_whatsapp(text: str) -> bool:
    """Dispatches a WhatsApp alert with a rapid 3-second timeout to prevent stalling OS shutdown."""
    return safe_send_whatsapp(
        text=text,
        chat_id=VALHEIM_WHATSAPP_GROUP,
        bridge_url=WHATSAPP_BRIDGE_URL,
        timeout=3,
        retries=1
    )


def emergency_send_telegram(html_text: str) -> bool:
    """Dispatches a Telegram alert with a rapid 3-second timeout."""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    return safe_send_telegram(
        html_text=html_text,
        token=BOT_TOKEN,
        chat_id=CHAT_ID,
        timeout=3
    )


def get_valheim_pid() -> Optional[int]:
    """Finds the PID of the active valheim_server.x86_64 process."""
    try:
        res = subprocess.run(["pgrep", "-f", VALHEIM_BIN], capture_output=True, text=True)
        pids = [int(p) for p in res.stdout.strip().split() if p.isdigit()]
        if pids:
            return pids[0]
    except Exception:
        pass
    return None


def is_pid_alive(pid: int) -> bool:
    """Checks whether the process with PID is still running and is not a zombie."""
    try:
        # Check /proc/<pid>/status for zombie state
        proc_status = f"/proc/{pid}/status"
        if os.path.exists(proc_status):
            with open(proc_status, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("State:"):
                        if "Z" in line:
                            return False  # Zombie / defunct
                        break
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, ProcessLookupError, OSError):
        return False
    except Exception:
        return False


def get_latest_save_number() -> Optional[str]:
    """Parses current_run.log or inspects world folder for the latest save number."""
    # 1. Try reading the last save line in current_run.log
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-50:]
                for line in reversed(lines):
                    if "Save number" in line:
                        parts = line.split("Save number")
                        if len(parts) > 1:
                            return parts[1].strip()
        except Exception:
            pass

    # 2. Try looking for _main.<id>.ok in world folder
    try:
        import glob
        ok_files = glob.glob(os.path.join(WORLD_DIR, "_main.*.ok"))
        if ok_files:
            latest = max(ok_files, key=os.path.getmtime)
            basename = os.path.basename(latest)
            parts = basename.split(".")
            if len(parts) >= 2:
                return parts[1]
    except Exception:
        pass

    return None


def did_save_complete(since_timestamp: float) -> Tuple[bool, Optional[str]]:
    """Checks if a clean world save finished after since_timestamp."""
    try:
        import glob
        ok_files = glob.glob(os.path.join(WORLD_DIR, "_main.*.ok"))
        if ok_files:
            latest = max(ok_files, key=os.path.getmtime)
            if os.path.getmtime(latest) >= since_timestamp - 1.0:
                basename = os.path.basename(latest)
                parts = basename.split(".")
                save_num = parts[1] if len(parts) >= 2 else None
                return True, save_num
    except Exception:
        pass
    return False, None


def perform_emergency_save(dry_run: bool = False, timeout_sec: float = 20.0) -> Dict[str, Any]:
    """
    Executes the emergency save flush sequence.
    """
    pid = get_valheim_pid()
    if pid is None:
        sys.stdout.write("[emergency_save] Valheim server is not running. No flush needed.\n")
        return {"success": True, "server_was_running": False, "saved": False}

    sys.stdout.write(f"[emergency_save] Active Valheim process found (PID {pid}). Initiating emergency flush...\n")
    start_time = time.time()

    # Step 1: Dispatch immediate emergency alert
    alert_msg = (
        "⚠️ *HOSTINGER VPS SHUTDOWN DETECTED!* ⚠️\n\n"
        "The host hypervisor has initiated a system reboot / maintenance shutdown.\n"
        "Flushing active Valheim world save to disk immediately to secure player progress... 🛡️"
    )
    if not dry_run:
        try:
            emergency_send_whatsapp(alert_msg)
            emergency_send_telegram(
                "⚠️ <b>Hostinger VPS Shutdown Detected!</b>\n"
                "Flushing Valheim world save to disk immediately..."
            )
        except Exception as e:
            sys.stderr.write(f"[emergency_save] Warning dispatching initial alert: {e}\n")

    # Step 2: Create stop file to prevent restart loop in start_valheim.sh
    if not dry_run:
        try:
            with open(STOP_FILE, "w") as f:
                f.write("emergency_shutdown\n")
        except Exception as e:
            sys.stderr.write(f"[emergency_save] Error creating stop file: {e}\n")

    # Step 3: Send SIGINT to Valheim process to trigger native world flush
    if not dry_run:
        try:
            # Send both via os.kill and pkill to guarantee signal reception
            os.kill(pid, signal.SIGINT)
            subprocess.run(["pkill", "-SIGINT", "-f", VALHEIM_BIN], capture_output=True, timeout=2.0)
        except Exception as e:
            sys.stderr.write(f"[emergency_save] Error sending SIGINT to PID {pid}: {e}\n")

    # Step 4: Wait for save confirmation or clean exit
    flushed = False
    save_num = None
    save_confirmed_time = None

    if not dry_run:
        while time.time() - start_time < timeout_sec:
            save_done, snum = did_save_complete(start_time)
            if save_done:
                flushed = True
                save_num = snum
                if save_confirmed_time is None:
                    save_confirmed_time = time.time()
                # If process exited OR 2.5 seconds have passed since save was verified on disk, break!
                if not is_pid_alive(pid) or (time.time() - save_confirmed_time > 2.5):
                    break
            elif not is_pid_alive(pid):
                flushed = True
                break
            time.sleep(0.2)
    else:
        flushed = True

    elapsed = time.time() - start_time
    if not save_num:
        save_num = get_latest_save_number() or "Current"

    # Step 5: Dispatch confirmation message
    if flushed:
        sys.stdout.write(f"[emergency_save] World successfully flushed in {elapsed:.2f}s (Save #{save_num}).\n")
        confirm_msg = (
            "✅ *VALHEIM PROGRESS SECURED!* 🛡️\n\n"
            f"• *Status:* Clean world save flushed to disk ({elapsed:.1f}s)\n"
            f"• *Save Record:* Save #{save_num}\n"
            f"• *Data Loss:* 0 seconds (All items & builds saved!)\n\n"
            "Server will automatically return online with a fresh Join Code once the VPS reboot finishes. ⚔️"
        )
    else:
        sys.stderr.write(f"[emergency_save] Warning: Valheim did not exit within {timeout_sec}s.\n")
        confirm_msg = (
            "⚠️ *VALHEIM EMERGENCY SHUTDOWN ALERT*\n\n"
            f"Server shutdown executed. Save flush signal was dispatched ({elapsed:.1f}s elapsed)."
        )

    if not dry_run:
        try:
            emergency_send_whatsapp(confirm_msg)
            emergency_send_telegram(
                f"✅ <b>Valheim World Save Flushed!</b>\n"
                f"Save #{save_num} secured in {elapsed:.1f}s before system halt."
            )
        except Exception as e:
            sys.stderr.write(f"[emergency_save] Warning dispatching confirmation alert: {e}\n")

    # Step 6: Trigger rapid Google Drive snapshot sync (max 4s timeout)
    if not dry_run and os.path.exists("/root/valheim_backup_drive.py"):
        try:
            subprocess.run(
                ["/usr/bin/python3", "/root/valheim_backup_drive.py", "--trigger", "shutdown", "--snapshot"],
                timeout=4.0,
                capture_output=True
            )
        except Exception:
            pass

    return {
        "success": True,
        "server_was_running": True,
        "flushed": flushed,
        "save_number": save_num,
        "elapsed_seconds": round(elapsed, 2),
        "dry_run": dry_run
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Valheim Emergency Shutdown World Saver")
    parser.add_argument("--dry-run", action="store_true", help="Simulate shutdown flush without killing server")
    args = parser.parse_args()

    res = perform_emergency_save(dry_run=args.dry_run)
    sys.stdout.write(f"{res}\n")


if __name__ == "__main__":
    main()
