#!/usr/bin/env python3
"""
/root/valheim_weekly_superlatives.py
Valheim Weekly Hall of Fame & Shame — Clan Superlatives & Accolades.

Aggregates statistics from the past 7 days:
  • The Iron Jarl (Highest survival ratio: hours lived per fall)
  • The Grand Beaver (Homestead Architect: most playtime)
  • Tombstone Magnate (Valhalla's VIP: most combat falls)
  • Homestead Defender (Raid Vanguard: most base sieges defended)
  • The Naked Sprinter (Daredevil Corpse Runner: rapid succession deaths)
  • The Night Owl (Midnight Raider: most playtime 00:00-06:00 IST)
  • Realm Metrics (Total casualties, combined hours, tribal treasury)

Usage:
  python3 /root/valheim_weekly_superlatives.py --dry-run
  python3 /root/valheim_weekly_superlatives.py --post
  python3 /root/valheim_weekly_superlatives.py --days 7 --post
"""

import os
import sys
import re
import json
import glob
import struct
import argparse
import subprocess
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict

sys.path.insert(0, "/root")
from valheim_utils import (
    LOG_FILE,
    IST,
    format_player_name,
    safe_send_whatsapp,
    get_stable_hash,
)
DEATHS_FILE = "/root/valheim_deaths_history.json"

# --- Stable Hash & Inventory Helpers ---

ITEM_CATALOG = {
    'Coins': 1,
    'Amber': 5,
    'AmberPearl': 10,
    'Ruby': 20,
    'SilverNecklace': 30,
}
HASH_TO_KEY = {get_stable_hash(k): k for k in ITEM_CATALOG}
TARGET_S_ITEMS = struct.pack('<i', -938864442)

# Player-built container prefabs (chests, carts, ships)
PLAYER_CONTAINER_PREFABS = [
    'piece_chest_wood', 'piece_chest', 'piece_chest_blackmetal', 'piece_chest_private',
    'piece_chestwood', 'piece_chestblackmetal', 'piece_chestprivate',
    'piece_chestbarrel', 'piece_chestgrausten', 'piece_chestwarderobe', 'piece_chesttreasure',
    'Cart', 'VikingShip', 'Karve'
]
PACKED_PLAYER_HASHES = [struct.pack('<i', get_stable_hash(p)) for p in PLAYER_CONTAINER_PREFABS]

def scan_world_treasury():
    coins = 0
    gems = 0
    chunks = glob.glob('/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/*.chunk')
    for c in chunks:
        try:
            with open(c, 'rb') as f:
                data = f.read()
            idx = 0
            while True:
                idx = data.find(TARGET_S_ITEMS, idx)
                if idx == -1: break
                p = idx + 4
                if p + 4 > len(data): break
                payload_len = struct.unpack('<I', data[p:p+4])[0]
                p += 4
                if p + payload_len <= len(data) and payload_len >= 6:
                    payload = data[p:p+payload_len]
                    version, count = struct.unpack('<IH', payload[:6])
                    if version == 109 and count < 100:
                        window = data[max(0, idx - 80):idx]
                        if any(ph in window for ph in PACKED_PLAYER_HASHES):
                            for i in range(6, payload_len - 5):
                                cand_hash = struct.unpack('<i', payload[i+2:i+6])[0]
                                if cand_hash in HASH_TO_KEY:
                                    stack = struct.unpack('<H', payload[i:i+2])[0]
                                    if 1 <= stack <= 999:
                                        k = HASH_TO_KEY[cand_hash]
                                        val = ITEM_CATALOG[k] * stack
                                        if k == 'Coins':
                                            coins += stack
                                        else:
                                            gems += val
                idx += 4
        except Exception:
            pass
    return coins, gems

def generate_superlatives_report(days=7):
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(days=days)
    start_ist = cutoff_utc.astimezone(IST).strftime("%b %d")
    end_ist = now_utc.astimezone(IST).strftime("%b %d, %Y")

    # 1. Parse Deaths History
    deaths_history = {}
    if os.path.exists(DEATHS_FILE):
        try:
            with open(DEATHS_FILE, "r") as f:
                deaths_history = json.load(f)
        except Exception:
            pass

    week_deaths = []
    for k, v in deaths_history.items():
        ts_str = v.get("timestamp", "")
        try:
            dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
            if dt >= cutoff_utc:
                week_deaths.append((dt, format_player_name(v.get("player", "Unknown"))))
        except Exception:
            pass

    total_week_deaths = len(week_deaths)
    deaths_by_player = Counter([p for dt, p in week_deaths])

    # Calculate naked corpse runs (deaths within 180s by the same player)
    naked_runs_by_player = Counter()
    player_deaths_map = defaultdict(list)
    for dt, p in sorted(week_deaths, key=lambda x: x[0]):
        player_deaths_map[p].append(dt)
    for p, d_list in player_deaths_map.items():
        for i in range(1, len(d_list)):
            if (d_list[i] - d_list[i-1]).total_seconds() <= 180:
                naked_runs_by_player[p] += 1

    # 2. Parse Player Activity and Playtimes via journalctl
    cmd = ["journalctl", "-u", "valheim-monitor", "--since", cutoff_utc.strftime("%Y-%m-%d %H:%M:%S"), "--no-pager"]
    res = subprocess.run(cmd, capture_output=True, text=True)

    playtimes = defaultdict(float)
    night_playtimes = defaultdict(float)
    player_intervals = defaultdict(list)  # {player: [(start_utc, end_utc)]}
    def record_session(p, st, et):
        p = format_player_name(p)
        dur = (et - st).total_seconds()
        if dur > 4 * 3600:
            et = st + timedelta(hours=4)
            dur = 4 * 3600
        if dur > 0:
            playtimes[p] += dur
            player_intervals[p].append((st, et))
            cur = st
            while cur < et:
                cur_ist = cur.astimezone(IST)
                next_step = min(et, cur + timedelta(minutes=15))
                if 0 <= cur_ist.hour < 6:
                    night_playtimes[p] += (next_step - cur).total_seconds()
                cur = next_step

    active_since = {}
    for line in res.stdout.split("\n"):
        m_ts = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})", line)
        if not m_ts: continue
        try:
            dt = datetime.strptime(f"{now_utc.year} {m_ts.group(1)}", "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if "Pre-seeded active players:" in line:
            m_pre = re.search(r"Pre-seeded active players:\s*(\{[^\}]*\}|set\(\))", line)
            if m_pre:
                raw_set = m_pre.group(1)
                seeded = set() if raw_set == "set()" else set(re.findall(r"'([^']+)'", raw_set))
                for p in list(active_since.keys()):
                    if p not in seeded:
                        st = active_since.pop(p)
                        if dt > st:
                            record_session(p, st, dt)
                for p in seeded:
                    if p not in active_since:
                        active_since[p] = dt
            continue

        if "zero_flush" in line:
            for p in list(active_since.keys()):
                st = active_since.pop(p)
                if dt > st:
                    record_session(p, st, dt)
            continue

        if "Join: " in line:
            m = re.search(r"Join:\s+([^\s\(]+)", line)
            if m:
                p = m.group(1)
                if p in active_since:
                    st = active_since.pop(p)
                    if dt > st:
                        record_session(p, st, dt)
                active_since[p] = dt
        elif "Leave " in line or "Leave: " in line:
            m = re.search(r"Leave(?:\s\([^\)]+\))?:\s+([^\s]+)", line)
            if m:
                p = m.group(1)
                if p in active_since:
                    st = active_since.pop(p)
                    if dt > st:
                        record_session(p, st, dt)

    current_online = set()
    try:
        import valheim_whatsapp_action
        srv = valheim_whatsapp_action.get_server_info()
        if srv.get("running"):
            current_online = set(srv.get("players", []))
    except Exception:
        pass

    for p, st in active_since.items():
        if p in current_online and now_utc > st:
            dur = (now_utc - st).total_seconds()
            if dur <= 12 * 3600:
                record_session(p, st, now_utc)

    total_exploration_seconds = sum(playtimes.values())
    total_exploration_hours = total_exploration_seconds / 3600

    # 3. Parse Raids & Siege Defense
    raids = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", errors="ignore") as f:
                for line in f:
                    if "Random event set:" in line:
                        m = re.match(r"^(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}):\s+Random event set:(\w+)", line)
                        if m:
                            dt = datetime.strptime(m.group(1), "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
                            if dt >= cutoff_utc:
                                raids.append((dt, m.group(2)))
        except Exception:
            pass

    raid_defense_counts = Counter()
    for raid_dt, raid_name in raids:
        for p, intervals in player_intervals.items():
            for st, et in intervals:
                if st - timedelta(seconds=60) <= raid_dt <= et + timedelta(seconds=60):
                    raid_defense_counts[p] += 1
                    break

    # 4. Determine Award Winners
    # The Grand Beaver (Homestead Architect: Most Playtime)
    grand_beaver = None
    if playtimes:
        beaver_p, beaver_sec = max(playtimes.items(), key=lambda x: x[1])
        if beaver_sec >= 1800:
            hrs = round(beaver_sec / 3600, 1)
            grand_beaver = (format_player_name(beaver_p), f"{hrs}h logged in the realm")

    # Tombstone Magnate (Valhalla VIP: Most Falls)
    tombstone_magnate = None
    if deaths_by_player:
        tomb_p, tomb_c = deaths_by_player.most_common(1)[0]
        tombstone_magnate = (format_player_name(tomb_p), f"{tomb_c} falls in battle")

    # The Iron Jarl (Apex Survivor: Highest hours lived per death, min 1h played)
    iron_jarl = None
    survivor_scores = []
    for p, sec in playtimes.items():
        if sec >= 3600:
            hrs = sec / 3600
            d_count = deaths_by_player.get(p, 0)
            score = (hrs * 2.0) if d_count == 0 else (hrs / d_count)
            survivor_scores.append((p, score, hrs, d_count))

    if survivor_scores:
        survivor_scores.sort(key=lambda x: x[1], reverse=True)
        jarl_p, score, hrs, d_count = survivor_scores[0]
        if d_count == 0:
            iron_jarl = (format_player_name(jarl_p), f"{round(hrs, 1)}h played with 0 falls (Flawless!)")
        else:
            iron_jarl = (format_player_name(jarl_p), f"{round(score, 1)}h lived per Valhalla fall")

    # The Naked Sprinter (Corpse Runner: rapid deaths)
    naked_sprinter = None
    if naked_runs_by_player:
        sprinter_p, runs = naked_runs_by_player.most_common(1)[0]
        naked_sprinter = (format_player_name(sprinter_p), f"{runs} rapid tombstone recovery falls")
    elif deaths_by_player:
        # Fallback to someone with multiple deaths
        p_top = deaths_by_player.most_common(1)[0][0]
        naked_sprinter = (format_player_name(p_top), "Frequent visitor to their own gravestones")

    # Homestead Defender (Raid Vanguard)
    homestead_defender = None
    if raid_defense_counts:
        top_def_count = max(raid_defense_counts.values())
        top_defenders = [p for p, c in raid_defense_counts.items() if c == top_def_count]
        def_names = " & ".join(f"*{format_player_name(p)}*" for p in sorted(top_defenders))
        homestead_defender = (def_names, f"Stood guard during {top_def_count} base siege{'s' if top_def_count != 1 else ''}")

    # The Night Owl (Midnight Raider: 00:00 - 06:00 IST)
    night_owl = None
    if night_playtimes:
        owl_p, owl_sec = max(night_playtimes.items(), key=lambda x: x[1])
        if owl_sec >= 1800:
            owl_hrs = round(owl_sec / 3600, 1)
            night_owl = (format_player_name(owl_p), f"{owl_hrs}h prowling between midnight and dawn")

    # 5. Treasury Net Worth
    coins, gems = scan_world_treasury()
    total_wealth = coins + gems

    # 6. Compose Message
    lines = [
        "🏆👑 *VALHEIM WEEKLY HALL OF FAME & SHAME* 👑🏆",
        f"_{start_ist} – {end_ist} • Chapter 8 Awards_",
        ""
    ]

    if iron_jarl:
        lines.append("🛡️ *The Iron Jarl (Apex Survivor)*")
        lines.append(f"• Winner: *{iron_jarl[0]}* ({iron_jarl[1]})")
        lines.append("_Steadfast warrior who kept shield up and boots on the ground._")
        lines.append("")

    if grand_beaver:
        lines.append("🪓 *The Grand Beaver (Homestead Architect)*")
        lines.append(f"• Winner: *{grand_beaver[0]}* ({grand_beaver[1]})")
        lines.append("_Felled ancient timbers, quarrying rock and feeding the hearth._")
        lines.append("")

    if tombstone_magnate:
        lines.append("🪦 *Tombstone Magnate (Valhalla's VIP)*")
        lines.append(f"• Winner: *{tombstone_magnate[0]}* ({tombstone_magnate[1]})")
        lines.append("_Odin's Valkyries have a reserved front-row banquet seat for them._")
        lines.append("")

    if homestead_defender:
        lines.append("🏹 *Homestead Defender (Raid Vanguard)*")
        lines.append(f"• Winner: {homestead_defender[0]} ({homestead_defender[1]})")
        lines.append("_Rallied to the palisades when the horn of war sounded._")
        lines.append("")

    if naked_sprinter:
        lines.append("🩲 *The Naked Sprinter (Corpse Run Champion)*")
        lines.append(f"• Winner: *{naked_sprinter[0]}* ({naked_sprinter[1]})")
        lines.append("_Sprinted across the biomes in loincloth and optimism._")
        lines.append("")

    if night_owl:
        lines.append("🦉 *The Night Owl (Midnight Raider)*")
        lines.append(f"• Winner: *{night_owl[0]}* ({night_owl[1]})")
        lines.append("_Haunting the black forests while the rest of Midgard sleeps._")
        lines.append("")

    lines.append("📊 *Weekly Realm Metrics:*")
    lines.append(f"• *Total Casualties:* {total_week_deaths} fallen warriors")
    lines.append(f"• *Expedition Playtime:* {round(total_exploration_hours, 1)} combined clan hours")
    lines.append(f"• *Tribal Net Worth:* ~{total_wealth:,} Gold ({coins:,} Coins + {gems:,} Gems)")
    lines.append("")
    lines.append("_May your mead be sweet and your axes razor-sharp in the week ahead! Skål!_ 🍻⚔️")

    return "\n".join(lines)

def post_to_whatsapp(text: str) -> bool:
    success = safe_send_whatsapp(text, timeout=15, retries=2)
    if success:
        print("Successfully posted Weekly Superlatives to WhatsApp group.")
    else:
        print("Failed to post Weekly Superlatives to WhatsApp group.", file=sys.stderr)
    return success

def main():
    parser = argparse.ArgumentParser(description="Valheim Weekly Superlatives")
    parser.add_argument("--dry-run", action="store_true", help="Print superlatives to stdout without posting")
    parser.add_argument("--post", action="store_true", help="Post superlatives to WhatsApp group")
    parser.add_argument("--days", type=int, default=7, help="Number of days to analyze (default: 7)")
    args = parser.parse_args()

    report = generate_superlatives_report(days=args.days)

    if args.post and not args.dry_run:
        print("Posting Weekly Superlatives to WhatsApp...")
        post_to_whatsapp(report)
    else:
        print("=== VALHEIM WEEKLY SUPERLATIVES PREVIEW ===")
        print(report)
        print("===========================================")

if __name__ == "__main__":
    main()
