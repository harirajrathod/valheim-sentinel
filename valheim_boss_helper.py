#!/usr/bin/env python3
"""
/root/valheim_boss_helper.py
Comprehensive Valheim Boss Battle Analysis & Publication Engine.

Provides deep telemetry analysis of boss encounters, casualty breakdowns,
warrior role classifications, corpse run tracking, and publication-grade
WhatsApp chronicles for every boss battle in Valheim.
"""

import os
import sys
import re
import json
from datetime import datetime, timezone, timedelta
from collections import Counter

sys.path.insert(0, "/root")
from valheim_utils import (
    safe_send_whatsapp,
    VALHEIM_WHATSAPP_GROUP,
    WHATSAPP_BRIDGE_URL,
    IST,
    LOG_FILE,
)

BOSS_BATTLES_FILE = "/root/valheim_boss_battles.json"

def format_player_name(name: str) -> str:
    if not name:
        return ""
    if name.strip().lower() in ("musashi", "musashi(musa bhai)", "musa bhai"):
        return "Musashi(Musa Bhai)"
    return name

BOSS_DATA = {
    "defeated_eikthyr": {
        "name": "Eikthyr ⚡",
        "title": "The Storm Stag of the Meadows",
        "biome": "Meadows",
        "altar_item": "Deer Trophies",
        "reward": "Hard Antler (Crafts first Antler Pickaxe)",
        "power": "Run & Jump Stamina Drain -60%",
        "next_era": "The Black Forest (The Bronze Age)",
        "next_objective": "Delve into Burial Chambers for Surtling Cores, smelt Copper & Tin, and seek the ancient altar of The Elder.",
        "stanza": (
            "The lightning flashed, the thunder broke,\n"
            "The horned beast in the meadows awoke.\n"
            "Through antler charges and storm-tossed plain,\n"
            "The stag was brought to heel and slain!\n"
            "With hard-won antler in their hand,\n"
            "The Bronze Age beckons across the land!"
        )
    },
    "defeated_gdking": {
        "name": "The Elder 🌲",
        "title": "Colossus of the Black Forest",
        "biome": "Black Forest",
        "altar_item": "Ancient Seeds",
        "reward": "Swamp Key (Unlocks Sunken Crypts)",
        "power": "Wood Cutting Speed +60%",
        "next_era": "The Swamp Era (The Iron Age)",
        "next_objective": "Venture into the murky Swamps, unlock Sunken Crypts with the Swamp Key, mine Scrap Iron, and prepare to face Bonemass.",
        "stanza": (
            "The seeds were burnt, the ancient woke,\n"
            "The forest screamed in fire and smoke.\n"
            "Through vine and thorn and bitter falls,\n"
            "The shieldwall answered Valhalla's calls!\n"
            "The titan cracked, the colossus fell,\n"
            "The Swamp awaits with its murky hell!"
        )
    },
    "defeated_bonemass": {
        "name": "Bonemass ☣️",
        "title": "The Slime Sovereign of the Swamps",
        "biome": "Swamps",
        "altar_item": "Withered Bones",
        "reward": "Wishbone (Detects buried Silver & Buried Treasure)",
        "power": "Physical Damage Resistance (Blunt, Slash, Pierce)",
        "next_era": "The Mountain Era (The Silver Age)",
        "next_objective": "Equip Wolf armor or frost resistance mead, climb the freezing Mountain peaks with the Wishbone, mine Silver, and hunt Moder.",
        "stanza": (
            "From murky ooze and rotten fen,\n"
            "The toxic sovereign rose again.\n"
            "With maces swung and blunt force true,\n"
            "Through poison clouds the warriors blew!\n"
            "The wishbone hums beneath the snow,\n"
            "To frozen mountain peaks we go!"
        )
    },
    "defeated_writhan": {
        "name": "Moder ❄️",
        "title": "The Weeping Queen of the Mountains",
        "biome": "Mountains",
        "altar_item": "Dragon Eggs",
        "reward": "Dragon Tear (Crafts Artisan Table & Blast Furnace)",
        "power": "Always Tailwind when Sailing",
        "next_era": "The Plains Era (The Black Metal Age)",
        "next_objective": "Build the Artisan Table, spin Linen Thread, smelt Black Metal, build windmills, and assault Fuling villages.",
        "stanza": (
            "A frozen shriek above the cloud,\n"
            "The mountain queen in frost was proud.\n"
            "From icy skies her tears rained down,\n"
            "Yet Viking arrows claimed her crown!\n"
            "The wind now fills our sails with grace,\n"
            "To golden Plains we set our chase!"
        )
    },
    "defeated_goblinking": {
        "name": "Yagluth ⚔️",
        "title": "The Skeletal Sorcerer of the Plains",
        "biome": "Plains",
        "altar_item": "Fuling Totems",
        "reward": "Torn Spirit (Crafts Wisp Fountain)",
        "power": "Elemental Resistance (Fire, Frost, Lightning)",
        "next_era": "The Mistlands Era (The Eitr & Black Marble Age)",
        "next_objective": "Capture Wisps to pierce the eternal fog of the Mistlands, craft Eitr magic, and locate the Infested Mines to challenge The Queen.",
        "stanza": (
            "The sky rained fire, the meteors fell,\n"
            "The severed king summoned from hell.\n"
            "With black metal forged and barley fed,\n"
            "The sorcerer joined the ancient dead!\n"
            "Through blinding mist a spirit guides,\n"
            "Where ancient carapace resides!"
        )
    },
    "defeated_queen": {
        "name": "The Queen 🪲",
        "title": "The Hive Sovereign of the Mistlands",
        "biome": "Mistlands",
        "altar_item": "Sealbreaker",
        "reward": "Majestic Carapace (Unlocks Ashlands preparation)",
        "power": "Eitr Regeneration +100% & Mining Speed +60%",
        "next_era": "The Ashlands Era (The Flametal Age)",
        "next_objective": "Construct the Drakkar ship, brew Fire Resistance Barley Wine, sail past the boiling ocean into the fiery Ashlands, and breach the Charred Fortresses.",
        "stanza": (
            "Within the vault the brood did crawl,\n"
            "The hive queen ruled the shadowed hall.\n"
            "With magic, blade, and carapace broke,\n"
            "The queen went down in blood and smoke!\n"
            "Beyond the boil the boiling sea,\n"
            "The Ashlands burn for you and me!"
        )
    },
    "defeated_fader": {
        "name": "Fader 🔥",
        "title": "Lord of Cinder of the Ashlands",
        "biome": "Ashlands",
        "altar_item": "Bell Fragments",
        "reward": "Fader Trophy & Mythic Spoils",
        "power": "Increased Carry Weight & Movement Speed in Ashlands",
        "next_era": "The Deep North Era (The Glacial Age)",
        "next_objective": "Venture into the extreme frozen Deep North, locate Mörkhalla, smelt Bloodgold in the Frost Foundry, craft Intricate Keys, and claim Malicious Blood to summon Kall Fimbulbringer.",
        "stanza": (
            "The burning lord of cinder rose,\n"
            "Amidst the ash where no green grows.\n"
            "Through flame and spire the clan fought on,\n"
            "Until the tyrant's breath was gone!\n"
            "The Ashlands bow before our blade,\n"
            "A legend that will never fade!"
        )
    },
    "defeated_fimbulbringer": {
        "name": "Kall Fimbulbringer ❄️",
        "title": "The Frost Jotun King of the Deep North",
        "biome": "Deep North",
        "altar_item": "Malicious Blood (3x)",
        "reward": "Fimbulbringer Trophy & Heart of the Jotun",
        "power": "Supreme Frost Immunity & Glacial Wrath",
        "next_era": "Valhalla Ascended (Realm Mastered)",
        "next_objective": "All eight Forsaken have fallen. The realm of Valheim is conquered!",
        "stanza": (
            "Across the frozen peaks of white,\n"
            "The Jotun king met Viking might.\n"
            "With bloodgold blade and frost defied,\n"
            "The last Forsaken fell and died!\n"
            "From Meadows green to northern cold,\n"
            "The saga of our clan is told!"
        )
    }
}
# Alias for game engine's internal Moder defeat key
BOSS_DATA["defeated_dragon"] = BOSS_DATA["defeated_writhan"]

def load_boss_battles():
    if os.path.exists(BOSS_BATTLES_FILE):
        try:
            with open(BOSS_BATTLES_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {BOSS_BATTLES_FILE}: {e}", file=sys.stderr)
    return {}

def save_boss_battle(boss_key, battle_data):
    try:
        battles = load_boss_battles()
        battles[boss_key] = battle_data
        with open(BOSS_BATTLES_FILE, "w") as f:
            json.dump(battles, f, indent=2)
    except Exception as e:
        print(f"Error saving {BOSS_BATTLES_FILE}: {e}", file=sys.stderr)

def get_recent_boss_battles(hours=24):
    battles = load_boss_battles()
    recent = []
    now_utc = datetime.now(timezone.utc)
    for b_key, b_data in battles.items():
        ts_str = b_data.get("defeat_time_utc")
        if ts_str:
            try:
                dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if (now_utc - dt).total_seconds() <= hours * 3600:
                    recent.append(b_data)
            except Exception:
                pass
    return recent

def analyze_boss_battle(boss_key, defeat_time_dt=None, active_players=None, log_file=LOG_FILE, lookback_minutes=45):
    """
    Scans the server log for combat deaths and player events leading up to the boss defeat.
    Returns structured telemetry including duration, per-player deaths, corpse runs, and assigned roles.
    """
    if defeat_time_dt is None:
        defeat_time_dt = datetime.now(timezone.utc)
    elif defeat_time_dt.tzinfo is None:
        defeat_time_dt = defeat_time_dt.replace(tzinfo=timezone.utc)

    window_start = defeat_time_dt - timedelta(minutes=lookback_minutes)
    
    deaths = []
    players_seen = set()
    if active_players:
        if isinstance(active_players, (set, list)):
            players_seen.update(active_players)
        elif isinstance(active_players, str):
            players_seen.add(active_players)

    if os.path.exists(log_file):
        try:
            with open(log_file, "r", errors="ignore") as f:
                for line in f:
                    m_ts = re.match(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}):", line)
                    if not m_ts:
                        continue
                    ts_str = m_ts.group(1)
                    try:
                        dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue

                    if dt < window_start or dt > defeat_time_dt + timedelta(minutes=2):
                        continue

                    if ": 0:0" in line:
                        m_death = re.search(r"Got character ZDOID from ([^:]+) : 0:0", line)
                        if m_death:
                            pname = m_death.group(1).strip()
                            if pname and pname != "0":
                                deaths.append((dt, pname))
                                players_seen.add(pname)
                    elif "Got character ZDOID from " in line:
                        m_join = re.search(r"Got character ZDOID from ([^:]+) : (-?\d+):", line)
                        if m_join:
                            pname = m_join.group(1).strip()
                            owner = m_join.group(2).strip()
                            if pname and owner != "0":
                                players_seen.add(pname)
        except Exception as e:
            print(f"Error scanning log for boss battle: {e}", file=sys.stderr)

    # Calculate per-player deaths and corpse runs
    warrior_stats = {}
    for p in sorted(players_seen):
        warrior_stats[p] = {
            "falls": 0,
            "corpse_runs": 0,
            "death_times": []
        }

    for dt, p in deaths:
        if p not in warrior_stats:
            warrior_stats[p] = {"falls": 0, "corpse_runs": 0, "death_times": []}
        st = warrior_stats[p]
        if st["death_times"] and (dt - st["death_times"][-1]).total_seconds() <= 180:
            st["corpse_runs"] += 1
        st["falls"] += 1
        st["death_times"].append(dt)

    total_falls = len(deaths)
    
    # Calculate battle start and duration
    if deaths:
        battle_start_dt = deaths[0][0]
        duration_seconds = max(60, int((defeat_time_dt - battle_start_dt).total_seconds()))
    else:
        duration_seconds = 180
        battle_start_dt = defeat_time_dt - timedelta(seconds=duration_seconds)

    duration_mins = max(1, round(duration_seconds / 60))

    # Determine warrior roles dynamically
    # Sort warriors by falls descending
    sorted_warriors = sorted(warrior_stats.items(), key=lambda x: (x[1]["falls"], x[1]["corpse_runs"]), reverse=True)
    
    roles = {}
    max_falls = sorted_warriors[0][1]["falls"] if sorted_warriors else 0

    for idx, (p, st) in enumerate(sorted_warriors):
        falls = st["falls"]
        c_runs = st["corpse_runs"]
        
        if falls == 0:
            title = "The Unbroken Champion"
            desc = "Survived the entire mythological onslaught without a single fall, holding the shieldwall firm."
        elif falls == max_falls and falls >= 5:
            if idx == 0:
                title = "The Indomitable Berserker"
                desc = "Frontline target of primary boss attacks; died, sprinted back naked, and kept attacking until the end."
            else:
                title = "The Valiant Sponge"
                desc = "Absorbed massive boss aggro, trading life after life to give allies room to breathe and strike."
        elif c_runs >= 3:
            title = "The Relentless Vanguard"
            desc = f"Crushed repeatedly in the thick of melee, executing {c_runs} frantic naked corpse runs through the dark."
        elif falls >= 3:
            title = "The Fearless Skirmisher"
            desc = "Repeatedly charged the flank, trading blows with the beast and rallying quickly after each fall."
        elif falls in (1, 2):
            if idx == len(sorted_warriors) - 1 or idx == len(sorted_warriors) - 2:
                title = "The Anchor & Executioner"
                desc = "Dodged through the chaos, kept high uptime, and delivered devastating critical strikes to bring down the titan."
            else:
                title = "The Tactical Marksman"
                desc = "Held perimeter distance, kited through obstacles, and laid down precision bow fire."
        else:
            title = "The Valiant Raider"
            desc = "Stood shoulder-to-shoulder with the clan, defying the ancient beast."

        roles[p] = {
            "title": title,
            "desc": desc,
            "falls": falls,
            "corpse_runs": c_runs
        }

    start_ist = battle_start_dt.astimezone(IST).strftime("%H:%M")
    defeat_ist = defeat_time_dt.astimezone(IST).strftime("%H:%M IST")

    battle_data = {
        "boss_key": boss_key,
        "boss_name": BOSS_DATA.get(boss_key, {}).get("name", boss_key.replace("defeated_", "").title()),
        "defeat_time_utc": defeat_time_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "defeat_time_ist": defeat_time_dt.astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST"),
        "time_range_ist": f"{start_ist} – {defeat_ist}",
        "duration_minutes": duration_mins,
        "total_falls": total_falls,
        "warriors": roles,
        "active_players": sorted(list(players_seen))
    }

    return battle_data

def format_boss_assessment_message(boss_key, battle_data, day=None):
    """
    Formats a publication-grade WhatsApp assessment for a boss fight.
    Uses clean WhatsApp markdown with no breaking tables.
    """
    b_info = BOSS_DATA.get(boss_key, {
        "name": boss_key.replace("defeated_", "").title(),
        "title": "Ancient Dread Lord",
        "biome": "The Realm",
        "altar_item": "Sacrificial Trophies",
        "reward": "Mythic Spoils",
        "power": "Forsaken Blessing",
        "next_era": "The Next Frontier",
        "next_objective": "Push deeper into the unexplored biomes.",
        "stanza": "The ancient fell, the realm rejoices!\nRaise your horns and lift your voices!"
    })

    boss_name = b_info["name"]
    biome = b_info["biome"]
    dur_mins = battle_data.get("duration_minutes", 15)
    total_falls = battle_data.get("total_falls", 0)
    time_range = battle_data.get("time_range_ist", "Recent Battle")
    warriors = battle_data.get("warriors", {})
    w_count = len(warriors)
    day_str = f"Day {day}" if day else "the realm"

    falls_hdr = f"{total_falls} Fall" if total_falls == 1 else f"{total_falls} Falls"
    falls_str = f"{total_falls} combat fall" if total_falls == 1 else f"{total_falls} combat falls"
    warriors_str = f"{w_count} warrior" if w_count == 1 else f"{w_count} warriors"

    lines = [
        f"🏆⚡ *VICTORY IN VALHEIM! THE FALL OF {boss_name.upper()}!* ⚡🏆",
        f"_{b_info['title']} Vanquished!_",
        "",
        "🔥 *The Sacrificial Altar*",
        f"On {day_str}, deep within the {biome}, the offering of *{b_info['altar_item']}* was burned upon the ancient stone. The earth shuddered and *{boss_name}* arose in terrifying wrath!",
        "",
        f"⚔️ *The {dur_mins}-Minute Meat Grinder ({falls_hdr})*",
        f"• *Battle Duration:* ~{dur_mins} minutes ({time_range})",
        f"• *Total Casualties:* {falls_str} across {warriors_str}",
        "",
        "🩸 *Sacrifices & Battle Valor:*"
    ]

    if warriors:
        for p, info in sorted(warriors.items(), key=lambda x: (x[1]["falls"], x[1]["corpse_runs"]), reverse=True):
            f_count = info["falls"]
            f_str = f"*{f_count} fall*" if f_count == 1 else f"*{f_count} falls*"
            lines.append(f"• 💀 *{format_player_name(p)}:* {f_str} — _{info['title']}:_ {info['desc']}")
    else:
        lines.append("• 🛡️ *Flawless Victory:* Not a single Viking fell in battle!")

    if total_falls > 0:
        lines.append("")
        lines.append("🏃💨 *The Great Naked Sprint of Valhalla*")
        lines.append("Whenever a warrior fell, they respawned at base on 25 HP and zero armor, executing frantic naked sprints through the dark to snatch their tombstones before the beast could strike again!")

    lines.append("")
    lines.append("🎁 *Claimed Spoils & Realm Unlocks:*")
    lines.append(f"• 🗝️ *{b_info['reward']}*")
    lines.append(f"• 🦌 *{boss_name} Trophy* ({b_info['power']} at Sacrificial Stones)")
    lines.append(f"• 🌲 *The {biome} Era Closes* ➔ *{b_info['next_era']} Begins!*")
    lines.append(f"• 🎯 *Next Objective:* {b_info['next_objective']}")
    lines.append("")
    lines.append("📜 *The Skald's Stanza:*")
    stanza_lines = b_info["stanza"].split("\n")
    for s_line in stanza_lines:
        lines.append(f"_{s_line}_")
    lines.append("")
    lines.append("Odin nods in deep approval. Skål to the champions of Valheim! 🍻🥩🔥")

    return "\n".join(lines)

def post_to_whatsapp(text):
    try:
        success = safe_send_whatsapp(text, chat_id=VALHEIM_WHATSAPP_GROUP, bridge_url=WHATSAPP_BRIDGE_URL, timeout=15)
        if success:
            print("Successfully posted Boss Victory Chronicle to WhatsApp.")
        return success
    except Exception as e:
        print(f"Error posting Boss Victory Chronicle to WhatsApp: {e}", file=sys.stderr)
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Valheim Boss Battle Analysis & Publication")
    parser.add_argument("--trigger", type=str, help="Boss key to trigger battle analysis for (e.g. defeated_bonemass or bonemass)")
    parser.add_argument("--latest", action="store_true", help="Print or post latest boss victory chronicle")
    parser.add_argument("--list", action="store_true", help="List all recorded boss battles")
    parser.add_argument("--post", action="store_true", help="Post chronicle to WhatsApp")
    parser.add_argument("--dry-run", action="store_true", help="Do not mutate state or post")
    args = parser.parse_args()

    battles = load_boss_battles()

    if args.list:
        print("=== RECORDED BOSS BATTLES ===")
        for k, v in battles.items():
            print(f"• {k}: {v.get('boss_name')} - {v.get('defeat_time_ist')} ({v.get('total_falls')} falls)")
        return

    if args.latest:
        if not battles:
            print("No boss battles recorded yet.")
            return
        latest_key = list(battles.keys())[-1]
        b_data = battles[latest_key]
        from valheim_info import get_persisted_day
        day = get_persisted_day()
        msg = format_boss_assessment_message(latest_key, b_data, day=day)
        print(msg)
        if args.post and not args.dry_run:
            post_to_whatsapp(msg)
        return

    if args.trigger:
        boss_key = args.trigger.lower().strip()
        if not boss_key.startswith("defeated_"):
            boss_key = f"defeated_{boss_key}"

        from valheim_info import get_persisted_day
        day = get_persisted_day()
        active_players = ["Dexter", "Hilda", "Musashi", "Faye"]

        battle_data = analyze_boss_battle(
            boss_key,
            defeat_time_dt=datetime.now(timezone.utc),
            active_players=active_players
        )
        msg = format_boss_assessment_message(boss_key, battle_data, day=day)
        print(msg)

        if not args.dry_run:
            save_boss_battle(boss_key, battle_data)
            # Update valheim_bosses_defeated.json
            boss_state_file = "/root/valheim_bosses_defeated.json"
            known = set()
            if os.path.exists(boss_state_file):
                try:
                    with open(boss_state_file) as f:
                        known = set(json.load(f))
                except Exception:
                    pass
            known.add(boss_key)
            with open(boss_state_file, "w") as f:
                json.dump(sorted(list(known)), f, indent=2)

        if args.post and not args.dry_run:
            post_to_whatsapp(msg)

if __name__ == "__main__":
    main()
