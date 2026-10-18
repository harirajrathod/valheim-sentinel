#!/usr/bin/env python3
"""
/root/valheim_daily_chronicle.py
Daily Valheim Battle Chronicle & War Journal generator for WhatsApp.

Parses server events, raids, player combat deaths, dungeon discoveries,
and player activity over the past 24 hours, and posts a formatted Viking
digest to the WhatsApp group 'Valheim - Chapter 8 - Deep North'.

Usage:
  python3 /root/valheim_daily_chronicle.py --dry-run
  python3 /root/valheim_daily_chronicle.py --post
  python3 /root/valheim_daily_chronicle.py --hours 24 --post
"""

import os
import sys
import re
import json
import argparse
import subprocess
import glob
import struct
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/root")
from valheim_utils import (
    LOG_FILE,
    IST,
    format_player_name,
    safe_send_whatsapp,
    get_stable_hash,
)
from valheim_constants import PATTERNS

RAID_LORE = {
    "army_eikthyr": ("Eikthyr rallies the creatures of the forest! ⚡", "Boars & Necks"),
    "army_theelder": ("The forest is moving... 🌲", "Greydwarf Horde & Brutes"),
    "army_bonemass": ("A foul smell from the swamp... ☣️", "Skeletons & Blobs"),
    "blobs": ("A foul smell from the swamp... ☣️", "Blobs & Oozers"),
    "army_moder": ("A cold wind blows from the mountain... ❄️", "Drakes"),
    "army_goblin": ("The horde is attacking! ⚔️", "Fuling Goblin Army"),
    "army_yagluth": ("The horde is attacking! ⚔️", "Fuling Goblin Army"),
    "army_queen": ("They sought you out... 🪲", "Seekers & Brood"),
    "army_fader": ("The Charred march... 🔥", "Ashlands Legion"),
    "army_fimbulbringer": ("The frost bites deep... ❄️", "Jotun Legion"),
    "wolves": ("You are being hunted... 🐺", "Wolf Pack"),
    "skeletons": ("Skeleton Surprise! 💀", "Skeleton Army"),
    "foresttrolls": ("The ground is shaking... 🧌", "Trolls"),
    "surtlings": ("A smell of sulfur in the air... 🔥", "Surtlings"),
    "bats": ("You stirred the cauldron... 🦇", "Bat Swarm"),
    "ghosts": ("A cold chill runs down your spine... 👻", "Spectres & Wraiths")
}

LOCATION_DEFS = [
    # Prefix, Clean Name, Emoji, Biome, is_major_dungeon
    # Note: Specific prefixes must come before shorter ones!
    ("SunkenCrypt", "Sunken Crypt", "🗝️", "Swamp", True),
    ("Crypt", "Burial Chamber", "💀", "Black Forest", True),
    ("MountainCave", "Frost Cave", "🧊", "Mountains", True),
    ("TrollCave", "Troll Cave", "🧌", "Black Forest", True),
    ("GoblinCamp", "Fuling Village", "🏕️", "Plains", True),
    ("InfestedMine", "Infested Mine", "🕸️", "Mistlands", True),
    ("CharredFortress", "Charred Fortress", "⚔️", "Ashlands", True),
    ("Morkhalla", "Mörkhalla Dungeon", "🏰", "Deep North", True),
    ("WindingTunnel", "Winding Tunnels", "⛏️", "Deep North", True),
    ("AesirPassage", "Aesir Passage", "❄️", "Deep North", True),
    ("Hildir", "Hildir's Camp", "👗", "Meadows", True),
    ("BogWitch", "Bog Witch's Camp", "🧙‍♀️", "Swamp", True),
    ("Haldor", "Haldor's Camp", "💰", "Black Forest", True),
    ("TarPit", "Tar Pit", "⚫", "Plains", True),
    ("MountainGrave", "Mountain Grave", "🪦", "Mountains", True),
    ("StoneTowerRuins", "Ancient Stone Tower", "🏰", "Ruins", False),
    ("StoneTower", "Ancient Stone Tower", "🏰", "Ruins", False),
    ("StoneHouse", "Abandoned Stone House", "🏚️", "Ruins", False),
    ("Ruin", "Ancient Ruins", "🏛️", "Ruins", False),
]

def get_location_meta(raw_name):
    if not isinstance(raw_name, str):
        return str(raw_name), "📍", "Wilderness", False
    for prefix, name, icon, biome, is_major in LOCATION_DEFS:
        if raw_name.startswith(prefix):
            return name, icon, biome, is_major
    return raw_name, "📍", "Wilderness", False

def clean_location(raw_name):
    name, icon, biome, _ = get_location_meta(raw_name)
    if icon == "📍":
        return f"📍 *{raw_name}*"
    return f"{icon} *{name}* ({biome})"

def is_server_running():
    try:
        res = subprocess.run(["pgrep", "-f", "valheim_server.x86_64"], capture_output=True, text=True)
        return bool(res.stdout.strip())
    except Exception:
        return False

def is_crossplay_configured():
    start_script = "/root/valheim_server/start_valheim.sh"
    try:
        if os.path.exists(start_script):
            with open(start_script, "r", encoding="utf-8", errors="ignore") as f:
                return "-crossplay" in f.read()
    except Exception:
        pass
    return False


def get_active_join_code():
    if not is_crossplay_configured():
        return "Disabled"
    if not os.path.exists(LOG_FILE):
        return "Unknown"
    try:
        with open(LOG_FILE, "r", errors="ignore") as f:
            lines = f.readlines()
        for line in reversed(lines):
            m = re.search(r"registered with join code\s+(\d+)", line)
            if m:
                return m.group(1)
            m_alt = re.search(r"join code\s+(\d+)", line)
            if m_alt:
                return m_alt.group(1)
    except Exception:
        pass
    return "Unknown"

def parse_player_activity(cutoff_utc, now_utc):
    cutoff_str = cutoff_utc.strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Determine who was online immediately prior to cutoff
    cmd_pre = ["journalctl", "-u", "valheim-monitor", "--until", cutoff_str, "-n", "60", "--no-pager"]
    res_pre = subprocess.run(cmd_pre, capture_output=True, text=True)
    
    initial_online = set()
    for line in res_pre.stdout.split("\n"):
        if "Pre-seeded active players:" in line:
            m_pre = re.search(r"Pre-seeded active players:\s*(\{[^\}]*\}|set\(\))", line)
            if m_pre:
                raw_set = m_pre.group(1)
                initial_online = set() if raw_set == "set()" else set(re.findall(r"'([^']+)'", raw_set))
            continue
        if "zero_flush" in line:
            initial_online.clear()
            continue
        if "Join: " in line:
            m = re.search(r"Join:\s+([^\s\(]+)", line)
            if m:
                initial_online.add(m.group(1))
        elif "Leave " in line or "Leave: " in line:
            m = re.search(r"Leave(?:\s\([^\)]+\))?:\s+([^\s]+)", line)
            if m:
                initial_online.discard(m.group(1))
                
    # 2. Parse events in window
    cmd = ["journalctl", "-u", "valheim-monitor", "--since", cutoff_str, "--no-pager"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    player_sessions = {}  # {player: [(start, end)]}
    active_since = {p: cutoff_utc for p in initial_online}
    
    timeline = []  # [(time, delta, player)]
    for p in initial_online:
        timeline.append((cutoff_utc, +1, p))
        
    for line in res.stdout.split("\n"):
        if not line.strip():
            continue
        m_ts = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})", line)
        if not m_ts:
            continue
        ts_raw = m_ts.group(1)
        try:
            dt = datetime.strptime(f"{now_utc.year} {ts_raw}", "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
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
                            dur = (dt - st).total_seconds()
                            if dur > 4 * 3600:
                                end_t = st + timedelta(hours=4)
                                player_sessions.setdefault(p, []).append((st, end_t))
                                timeline.append((end_t, -1, p))
                            else:
                                player_sessions.setdefault(p, []).append((st, dt))
                                timeline.append((dt, -1, p))
                for p in seeded:
                    if p not in active_since:
                        active_since[p] = dt
                        timeline.append((dt, +1, p))
            continue

        if "zero_flush" in line:
            for p in list(active_since.keys()):
                st = active_since.pop(p)
                if dt > st:
                    dur = (dt - st).total_seconds()
                    if dur > 4 * 3600:
                        end_t = st + timedelta(hours=4)
                        player_sessions.setdefault(p, []).append((st, end_t))
                        timeline.append((end_t, -1, p))
                    else:
                        player_sessions.setdefault(p, []).append((st, dt))
                        timeline.append((dt, -1, p))
            continue
            
        if "Join: " in line:
            m = re.search(r"Join:\s+([^\s\(]+)", line)
            if m:
                p = m.group(1)
                if p in active_since:
                    st = active_since.pop(p)
                    dur = (dt - st).total_seconds()
                    if dur > 4 * 3600:
                        end_t = st + timedelta(hours=4)
                        player_sessions.setdefault(p, []).append((st, end_t))
                        timeline.append((end_t, -1, p))
                    elif dt > st:
                        player_sessions.setdefault(p, []).append((st, dt))
                        timeline.append((dt, -1, p))
                    timeline.append((dt, +1, p))
                else:
                    timeline.append((dt, +1, p))
                active_since[p] = dt
        elif "Leave " in line or "Leave: " in line:
            m = re.search(r"Leave(?:\s\([^\)]+\))?:\s+([^\s]+)", line)
            if m:
                p = m.group(1)
                if p in active_since:
                    start_t = active_since.pop(p)
                    if dt > start_t:
                        dur = (dt - start_t).total_seconds()
                        if dur > 4 * 3600:
                            end_t = start_t + timedelta(hours=4)
                            player_sessions.setdefault(p, []).append((start_t, end_t))
                            timeline.append((end_t, -1, p))
                        else:
                            player_sessions.setdefault(p, []).append((start_t, dt))
                            timeline.append((dt, -1, p))

    # Cross-reference with live server info so offline players don't accumulate ghost hours
    current_online = set()
    try:
        import valheim_whatsapp_action
        srv = valheim_whatsapp_action.get_server_info()
        if srv.get("running"):
            current_online = set(srv.get("players", []))
    except Exception:
        pass

    for p, start_t in active_since.items():
        if p in current_online and now_utc > start_t:
            dur = (now_utc - start_t).total_seconds()
            if dur <= 12 * 3600:
                player_sessions.setdefault(p, []).append((start_t, now_utc))
                timeline.append((now_utc, -1, p))

    # Calculate concurrency
    timeline.sort(key=lambda x: x[0])
    current_set = set()
    peak_count = 0
    peak_time = None
    peak_players = []
    
    for dt, delta, p in timeline:
        if delta > 0:
            current_set.add(p)
        else:
            current_set.discard(p)
        if len(current_set) > peak_count:
            peak_count = len(current_set)
            peak_time = dt
    merged_sessions = {}
    for p, s_list in player_sessions.items():
        np = format_player_name(p)
        merged_sessions.setdefault(np, []).extend(s_list)
        
    return merged_sessions, peak_count, peak_time, peak_players

def parse_server_events(cutoff_utc):
    raids = []
    deaths = []
    locations = []
    boss_defeats = []
    
    boss_re = PATTERNS["boss_defeat_chronicle"]

    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", errors="ignore") as f:
            for line in f:
                m_ts = PATTERNS["ts_line"].match(line)
                if not m_ts:
                    continue
                ts_str = m_ts.group(1)
                try:
                    dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                    
                if dt < cutoff_utc:
                    continue
                    
                if "Random event set:" in line:
                    m_raid = PATTERNS["raid_event"].search(line)
                    if m_raid:
                        raids.append((dt, m_raid.group(1)))
                        
                if ": 0:0" in line:
                    m_death = PATTERNS["zdo_death"].search(line)
                    if m_death:
                        pname = m_death.group(1).strip()
                        if pname and pname != "0":
                            deaths.append((dt, format_player_name(pname)))
                            
                if "Placed location" in line:
                    m_loc = PATTERNS["placed_location"].search(line)
                    if m_loc:
                        locations.append((dt, m_loc.group(1), m_loc.group(2), m_loc.group(3)))

                m_b = boss_re.search(line)
                if m_b:
                    b_key = m_b.group(1).lower()
                    if not any(b[1] == b_key for b in boss_defeats):
                        boss_defeats.append((dt, b_key))

    # Cross-reference with valheim_boss_battles.json for recent boss fights
    try:
        from valheim_boss_helper import load_boss_battles
        battles = load_boss_battles()
        for b_key, b_data in battles.items():
            ts_str = b_data.get("defeat_time_utc")
            if ts_str:
                dt_b = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt_b >= cutoff_utc:
                    if not any(b[1] == b_key for b in boss_defeats):
                        boss_defeats.append((dt_b, b_key))
    except Exception:
        pass

    boss_defeats.sort(key=lambda x: x[0])
    return raids, deaths, locations, boss_defeats

def determine_death_cause(d_time, player, raids, locations, all_deaths):
    # 1. Rapid death by the same player (failed corpse run / naked tombstone recovery)
    same_recent = [
        d for d, name in all_deaths 
        if name == player and d < d_time and (d_time - d).total_seconds() <= 180
    ]
    if same_recent:
        return "Failed Corpse Run / Tombstone Recovery"

    # 2. Squad ambush / heavy team skirmish (fellow warrior died within 2.5 min)
    close_fellows = [
        name for d, name in all_deaths 
        if name != player and abs((d_time - d).total_seconds()) <= 150
    ]
    if close_fellows:
        fellows_str = ", ".join(sorted(set(close_fellows)))
        return f"Squad Ambush / Heavy Skirmish (alongside _{fellows_str}_)"

    # 3. Active raid defense (within 25 min of a raid triggering)
    for r_time, r_code in raids:
        delta_min = (d_time - r_time).total_seconds() / 60
        if 0 <= delta_min <= 25:
            title, enemy = RAID_LORE.get(r_code, (r_code, "Hostile forces"))
            return f"Base Defense: *{title}* ({enemy})"

    # 4. Recent POI / dungeon discovery (within 15 min of placement)
    for l_time, raw, _, _ in reversed(locations):
        delta_min = (d_time - l_time).total_seconds() / 60
        if 0 <= delta_min <= 15:
            cleaned_loc = clean_location(raw)
            return f"Frontier Expedition ({cleaned_loc})"

    # 5. General field combat or environmental hazard
    return "Wilderness Combat / Environmental Hazard"

DEATHS_HISTORY_FILE = "/root/valheim_deaths_history.json"

def get_all_time_deaths(dry_run=False):
    history = {}
    if os.path.exists(DEATHS_HISTORY_FILE):
        try:
            with open(DEATHS_HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            pass

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", errors="ignore") as f:
                for line in f:
                    if ": 0:0" in line:
                        m = re.search(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}): Got character ZDOID from ([^:]+) : 0:0", line)
                        if m:
                            ts, p = m.group(1), m.group(2).strip()
                            if p and p != "0":
                                key = f"{ts}_{p}"
                                if key not in history:
                                    history[key] = {"timestamp": ts, "player": p}
            if not dry_run:
                with open(DEATHS_HISTORY_FILE, "w") as f:
                    json.dump(history, f, indent=2)
        except Exception:
            pass

    from collections import Counter
    counts = Counter([format_player_name(v["player"]) for v in history.values() if v.get("player")])
    total = len(history)
    return total, counts

def load_death_causes():
    """
    Returns a dict mapping (datetime_utc, player) -> cause string.
    """
    causes = {}
    if os.path.exists(DEATHS_HISTORY_FILE):
        try:
            with open(DEATHS_HISTORY_FILE, "r") as f:
                history = json.load(f)
            for k, v in history.items():
                c = v.get("cause")
                p = v.get("player")
                ts = v.get("timestamp")
                if c and p and ts:
                    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                        try:
                            dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                            causes[(dt, p)] = c.strip()
                            break
                        except ValueError:
                            pass
        except Exception:
            pass
    return causes

def lookup_death_cause(d_time, player, causes_dict, tolerance_seconds=120):
    if (d_time, player) in causes_dict:
        return causes_dict[(d_time, player)]
    for (dt, p), c in causes_dict.items():
        if p.lower() == player.lower() and abs((d_time - dt).total_seconds()) <= tolerance_seconds:
            return c
    return None

ITEM_CATALOG = {
    'Coins': ('🪙 Coins (Gold)', 'treasure'),
    'Stone': ('🪨 Stone', 'resource'),
    'Wood': ('🪵 Wood', 'resource'),
    'FineWood': ('🌳 Fine Wood', 'resource'),
    'RoundLog': ('🌲 Core Wood', 'resource'),
    'Resin': ('🌲 Resin', 'material'),
    'ArrowFlint': ('🏹 Flinthead Arrows', 'weapon'),
    'Mushroom': ('🍄 Mushrooms', 'food'),
    'Feathers': ('🪶 Feathers', 'material'),
    'ArrowFire': ('🔥 Fire Arrows', 'weapon'),
    'GreydwarfEye': ('👁️ Greydwarf Eyes', 'material'),
    'Honey': ('🍯 Honey', 'food'),
    'BoneFragments': ('🦴 Bone Fragments', 'material'),
    'LeatherScraps': ('📜 Leather Scraps', 'material'),
    'Flint': ('🪓 Flint', 'resource'),
    'Amber': ('💎 Amber', 'treasure'),
    'Ruby': ('💎 Rubies', 'treasure'),
    'AmberPearl': ('🦪 Amber Pearls', 'treasure'),
    'SilverNecklace': ('👑 Silver Necklaces', 'treasure'),
    'DeerHide': ('🦌 Deer Hides', 'material'),
    'TrollHide': ('🧌 Troll Hides', 'material'),
    'Copper': ('Copper Bars', 'metal'),
    'CopperOre': ('Copper Ore', 'metal'),
    'Tin': ('Tin Bars', 'metal'),
    'TinOre': ('Tin Ore', 'metal'),
    'Bronze': ('Bronze Bars', 'metal'),
    'Iron': ('Iron Bars', 'metal'),
    'IronScrap': ('Scrap Iron', 'metal'),
    'Silver': ('Silver Bars', 'metal'),
    'SilverOre': ('Silver Ore', 'metal'),
    'BlackMetal': ('Black Metal', 'metal'),
    'BlackMetalScrap': ('Black Metal Scrap', 'metal'),
    'Flametal': ('Flametal Bars', 'metal'),
    'FlametalOre': ('Flametal Ore', 'metal'),
    'Obsidian': ('Obsidian', 'metal'),
    'SurtlingCore': ('Surtling Cores', 'metal'),
    'LinenThread': ('Linen Thread', 'material'),
    'WolfPelt': ('Wolf Pelts', 'material'),
}


HASH_TO_ITEM = {get_stable_hash(name): name for name in ITEM_CATALOG}
TARGET_S_ITEMS = struct.pack('<i', -938864442)

# Player-built container prefabs (chests, carts, ships)
PLAYER_CONTAINER_PREFABS = [
    'piece_chest_wood', 'piece_chest', 'piece_chest_blackmetal', 'piece_chest_private',
    'piece_chestwood', 'piece_chestblackmetal', 'piece_chestprivate',
    'piece_chestbarrel', 'piece_chestgrausten', 'piece_chestwarderobe', 'piece_chesttreasure',
    'Cart', 'VikingShip', 'Karve'
]
PACKED_PLAYER_HASHES = [struct.pack('<i', get_stable_hash(p)) for p in PLAYER_CONTAINER_PREFABS]

def scan_inventory_status():
    from valheim_inventory import scan_world_inventory
    totals, container_count = scan_world_inventory()

    top5 = []
    for k, cnt in sorted(totals.items(), key=lambda x: x[1], reverse=True):
        if k in ITEM_CATALOG:
            top5.append((ITEM_CATALOG[k][0], cnt))
        else:
            top5.append((k, cnt))
        if len(top5) >= 5:
            break

    metal_items = []
    cop = totals.get('Copper', 0)
    cop_ore = totals.get('CopperOre', 0)
    if cop > 0 or cop_ore > 0:
        metal_items.append(f"{cop + cop_ore} Copper ({cop} bars + {cop_ore} ore)")

    tin = totals.get('Tin', 0)
    tin_ore = totals.get('TinOre', 0)
    if tin > 0 or tin_ore > 0:
        metal_items.append(f"{tin + tin_ore} Tin ({tin} bars + {tin_ore} ore)")

    brz = totals.get('Bronze', 0)
    if brz > 0:
        metal_items.append(f"{brz} Bronze")

    iron = totals.get('Iron', 0) + totals.get('IronScrap', 0)
    if iron > 0:
        metal_items.append(f"{iron} Iron")

    sil_bars = totals.get('Silver', 0)
    sil_ore = totals.get('SilverOre', 0)
    if sil_bars > 0 or sil_ore > 0:
        metal_items.append(f"{sil_bars + sil_ore} Silver ({sil_bars} bars + {sil_ore} ore)")

    bm_bars = totals.get('BlackMetal', 0)
    bm_scrap = totals.get('BlackMetalScrap', 0)
    if bm_bars > 0 or bm_scrap > 0:
        metal_items.append(f"{bm_bars + bm_scrap} Black Metal ({bm_bars} bars + {bm_scrap} scrap)")

    flametal = totals.get('Flametal', 0) + totals.get('FlametalOre', 0)
    if flametal > 0:
        metal_items.append(f"{flametal} Flametal")

    obs = totals.get('Obsidian', 0)
    if obs > 0:
        metal_items.append(f"{obs} Obsidian")

    cores = totals.get('SurtlingCore', 0)
    if cores > 0:
        metal_items.append(f"{cores} Surtling Cores")

    return top5, metal_items, container_count

def generate_chronicle(hours=24, save_story_to_master=False, dry_run=False):
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(hours=hours)
    
    now_ist = now_utc.astimezone(IST)
    cutoff_ist = cutoff_utc.astimezone(IST)
    
    server_running = is_server_running()
    join_code = get_active_join_code()
    
    player_sessions, peak_count, peak_time, peak_players = parse_player_activity(cutoff_utc, now_utc)
    raids, deaths, locations, boss_defeats = parse_server_events(cutoff_utc)
    
    status_icon = "🟢" if server_running else "🔴"
    status_text = "Online & Ready" if server_running else "Offline"
    
    msg_lines = [
        "⚔️📜 *VALHEIM DAILY CHRONICLE* 📜⚔️",
        f"_{cutoff_ist.strftime('%d %b, %H:%M')} — {now_ist.strftime('%d %b, %H:%M IST')}_",
        "",
        "🏰 *Realm Status*",
        f"• *Status:* {status_icon} {status_text}",
    ]
    if join_code == "Disabled":
        msg_lines.extend([
            "• *Network:* Direct Steam Sockets (`72.62.227.29:2458`)",
            "• *World:* `Valheim10` (Direct Steam)",
            ""
        ])
    else:
        msg_lines.extend([
            f"• *Join Code:* `{join_code}` | *Port:* `2458`",
            "• *World:* `Valheim10` (Crossplay Active)",
            ""
        ])
    
    # --- Raids & Sieges ---
    msg_lines.append("🛡️ *Raids & Sieges*")
    if raids:
        for r_time, r_code in raids:
            r_ist = r_time.astimezone(IST).strftime("%H:%M IST")
            title, enemy = RAID_LORE.get(r_code, (f"Raid: {r_code}", "Hostile forces"))
            
            # Find who was online during raid
            defenders = []
            for p, s_list in player_sessions.items():
                for s, e in s_list:
                    if s <= r_time <= e:
                        defenders.append(p)
                        break
            defenders_str = f"Defenders: _{', '.join(sorted([format_player_name(d) for d in defenders]))}_" if defenders else "Defenders: _None recorded_"
            msg_lines.append(f"• *{r_ist}* — *{title}* ({enemy})\n  ↳ {defenders_str}")
    else:
        msg_lines.append("• _The realm was peaceful. No enemy warhorns sounded across the meadows._")
    msg_lines.append("")
    
    # --- Hall of Valhalla (Battle Storyline & All-Time Counter) ---
    all_time_total, all_time_counts = get_all_time_deaths(dry_run=dry_run)
    msg_lines.append(f"💀 *Hall of Valhalla ({len(deaths)} Falls in 24h | {all_time_total} All-Time)*")
    msg_lines.append("")

    if deaths:
        death_causes = load_death_causes()
        battle_events = []
        handled_indices = set()

        # 0. Boss Battle Confrontations
        for b_time, b_code in boss_defeats:
            b_deaths = []
            for idx, (d_time, p) in enumerate(deaths):
                delta = (b_time - d_time).total_seconds() / 60
                if 0 <= delta <= 45:
                    b_deaths.append((d_time, p))
                    handled_indices.add(idx)
            if b_deaths:
                start_ist = b_deaths[0][0].astimezone(IST).strftime("%H:%M")
                end_ist = b_time.astimezone(IST).strftime("%H:%M IST")
                time_range = f"_{start_ist} IST_" if start_ist == end_ist else f"_{start_ist} – {end_ist}_"
                from valheim_boss_helper import BOSS_DATA
                b_info = BOSS_DATA.get(b_code, {})
                b_name = b_info.get("name", b_code.replace("defeated_", "").title())
                
                from collections import Counter
                p_counts = Counter([p for _, p in b_deaths])
                b_bullets = [
                    f"• The clan rallied against *{b_name}* at the ancient altar!",
                    f"• *Total Casualties:* {len(b_deaths)} falls across {len(p_counts)} warriors."
                ]
                for p, c in p_counts.most_common():
                    f_str = f"{c} fall" if c == 1 else f"{c} falls"
                    b_bullets.append(f"  💀 *{format_player_name(p)}:* {f_str}")
                b_bullets.append(f"• 🏆 *Outcome:* *{b_name}* was VANQUISHED! Claimed *{b_info.get('reward', 'Spoils')}*! Skål! 🍻")
                battle_events.append({
                    "title": f"🏆⚡ *The Epic Confrontation: The Fall of {b_name}* {time_range}",
                    "bullets": b_bullets
                })

        # 1. Raid Sieges
        for r_time, r_code in raids:
            title, enemy = RAID_LORE.get(r_code, (r_code, "Hostile forces"))
            r_deaths = []
            for idx, (d_time, p) in enumerate(deaths):
                delta = (d_time - r_time).total_seconds() / 60
                if 0 <= delta <= 25:
                    r_deaths.append((d_time, p))
                    handled_indices.add(idx)
            if r_deaths:
                start_ist = r_deaths[0][0].astimezone(IST).strftime("%H:%M")
                end_ist = r_deaths[-1][0].astimezone(IST).strftime("%H:%M IST")
                time_range = f"_{start_ist} IST_" if start_ist == end_ist else f"_{start_ist} – {end_ist}_"
                p_names = sorted(list(set([p for _, p in r_deaths])))
                p_str = ", ".join([f"*{format_player_name(name)}*" for name in p_names])
                battle_events.append({
                    "title": f"🌲 *The Siege of the Homestead* ({title}) {time_range}",
                    "bullets": [f"• {p_str} fell holding the line against the {enemy}."]
                })

        # 2. Skirmish Clusters (within 3 min)
        remaining_indices = [i for i in range(len(deaths)) if i not in handled_indices]
        clusters = []
        curr = []
        for i in remaining_indices:
            if not curr:
                curr.append(i)
            else:
                prev_t = deaths[curr[-1]][0]
                curr_t = deaths[i][0]
                if (curr_t - prev_t).total_seconds() <= 180:
                    curr.append(i)
                else:
                    clusters.append(curr)
                    curr = [i]
        if curr:
            clusters.append(curr)

        solo_skirmish_items = []
        for cl in clusters:
            cl_deaths = [deaths[i] for i in cl]
            start_ist = cl_deaths[0][0].astimezone(IST).strftime("%H:%M")
            end_ist = cl_deaths[-1][0].astimezone(IST).strftime("%H:%M IST")
            time_label = f"_{start_ist} IST_" if start_ist == end_ist else f"_{start_ist} – {end_ist}_"

            seen_player = {}
            corpse_runners = set()
            skirmishers = []
            for d_time, p in cl_deaths:
                if p in seen_player:
                    corpse_runners.add(p)
                else:
                    seen_player[p] = d_time
                    c_found = lookup_death_cause(d_time, p, death_causes)
                    skirmishers.append((p, c_found))

            cluster_causes = [c for _, c in skirmishers if c]

            # Fetch active era and biome dynamically
            from valheim_info import get_active_boss_and_era
            era_ctx = get_active_boss_and_era()
            active_biome = era_ctx.get("target_biome", "Wilderness")

            has_poison = any("poison" in c.lower() or "blob" in c.lower() or "ooze" in c.lower() for c in cluster_causes)
            has_swamp = any("swamp" in c.lower() or "crypt" in c.lower() or "draugr" in c.lower() or "leech" in c.lower() for c in cluster_causes)
            has_mountain = any("mountain" in c.lower() or "drake" in c.lower() or "wolf" in c.lower() or "freeze" in c.lower() or "blizzard" in c.lower() for c in cluster_causes)
            has_ocean = any("ocean" in c.lower() or "sea" in c.lower() or "serpent" in c.lower() or "drown" in c.lower() for c in cluster_causes)
            has_plains = any("plain" in c.lower() or "fuling" in c.lower() or "lox" in c.lower() or "deathsquito" in c.lower() for c in cluster_causes)

            # Hierarchical priority: specific identified causes take precedence over generic era fallback
            if has_poison or has_swamp:
                biome_icon = "☣️"
                default_title = "Swamp Skirmish"
                fallback_desc = "during a swamp expedition"
            elif has_mountain:
                biome_icon = "❄️"
                default_title = "Mountain Peril"
                fallback_desc = "braving the mountain peaks"
            elif has_plains:
                biome_icon = "🌾"
                default_title = "Plains Ambush"
                fallback_desc = "during a plains patrol"
            elif has_ocean:
                biome_icon = "🌊"
                default_title = "Ocean Hazard"
                fallback_desc = "on a perilous sea voyage"
            elif active_biome == "Mountains":
                biome_icon = "❄️"
                default_title = "Mountain & Frontier Skirmish"
                fallback_desc = "in mountain exploration"
            elif active_biome == "Swamps":
                biome_icon = "☣️"
                default_title = "Swamp Skirmish"
                fallback_desc = "during a swamp expedition"
            elif active_biome == "Black Forest":
                biome_icon = "🌲"
                default_title = "Black Forest Skirmish"
                fallback_desc = "in woodland combat"
            else:
                biome_icon = "⚔️"
                default_title = "Frontier Ambush"
                fallback_desc = "in wilderness combat"

            b_list = []
            if len(skirmishers) > 1:
                title = f"{biome_icon} *The Field Ambush & Skirmish* {time_label}"
                for p, c in skirmishers:
                    if c:
                        b_list.append(f"• *{format_player_name(p)}* fell to {c}.")
                    else:
                        b_list.append(f"• *{format_player_name(p)}* was overwhelmed in close combat.")
                for p in corpse_runners:
                    b_list.append(f"• *{format_player_name(p)}* suffered a fatal naked corpse run attempting to recover their tombstone! 🏃💨")
                battle_events.append({
                    "title": title,
                    "bullets": b_list
                })
            elif len(skirmishers) == 1:
                p_name, c = skirmishers[0]
                if corpse_runners:
                    title = f"{biome_icon} *{default_title}* {time_label}"
                    if c:
                        b_list.append(f"• *{format_player_name(p_name)}* succumbed to {c}.")
                    else:
                        b_list.append(f"• *{format_player_name(p_name)}* fell {fallback_desc}.")
                    for p in corpse_runners:
                        b_list.append(f"• *{format_player_name(p)}* suffered a fatal naked corpse run attempting to recover their tombstone! 🏃💨")
                    battle_events.append({
                        "title": title,
                        "bullets": b_list
                    })
                else:
                    solo_skirmish_items.append({
                        "time_dt": cl_deaths[0][0],
                        "time_str": start_ist,
                        "player": p_name,
                        "cause": c,
                        "fallback_desc": fallback_desc,
                        "biome_icon": biome_icon
                    })

        if solo_skirmish_items:
            if len(solo_skirmish_items) <= 2:
                for item in solo_skirmish_items:
                    t_lbl = f"_{item['time_str']} IST_"
                    title = f"{item['biome_icon']} *{item.get('default_title', 'Field Skirmish')}* {t_lbl}"
                    p_fmt = format_player_name(item['player'])
                    if item['cause']:
                        b_text = f"• *{p_fmt}* succumbed to {item['cause']}."
                    else:
                        b_text = f"• *{p_fmt}* fell {item['fallback_desc']}."
                    battle_events.append({"title": title, "bullets": [b_text]})
            else:
                solo_bullets = []
                i = 0
                while i < len(solo_skirmish_items):
                    curr = solo_skirmish_items[i]
                    j = i + 1
                    while j < len(solo_skirmish_items) and solo_skirmish_items[j]['player'] == curr['player'] and (solo_skirmish_items[j]['time_dt'] - solo_skirmish_items[j-1]['time_dt']).total_seconds() <= 3600:
                        j += 1
                    count = j - i
                    p_fmt = format_player_name(curr['player'])
                    if count > 1:
                        end_t = solo_skirmish_items[j-1]['time_str']
                        t_span = f"_{curr['time_str']} – {end_t} IST_"
                        solo_bullets.append(f"• {t_span} — *{p_fmt}* suffered {count} falls {curr['fallback_desc']}.")
                    else:
                        t_span = f"_{curr['time_str']} IST_"
                        if curr['cause']:
                            solo_bullets.append(f"• {t_span} — *{p_fmt}* succumbed to {curr['cause']}.")
                        else:
                            solo_bullets.append(f"• {t_span} — *{p_fmt}* fell {curr['fallback_desc']}.")
                    i = j
                battle_events.append({
                    "title": "⚔️ *Frontier Skirmishes & Solo Perils*",
                    "bullets": solo_bullets
                })

        for ev in battle_events:
            msg_lines.append(ev["title"])
            for b in ev["bullets"]:
                msg_lines.append(b)
            msg_lines.append("")

        # Highlight unscathed survivors who played in 24h with 0 deaths
        fallen_players = set([p for _, p in deaths])
        survivors = [p for p in player_sessions.keys() if p not in fallen_players]
        if survivors:
            survivor_str = ", ".join([f"*{format_player_name(name)}*" for name in sorted(survivors)])
            msg_lines.append(f"🛡️ *Viking of the Day (0 deaths):* {survivor_str} _(Walked away unbroken!)_")
            msg_lines.append("")
    else:
        if player_sessions:
            msg_lines.append("• 🛡️ _Zero casualties! All exploring Vikings returned unbroken._")
        else:
            msg_lines.append("• _No battles were fought._")
        msg_lines.append("")

    # All-Time Leaderboard Counter
    if all_time_counts:
        top_fallen = " | ".join([f"*{format_player_name(p)}:* {c}" for p, c in all_time_counts.most_common()])
        msg_lines.append(f"⚰️ *All-Time Realm Casualties ({all_time_total} Total):*")
        msg_lines.append(f"• {top_fallen}")
        msg_lines.append("")
    
    # --- Frontier Discoveries & Dungeons (Small & Compact Version) ---
    msg_lines.append("🗺️ *Frontier Discoveries*")
    major_counts = {}
    minor_count = 0
    if locations:
        for _, raw, _, _ in locations:
            name, icon, biome, is_major = get_location_meta(raw)
            if is_major:
                key = f"{icon} *{name}*"
                major_counts[key] = major_counts.get(key, 0) + 1
            else:
                minor_count += 1

    if major_counts:
        top_major = [f"{k} ×{c}" for k, c in sorted(major_counts.items(), key=lambda x: x[1], reverse=True)[:5]]
        msg_lines.append("• " + " | ".join(top_major))
    elif minor_count > 0:
        msg_lines.append("• _No major dungeons discovered (scouted local territory)._")
    else:
        msg_lines.append("• _No new uncharted locations were claimed._")
    msg_lines.append("")
    
    # --- Viking Warriors & Playtime ---
    msg_lines.append("🍻 *Warriors of the Realm*")
    if player_sessions:
        for p, s_list in sorted(player_sessions.items(), key=lambda x: sum((e-s).total_seconds() for s,e in x[1]), reverse=True):
            total_sec = sum((e-s).total_seconds() for s,e in s_list)
            hrs = int(total_sec // 3600)
            mins = int((total_sec % 3600) // 60)
            sessions_count = len(s_list)
            s_str = "expedition" if sessions_count == 1 else "expeditions"
            time_display = f"{hrs}h {mins:02d}m" if hrs > 0 else f"{mins}m"
            msg_lines.append(f"• *{format_player_name(p)}:* {time_display} across {sessions_count} {s_str}")
            
        if peak_count > 1 and peak_time:
            peak_ist = peak_time.astimezone(IST).strftime("%H:%M IST")
            msg_lines.append(f"🔥 *Peak War Party:* *{peak_count} Vikings* online together at {peak_ist}")
    else:
        msg_lines.append("• _No Vikings walked the realm during this cycle._")
    msg_lines.append("")

    # --- Tribal Strongbox & Inventory ---
    msg_lines.append("📦 *Tribal Strongbox & Inventory*")
    inv_top5, inv_metals, container_count = scan_inventory_status()
    if inv_top5:
        msg_lines.append(f"_Top 5 Stockpiled Resources ({container_count} homestead chests):_")
        for label, count in inv_top5:
            msg_lines.append(f"• *{label}:* {count:,}")
        if inv_metals:
            msg_lines.append(f"⛏️ _Key Metals & Cores:_ {', '.join(inv_metals)}")
        try:
            from valheim_info import get_progression_state
            prog_info = get_progression_state()
            if prog_info.get("next_boss"):
                nb = prog_info["next_boss"]
                msg_lines.append(f"🎯 *Next Frontier:* Slay *{nb['name']}* in the *{nb['biome']}* (Check `!progress` or `!armourus` for prep)")
        except Exception:
            pass
    else:
        msg_lines.append("• _No chest inventory records found._")
        
    msg_lines.append("")
    msg_lines.append("_May Odin guide your arrows and Thor bless your steel!_ ⚔️")
    
    # --- Append 📜 STORY TIME ---
    try:
        from collections import Counter
        sys.path.insert(0, "/root/valheim_chronicles")
        from skald import generate_daily_story
        from valheim_info import get_persisted_day
        
        current_day = get_persisted_day()
        active_players_list = sorted(list(player_sessions.keys())) if player_sessions else []
        
        # Casualties & battle masala
        cas_str = "None. The shieldwall stood firm."
        death_details = []
        if deaths:
            c_counts = Counter([p for _, p in deaths])
            cas_str = ", ".join([f"{format_player_name(p)} ({cnt} combat fall{'s' if cnt != 1 else ''})" for p, cnt in c_counts.items()]) + f" (Total: {len(deaths)} fall{'s' if len(deaths) != 1 else ''} in 24h)"
            for b in battle_events:
                t = b.get("title", "")
                bullets = " ".join(b.get("bullets", []))
                clean_event = re.sub(r"[*_]", "", f"{t}: {bullets}").strip()
                death_details.append(clean_event)

        # Economic fight telemetry
        econ_summary = "No chest inventory records found."
        if inv_top5:
            stock_str = ", ".join([f"{label}: {count}" for label, count in inv_top5])
            metal_str = ", ".join(inv_metals) if inv_metals else "No smelted metals on hand"
            try:
                from valheim_info import get_progression_state
                _p = get_progression_state()
                _tier = _p.get("current_tier", 4)
                if _tier >= 5:
                    era_grind = "Plains era: Fuling Black Metal scrap & Flax Linen spinning at Artisan Table."
                elif _tier == 4:
                    era_grind = "Mountain/Plains era: Silver forging, Wolf pelt armor, smelting scrap & Plains scouting."
                elif _tier == 3:
                    era_grind = "Swamp era: Scrap iron crypt hauling & sunken bog exploration."
                elif _tier == 2:
                    era_grind = "Bronze era: 2:1 copper/tin smelting & Black Forest mining."
                else:
                    era_grind = "Meadows awakening: Flint tools & leather crafting."
            except Exception:
                era_grind = "Smelter & kiln production."

            econ_summary = (
                f"Stockpiled across {container_count} chests: {stock_str}. "
                f"Metal Reserves & Smelting Works: {metal_str}. "
                f"({era_grind} Portals strictly reject raw ore)."
            )

        # Raid summary
        raid_str = "None"
        if raids:
            raid_titles = []
            for _, r_code in raids:
                t, foes = RAID_LORE.get(r_code, (r_code, "Hostile forces"))
                raid_titles.append(f"{t} ({foes})")
            raid_str = "; ".join(raid_titles)

        # Discovery summary - clean landmarks for narrative skald
        disc_str = "None"
        if locations:
            major_names = []
            minor_names = []
            for _, raw, _, _ in locations:
                name, _, _, is_major = get_location_meta(raw)
                if is_major:
                    if name not in major_names:
                        major_names.append(name)
                else:
                    if name not in minor_names:
                        minor_names.append(name)
            if major_names:
                disc_str = ", ".join(major_names[:4])
                remaining = len(minor_names)
                if remaining > 0:
                    disc_str += f", and {remaining} frontier landmarks"
            elif minor_names:
                clean_names = sorted(list(set(re.sub(r"[^\w\s\(\)]", "", name).strip() for name in minor_names)))
                disc_str = ", ".join(clean_names[:3])

        from valheim_info import get_active_boss_and_era
        era_ctx = get_active_boss_and_era()
        curr_era = era_ctx.get("current_era", "The Iron Age")
        t_boss = era_ctx.get("target_boss", "Bonemass")
        t_biome = era_ctx.get("target_biome", "Swamps")
        t_reward = era_ctx.get("target_reward", "Wishbone")
        t_trib = era_ctx.get("tribute_summary", "")
        t_portal = era_ctx.get("altar_portal", "")

        if boss_defeats:
            latest_b_code = boss_defeats[-1][1]
            from valheim_boss_helper import BOSS_DATA
            b_info = BOSS_DATA.get(latest_b_code, {})
            b_name = b_info.get("name", "The Forsaken Boss")
            b_reward = b_info.get("reward", "mythic spoils")
            b_power = b_info.get("power", "Forsaken Power")
            ambition_text = (
                f"VICTORY! {b_name} has been vanquished at the sacred altar! "
                f"The clan claimed {b_reward} and the {b_power}. "
                f"The clan now enters {curr_era}. Next campaign: Slay {t_boss} in the {t_biome}!"
            )
        else:
            ambition_text = (
                f"Forging armaments for {curr_era}. "
                f"Active campaign: Prepare to summon and defeat {t_boss} in the {t_biome} to claim the {t_reward}! "
                f"Tributes: {t_trib}."
            )
            if t_portal:
                ambition_text += f" Altar portal tag: '{t_portal}'."

        story_facts = {
            "day": current_day,
            "era": curr_era,
            "target_boss": t_boss,
            "target_biome": t_biome,
            "active_players": [format_player_name(p) for p in active_players_list],
            "casualties_summary": cas_str,
            "death_actions": death_details or ["Peaceful patrol, no falls"],
            "raids_summary": raid_str,
            "discoveries_summary": disc_str,
            "economic_telemetry": econ_summary,
            "ambition_context": ambition_text
        }
        
        story_section = generate_daily_story(story_facts, save_to_master=save_story_to_master, dry_run=dry_run)
        if story_section:
            msg_lines.append("")
            msg_lines.append(story_section)
    except Exception as e:
        print(f"[Chronicle] Error generating Story Time: {e}", file=sys.stderr)
        
    return "\n".join(msg_lines)

def send_to_whatsapp(text: str) -> bool:
    success = safe_send_whatsapp(text, timeout=15, retries=3)
    if success:
        print("[OK] Successfully dispatched Daily Chronicle to WhatsApp group.")
    else:
        print("Failed to dispatch Daily Chronicle to WhatsApp group.", file=sys.stderr)
    return success

def main():
    parser = argparse.ArgumentParser(description="Valheim Daily Battle Chronicle")
    parser.add_argument("--post", action="store_true", help="Post chronicle directly to WhatsApp group")
    parser.add_argument("--dry-run", action="store_true", help="Print chronicle to stdout without sending")
    parser.add_argument("--hours", type=int, default=24, help="Number of hours to look back (default: 24)")
    parser.add_argument("--no-audio", action="store_true", help="Skip sending Skald audio voice note")
    args = parser.parse_args()
    
    save_to_master = bool(args.post and not args.dry_run)
    chronicle_text = generate_chronicle(hours=args.hours, save_story_to_master=save_to_master, dry_run=args.dry_run)
    
    if args.dry_run or not args.post:
        print("=== VALHEIM CHRONICLE PREVIEW ===")
        print(chronicle_text)
        print("=================================")
        
    if args.post and not args.dry_run:
        success = send_to_whatsapp(chronicle_text)
        if success and not args.no_audio:
            try:
                from valheim_voice import narrate_daily_chronicle
                narrate_daily_chronicle(chronicle_text)
            except Exception as e:
                print(f"[Chronicle] Note: Audio narration skipped or failed: {e}", file=sys.stderr)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
