#!/usr/bin/env python3
"""
/root/valheim_monitor.py - Real-Time Valheim Activity Monitor, Combat SRE & Raider Radar

Features:
- Live tailing of Valheim server logs with seamless rotation handling
- Join/Leave notifications with paired dynamic Viking roasts
- Real-time Horn of War raid detection, siege timers, casualty tracking, and victory shouts
- Real-time Boss Defeat War-Cry (server log and binary DB2 world save decompressed tracking)
- Real-time Trader Camp discovery alerts (Haldor, Hildir, Bog Witch)
- Hildir brass chest quest completion alerts
- Atomic JSON persistence for all state files (zero risk of file corruption)
- Modular session event classifier with full testability
- Clean signal handling (SIGTERM/SIGINT) with state flush on service restarts
"""

import os
import sys
import time
import re
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from collections import Counter
import glob
import zlib
import signal
from typing import Dict, Any, Set, List, Optional, Tuple

sys.path.insert(0, "/root")
from valheim_utils import (
    VALHEIM_DIR,
    LOG_FILE,
    ENV_FILE,
    IST,
    VALHEIM_WHATSAPP_GROUP,
    format_player_name,
    safe_load_json,
    atomic_save_json,
    safe_send_whatsapp,
    safe_send_telegram,
    load_env
)

try:
    from valheim_messages import (
        get_random_join_message,
        get_random_leave_message,
        get_session_leave_message,
        get_session_resume_message
    )
except Exception:
    def get_random_join_message(name: str, target: str = "whatsapp") -> str:
        name = format_player_name(name)
        return f"⚔️ [Valheim] *{name}* entered the realm!" if target == "whatsapp" else f"⚔️ <b>Valheim</b> — {name} joined the server!"

    def get_random_leave_message(name: str, target: str = "whatsapp") -> str:
        name = format_player_name(name)
        return f"🛡️ [Valheim] *{name}* left the server." if target == "whatsapp" else f"🛡️ <b>Valheim</b> — {name} left the server."

    def get_session_leave_message(name: str, event_type: str, session_data: Optional[Dict[str, Any]] = None, target: str = "whatsapp") -> str:
        return get_random_leave_message(name, target)

    def get_session_resume_message(name: str, last_state: Optional[Dict[str, Any]] = None, target: str = "whatsapp") -> str:
        return get_random_join_message(name, target)

# --- Lore & Alert Constants ---
RAID_LORE = {
    "army_eikthyr": ("Eikthyr rallies the creatures of the forest! ⚡", "Boars & Necks"),
    "army_theelder": ("The forest is moving... 🌲", "Greydwarf Horde & Brutes"),
    "army_bonemass": ("A foul smell from the swamp... ☣️", "Skeletons & Blobs"),
    "army_moder": ("A cold wind blows from the mountain... ❄️", "Drakes"),
    "army_goblin": ("The horde is attacking! ⚔️", "Fuling Goblin Army"),
    "army_yagluth": ("The horde is attacking! ⚔️", "Fuling Goblin Army"),
    "army_queen": ("They sought you out... 🪲", "Seekers & Brood"),
    "army_fader": ("The Charred march... 🔥", "Ashlands Legion"),
    "wolves": ("You are being hunted... 🐺", "Wolf Pack"),
    "skeletons": ("Skeleton Surprise! 💀", "Skeleton Army"),
    "foresttrolls": ("The ground is shaking... 🧌", "Trolls"),
    "surtlings": ("A smell of sulfur in the air... 🔥", "Surtlings"),
    "bats": ("You stirred the cauldron... 🦇", "Bat Swarm"),
    "ghosts": ("A cold chill runs down your spine... 👻", "Spectres & Wraiths")
}

RAID_SPAWN_DURATIONS = {
    "army_eikthyr": 90,
    "army_theelder": 120,
    "army_bonemass": 120,
    "army_moder": 120,
    "army_goblin": 120,
    "army_yagluth": 120,
    "army_queen": 120,
    "army_fader": 150,
    "wolves": 120,
    "skeletons": 120,
    "foresttrolls": 80,
    "surtlings": 120,
    "bats": 120,
    "ghosts": 120
}
RAID_DURATIONS = RAID_SPAWN_DURATIONS
MOPUP_BUFFER = 120
CALM_BUFFER = 90
MAX_RAID_DURATION = 480
POST_VICTORY_MOPUP_WINDOW = 90

BOSS_MAP = {
    "defeated_eikthyr": ("Eikthyr ⚡", "Meadows", "Hard Antler (Pickaxe)"),
    "defeated_gdking": ("The Elder 🌲", "Black Forest", "Swamp Key"),
    "defeated_bonemass": ("Bonemass ☣️", "Swamps", "Wishbone"),
    "defeated_dragon": ("Moder ❄️", "Mountains", "Dragon Tear (Artisan Table)"),
    "defeated_writhan": ("Moder ❄️", "Mountains", "Dragon Tear (Artisan Table)"),
    "defeated_goblinking": ("Yagluth ⚔️", "Plains", "Torn Spirit"),
    "defeated_queen": ("The Queen 🪲", "Mistlands", "Majestic Carapace"),
    "defeated_fader": ("Fader 🔥", "Ashlands", "Lord of Cinder Trophy & Bell Fragment"),
    "defeated_fimbulbringer": ("Kall Fimbulbringer ❄️", "Deep North", "Fimbulbringer Trophy & Heart of the Jotun")
}

BOSS_STATE_FILE     = "/root/valheim_bosses_defeated.json"
LAST_RAID_FILE      = "/root/valheim_last_raid.json"
DEATHS_HISTORY_FILE = "/root/valheim_deaths_history.json"
PLAYER_STATE_FILE   = "/root/valheim_player_state.json"
ACTIVE_SESSIONS_FILE = "/root/valheim_active_sessions.json"
TRADER_STATE_FILE   = "/root/valheim_known_traders.json"
HILDIR_STATE_FILE   = "/root/valheim_hildir_quests.json"

TRADER_LOC_MAP = {
    "Vendor_BlackForest": ("🪙", "Haldor the Merchant", "Black Forest", "Equipment, Dvergr Circlets & Ymir Flesh are now tradeable!"),
    "Hildir_camp": ("👗", "Hildir the Trader", "Meadows", "Vanity apparel, hats & quest contracts unlocked!"),
    "BogWitch_Camp": ("🧙‍♀️", "The Bog Witch", "Swamps", "Alchemy draughts, feast spices & witch tools available!")
}

HILDIR_QUEST_MAP = {
    "hildir1": ("Forest Crypt", "New vanity clothing & tunics"),
    "hildir2": ("Mountain Cavern", "Winter dresses & apparel"),
    "hildir3": ("Plains Sealed Tower", "Master Barbarian armour & finery")
}

POI_MAP = {
    "SunkenCrypt": ("⚔️", "A Sunken Crypt has been discovered in the Swamp!"),
    "MountainCave": ("🏔️", "A Frost Cave has been discovered in the Mountains!"),
    "FrostCave": ("🏔️", "A Frost Cave has been discovered in the Mountains!"),
    "GoblinCamp": ("🔥", "A Fuling Village has been spotted in the Plains!"),
    "Fuling": ("🔥", "A Fuling Village has been spotted in the Plains!"),
    "InfestedMine": ("🕷️", "An Infested Mine has been discovered!")
}

# Telegram alerts configuration
_ENV = load_env()
ENABLE_TELEGRAM = _ENV.get("VALHEIM_MONITOR_TELEGRAM", "false").lower() in ("1", "true", "yes")


def send_telegram(text: str) -> None:
    if ENABLE_TELEGRAM:
        safe_send_telegram(text)


def send_whatsapp(text: str) -> bool:
    return safe_send_whatsapp(text)


def load_player_states() -> Dict[str, Any]:
    return safe_load_json(PLAYER_STATE_FILE, default={})


def save_player_state(name: str, summary: Dict[str, Any]) -> None:
    states = load_player_states()
    states[name] = summary
    atomic_save_json(PLAYER_STATE_FILE, states)


def load_active_sessions() -> Dict[str, Any]:
    return safe_load_json(ACTIVE_SESSIONS_FILE, default={})


def save_active_sessions(
    sessions: Dict[str, Dict[str, Any]],
    active: Set[str],
    n2o: Dict[str, str],
    n2s: Dict[str, str],
    o2n: Dict[str, str],
    s2n: Dict[str, str]
) -> None:
    data: Dict[str, Any] = {
        "active_names": sorted(list(active)),
        "name_to_owner": dict(n2o),
        "name_to_socket": dict(n2s),
        "owner_to_name": dict(o2n),
        "socket_to_name": dict(s2n),
        "sessions": {}
    }
    for p, s in sessions.items():
        data["sessions"][p] = {
            "login_time": s.get("login_time", time.time()),
            "deaths": list(s.get("deaths", [])),
            "corpse_runs": s.get("corpse_runs", 0),
            "raids_participated": sorted(list(s.get("raids_participated", set()))),
            "raids_died_in": sorted(list(s.get("raids_died_in", set()))),
            "bosses_defeated": sorted(list(s.get("bosses_defeated", set()))),
            "locations_discovered": sorted(list(s.get("locations_discovered", set()))),
            "sea_voyage": bool(s.get("sea_voyage", False))
        }
    atomic_save_json(ACTIVE_SESSIONS_FILE, data)


def get_active_join_code() -> str:
    if not os.path.exists(LOG_FILE):
        return "Unknown"
    try:
        with open(LOG_FILE, "r", errors="ignore") as f:
            lines = f.readlines()
        for line in reversed(lines[-200:]):
            m = re.search(r"registered with join code\s+(\d+)", line)
            if m:
                return m.group(1)
            m_alt = re.search(r"join code\s+(\d+)", line)
            if m_alt:
                return m_alt.group(1)
    except Exception:
        pass
    return "Unknown"


def get_db2_defeated_bosses() -> Set[str]:
    keys: Set[str] = set()
    db_files = sorted(glob.glob('/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/_main.*.db2'))
    if db_files:
        try:
            with open(db_files[-1], 'rb') as f:
                data = f.read()
            idx = data.find(b'\x1f\x8b\x08')
            if idx != -1:
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                decomp = d.decompress(data[idx:])
                found = re.findall(rb'defeated_\w+', decomp)
                for k in found:
                    k_str = k.decode('latin1').lower()
                    if k_str in BOSS_MAP:
                        keys.add(k_str)
        except Exception as e:
            sys.stderr.write(f"[Monitor] Error reading db2 for defeated keys: {e}\n")
    return keys


def save_known_defeated_bosses(keys: Set[str]) -> None:
    atomic_save_json(BOSS_STATE_FILE, sorted(list(keys)))


def load_known_defeated_bosses() -> Set[str]:
    data = safe_load_json(BOSS_STATE_FILE, default=None)
    if isinstance(data, list):
        return set(data)
    keys = get_db2_defeated_bosses()
    save_known_defeated_bosses(keys)
    return keys


def get_db2_hildir_quests() -> Set[str]:
    keys: Set[str] = set()
    db_files = sorted(glob.glob('/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/_main.*.db2'))
    if db_files:
        try:
            with open(db_files[-1], 'rb') as f:
                data = f.read()
            idx = data.find(b'\x1f\x8b\x08')
            if idx != -1:
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                decomp = d.decompress(data[idx:])
                for qk in [b'hildir1', b'hildir2', b'hildir3']:
                    if qk in decomp.lower():
                        keys.add(qk.decode('latin1'))
        except Exception as e:
            sys.stderr.write(f"[Monitor] Error reading db2 for hildir quests: {e}\n")
    return keys


def save_known_traders(keys: Set[str]) -> None:
    atomic_save_json(TRADER_STATE_FILE, sorted(list(keys)))


def load_known_traders() -> Set[str]:
    data = safe_load_json(TRADER_STATE_FILE, default=None)
    if isinstance(data, list):
        return set(data)
    initial = {"Vendor_BlackForest", "Hildir_camp", "BogWitch_Camp"}
    save_known_traders(initial)
    return initial


def save_known_hildir_quests(keys: Set[str]) -> None:
    atomic_save_json(HILDIR_STATE_FILE, sorted(list(keys)))


def load_known_hildir_quests() -> Set[str]:
    data = safe_load_json(HILDIR_STATE_FILE, default=None)
    if isinstance(data, list):
        return set(data)
    keys = get_db2_hildir_quests()
    save_known_hildir_quests(keys)
    return keys


def _serialize_raid_item(obj: Any) -> Any:
    if isinstance(obj, (set, frozenset)):
        return sorted(list(obj))
    if isinstance(obj, dict):
        return {k: _serialize_raid_item(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_raid_item(x) for x in obj]
    return obj


def save_raid_state(active: bool, data: Dict[str, Any]) -> None:
    clean_data = _serialize_raid_item(data)
    payload = {"active": active, **clean_data}
    atomic_save_json(LAST_RAID_FILE, payload)


def load_raid_state() -> Optional[Dict[str, Any]]:
    return safe_load_json(LAST_RAID_FILE, default=None)


def record_death(player_name: str, line: str, active_raid: Optional[Dict[str, Any]] = None) -> None:
    m_ts = re.search(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}):", line)
    ts = m_ts.group(1) if m_ts else datetime.now(timezone.utc).strftime("%m/%d/%Y %H:%M:%S")
    entry_key = f"{ts}_{player_name}"
    try:
        history = safe_load_json(DEATHS_HISTORY_FILE, default={})
        if entry_key not in history:
            entry = {"timestamp": ts, "player": player_name}
            if active_raid:
                lore = RAID_LORE.get(active_raid.get("key", ""), (active_raid.get("key", "Raid"), "Enemy Invaders"))
                entry["cause"] = f"base defense against {lore[1]} ({lore[0]})"
            history[entry_key] = entry
            atomic_save_json(DEATHS_HISTORY_FILE, history)
    except Exception as e:
        sys.stderr.write(f"[Monitor] Error recording death: {e}\n")


def format_raid_alert(raid_key: str, active_players: Set[str], join_code: str) -> str:
    lore = RAID_LORE.get(raid_key, (f"Hostile creatures approach ({raid_key})! ⚔️", "Enemy Invaders"))
    event_title, foes = lore
    if active_players:
        defenders_str = ", ".join(f"*{format_player_name(p)}*" for p in sorted(active_players))
    else:
        defenders_str = "_No warriors currently online! The longhouse is unprotected!_"

    lines = [
        "📯💥 *HORN OF WAR! HOMESTEAD UNDER SIEGE!* 💥📯",
        "",
        f"*{event_title}*",
        f"• *Enemy Host:* {foes}",
        f"• *Active Defenders:* {defenders_str}",
        "",
        f"⚔️ *Rally to the Shieldwall!* Join Code: `{join_code}`",
        "Draw steel and protect the hearth!"
    ]
    return "\n".join(lines)


def format_raid_victory_message(
    raid_key: str,
    defenders: Set[str],
    sacrifices: List[str],
    duration_seconds: Optional[int] = None
) -> str:
    lore = RAID_LORE.get(raid_key, (f"Hostile creatures repelled ({raid_key})! ⚔️", "Enemy Invaders"))
    event_title, foes = lore
    defenders_str = ", ".join(f"*{format_player_name(p)}*" for p in sorted(defenders)) if defenders else "Valiant Vikings"

    lines = [
        "🛡️⚔️ *VICTORY IN VALHEIM! THE SIEGE IS BROKEN!* ⚔️🛡️",
        "",
        f"*{event_title}*",
        f"• *Repelled Host:* {foes} (Vanquished)",
        f"• *Stalwart Defenders:* {defenders_str}",
    ]
    if duration_seconds:
        mins = duration_seconds // 60
        secs = duration_seconds % 60
        dur_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        lines.append(f"• *Siege Duration:* {dur_str}")

    lines.append("")
    if sacrifices:
        counts = Counter(sacrifices)
        lines.append("🩸 *SACRIFICES OF VALOR:*")
        for victim, count in counts.most_common():
            fall_str = f"{count} fall" if count == 1 else f"{count} falls"
            lines.append(f"  💀 *{format_player_name(victim)}* ({fall_str})")
        lines.append("_Their blood watered the sacred soil, but their courage held the shieldwall! Valhalla welcomes the brave!_ 🪓")
    else:
        lines.append("🛡️ *SACRIFICES:*")
        lines.append("  ✨ *FLAWLESS DEFENSE!* Zero casualties sustained! Not a single drop of Viking blood was spilled on the longhouse floor.")

    lines.append("")
    lines.append("The hearth fires burn bright and the longhouse stands secure. Odin nods in approval! Skål! 🍻🥩🔥")
    return "\n".join(lines)


def format_raid_amendment_message(raid_key: str, fallen_warrior: str, all_sacrifices: List[str]) -> str:
    lore = RAID_LORE.get(raid_key, (f"Hostile creatures ({raid_key})", "Enemy Invaders"))
    event_title, foes = lore
    counts = Counter(all_sacrifices)
    fall_count = counts.get(fallen_warrior, 1)
    fall_str = f"{fall_count} fall" if fall_count == 1 else f"{fall_count} falls"

    lines = [
        "🩸⚔️ *CASUALTY UPDATE — SANGUINE SHIELDWALL!* ⚔️🩸",
        "",
        f"*{event_title}*",
        "Hold the toasts! Hostile stragglers ambushed the homestead during the final mop-up!",
        f"💀 *{format_player_name(fallen_warrior)}* has fallen in battle! ({fall_str})",
        "",
        f"• *Enemy Host:* {foes}",
        f"• *Total Casualties:* {len(all_sacrifices)} fallen",
        "",
        "_Their blood watered the sacred soil, but their courage held the shieldwall! Valhalla welcomes the brave!_ 🪓 Skål! 🍻🥩"
    ]
    return "\n".join(lines)


def format_boss_defeat_message(boss_key: str, active_players: Set[str]) -> str:
    info = BOSS_MAP.get(boss_key, (boss_key.replace('defeated_', '').title(), "The Realm", "Mythic Spoils"))
    boss_name, biome, reward = info
    player_str = ", ".join(f"*{format_player_name(p)}*" for p in sorted(active_players)) if active_players else "Valiant Vikings"

    lines = [
        "🏆⚡ *VICTORY IN VALHEIM! A MYTHIC BEAST HAS FALLEN!* ⚡🏆",
        "",
        f"Hail, warriors! The dread lord of the {biome}, *{boss_name}*, has been vanquished!",
        f"The gods smile upon our champions: {player_str}!",
        "",
        f"🎁 *Claimed Spoils & Unlock:* *{reward}*",
        "The world grows darker, but our clan grows mightier. Skål! 🍻🥩"
    ]
    return "\n".join(lines)


def handle_boss_defeat(boss_key: str, active_players: Set[str]) -> str:
    try:
        import valheim_boss_helper as vbh
        from valheim_info import get_persisted_day
        day = get_persisted_day()
        battle_data = vbh.analyze_boss_battle(
            boss_key,
            defeat_time_dt=datetime.now(timezone.utc),
            active_players=active_players
        )
        vbh.save_boss_battle(boss_key, battle_data)
        msg = vbh.format_boss_assessment_message(boss_key, battle_data, day=day)
        print(f"Deep boss battle assessment generated for {boss_key} ({battle_data['total_falls']} falls in {battle_data['duration_minutes']}m)")
        return msg
    except Exception as e:
        sys.stderr.write(f"[Monitor] Error generating deep boss assessment for {boss_key}: {e}\n")
        return format_boss_defeat_message(boss_key, active_players)


# --- Modular Event Classification Helper ---

def classify_session_event(
    sess: Dict[str, Any],
    reason: str,
    now_t: float
) -> Tuple[str, Dict[str, Any], int, int]:
    """
    Pure classifier for player session departure.
    Returns (event_type, event_detail, duration_mins, deaths_count).
    """
    login_t = sess.get("login_time", now_t - 60)
    dur_seconds = max(0, int(now_t - login_t))
    dur_mins = max(1, dur_seconds // 60)
    deaths = sess.get("deaths", [])
    deaths_count = len(deaths)
    corpse_runs = sess.get("corpse_runs", 0)
    raids_died = list(sess.get("raids_died_in", []))
    raids_part = list(sess.get("raids_participated", []))
    bosses = list(sess.get("bosses_defeated", []))
    locs = list(sess.get("locations_discovered", []))
    sea_voyage = sess.get("sea_voyage", False)
    time_since_death = (now_t - deaths[-1]) if deaths else 999999
    is_rage_quit = (time_since_death <= 60) or (reason == "socket_drop" and time_since_death <= 120)

    # Hierarchical condition ladder (most specific/high-value first)
    if raids_died:
        event_type = "RAID_CASUALTY"
        event_detail = {"raid_key": raids_died[-1], "deaths": deaths_count}
    elif is_rage_quit:
        event_type = "RAGE_QUIT"
        event_detail = {"deaths": deaths_count, "time_since_death": int(time_since_death)}
    elif corpse_runs >= 1 or deaths_count >= 3:
        event_type = "CORPSE_RUN_FAIL"
        event_detail = {"deaths": deaths_count, "corpse_runs": corpse_runs}
    elif bosses:
        event_type = "BOSS_SLAYER"
        event_detail = {"boss_key": bosses[-1]}
    elif raids_part and not raids_died:
        event_type = "RAID_SURVIVOR"
        event_detail = {"raid_key": raids_part[-1]}
    elif sea_voyage and deaths_count > 0:
        event_type = "SEA_CASUALTY"
        event_detail = {"deaths": deaths_count, "duration_mins": dur_mins}
    elif dur_mins >= 60 and deaths_count == 0:
        event_type = "MARATHON_GRIND"
        event_detail = {"duration_mins": dur_mins}
    elif sea_voyage:
        event_type = "SEA_VOYAGE"
        event_detail = {"duration_mins": dur_mins}
    elif deaths_count > 0:
        event_type = "WILDERNESS_DEATH"
        event_detail = {"deaths": deaths_count}
    elif locs:
        event_type = "DUNGEON_CRAWLER"
        event_detail = {"location": locs[-1]}
    elif dur_seconds <= 300:
        event_type = "QUICK_DIP"
        event_detail = {"duration_mins": dur_mins}
    else:
        event_type = "PEACEFUL_LOGOUT"
        event_detail = {"duration_mins": dur_mins}

    return event_type, event_detail, dur_mins, deaths_count


# --- Main Monitor Loop ---

def monitor() -> None:
    print(f"Starting Valheim monitor on {LOG_FILE}")
    if ENABLE_TELEGRAM:
        send_telegram("⚔️ <b>Valheim Monitor Online</b>\nPlayer join/leave alerts are now active.")

    active_names: Set[str] = set()
    active_sessions: Dict[str, Dict[str, Any]] = {}
    name_to_owner: Dict[str, str] = {}
    name_to_socket: Dict[str, str] = {}
    owner_to_name: Dict[str, str] = {}
    socket_to_name: Dict[str, str] = {}
    last_id_seen: Optional[str] = None

    # Load previously cached active sessions across monitor restarts/deployments
    cached_data = load_active_sessions()
    cached_sessions = cached_data.get("sessions", {})
    if cached_data.get("owner_to_name"):
        owner_to_name.update(cached_data["owner_to_name"])
    if cached_data.get("name_to_owner"):
        name_to_owner.update(cached_data["name_to_owner"])
    if cached_data.get("socket_to_name"):
        socket_to_name.update(cached_data["socket_to_name"])
    if cached_data.get("name_to_socket"):
        name_to_socket.update(cached_data["name_to_socket"])

    # Pre-seed active players from recent server log state
    try:
        import valheim_whatsapp_action
        srv_info = valheim_whatsapp_action.get_server_info()
        online_players = srv_info.get("players", [])
        if online_players:
            for p in online_players:
                active_names.add(p)
                if p in cached_sessions:
                    cs = cached_sessions[p]
                    active_sessions[p] = {
                        "login_time": cs.get("login_time", time.time()),
                        "deaths": list(cs.get("deaths", [])),
                        "corpse_runs": cs.get("corpse_runs", 0),
                        "raids_participated": set(cs.get("raids_participated", [])),
                        "raids_died_in": set(cs.get("raids_died_in", [])),
                        "bosses_defeated": set(cs.get("bosses_defeated", [])),
                        "locations_discovered": set(cs.get("locations_discovered", [])),
                        "sea_voyage": bool(cs.get("sea_voyage", False))
                    }
                elif p not in active_sessions:
                    p_dur_mins = 0
                    for ps in srv_info.get("player_sessions", []):
                        if ps.get("name") == p:
                            p_dur_mins = ps.get("duration_mins", 0)
                            break
                    active_sessions[p] = {
                        "login_time": time.time() - (p_dur_mins * 60),
                        "deaths": [],
                        "corpse_runs": 0,
                        "raids_participated": set(),
                        "raids_died_in": set(),
                        "bosses_defeated": set(),
                        "locations_discovered": set(),
                        "sea_voyage": False
                    }
        if srv_info.get("owner_to_name"):
            owner_to_name.update(srv_info["owner_to_name"])
        if srv_info.get("name_to_owner"):
            name_to_owner.update(srv_info["name_to_owner"])
        print(f"Pre-seeded active players: {active_names}, owners: {owner_to_name}")
    except Exception as e:
        print(f"Could not pre-seed active players: {e}")

    known_defeated = load_known_defeated_bosses()
    print(f"Tracking known defeated bosses: {known_defeated}")
    known_traders = load_known_traders()
    print(f"Tracking known traders: {known_traders}")
    known_hildir_quests = load_known_hildir_quests()
    print(f"Tracking known Hildir quests: {known_hildir_quests}")
    last_raid_event: Optional[str] = None
    last_raid_time: float = 0
    last_db_check_time: float = time.time()
    active_raid: Optional[Dict[str, Any]] = None
    last_completed_raid: Optional[Dict[str, Any]] = None
    last_poi_alerts: Dict[str, float] = {}

    # Restore any ongoing raid state
    saved_state = load_raid_state()
    if saved_state:
        if saved_state.get("last_raid"):
            last_completed_raid = saved_state["last_raid"]
        if saved_state.get("active") and saved_state.get("active_raid"):
            ar = saved_state["active_raid"]
            now_curr = time.time()
            if now_curr < ar.get("end_time", 0):
                active_raid = {
                    "key": ar["key"],
                    "start_time": ar["start_time"],
                    "end_time": ar["end_time"],
                    "max_end_time": ar.get("max_end_time", ar["start_time"] + MAX_RAID_DURATION),
                    "last_casualty_time": ar.get("last_casualty_time", 0),
                    "defenders": set(ar.get("defenders", [])),
                    "sacrifices": list(ar.get("sacrifices", []))
                }
                print(f"Restored ongoing active raid: {active_raid['key']}, finishes in {int(active_raid['end_time'] - now_curr)}s")
            else:
                dur = int(ar.get("end_time", now_curr) - ar.get("start_time", now_curr))
                key = ar.get("key", "raid")
                defenders = set(ar.get("defenders", []))
                sacrifices = list(ar.get("sacrifices", []))
                msg = format_raid_victory_message(key, defenders, sacrifices, duration_seconds=dur)
                last_completed_raid = {
                    "key": key,
                    "title": RAID_LORE.get(key, (key, "Enemy Invaders"))[0],
                    "foes": RAID_LORE.get(key, (key, "Enemy Invaders"))[1],
                    "start_time": ar.get("start_time", now_curr),
                    "end_time": ar.get("end_time", now_curr),
                    "duration_seconds": dur,
                    "defenders": sorted(list(defenders)),
                    "sacrifices": sacrifices,
                    "flawless": len(sacrifices) == 0,
                    "message": msg
                }
                save_raid_state(False, {"last_raid": last_completed_raid})
                print(f"Resolved expired active raid on startup: {key} (active cleared)")

    handshake_re    = re.compile(r"Got handshake from client (\S+)")
    join_re         = re.compile(r"Got character ZDOID from ([^:]+) : (-?\d+):(\d+)")
    destroy_re      = re.compile(r"Destroying abandoned non persistent zdo \S+ owner (-?\d+)")
    socket_leave_re = re.compile(r"Closing socket\s+(\S+)")
    zero_re         = re.compile(r"(?:Connections 0 ZDOS|now 0 player\(s\))")
    raid_re         = re.compile(r"Random event set:(\w+)")
    boss_re         = re.compile(r"\b(defeated_\w+)\b", re.IGNORECASE)
    save_re         = re.compile(r"World save \(\d+/\d+\)")
    loc_re          = re.compile(r"Placed location (\w+) in zone (-?\d+),(-?\d+)")

    def handle_leave(name: str, reason: str = "", announce: bool = True) -> None:
        if name not in active_names:
            return
        active_names.remove(name)
        owner = name_to_owner.pop(name, None)
        if owner:
            owner_to_name.pop(owner, None)
        sid = name_to_socket.pop(name, None)
        if sid:
            socket_to_name.pop(sid, None)

        now_t = time.time()
        sess = active_sessions.pop(name, None) or {
            "login_time": now_t - 60,
            "deaths": [],
            "corpse_runs": 0,
            "raids_participated": set(),
            "raids_died_in": set(),
            "bosses_defeated": set(),
            "locations_discovered": set(),
            "sea_voyage": False
        }

        # Keep active sessions cache in sync
        try:
            save_active_sessions(active_sessions, active_names, name_to_owner, name_to_socket, owner_to_name, socket_to_name)
        except Exception:
            pass

        event_type, event_detail, dur_mins, deaths_count = classify_session_event(sess, reason, now_t)

        summary = {
            "logout_timestamp": now_t,
            "event_type": event_type,
            "event_detail": event_detail,
            "duration_mins": dur_mins,
            "deaths_count": deaths_count,
            "exit_reason": reason
        }

        # Guard: If silent or service shutdown or zero flush, do NOT broadcast and do not overwrite player state
        if not announce or reason in ("service_shutdown", "zero_flush", "silent"):
            print(f"Silent leave ({reason}): {name} [{event_type}] (no broadcast sent)")
            return

        save_player_state(name, summary)

        msg_wa = get_session_leave_message(name, event_type, summary, target="whatsapp")
        print(f"Leave ({reason}): {name} [{event_type}] => {msg_wa}")
        if ENABLE_TELEGRAM:
            msg_tg = get_session_leave_message(name, event_type, summary, target="telegram")
            send_telegram(msg_tg)
        send_whatsapp(msg_wa)
        if event_type in ("RAGE_QUIT", "CORPSE_RUN_FAIL", "SEA_CASUALTY"):
            try:
                from valheim_voice import speak_eulogy
                speak_eulogy(name, event_type)
            except Exception as ve:
                print(f"[Monitor] Voice eulogy skipped: {ve}", file=sys.stderr)

    def check_raid_completion(now_t: float, force: bool = False) -> None:
        nonlocal active_raid, last_completed_raid
        if not active_raid:
            return
        time_since_casualty = now_t - active_raid.get("last_casualty_time", 0)
        has_calm = (active_raid.get("last_casualty_time", 0) == 0) or (time_since_casualty >= CALM_BUFFER)
        if force or (now_t >= active_raid["end_time"] and has_calm):
            dur = int(now_t - active_raid["start_time"])
            key = active_raid["key"]
            defenders = set(active_raid["defenders"])
            sacrifices = list(active_raid["sacrifices"])

            msg = format_raid_victory_message(key, defenders, sacrifices, duration_seconds=dur)
            print(f"Raid victory shout triggered: {key} (defenders: {defenders}, sacrifices: {sacrifices}, duration: {dur}s)")
            send_whatsapp(msg)
            try:
                from valheim_voice import speak_raid_victory
                speak_raid_victory(key, flawless=(len(sacrifices) == 0), defenders=list(defenders))
            except Exception as ve:
                print(f"[Monitor] Voice raid victory skipped: {ve}", file=sys.stderr)

            last_completed_raid = {
                "key": key,
                "title": RAID_LORE.get(key, (key, "Enemy Invaders"))[0],
                "foes": RAID_LORE.get(key, (key, "Enemy Invaders"))[1],
                "start_time": active_raid["start_time"],
                "end_time": now_t,
                "duration_seconds": dur,
                "defenders": sorted(list(defenders)),
                "sacrifices": sacrifices,
                "flawless": len(sacrifices) == 0,
                "message": msg
            }
            save_raid_state(False, {"last_raid": last_completed_raid})
            active_raid = None

    def run_db_and_farm_checks() -> None:
        nonlocal last_db_check_time
        last_db_check_time = time.time()
        try:
            db_bosses = get_db2_defeated_bosses()
            new_bosses = db_bosses - known_defeated
            for b_key in new_bosses:
                known_defeated.add(b_key)
                save_known_defeated_bosses(known_defeated)
                for p in active_names:
                    if p in active_sessions:
                        active_sessions[p]["bosses_defeated"].add(b_key)
                msg = handle_boss_defeat(b_key, active_names)
                print(f"Boss defeat triggered (db2): {b_key}")
                send_whatsapp(msg)
                try:
                    from valheim_voice import speak_boss_defeat
                    speak_boss_defeat(b_key, list(active_names))
                except Exception as ve:
                    print(f"[Monitor] Voice boss defeat proclamation skipped: {ve}", file=sys.stderr)

            db_hildir = get_db2_hildir_quests()
            new_hildir = db_hildir - known_hildir_quests
            for q_key in new_hildir:
                known_hildir_quests.add(q_key)
                save_known_hildir_quests(known_hildir_quests)
                loc_title, reward = HILDIR_QUEST_MAP.get(q_key, ("an ancient dungeon", "New wares"))
                msg = (
                    f"📦 *[Hildir's Request]* A lost brass chest from the *{loc_title}* was returned to *Hildir*!\n"
                    f"• *Reward:* *{reward}* unlocked in her shop at the Meadows camp!"
                )
                print(f"Hildir quest completed: {q_key}")
                send_whatsapp(msg)
                try:
                    from valheim_voice import speak_hildir_quest
                    speak_hildir_quest(loc_title, reward)
                except Exception as ve:
                    print(f"[Monitor] Voice Hildir quest skipped: {ve}", file=sys.stderr)

            # Check for Homestead Seed Cycle completion
            try:
                import valheim_farm
                valheim_farm.check_and_announce_seed_cycle()
            except Exception as e:
                sys.stderr.write(f"[Monitor] Error checking farm seed cycle: {e}\n")
        except Exception as ex:
            sys.stderr.write(f"[Monitor] Error running db and farm checks: {ex}\n")

    # Handle clean termination
    def shutdown_handler(signum: int, frame: Any) -> None:
        print(f"Shutting down Valheim monitor cleanly on signal {signum}...")
        try:
            save_active_sessions(active_sessions, active_names, name_to_owner, name_to_socket, owner_to_name, socket_to_name)
        except Exception as e:
            print(f"Error persisting active sessions on shutdown: {e}")

        # NOTE: Do NOT call handle_leave here! Valheim monitor service restarts/deployments
        # are daemon lifecycle events, not in-game player departures.

        if active_raid:
            save_raid_state(True, {"active_raid": active_raid})
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    try:
        file = open(LOG_FILE, "r", errors="ignore")
        file.seek(0, os.SEEK_END)
    except FileNotFoundError:
        print(f"Waiting for log file {LOG_FILE}...")
        while not os.path.exists(LOG_FILE):
            time.sleep(5)
        file = open(LOG_FILE, "r", errors="ignore")
        file.seek(0, os.SEEK_END)

    while True:
        now_curr = time.time()
        check_raid_completion(now_curr)

        if now_curr - last_db_check_time > 60:
            run_db_and_farm_checks()

        line = file.readline()
        if not line:
            if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) < file.tell():
                print("Log file rotated/truncated, resetting...")
                file.close()
                file = open(LOG_FILE, "r", errors="ignore")
                active_names.clear()
                active_sessions.clear()
                name_to_owner.clear()
                name_to_socket.clear()
                owner_to_name.clear()
                socket_to_name.clear()
                last_id_seen = None
                try:
                    if os.path.exists(ACTIVE_SESSIONS_FILE):
                        os.remove(ACTIVE_SESSIONS_FILE)
                except Exception:
                    pass
            else:
                time.sleep(1)
            continue

        # Handshake
        m_handshake = handshake_re.search(line)
        if m_handshake:
            last_id_seen = m_handshake.group(1).rstrip(",")
            continue

        # Character Join or Character Death
        m_join = join_re.search(line)
        if m_join:
            raw_name = m_join.group(1).strip()
            name = format_player_name(raw_name)
            owner = m_join.group(2).strip()
            if owner != "0":
                name_to_owner[name] = owner
                owner_to_name[owner] = name
                if last_id_seen:
                    name_to_socket[name] = last_id_seen
                    socket_to_name[last_id_seen] = name
                    last_id_seen = None

                if name not in active_names:
                    active_names.add(name)
                    last_states = load_player_states()
                    last_state = last_states.get(name)
                    join_msg_wa = get_session_resume_message(name, last_state, target="whatsapp")
                    print(f"Join: {name} (owner={owner}, sid={name_to_socket.get(name)}) => {join_msg_wa}")
                    if ENABLE_TELEGRAM:
                        join_msg_tg = get_session_resume_message(name, last_state, target="telegram")
                        send_telegram(join_msg_tg)
                    send_whatsapp(join_msg_wa)

                    active_sessions[name] = {
                        "login_time": time.time(),
                        "deaths": [],
                        "corpse_runs": 0,
                        "raids_participated": set(),
                        "raids_died_in": set(),
                        "bosses_defeated": set(),
                        "locations_discovered": set(),
                        "sea_voyage": False
                    }
                try:
                    save_active_sessions(active_sessions, active_names, name_to_owner, name_to_socket, owner_to_name, socket_to_name)
                except Exception:
                    pass

                if active_raid:
                    active_raid["defenders"].add(name)
                    if name in active_sessions:
                        active_sessions[name]["raids_participated"].add(active_raid["key"])
                    save_raid_state(True, {
                        "active_raid": {
                            "key": active_raid["key"],
                            "title": RAID_LORE.get(active_raid["key"], (active_raid["key"], "Enemy Invaders"))[0],
                            "foes": RAID_LORE.get(active_raid["key"], (active_raid["key"], "Enemy Invaders"))[1],
                            "start_time": active_raid["start_time"],
                            "end_time": active_raid["end_time"],
                            "max_end_time": active_raid.get("max_end_time", active_raid["start_time"] + MAX_RAID_DURATION),
                            "last_casualty_time": active_raid.get("last_casualty_time", 0),
                            "defenders": sorted(list(active_raid["defenders"])),
                            "sacrifices": active_raid["sacrifices"]
                        }
                    })
            else:
                # Character death: ZDOID 0:0
                if name and name != "0":
                    print(f"Death: {name}")
                    record_death(name, line, active_raid)
                    if name in active_sessions:
                        sess = active_sessions[name]
                        now_death = time.time()
                        if sess["deaths"] and (now_death - sess["deaths"][-1] <= 180):
                            sess["corpse_runs"] += 1
                        sess["deaths"].append(now_death)
                        if active_raid:
                            sess["raids_died_in"].add(active_raid["key"])
                    if active_raid:
                        active_raid["sacrifices"].append(name)
                        active_raid["defenders"].add(name)
                        active_raid["last_casualty_time"] = now_curr
                        needed_end = now_curr + CALM_BUFFER
                        if active_raid["end_time"] < needed_end:
                            active_raid["end_time"] = min(needed_end, active_raid.get("max_end_time", active_raid["start_time"] + MAX_RAID_DURATION))
                        print(f"Raid casualty recorded: {name} (end_time extended to {int(active_raid['end_time'] - now_curr)}s from now)")
                        save_raid_state(True, {
                            "active_raid": {
                                "key": active_raid["key"],
                                "title": RAID_LORE.get(active_raid["key"], (active_raid["key"], "Enemy Invaders"))[0],
                                "foes": RAID_LORE.get(active_raid["key"], (active_raid["key"], "Enemy Invaders"))[1],
                                "start_time": active_raid["start_time"],
                                "end_time": active_raid["end_time"],
                                "max_end_time": active_raid.get("max_end_time", active_raid["start_time"] + MAX_RAID_DURATION),
                                "last_casualty_time": active_raid["last_casualty_time"],
                                "defenders": sorted(list(active_raid["defenders"])),
                                "sacrifices": active_raid["sacrifices"]
                            }
                        })
                    elif last_completed_raid and (now_curr - last_completed_raid.get("end_time", 0) <= POST_VICTORY_MOPUP_WINDOW):
                        last_completed_raid["sacrifices"].append(name)
                        if name not in last_completed_raid["defenders"]:
                            last_completed_raid["defenders"].append(name)
                        last_completed_raid["flawless"] = False

                        dur = last_completed_raid.get("duration_seconds", 0)
                        key = last_completed_raid.get("key", "raid")
                        updated_msg = format_raid_victory_message(
                            key,
                            set(last_completed_raid["defenders"]),
                            last_completed_raid["sacrifices"],
                            duration_seconds=dur
                        )
                        last_completed_raid["message"] = updated_msg
                        save_raid_state(False, {"last_raid": last_completed_raid})

                        amendment_msg = format_raid_amendment_message(key, name, last_completed_raid["sacrifices"])
                        print(f"Post-victory casualty amendment sent: {name} in {key}")
                        send_whatsapp(amendment_msg)
            last_id_seen = None
            continue

        # Graceful Leave (ZDO Destroyed by Valheim on menu logout)
        m_destroy = destroy_re.search(line)
        if m_destroy:
            owner = m_destroy.group(1).strip()
            name = owner_to_name.get(owner)
            if name:
                handle_leave(name, reason="logout")
            continue

        # Ungraceful Leave (Socket disconnect / timeout)
        m_socket = socket_leave_re.search(line)
        if m_socket:
            sid = m_socket.group(1).rstrip(",")
            name = socket_to_name.get(sid)
            if name:
                handle_leave(name, reason="socket_drop")
            continue

        # Zero connections sanity flush
        m_zero = zero_re.search(line)
        if m_zero and active_names:
            try:
                import valheim_whatsapp_action
                srv = valheim_whatsapp_action.get_server_info()
                if srv.get("player_count", 0) > 0:
                    print(f"[Monitor] zero_re matched '{line.strip()}', but server reports {srv['player_count']} online {srv.get('players')}. Suppressing false eviction.")
                    continue
            except Exception as e:
                print(f"[Monitor] Error verifying active count on zero_re: {e}")

            for name in list(active_names):
                handle_leave(name, reason="zero_flush", announce=False)

        # Horn of War: Random Event / Raid Alert
        m_raid = raid_re.search(line)
        if m_raid:
            raid_key = m_raid.group(1)
            for p in active_names:
                if p in active_sessions:
                    active_sessions[p]["raids_participated"].add(raid_key)
            now_t = time.time()
            if raid_key != last_raid_event or (now_t - last_raid_time > 300):
                if active_raid:
                    check_raid_completion(now_t, force=True)

                last_raid_event = raid_key
                last_raid_time = now_t
                jcode = get_active_join_code()
                msg = format_raid_alert(raid_key, active_names, jcode)
                print(f"Raid alert triggered: {raid_key} (defenders: {active_names})")
                send_whatsapp(msg)
                try:
                    from valheim_voice import speak_raid_alert
                    speak_raid_alert(raid_key, list(active_names))
                except Exception as ve:
                    print(f"[Monitor] Voice raid alert skipped: {ve}", file=sys.stderr)

                spawn_dur = RAID_SPAWN_DURATIONS.get(raid_key, 120)
                nominal_dur = spawn_dur + MOPUP_BUFFER
                active_raid = {
                    "key": raid_key,
                    "start_time": now_t,
                    "end_time": now_t + nominal_dur,
                    "max_end_time": now_t + MAX_RAID_DURATION,
                    "last_casualty_time": 0,
                    "defenders": set(active_names),
                    "sacrifices": []
                }
                save_raid_state(True, {
                    "active_raid": {
                        "key": raid_key,
                        "title": RAID_LORE.get(raid_key, (raid_key, "Enemy Invaders"))[0],
                        "foes": RAID_LORE.get(raid_key, (raid_key, "Enemy Invaders"))[1],
                        "start_time": now_t,
                        "end_time": active_raid["end_time"],
                        "max_end_time": active_raid["max_end_time"],
                        "last_casualty_time": 0,
                        "defenders": sorted(list(active_names)),
                        "sacrifices": []
                    }
                })
            continue

        # Boss Defeat War-Cry: from server log
        m_boss = boss_re.search(line)
        if m_boss:
            boss_key = m_boss.group(1).lower()
            if boss_key in BOSS_MAP and boss_key not in known_defeated:
                known_defeated.add(boss_key)
                save_known_defeated_bosses(known_defeated)
                for p in active_names:
                    if p in active_sessions:
                        active_sessions[p]["bosses_defeated"].add(boss_key)
                msg = handle_boss_defeat(boss_key, active_names)
                print(f"Boss defeat triggered (log): {boss_key}")
                send_whatsapp(msg)
                try:
                    from valheim_voice import speak_boss_defeat
                    speak_boss_defeat(boss_key, list(active_names))
                except Exception as ve:
                    print(f"[Monitor] Voice boss defeat proclamation skipped: {ve}", file=sys.stderr)
            continue

        # Location / Dungeon Discovery & Sea Voyage Detection
        m_loc = loc_re.search(line)
        if m_loc:
            loc_name = m_loc.group(1)
            try:
                zx = int(m_loc.group(2))
                zy = int(m_loc.group(3))
                dist_m = ((zx ** 2) + (zy ** 2)) ** 0.5 * 64
            except Exception:
                dist_m = 0
            is_shipwreck = loc_name.startswith("ShipWreck")
            is_deep_ocean_landfall = dist_m >= 1100

            for p in active_names:
                if p in active_sessions:
                    active_sessions[p]["locations_discovered"].add(loc_name)
                    if is_shipwreck or is_deep_ocean_landfall:
                        active_sessions[p]["sea_voyage"] = True

            # Real-Time POI Discovery Alert
            for poi_key, (icon, msg_text) in POI_MAP.items():
                if poi_key in loc_name:
                    now_t = time.time()
                    if now_t - last_poi_alerts.get(poi_key, 0) > 300:
                        last_poi_alerts[poi_key] = now_t
                        finder = ", ".join(sorted([format_player_name(p) for p in active_names])) if active_names else "A courageous Viking"
                        msg = f"{icon} *[Realm Discovery]* {msg_text} (Found by *{finder}*)"
                        print(f"POI discovered: {loc_name}")
                        send_whatsapp(msg)
                        try:
                            from valheim_voice import speak_poi_discovery
                            speak_poi_discovery(poi_key, finder)
                        except Exception as ve:
                            print(f"[Monitor] Voice POI discovery skipped: {ve}", file=sys.stderr)
                    break

            # Real-Time Trader Discovery Alert
            if loc_name in TRADER_LOC_MAP and loc_name not in known_traders:
                known_traders.add(loc_name)
                save_known_traders(known_traders)
                icon, t_name, t_biome, t_desc = TRADER_LOC_MAP[loc_name]
                finder = ", ".join(sorted([format_player_name(p) for p in active_names])) if active_names else "A courageous Viking"
                msg = (
                    f"{icon} *[Realm Discovery]* The camp of *{t_name}* has been discovered in the *{t_biome}* by *{finder}*!\n"
                    f"• *Trade Goods:* {t_desc}\n"
                    f"• *Tip:* Mark a portal tag at the site to link it back to base!"
                )
                print(f"Trader discovered: {loc_name}")
                send_whatsapp(msg)
                try:
                    from valheim_voice import speak_discovery
                    speak_discovery(t_name, t_biome, finder)
                except Exception as ve:
                    print(f"[Monitor] Voice trader discovery skipped: {ve}", file=sys.stderr)

        # World Save trigger for immediate DB2 check
        m_save = save_re.search(line)
        if m_save:
            run_db_and_farm_checks()


if __name__ == "__main__":
    try:
        monitor()
    except KeyboardInterrupt:
        print("Stopped.")
