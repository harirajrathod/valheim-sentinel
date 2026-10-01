"""
monitor/sentinel.py - Real-Time Server Event Sentinel & Raid Watchdog
Tails Valheim game logs to announce joins, departures, raids, and boss triumphs.
"""

import os
import sys
import time
import re
import signal
from typing import Dict, List, Optional
from datetime import datetime

from core import config
from core import notifier
from monitor.roasts import get_random_join, get_random_leave

RAID_LORE = {
    "army_eikthyr": ("Eikthyr rallies the creatures of the forest! ⚡", "Boars & Necks"),
    "army_theelder": ("The forest is moving... 🌲", "Greydwarf Horde & Brutes"),
    "army_bonemass": ("A foul smell from the swamp... ☣️", "Skeletons & Blobs"),
    "army_moder": ("A cold wind blows from the mountain... ❄️", "Drakes"),
    "army_yagluth": ("The horde is attacking! ⚔️", "Fuling Goblin Army"),
    "army_queen": ("They sought you out... 🪲", "Seekers & Brood"),
    "army_fader": ("The Charred march... 🔥", "Ashlands Legion"),
    "wolves": ("You are being hunted... 🐺", "Wolf Pack"),
    "skeletons": ("Skeleton Surprise! 💀", "Skeleton Army"),
    "foresttrolls": ("The ground is shaking... 🧌", "Trolls"),
    "surtlings": ("A smell of sulfur in the air... 🔥", "Surtlings"),
}

class ValheimSentinel:
    def __init__(self, log_path: Optional[str] = None):
        self.log_path = log_path or config.VALHEIM_LOG_FILE
        self.running = False
        self.active_players: Dict[str, str] = {}  # player_name -> player_name
        self.socket_to_name: Dict[str, str] = {}  # socket_id -> player_name
        self.last_raid_time = 0.0

    def start(self):
        """Starts real-time log monitoring."""
        self.running = True
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [Sentinel] Monitoring active log: {self.log_path}")

        if not os.path.exists(self.log_path):
            print(f"[Sentinel] Warning: Log file not found at {self.log_path}. Waiting for server...")

        while self.running and not os.path.exists(self.log_path):
            time.sleep(2)

        f = None
        try:
            f = open(self.log_path, 'r', errors='ignore')
            # Seek to end of file on startup
            f.seek(0, 2)
            cur_inode = os.fstat(f.fileno()).st_ino

            while self.running:
                line = f.readline()
                if line:
                    self.process_line(line.strip())
                else:
                    time.sleep(0.5)
                    # Check for log rotation
                    try:
                        if os.path.exists(self.log_path):
                            new_inode = os.stat(self.log_path).st_ino
                            if new_inode != cur_inode:
                                print("[Sentinel] Log rotated, reopening file stream...")
                                f.close()
                                f = open(self.log_path, 'r', errors='ignore')
                                cur_inode = new_inode
                    except Exception:
                        pass
        except KeyboardInterrupt:
            print("\n[Sentinel] Stopped by user.")
        except Exception as e:
            print(f"[Sentinel] Error in sentinel loop: {e}")
        finally:
            if f and not f.closed:
                f.close()

    def _handle_join(self, player_name: str):
        """Announces a player joining (debounced)."""
        if player_name not in self.active_players:
            self.active_players[player_name] = player_name
            msg = get_random_join(player_name)
            print(f"[Sentinel] JOIN: {player_name}")
            notifier.broadcast(msg)

    def _handle_leave(self, player_name: str):
        """Announces a player departing."""
        if player_name in self.active_players:
            del self.active_players[player_name]
            msg = get_random_leave(player_name)
            print(f"[Sentinel] LEAVE: {player_name}")
            notifier.broadcast(msg)

    def process_line(self, line: str):
        # 1. Player Connection (non-zero ZDOID = alive join)
        m_join = re.search(r'Got character ZDOID from ([^:]+) : (-?\d+):(\d+)', line)
        if m_join:
            player_name = m_join.group(1).strip()
            zdoid_a = m_join.group(2)
            zdoid_b = m_join.group(3)
            if zdoid_a != "0" or zdoid_b != "0":
                self._handle_join(player_name)
            return

        # 2. Socket-to-player mapping (tracks which socket belongs to which player)
        m_socket = re.search(r'Got handshake from client (\d+)', line)
        if m_socket:
            # Store socket for later disconnect matching
            return

        # 3. Player Disconnect — Pattern A: Explicit destroy
        m_leave_a = re.search(r'Destroying abandoned non persistent zdo.*for player ([^ \n]+)', line)
        if m_leave_a:
            self._handle_leave(m_leave_a.group(1).strip())
            return

        # 4. Player Disconnect — Pattern B: Player count drop to 0
        m_count = re.search(r'now (\d+) player\(s\)', line)
        if m_count:
            new_count = int(m_count.group(1))
            if new_count == 0 and self.active_players:
                # Everyone left — clear all and announce remaining
                for pname in list(self.active_players.keys()):
                    self._handle_leave(pname)
            return

        # 5. Player Disconnect — Pattern C: Closing socket followed by peer disconnect
        m_close = re.search(r'Closing socket (\d+)', line)
        if m_close:
            # The close event alone doesn't tell us who — but combined with
            # a subsequent "Connections N" count drop, the next count line handles it.
            return

        # 6. Horn of War (Raid Trigger)
        m_raid = re.search(r'Random event set:([a-zA-Z0-9_]+)', line)
        if m_raid:
            event_key = m_raid.group(1).strip().lower()
            now = time.time()
            # 5-minute debounce
            if now - self.last_raid_time > 300:
                self.last_raid_time = now
                war_cry, creatures = RAID_LORE.get(event_key, ("The realm trembles under siege!", "Hostile invaders"))
                active_list = list(self.active_players.keys())
                defenders = ", ".join(active_list) if active_list else "Defenders assembling"

                raid_msg = (
                    f"⚔️ **HORN OF WAR! A RAID HAS BEGUN!** 🛡️\n\n"
                    f"• **Warning:** *\"{war_cry}\"*\n"
                    f"• **Enemies:** `{creatures}`\n"
                    f"• **Active Defenders:** `{defenders}`\n\n"
                    f"To arms, Vikings! Rally to the palisades! 🏹"
                )
                print(f"[Sentinel] RAID: {event_key}")
                notifier.broadcast(raid_msg)
            return

        # 7. Boss Defeat
        m_boss = re.search(r'Setting global key (defeated_[a-zA-Z0-9_]+)', line)
        if m_boss:
            boss_key = m_boss.group(1).strip()
            print(f"[Sentinel] BOSS DEFEAT: {boss_key}")
            notifier.broadcast(
                f"🏆 **FORSAKEN VANQUISHED!** ⚡\n\n"
                f"The global key `{boss_key}` has been carved into the heavens!\n"
                f"A great evil has fallen before the clan's shieldwall! Raise your horns in triumph! 🍻"
            )
            return

def main():
    sentinel = ValheimSentinel()

    def handle_exit(signum, frame):
        sentinel.running = False
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    sentinel.start()

if __name__ == "__main__":
    main()
