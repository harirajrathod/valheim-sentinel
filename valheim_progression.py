import os
import sys
import time
import re
import glob
import json
import zlib
import subprocess
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/root')
from valheim_utils import (
    LOG_FILE,
    format_player_name,
    safe_load_json,
    atomic_save_json,
)

from valheim_constants import BOSS_CHAIN

DEATHS_FILE = "/root/valheim_deaths_history.json"


def _load_db2_decomp():
    """Load and decompress the latest db2 world save. Returns bytes or b''."""
    db_files = glob.glob('/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/_main.*.db2')
    if not db_files:
        return b''
    def _sid(p):
        m = re.search(r'_main\.(\d+)\.db2$', p)
        return int(m.group(1)) if m else 0
    try:
        with open(max(db_files, key=_sid), 'rb') as f:
            data = f.read()
        idx = data.find(b'\x1f\x8b\x08')
        if idx == -1:
            return b''
        return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(data[idx:])
    except Exception:
        return b''

def get_progression_state():
    """
    Returns the authoritative clan progression state derived from both
    the JSON boss file and the db2 world save. Handles alias keys
    (e.g. defeated_writhan == Moder).

    Returns dict:
        bosses_defeated  : list of canonical boss dicts that are slain
        current_tier     : int 0-8 (0 = no bosses)
        current_biome    : str  (biome of last defeated boss, or 'Meadows')
        next_boss        : dict or None  (next undefeated boss in chain)
        next_biome       : str  (biome of next boss, or current if all done)
        all_defeated     : bool
        defeated_keys    : set  of canonical 'key' strings
    """
    # 1. Load JSON override
    json_defeated = set()
    try:
        with open('/root/valheim_bosses_defeated.json') as f:
            for k in json.load(f):
                json_defeated.add(k.lower().strip())
    except Exception:
        pass

    # 2. Load db2 keys
    decomp = _load_db2_decomp()

    # 3. Determine which canonical bosses are slain
    defeated_canonical = set()
    for boss in BOSS_CHAIN:
        all_keys = [boss['key']] + boss['aliases']
        is_slain = any(
            (k.encode() in decomp) or (k in json_defeated)
            for k in all_keys
        )
        if is_slain:
            defeated_canonical.add(boss['key'])

    # 4. Walk chain to find current tier & next boss
    current_tier = 0
    current_biome = 'Meadows'
    next_boss = None
    bosses_defeated = []

    for boss in BOSS_CHAIN:
        if boss['key'] in defeated_canonical:
            bosses_defeated.append(boss)
            current_tier = boss['tier']
            current_biome = boss['biome']
        else:
            if next_boss is None:
                next_boss = boss
            # don't break — keep walking to build full defeated list

    all_defeated = (next_boss is None)
    next_biome = next_boss['biome'] if next_boss else current_biome

    return {
        'bosses_defeated': bosses_defeated,
        'current_tier': current_tier,
        'current_biome': current_biome,
        'next_boss': next_boss,
        'next_biome': next_biome,
        'all_defeated': all_defeated,
        'defeated_keys': defeated_canonical,
    }

DAY_STATE_FILE = "/root/valheim_world_day.json"

def get_persisted_day(check_log=True):
    data = safe_load_json(DAY_STATE_FILE, default={"day": 98})
    day = int(data.get("day", 98))

    if check_log and os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r', errors='ignore') as f:
                for line in reversed(f.readlines()[-2500:]):
                    m = re.search(r'Time\s+[\d\.]+,\s*day:(\d+)\s+nextm:[\d\.]+', line)
                    if m:
                        parsed_day = int(m.group(1))
                        if parsed_day > day:
                            day = parsed_day
                            save_persisted_day(day)
                        break
        except Exception:
            pass

    return day

def save_persisted_day(day):
    try:
        cur = get_persisted_day(check_log=False)
        if day >= cur:
            atomic_save_json(DAY_STATE_FILE, {
                "day": day,
                "updated_at": datetime.now(timezone.utc).isoformat()
            })
    except Exception:
        pass

def get_active_boss_and_era():
    from valheim_inventory import scan_world_inventory
    """
    Returns structured era, target boss, active biome, and lore context
    based on current defeated bosses and world progression.
    Uses get_progression_state() which correctly handles all boss key aliases
    (e.g. defeated_writhan == Moder / defeated_dragon).
    """
    prog = get_progression_state()
    next_boss_data = prog['next_boss']

    BOSS_LORE = {
        'defeated_eikthyr': 'Boar, Deer, Wood, Stone, Leather',
        'defeated_gdking':  'Copper, Tin, Bronze, Greydwarfs, Trolls',
        'defeated_bonemass':'Iron Scrap, Iron Bars, Ancient Bark, Blobs, Draugr, Leeches, Wraiths, Abominations, Poison',
        'defeated_dragon':  'Silver, Obsidian, Wolves, Drakes, Golems, Freeze',
        'defeated_goblinking': 'Black Metal, Tar, Fulings, Deathsquitos, Lox',
        'defeated_queen':   'Eitr, Black Marble, Seekers, Gjall, Dvergr, Sap',
        'defeated_fader':   'Flametal, Charred, Lava, Morgen, Valkyrie',
        'defeated_fimbulbringer': 'Bloodgold, Malicious Blood, Jotun, Frost Foundry, Glacial Relics, Intricate Keys',
    }
    ERA_NAMES = {
        'defeated_eikthyr':    'The Meadows Awakening',
        'defeated_gdking':     'The Bronze Age',
        'defeated_bonemass':   'The Swamp Era (The Iron Age)',
        'defeated_dragon':     'The Mountain Age (The Silver Era)',
        'defeated_goblinking': 'The Plains Conquest (The Black Metal Era)',
        'defeated_queen':      'The Mistlands Epoch (The Eitr Era)',
        'defeated_fader':      'The Ashlands Crusade (The Flametal Era)',
        'defeated_fimbulbringer': 'The Deep North Ascendancy (The Glacial Era)',
    }
    BOSS_TRIBUTES = {
        'defeated_eikthyr':    ('TrophyDeer', 2, 'Deer Trophies', None),
        'defeated_gdking':     ('AncientSeed', 3, 'Ancient Seeds', 'B_ELDER'),
        'defeated_bonemass':   ('WitheredBone', 10, 'Withered Bones', 'B_BONEMASS'),
        'defeated_dragon':     ('DragonEgg', 3, 'Dragon Eggs', 'B_MODER'),
        'defeated_goblinking': ('GoblinTotem', 5, 'Fuling Totems', 'B_YAGLUTH'),
        'defeated_queen':      ('Sealbreaker', 1, 'Sealbreaker', 'B_QUEEN'),
        'defeated_fader':      ('BellFragment', 3, 'Bell Fragments', 'B_FADER'),
        'defeated_fimbulbringer': ('MaliciousBlood', 3, 'Malicious Blood', 'B_FIMBULBRINGER'),
    }

    if next_boss_data:
        boss_key      = next_boss_data['key']
        target_boss   = next_boss_data['name']
        target_biome  = next_boss_data['biome']
        target_reward = next_boss_data['reward']
        lore_elements = BOSS_LORE.get(boss_key, '')
        current_era   = ERA_NAMES.get(boss_key, 'The Frontier Era')
    else:
        boss_key      = 'game_completed'
        target_boss   = 'Valhalla Ascended (Realm Mastered)'
        target_biome  = 'All Realms'
        target_reward = "Odin's Favor"
        lore_elements = 'All Forsaken conquered, peaceful realm'
        current_era   = 'The Age of Legends'

    tribute_summary = ""
    portal_tag = ""
    if boss_key in BOSS_TRIBUTES:
        mat_key, req_cnt, mat_name, portal_tag = BOSS_TRIBUTES[boss_key]
        try:
            totals, _ = scan_world_inventory()
            stock = totals.get(mat_key, 0)
            if stock >= req_cnt:
                tribute_summary = f"{stock} {mat_name} stockpiled (🔥 {req_cnt} required — {stock // req_cnt}x summon ready!)"
            else:
                tribute_summary = f"{stock}/{req_cnt} {mat_name} stockpiled (Need {req_cnt - stock} more)"
        except Exception:
            tribute_summary = f"{req_cnt} {mat_name} required"
        portal_tag = portal_tag or ""

    return {
        "current_era": current_era,
        "target_biome": target_biome,
        "target_boss": target_boss,
        "target_reward": target_reward,
        "boss_key": boss_key,
        "lore_elements": lore_elements,
        "tribute_summary": tribute_summary,
        "altar_portal": portal_tag,
    }

def get_era_report():
    from valheim_inventory import scan_world_inventory
    # 1. World Time, Day & Cycle
    day = get_persisted_day(check_log=False)
    world_time = None
    nextm = None

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r', errors='ignore') as f:
                for line in reversed(f.readlines()[-2500:]):
                    m = re.search(r'Time\s+([\d\.]+),\s*day:(\d+)\s+nextm:([\d\.]+)', line)
                    if m:
                        world_time = float(m.group(1))
                        parsed_day = int(m.group(2))
                        nextm = float(m.group(3))
                        day = max(day, parsed_day)
                        save_persisted_day(day)
                        break
        except Exception:
            pass

    if nextm is not None and world_time is not None:
        # A day is 1200s. Nighttime is ~360s preceding next morning.
        time_until_morning = nextm - world_time
        time_of_day = "Daytime ☀️" if time_until_morning > 360 else "Nighttime 🌙"
    else:
        time_of_day = "Daytime ☀️"

    # 2. Use central progression state (fixes defeated_writhan = Moder)
    prog = get_progression_state()
    next_boss_data = prog['next_boss']

    lines = [
        "🌅 *THE REALM OF VALHEIM10 — CALENDAR & ERA*",
        f"• *In-Game Calendar:* *Day {day}* ({time_of_day})",
        "• *Server Version:* Valheim 1.0 (Deep North / Crossplay)",
        "",
        "⚔️ *Boss Conquest Roadmap:*"
    ]

    next_boss_shown = False
    for boss in BOSS_CHAIN:
        is_slain = (boss['key'] in prog['defeated_keys'])
        if is_slain:
            lines.append(f"• ✅ *{boss['name']}* ({boss['biome']}) — Slain & Mounted")
        else:
            if not next_boss_shown:
                next_boss_shown = True
                lines.append(f"• ⏳ *{boss['name']}* ({boss['biome']}) — *CURRENT TARGET!*")
            else:
                lines.append(f"• 🔒 *{boss['name']}* ({boss['biome']}) — Locked")

    lines.append("")
    if next_boss_data:
        boss_key  = next_boss_data['key']
        BOSS_TRIBUTES = {
            'defeated_eikthyr':    ('TrophyDeer', 2, 'Deer Trophies', None),
            'defeated_gdking':     ('AncientSeed', 3, 'Ancient Seeds', 'B_ELDER'),
            'defeated_bonemass':   ('WitheredBone', 10, 'Withered Bones', 'B_BONEMASS'),
            'defeated_dragon':     ('DragonEgg', 3, 'Dragon Eggs', 'B_MODER'),
            'defeated_goblinking': ('GoblinTotem', 5, 'Fuling Totems', 'B_YAGLUTH'),
            'defeated_queen':      ('Sealbreaker', 1, 'Sealbreaker', 'B_QUEEN'),
            'defeated_fader':      ('BellFragment', 3, 'Bell Fragments', 'B_FADER'),
            'defeated_fimbulbringer': ('MaliciousBlood', 3, 'Malicious Blood', 'B_FIMBULBRINGER'),
        }
        lines.append(f"🎯 *Active Clan Mission:* Slay *{next_boss_data['name']}* in the *{next_boss_data['biome']}* to claim the *{next_boss_data['reward']}*!")
        if boss_key in BOSS_TRIBUTES:
            mat_key, req_cnt, mat_name, altar_portal_tag = BOSS_TRIBUTES[boss_key]
            try:
                totals, _ = scan_world_inventory()
                stock = totals.get(mat_key, 0)
                status_tribute = (
                    f"{stock} {mat_name} in base chests (🔥 {req_cnt} required — {stock // req_cnt}x summon ready!)"
                    if stock >= req_cnt else
                    f"{stock}/{req_cnt} {mat_name} in base chests (Need {req_cnt - stock} more)"
                )
            except Exception:
                status_tribute = f"{req_cnt} {mat_name} required"
            lines.append(f"• *Summon Tribute:* {status_tribute}")
            if altar_portal_tag:
                lines.append(f"• *Altar Portal:* `{altar_portal_tag}` (Linked & ready)")

        # Next biome context note
        next_biome = next_boss_data['biome']
        BIOME_NOTES = {
            'Black Forest':  "⚠️ _Bring a Bronze weapon and Troll Leather or better. Watch for Greydwarf Shamans._",
            'Swamps':        "⚠️ _Always brew Poison Resistance Mead before entering. Iron Scale armor is the minimum._",
            'Mountains':     "⚠️ _Frost Resistance Mead required until Wolf Armor is complete. Never mine Silver without the Wishbone._",
            'Plains':        "⚠️ _Deathsquitos one-shot light armor. Enter only with Wolf Armor minimum. Farm Fuling villages for Black Metal & Flax._",
            'Mistlands':     "⚠️ _Gjall detection is lethal. Craft Wisplight (Wispmother drop) to navigate the mist. Black Metal weapons are the minimum._",
            'Ashlands':      "⚠️ _Constant Charred spawns — never go without 100+ armor. Prepare Fire Resistance potions._",
            'Deep North':    "⚠️ _Jotun and Bloodgold enemies — Flametal armor is the target. Prepare Frost & Fire resistances._",
        }
        if next_biome in BIOME_NOTES:
            lines.append("")
            lines.append(f"💡 *Entering {next_biome}:* {BIOME_NOTES[next_biome]}")
            lines.append("_Use `!armourus` for equipment checklist | `!progress` for full prep checklist_")
    else:
        lines.append("🏆 *All Forsaken have been slain — Realm of Valheim10 is fully Mastered!*")

    return "\n".join(lines)

def get_leaderboard_report():
    # 1. Lifetime deaths
    history = {}
    if os.path.exists(DEATHS_FILE):
        try:
            with open(DEATHS_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            pass

    from collections import Counter
    death_counts = Counter([format_player_name(v.get("player", "Unknown")) for v in history.values() if isinstance(v, dict) and v.get("player")])
    total_deaths = len(history)

    # 2. 24h Playtime from journalctl
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(hours=24)
    cmd = ["journalctl", "-u", "valheim-monitor", "--since", cutoff_utc.strftime("%Y-%m-%d %H:%M:%S"), "--no-pager"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except (subprocess.TimeoutExpired, Exception):
        res = None

    playtimes = {}
    active_since = {}
    if res and res.stdout:
        for line in res.stdout.split("\n"):
            m_ts = re.match(r"^([A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2})", line)
            if not m_ts: continue
            try:
                dt = datetime.strptime(f"{now_utc.year} {m_ts.group(1)}", "%Y %b %d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt > now_utc + timedelta(days=1):
                    dt = dt.replace(year=now_utc.year - 1)
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
                                dur = (dt - st).total_seconds()
                                playtimes[p] = playtimes.get(p, 0) + min(dur, 4 * 3600)
                    for p in seeded:
                        if p not in active_since:
                            active_since[p] = dt
                continue

            if "zero_flush" in line:
                for p in list(active_since.keys()):
                    st = active_since.pop(p)
                    if dt > st:
                        dur = (dt - st).total_seconds()
                        playtimes[p] = playtimes.get(p, 0) + min(dur, 4 * 3600)
                continue

            if "Join: " in line:
                m = re.search(r"Join:\s+([^\s\(]+)", line)
                if m:
                    p = m.group(1)
                    if p in active_since:
                        st = active_since.pop(p)
                        if dt > st:
                            dur = (dt - st).total_seconds()
                            playtimes[p] = playtimes.get(p, 0) + min(dur, 4 * 3600)
                    active_since[p] = dt
            elif "Leave " in line or "Leave: " in line:
                m = re.search(r"Leave(?:\s\([^\)]+\))?:\s+([^\s]+)", line)
                if m:
                    p = m.group(1)
                    if p in active_since:
                        st = active_since.pop(p)
                        if dt > st:
                            dur = (dt - st).total_seconds()
                            playtimes[p] = playtimes.get(p, 0) + min(dur, 4 * 3600)

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
                playtimes[p] = playtimes.get(p, 0) + dur

    merged_playtimes = {}
    for p, sec in playtimes.items():
        np = format_player_name(p)
        merged_playtimes[np] = merged_playtimes.get(np, 0) + sec

    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8."]
    lines = [
        "🏆 *VALHEIM CLAN LEADERBOARDS*",
        "",
        f"💀 *All-Time Valhalla Casualties ({total_deaths} Total):*"
    ]
    for idx, (p, c) in enumerate(death_counts.most_common()):
        med = medals[idx] if idx < len(medals) else f"{idx+1}."
        fall_str = "fall" if c == 1 else "falls"
        lines.append(f"{med} *{p}:* {c} {fall_str}")

    lines.append("")
    lines.append("🍻 *Expedition Playtime (Past 24h):*")
    if merged_playtimes:
        for idx, (p, sec) in enumerate(sorted(merged_playtimes.items(), key=lambda x: x[1], reverse=True)):
            hrs = int(sec // 3600)
            mins = int((sec % 3600) // 60)
            t_str = f"{hrs}h {mins:02d}m" if hrs > 0 else f"{mins}m"
            med = medals[idx] if idx < len(medals) else f"{idx+1}."
            lines.append(f"{med} *{p}:* {t_str}")
    else:
        lines.append("• _No expeditions walked the realm in the past 24 hours._")

    return "\n".join(lines)

def get_raid_report():
    if os.path.exists("/root/valheim_last_raid.json"):
        try:
            with open("/root/valheim_last_raid.json", "r") as f:
                data = json.load(f)
            now_t = time.time()
            if data.get("active") and data.get("active_raid"):
                ar = data["active_raid"]
                end_t = ar.get("end_time", 0)
                if now_t < end_t:
                    rem = max(0, int(end_t - now_t))
                    defenders_str = ", ".join(f"*{format_player_name(p)}*" for p in ar.get("defenders", [])) or "None yet"
                    sac_str = ", ".join(f"*{format_player_name(p)}*" for p in ar.get("sacrifices", [])) or "None"
                    return (
                        "⚔️💥 *INVASION IN PROGRESS!* 💥⚔️\n\n"
                        f"*{ar.get('title', 'Unknown Event')}*\n"
                        f"• *Enemy Host:* {ar.get('foes', 'Hostile invaders')}\n"
                        f"• *Active Defenders:* {defenders_str}\n"
                        f"• *Sacrifices So Far:* {sac_str}\n"
                        f"• *Estimated Defense Remaining:* ~{rem}s\n\n"
                        "_Hold the shieldwall! Draw steel and defend the longhouse!_ 🛡️"
                    )
            if data.get("last_raid"):
                lr = data["last_raid"]
                return lr.get("message", "No recent invasion recorded.")
        except Exception as e:
            return f"⚠️ *[Valheim]* Error reading raid status: {e}"
    return "🛡️ *[Valheim]* No recent invasions recorded. The hearth is safe and the realm is at peace!"

def get_patch_report():
    """Returns formatted WhatsApp patch notes for !patch / !patchnotes command."""
    try:
        from valheim_autopatch import get_or_fetch_patch_notes
        notes = get_or_fetch_patch_notes()
        if notes and notes.get("wa_text"):
            return notes["wa_text"]
    except Exception:
        pass

    cache_path = "/root/valheim_latest_patch_notes.json"
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                d = json.load(f)
                if d.get("wa_text"):
                    return d["wa_text"]
        except Exception:
            pass
    return "⚔️ *[Valheim Patch Notes]*\nNo recent patch notes could be retrieved at this time. Check the Steam store page for updates!"

def get_progression_report():
    from valheim_inventory import scan_world_inventory
    """
    Full progression-aware readiness report for !progress / !prep.
    Shows current stage, what's now obsolete, what needs upgrading,
    and a structured next-biome preparation checklist.
    """
    prog = get_progression_state()
    totals, _ = scan_world_inventory()
    current_tier = prog['current_tier']
    current_biome = prog['current_biome']
    next_boss = prog['next_boss']
    next_biome = prog['next_biome']
    all_defeated = prog['all_defeated']

    # Compute day
    day = get_persisted_day(check_log=True)

    ERA_NAMES = {
        0: 'Pre-Progression',
        1: 'Meadows Era',
        2: 'Black Forest Era',
        3: 'Swamps Era (Iron Age)',
        4: 'Mountains Era (Silver Age)',
        5: 'Plains Era (Black Metal Age)',
        6: 'Mistlands Era (Eitr Age)',
        7: 'Ashlands Era (Flametal Age)',
        8: 'Deep North Era (Glacial Age)',
    }

    lines = [
        "🗺️ *VALHEIM CLAN PROGRESSION READINESS*",
        f"📅 *Day {day} | {ERA_NAMES.get(current_tier, 'Unknown Era')}*",
        f"🏰 *Current Stage:* {current_biome} (Boss Tier {current_tier}/8)",
    ]
    if next_boss:
        lines.append(f"🎯 *Next Objective:* Slay *{next_boss['name']}* in the *{next_biome}*")
    else:
        lines.append("🏆 *All Forsaken Defeated — Realm Mastered!*")

    lines.append("")

    # ── Current equipment status ───────────────────────────────────────────
    lines.append("🟢 *Current Tier Equipment:*")

    iron_bars   = totals.get('Iron', 0)
    iron_scrap  = totals.get('IronScrap', 0) + totals.get('IronOre', 0)
    silver_bars = totals.get('Silver', 0)
    silver_ore  = totals.get('SilverOre', 0)
    wolf_pelt   = totals.get('WolfPelt', 0)
    wolf_fang   = totals.get('WolfFang', 0)
    black_bars  = totals.get('BlackMetal', 0)
    black_scrap = totals.get('BlackMetalScrap', 0)
    linen       = totals.get('LinenThread', 0)
    troll_hide  = totals.get('TrollHide', 0)
    deer_hide   = totals.get('DeerHide', 0)

    if current_tier <= 1:
        lines.append("  • Craft Leather Armor → hunt Trolls → Troll Leather Set")
    elif current_tier == 2:
        troll_sets = min(troll_hide // 15, 4)
        lines.append(f"  • Troll Leather Set (18 armor) — {troll_sets} sets crafted from {troll_hide} hides")
        lines.append("  • Next: Farm Swamp Crypts for Iron Scrap → Iron Scale (42 armor)")
    elif current_tier == 3:
        iron_sets = iron_bars // 60
        lines.append(f"  • Iron Scale Armor (42 armor) — {iron_sets} sets from {iron_bars} bars")
        lines.append(f"  • Root Armor available for archers ({totals.get('Root',0)} roots)")
        lines.append("  • Next: Enter Mountains → mine Silver with Wishbone → Wolf Armor")
    elif current_tier == 4:
        lines.append(f"  • Wolf Armor (78 armor, Frost Resist) — {silver_bars} Silver bars in stock")
        lines.append(f"  • Pelts: {wolf_pelt} Wolf Pelts, {wolf_fang} Wolf Fangs")
        if silver_bars >= 14 and wolf_pelt >= 10:
            lines.append("  ✅ Full Wolf Armor craftable now!")
        else:
            missing = []
            if silver_bars < 14: missing.append(f"{14-silver_bars} Silver bars")
            if wolf_pelt < 10: missing.append(f"{10-wolf_pelt} Wolf Pelt")
            lines.append(f"  ⏳ Still need: {', '.join(missing)}")
    elif current_tier >= 5:
        padded_possible = min(iron_bars // 10, linen // 20) if linen > 0 else 0
        piece_plural = "piece" if padded_possible == 1 else "pieces"
        lines.append(f"  • Padded Armor (100 armor) — {linen} Linen Thread, {iron_bars} Iron bars")
        lines.append(f"  • {padded_possible} {piece_plural} craftable now | Black Metal: {black_bars} bars + {black_scrap} scrap")

    lines.append("")

    # ── Next biome preparation checklist ──────────────────────────────────
    if next_boss and next_biome != current_biome:
        lines.append(f"📋 *Preparation Checklist — {next_biome}:*")

        if next_biome == 'Black Forest':
            lines.append("  1. 🛡️ *Armor:* Troll Leather or Bronze Plate")
            lines.append("  2. ⚔️ *Weapons:* Flint Spear / Bronze Sword / Flint Knife")
            lines.append("  3. 🍖 *Food:* Cooked Meat + Honey + Grilled Neck Tail")
            lines.append("  4. 🏰 *Infra:* Forge (10 Stone + 4 Coal + 6 Copper + 4 Wood)")
            lines.append("  5. ⚠️ *Watch for:* Greydwarf Shamans (Poison), Trolls (1-shot)!")

        elif next_biome == 'Swamps':
            lines.append("  1. 🛡️ *Armor:* Iron Scale (42+ armor) | Root Armor for archers")
            lines.append("  2. ⚔️ *Weapons:* Iron Mace (blunt vs Skeletons/Blobs) + Iron Sword")
            lines.append("  3. 🍵 *Potions:* Poison Resistance Mead (MANDATORY) — Bloodbag+Honey+Thistle")
            lines.append("  4. 🔑 *Key:* Elder's Swamp Key — opens Sunken Crypts for Iron Scrap")
            lines.append("  5. 🍖 *Food:* Sausages + Turnip Stew + Black Soup (Swamp Cauldron)")
            lines.append("  6. ⚠️ *Threats:* Draugr Elites, Abominations, Blobs (Poison), Leeches, Wraiths (night)")

        elif next_biome == 'Mountains':
            lines.append("  1. 🛡️ *Armor:* Iron Scale minimum | Target: Wolf Armor + Drake Helmet")
            lines.append("  2. ⚔️ *Weapons:* Iron Pickaxe (Silver mining) | Iron Sword/Mace still viable")
            lines.append("  3. ❄️ *Frost Resist Mead:* MANDATORY until full Wolf set (Freeze Gland + Greydwarf Eye + Honey)")
            lines.append("  4. 🦴 *Wishbone:* Required to detect buried Silver veins (Bonemass reward)")
            lines.append("  5. 🍖 *Food:* Cooked Wolf Meat + Onion Soup + Wolf Skewer")
            lines.append("  6. 🥚 *Dragon Eggs:* Collect 3 for Moder's altar summon (heavy — use portal system)")
            lines.append("  7. ⚠️ *Threats:* Wolves (pack attacks), Stone Golems (Pickaxe/Blunt damage)")

        elif next_biome == 'Plains':
            stock_totems = totals.get('GoblinTotem', 0)
            lines.append("  • 🛡️ *Armor:* Wolf Armor minimum ➔ Target: Padded Armor (100 armor, needs Linen + Iron)")
            lines.append("  • ⚔️ *Weapons:* Black Metal Sword / Atgeir (smelt Fuling scrap in Blast Furnace)")
            lines.append("  • 🌾 *Stations:* Build Artisan Table (Dragon Tear) ➔ Unlocks Spinning Wheel, Blast Furnace & Windmill")
            lines.append("  • 🍖 *Food:* Lox Meat Pie, Fish Wraps & Blood Pudding (Plains Barley + Stone Oven)")
            lines.append(f"  • ⚔️ *Summon:* {stock_totems}/5 Fuling Totems in base chests for Yagluth's altar")
            lines.append("  • ⚠️ *Hazards:* Deathsquito pierce damage; kite Fuling Berserkers; avoid Lox herd aggro")

        elif next_biome == 'Mistlands':
            lines.append("  1. 🛡️ *Armor:* Padded Armor (100+) | Target: Carapace Armor (Seeker drops)")
            lines.append("  2. 🌫️ *Wisplight:* Craft from Wisp (Wisp Fountain at night) — MANDATORY to see")
            lines.append("  3. ⚔️ *Weapons:* Black Metal weapons minimum | Mistwalker (requires Dvergr cores)")
            lines.append("  4. 🏛️ *Galdr Table:* Black Marble + Yggdrasil Wood (Mistlands crafting station)")
            lines.append("  5. ⚠️ *Gjall:* Flying screamers — call waves of Seekers. Stealth approach is key")
            lines.append("  6. ⚠️ *Dvergr:* Neutral until attacked — don't aggro their camps")

        elif next_biome == 'Ashlands':
            lines.append("  1. 🛡️ *Armor:* Carapace/Flametal minimum — 100+ armor required")
            lines.append("  2. 🔥 *Fire Resistance:* Equip Eitr-based fire resist gear")
            lines.append("  3. ⚔️ *Weapons:* Mistwalker / Jotun-tier weapons")
            lines.append("  4. ⚠️ *Constant spawning:* No downtime — Charred Fortress is relentless")

        elif next_biome == 'Deep North':
            lines.append("  1. 🛡️ *Armor:* Flametal Armor | Target: Bloodgold Armor")
            lines.append("  2. ❄️ *Frost Resist:* Required for extreme cold")
            lines.append("  3. ⚔️ *Weapons:* Flametal weapons minimum")
            lines.append("  4. 🏛️ *Frost Foundry:* Required for Bloodgold crafting")

    elif all_defeated:
        lines.append("🏆 *Realm Mastered — All Forsaken are defeated!*")
        lines.append("  Maintain Padded/Carapace armor. Explore remaining biomes freely.")

    # ── Quick resource summary ─────────────────────────────────────────────
    lines.append("")
    lines.append("📊 *Key Resource Status:*")
    lines.append(f"  Iron: {iron_bars} bars + {iron_scrap} scrap | Silver: {silver_bars} bars + {silver_ore} ore")
    lines.append(f"  Black Metal: {black_bars} bars + {black_scrap} scrap | Linen: {linen}")
    lines.append(f"  Wolf Pelt: {wolf_pelt} | Wolf Fang: {wolf_fang}")
    lines.append(f"  Troll Hide: {troll_hide} | Deer Hide: {deer_hide}")
    lines.append("")
    lines.append("_Full details: `!armourus` • `!metalcount` • `!foodcount` • `!era`_")

    return "\n".join(lines)

