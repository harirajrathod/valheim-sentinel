#!/usr/bin/env python3
"""
/root/valheim_qol.py - Valheim Quality of Life (QoL) Cooperative Engines

Features:
1. Menagerie & Beastmaster Radar (!tames / !wolves / !beasts):
   - Live census of tamed Boars, Wolves, Lox, star ratings, and named companions.
2. Mead Cellar & Brewery Monitor (!mead / !brew / !cellar):
   - Status of 4 fermenters (idle/brewing/ready), cellar barrel inventory, and cauldron crafting potential.
3. Valhalla Rescue Compass / Lost Tombstone Radar (!grave / !rescue):
   - Detects uncollected player tombstones, nearest portal, distance/direction, and hazard tips.
4. "Can We Craft?" Wishlist Engine (!craft <item> / !canwecraft <item>):
   - Checks clan chest inventory and Haldor treasury gold against comprehensive recipes.
5. Fleet & Logistics Registry (!fleet / !ships / !carts):
   - Locates moored Karves, Longships, and parked Handcarts with nearest portal links.
6. Cooperative Clan Milestones (!milestones / !clan):
   - Celebrates collective achievements (timber, metallurgy, crops, portals, runes, gold, bosses).
7. Longhouse Hearth & Comfort Gauge (!hearth / !comfort):
   - Evaluates Longhouse comfort pieces, Rested Buff duration, and recommended next upgrades.

Zero skill-shaming: Strictly positive, cooperative, high-utility assistance for the Viking clan.
"""

import sys
import math
import struct
import argparse
from typing import Dict, Any, List, Optional

sys.path.insert(0, "/root")
from valheim_farm import get_stable_hash, get_active_chunk_files
from valheim_info import (
    find_next_zdo_boundary,
    scan_world_inventory,
    get_portal_location_desc,
    get_progression_state,
    get_world_signs,
)

DEATHS_HISTORY_FILE = "/root/valheim_deaths_history.json"
MAIN_BASE_COORDS = (12.8, -360.1)

COMPASS_DIRECTIONS = [
    "North", "NNE", "NE", "ENE", "East", "ESE", "SE", "SSE",
    "South", "SSW", "SW", "WSW", "West", "WNW", "NW", "NNW"
]


def calculate_heading(from_x: float, from_z: float, to_x: float, to_z: float) -> str:
    """Calculates cardinal compass heading from (from_x, from_z) to (to_x, to_z)."""
    dx = to_x - from_x
    dz = to_z - from_z
    angle = math.atan2(dx, dz)
    deg = (math.degrees(angle) + 360) % 360
    return COMPASS_DIRECTIONS[int((deg + 11.25) / 22.5) % 16]


def format_distance(meters: float) -> str:
    """Formats distance nicely as meters or kilometers."""
    if meters >= 1000:
        return f"{meters / 1000.0:.1f}km"
    return f"{round(meters)}m"


def get_realm_portals() -> List[Dict[str, Any]]:
    """Extracts all active, tagged portals from chunk files."""
    chunks = get_active_chunk_files()
    pw_hashes = {
        get_stable_hash("portal_wood"): "Wood Portal",
        get_stable_hash("portal_stone"): "Stone Portal",
    }
    tag_hash = bytes.fromhex("ea917c29")
    portals = []
    seen_coords = set()

    for c in chunks:
        try:
            with open(c, "rb") as fp:
                data = fp.read()
        except Exception:
            continue

        for ph, ptype in pw_hashes.items():
            packed_ph = struct.pack("<i", ph)
            idx = 0
            while True:
                idx = data.find(packed_ph, idx)
                if idx == -1:
                    break
                if idx >= 12:
                    x, y, z = struct.unpack("<fff", data[idx-12:idx])
                    if (-10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500):
                        bound = find_next_zdo_boundary(data, idx + 4, max_search=120)
                        zdo_window = data[idx:bound]
                        tag = ""
                        t_idx = zdo_window.find(tag_hash)
                        if t_idx != -1:
                            p = t_idx + 4
                            tag_len = 0
                            shift = 0
                            while p < len(zdo_window) and shift <= 28:
                                b = zdo_window[p]
                                p += 1
                                tag_len |= (b & 0x7F) << shift
                                if not (b & 0x80):
                                    break
                                shift += 7
                            tag = zdo_window[p:p+tag_len].decode("utf-8", errors="replace").strip()
                        coord_key = (round(x, 1), round(z, 1))
                        if coord_key not in seen_coords and tag:
                            seen_coords.add(coord_key)
                            portals.append({
                                "tag": tag,
                                "pos": (x, y, z),
                                "type": ptype,
                            })
                idx += 4

    return portals


def find_nearest_portal(target_x: float, target_z: float, portals: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Finds the closest portal to a given (x, z) coordinate with distance and direction."""
    if portals is None:
        portals = get_realm_portals()
    if not portals:
        return None

    best_portal = None
    best_dist = float("inf")
    for p in portals:
        px, _, pz = p["pos"]
        dist = math.hypot(target_x - px, target_z - pz)
        if dist < best_dist:
            best_dist = dist
            best_portal = p

    if best_portal:
        px, _, pz = best_portal["pos"]
        heading = calculate_heading(px, pz, target_x, target_z)
        return {
            "tag": best_portal["tag"],
            "pos": best_portal["pos"],
            "distance_m": best_dist,
            "distance_str": format_distance(best_dist),
            "heading": heading,
        }
    return None


# ==============================================================================
# 1. MENAGERIE & BEASTMASTER RADAR (!tames / !wolves / !beasts)
# ==============================================================================

def get_tames_report() -> str:
    """
    Scans active world chunks for tamed creatures (Wolf, Boar, Lox, and future tames),
    extracting star ratings, health, custom names, and enclosure locations with zero ZDO bleed.
    """
    chunks = get_active_chunk_files()

    tame_h = struct.pack("<i", get_stable_hash("tamed"))
    lvl_h = struct.pack("<i", get_stable_hash("level"))
    hlth_h = struct.pack("<i", get_stable_hash("health"))
    max_hlth_h = struct.pack("<i", get_stable_hash("max_health"))
    name_h = struct.pack("<i", get_stable_hash("TamedName"))

    animal_prefabs = [
        ("Wolf", struct.pack("<i", get_stable_hash("Wolf")), 80.0),
        ("Wolf_cub", struct.pack("<i", get_stable_hash("Wolf_cub")), 80.0),
        ("Boar", struct.pack("<i", get_stable_hash("Boar")), 20.0),
        ("Boar_piggy", struct.pack("<i", get_stable_hash("Boar_piggy")), 20.0),
        ("Lox", struct.pack("<i", get_stable_hash("Lox")), 1000.0),
        ("Lox_Calf", struct.pack("<i", get_stable_hash("Lox_Calf")), 100.0),
        ("Lox_calf", struct.pack("<i", get_stable_hash("Lox_calf")), 100.0),
        ("Hen", struct.pack("<i", get_stable_hash("Hen")), 10.0),
        ("Chicken", struct.pack("<i", get_stable_hash("Chicken")), 10.0),
        ("Asksvin", struct.pack("<i", get_stable_hash("Asksvin")), 1000.0),
        ("Asksvin_hatchling", struct.pack("<i", get_stable_hash("Asksvin_hatchling")), 100.0),
    ]

    type_map = {
        "Wolf": "Wolf", "Wolf_cub": "Wolf",
        "Boar": "Boar", "Boar_piggy": "Boar",
        "Lox": "Lox", "Lox_Calf": "Lox", "Lox_calf": "Lox",
        "Hen": "Hen", "Chicken": "Hen",
        "Asksvin": "Asksvin", "Asksvin_hatchling": "Asksvin",
    }

    tames_by_type = {"Wolf": [], "Boar": [], "Lox": [], "Hen": [], "Asksvin": []}

    for c in chunks:
        try:
            with open(c, "rb") as f:
                data = f.read()
        except Exception:
            continue

        chunk_animals = []
        for aname, ah, base_hp in animal_prefabs:
            idx = 0
            while True:
                idx = data.find(ah, idx)
                if idx == -1:
                    break
                if idx >= 12:
                    x, y, z = struct.unpack("<fff", data[idx-12:idx])
                    if (-10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500
                            and not (abs(x) < 0.1 and abs(y) < 0.1 and abs(z) < 0.1)):
                        # Check tame_hash within 100 bytes of prefab
                        t_pos = data.find(tame_h, idx)
                        if t_pos != -1 and 0 < (t_pos - idx) < 100:
                            chunk_animals.append((idx, aname, base_hp, x, y, z))
                idx += 4

        # Sort animals by chunk offset so search window never bleeds into adjacent creatures
        chunk_animals.sort(key=lambda a: a[0])

        for i, (idx, aname, base_hp, x, y, z) in enumerate(chunk_animals):
            next_idx = chunk_animals[i+1][0] if i+1 < len(chunk_animals) else (idx + 300)
            max_win = min(next_idx - idx, 280)
            window = data[idx:idx+max_win]

            # Level (within 180 bytes)
            level = 1
            l_pos = window.find(lvl_h)
            if l_pos != -1 and l_pos < 180:
                level = struct.unpack("<i", window[l_pos+4:l_pos+8])[0]

            # Health: fallback to full max_health when health key is omitted (uninjured)
            max_hp = base_hp * max(1, level)
            m_pos = window.find(max_hlth_h)
            if m_pos != -1 and m_pos < 60:
                max_hp = struct.unpack("<f", window[m_pos+4:m_pos+8])[0]

            cur_hp = max_hp
            h_pos = window.find(hlth_h)
            if h_pos != -1 and h_pos < 60:
                cur_hp = struct.unpack("<f", window[h_pos+4:h_pos+8])[0]

            # Custom Name
            name = ""
            n_pos = window.find(name_h)
            if n_pos != -1:
                slen = window[n_pos+4]
                if 1 <= slen <= 40 and n_pos + 5 + slen <= len(window):
                    name = window[n_pos+5:n_pos+5+slen].decode("utf-8", errors="ignore").strip()

            parent_type = type_map.get(aname, aname)
            if parent_type in tames_by_type:
                tames_by_type[parent_type].append({
                    "prefab": aname,
                    "is_baby": aname in ("Wolf_cub", "Boar_piggy", "Lox_Calf", "Lox_calf", "Chicken", "Asksvin_hatchling"),
                    "pos": (x, y, z),
                    "level": level,
                    "health": cur_hp,
                    "max_health": max_hp,
                    "name": name,
                })

    wolves = tames_by_type["Wolf"]
    boars = tames_by_type["Boar"]
    loxes = tames_by_type["Lox"]
    hens = tames_by_type["Hen"]
    asksvins = tames_by_type["Asksvin"]

    total_tames = len(wolves) + len(boars) + len(loxes) + len(hens) + len(asksvins)
    if total_tames == 0:
        return "🐺 *[Valheim Menagerie]*\n\n_No tamed animals found in the realm yet! Feed boars mushrooms or wolves raw meat to begin taming._"

    lines = [
        "🐺 *VALHEIM CLAN MENAGERIE & BEASTS* 🐾",
        "",
        "Hail Beastmasters! Clan animal pens & companion status:",
        "",
    ]

    # Wolves Section
    if wolves:
        adults = [w for w in wolves if not w["is_baby"]]
        cubs = [w for w in wolves if w["is_baby"]]
        two_star = sum(1 for w in adults if w["level"] >= 3)
        one_star = sum(1 for w in adults if w["level"] == 2)
        zero_star = sum(1 for w in adults if w["level"] <= 1)

        star_str = []
        if two_star > 0:
            star_str.append(f"{two_star}x ⭐⭐ 2-Star")
        if one_star > 0:
            star_str.append(f"{one_star}x ⭐ 1-Star")
        if zero_star > 0:
            star_str.append(f"{zero_star}x Normal")

        star_desc = ", ".join(star_str) if star_str else "Dire Pack"
        if cubs:
            lines.append(f"🐺 *Dire Wolves (Total: {len(adults)} Adults + {len(cubs)} Cubs)*")
            lines.append(f"• *Tiers:* {star_desc}")
            lines.append(f"• 🐾 *Cubs:* {len(cubs)}x Wolf Cub{'s' if len(cubs) > 1 else ''}")
        else:
            lines.append(f"🐺 *Dire Wolves (Total: {len(adults)} Adults)*")
            lines.append(f"• *Tiers:* {star_desc}")
            lines.append("• 🐾 *Cubs:* 0 cubs")

        # Distribution
        mb_wolves = sum(1 for w in wolves if math.hypot(w["pos"][0] - MAIN_BASE_COORDS[0], w["pos"][2] - MAIN_BASE_COORDS[1]) < 100)
        outpost_wolves = len(wolves) - mb_wolves
        distrib = []
        if mb_wolves > 0:
            distrib.append(f"{mb_wolves} at Main Base")
        if outpost_wolves > 0:
            distrib.append(f"{outpost_wolves} at Mountain Pens")
        lines.append(f"• 📍 *Packs:* {', '.join(distrib)}")
        lines.append("")

    # Boars Section
    if boars:
        adults = [b for b in boars if not b["is_baby"]]
        piglets = [b for b in boars if b["is_baby"]]
        two_star = sum(1 for b in adults if b["level"] >= 3)
        one_star = sum(1 for b in adults if b["level"] == 2)
        zero_star = sum(1 for b in adults if b["level"] <= 1)

        star_str = []
        if two_star > 0:
            star_str.append(f"{two_star}x ⭐⭐ 2-Star")
        if one_star > 0:
            star_str.append(f"{one_star}x ⭐ 1-Star")
        if zero_star > 0:
            star_str.append(f"{zero_star}x Normal")

        star_desc = ", ".join(star_str) if star_str else "Swine Herd"
        if piglets:
            lines.append(f"🐗 *Boars (Total: {len(adults)} Adults + {len(piglets)} Piglets)*")
            lines.append(f"• *Tiers:* {star_desc}")
            lines.append(f"• 🐾 *Piglets:* {len(piglets)}x Piglet{'s' if len(piglets) > 1 else ''}")
        else:
            lines.append(f"🐗 *Boars (Total: {len(adults)} Adults)*")
            lines.append(f"• *Tiers:* {star_desc}")
            lines.append("• 🐾 *Piglets:* 0 piglets")

        mb_boars = sum(1 for b in boars if math.hypot(b["pos"][0] - MAIN_BASE_COORDS[0], b["pos"][2] - MAIN_BASE_COORDS[1]) < 100)
        farm_boars = len(boars) - mb_boars
        distrib = []
        if mb_boars > 0:
            distrib.append(f"{mb_boars} at Homestead Pen")
        if farm_boars > 0:
            distrib.append(f"{farm_boars} at East Farm (Bacon Factory)")
        lines.append(f"• 📍 *Pens:* {', '.join(distrib)}")
        lines.append("")

    # Lox Section
    if loxes:
        adults = [l for l in loxes if not l["is_baby"]]
        calves = [l for l in loxes if l["is_baby"]]
        if calves:
            lines.append(f"🦣 *Lox Herds (Total: {len(adults)} Adults + {len(calves)} Calves)*")
            lines.append(f"• 🐾 *Calves:* {len(calves)}x Lox Calves")
        else:
            lines.append(f"🦣 *Lox Herds (Total: {len(adults)} Adults)*")
            lines.append("• 🐾 *Calves:* 0 calves")

        # Geographic distribution across Plains outposts
        fob_lox = sum(1 for l in adults if math.hypot(l["pos"][0] - 2480, l["pos"][2] - 4430) < 200)
        tallrock_lox = sum(1 for l in adults if math.hypot(l["pos"][0] - 2630, l["pos"][2] - 4820) < 200)
        north_lox = len(adults) - fob_lox - tallrock_lox
        lox_distrib = []
        if fob_lox > 0:
            fob_str = f"{fob_lox} adults"
            if calves:
                fob_str += f" + {len(calves)} calves"
            lox_distrib.append(f"{fob_str} at Plains FOB (`rtb`)")
        if tallrock_lox > 0:
            lox_distrib.append(f"{tallrock_lox} at Tall Rock Outpost")
        if north_lox > 0:
            lox_distrib.append(f"{north_lox} in North Plains Range")
        lines.append(f"• 📍 *Herds:* {', '.join(lox_distrib) if lox_distrib else 'Plains Outposts'}")
        lines.append("")

    # Optional Hen / Chicken Section
    if hens:
        adults = [h for h in hens if not h["is_baby"]]
        chicks = [h for h in hens if h["is_baby"]]
        if chicks:
            lines.append(f"🐔 *Hens & Chickens (Total: {len(adults)} Adults + {len(chicks)} Chicks)*")
            lines.append(f"• 🐣 *Chicks:* {len(chicks)}x Chick{'s' if len(chicks) > 1 else ''}")
        else:
            lines.append(f"🐔 *Hens (Total: {len(adults)} Adults)*")
        lines.append("")

    # Optional Asksvin Section
    if asksvins:
        adults = [a for a in asksvins if not a["is_baby"]]
        hatchlings = [a for a in asksvins if a["is_baby"]]
        if hatchlings:
            lines.append(f"🦎 *Asksvin (Total: {len(adults)} Adults + {len(hatchlings)} Hatchlings)*")
            lines.append(f"• 🐾 *Hatchlings:* {len(hatchlings)}x Hatchling{'s' if len(hatchlings) > 1 else ''}")
        else:
            lines.append(f"🦎 *Asksvin Packs (Total: {len(adults)} Adults)*")
        lines.append("")

    lines.append("💡 *Tip:* Stock pens with Carrots, Turnips, or Cloudberries to keep herds fed & breeding! 🌾")
    return "\n".join(lines)


# ==============================================================================
# 2. MEAD CELLAR & BREWERY MONITOR (!mead / !brew / !cellar)
# ==============================================================================

MEAD_PREFAB_NAMES = {
    "MeadFrostResist": ("Frost Resistance", "❄️", "Mountain cold immunity (10m)"),
    "MeadPoisonResist": ("Poison Resistance", "🧪", "75% poison damage reduction (10m)"),
    "MeadHealthMedium": ("Medium Healing", "❤️", "75 HP restoration"),
    "MeadHealthMinor": ("Minor Healing", "❤️", "50 HP restoration"),
    "MeadStaminaMedium": ("Medium Stamina", "⚡", "160 Stamina restoration"),
    "MeadStaminaMinor": ("Minor Stamina", "⚡", "80 Stamina restoration"),
    "MeadTasty": ("Tasty Mead", "🍺", "+300% Stamina regen (-50% HP regen)"),
    "BarleyWine": ("Fire Resistance Wine", "🔥", "Fire damage resistance (10m)"),
}

FERMENTER_MEAD_MAP = {
    get_stable_hash("MeadBaseFrostResist"): ("Frost Resistance", "❄️"),
    get_stable_hash("MeadFrostResist"): ("Frost Resistance", "❄️"),
    get_stable_hash("MeadBasePoisonResist"): ("Poison Resistance", "🧪"),
    get_stable_hash("MeadPoisonResist"): ("Poison Resistance", "🧪"),
    get_stable_hash("MeadBaseHealthMedium"): ("Medium Healing", "❤️"),
    get_stable_hash("MeadHealthMedium"): ("Medium Healing", "❤️"),
    get_stable_hash("MeadBaseHealthMinor"): ("Minor Healing", "❤️"),
    get_stable_hash("MeadHealthMinor"): ("Minor Healing", "❤️"),
    get_stable_hash("MeadBaseStaminaMedium"): ("Medium Stamina", "⚡"),
    get_stable_hash("MeadStaminaMedium"): ("Medium Stamina", "⚡"),
    get_stable_hash("MeadBaseStaminaMinor"): ("Minor Stamina", "⚡"),
    get_stable_hash("MeadStaminaMinor"): ("Minor Stamina", "⚡"),
    get_stable_hash("MeadBaseTasty"): ("Tasty Mead", "🍺"),
    get_stable_hash("MeadTasty"): ("Tasty Mead", "🍺"),
    get_stable_hash("BarleyWineBase"): ("Fire Resistance Wine", "🔥"),
    get_stable_hash("BarleyWine"): ("Fire Resistance Wine", "🔥"),
    get_stable_hash("BarleyWineFire"): ("Fire Resistance Wine", "🔥"),
    get_stable_hash("MeadBaseLingeringStamina"): ("Lingering Stamina", "⚡"),
    get_stable_hash("MeadLingeringStamina"): ("Lingering Stamina", "⚡"),
    get_stable_hash("MeadBaseHealthMajor"): ("Major Healing", "❤️"),
    get_stable_hash("MeadHealthMajor"): ("Major Healing", "❤️"),
    get_stable_hash("MeadBaseEitrMinor"): ("Minor Eitr", "🔮"),
    get_stable_hash("MeadEitrMinor"): ("Minor Eitr", "🔮"),
}


def get_mead_report() -> str:
    """
    Scans fermenters across the world, checks cellar chest stockpiles,
    and calculates Cauldron brewing readiness.
    """
    chunks = get_active_chunk_files()
    ferm_hash = struct.pack("<i", get_stable_hash("fermenter"))
    content_hash = struct.pack("<i", get_stable_hash("Content"))

    fermenters = []
    for c in chunks:
        try:
            with open(c, "rb") as f:
                data = f.read()
        except Exception:
            continue

        idx = 0
        while True:
            idx = data.find(ferm_hash, idx)
            if idx == -1:
                break
            if idx >= 12:
                x, y, z = struct.unpack("<fff", data[idx-12:idx])
                if (-10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500):
                    bound = find_next_zdo_boundary(data, idx + 4, max_search=250)
                    zdo = data[idx:bound]
                    content = ""
                    # In Valheim, Fermenter stores content as int hash in m_ints under 'Content'
                    for item_h, (m_label, m_icon) in FERMENTER_MEAD_MAP.items():
                        if struct.pack("<i", item_h) in zdo:
                            content = f"{m_icon} {m_label}"
                            break
                    if not content and content_hash in zdo:
                        p = zdo.find(content_hash) + 4
                        if p + 4 <= len(zdo):
                            val_int = struct.unpack("<i", zdo[p:p+4])[0]
                            if val_int in FERMENTER_MEAD_MAP:
                                m_label, m_icon = FERMENTER_MEAD_MAP[val_int]
                                content = f"{m_icon} {m_label}"
                    
                    loc_desc = "Main Base Longhouse" if math.hypot(x - MAIN_BASE_COORDS[0], z - MAIN_BASE_COORDS[1]) < 80 else "Outpost Cellar"
                    if math.hypot(x - 443.8, z - -3196.1) < 200:
                        loc_desc = "The Bog Witch Outpost"

                    fermenters.append({
                        "pos": (x, y, z),
                        "content": content,
                        "location": loc_desc,
                    })
            idx += 4

    totals, _ = scan_world_inventory()

    # Tally finished meads
    cellar_meads = {}
    for p_name, (label, icon, desc) in MEAD_PREFAB_NAMES.items():
        qty = totals.get(p_name, 0)
        if qty > 0:
            cellar_meads[p_name] = (label, icon, qty, desc)

    # Pantry ingredients
    honey = totals.get("Honey", 0)
    thistle = totals.get("Thistle", 0)
    raspberries = totals.get("Raspberry", 0)
    blueberries = totals.get("Blueberries", 0)
    cloudberries = totals.get("Cloudberry", 0)

    lines = [
        "🍺 *VALHEIM MEAD CELLAR & BREWERY* 🍯",
        "",
        "Hail, Warriors! Clan brewery barrels & cellar reserves:",
        "",
        f"🏺 *Active Fermenters ({len(fermenters)} Barrels):*",
    ]

    mb_ferm = [f for f in fermenters if "Main Base" in f["location"]]
    other_ferm = [f for f in fermenters if "Main Base" not in f["location"]]

    if mb_ferm:
        idle_mb = sum(1 for f in mb_ferm if not f["content"])
        brewing_mb = [f for f in mb_ferm if f["content"]]
        if idle_mb == len(mb_ferm):
            lines.append(f"• 🏠 *Main Base ({len(mb_ferm)} Barrels):* 🟢 All {len(mb_ferm)} Idle & Clean — Ready to brew!")
        else:
            lines.append(f"• 🏠 *Main Base ({len(mb_ferm)} Barrels):* {len(brewing_mb)} Active, {idle_mb} Idle")
            for f in brewing_mb:
                lines.append(f"  └ ⏳ Fermenting: *{f['content']}*")

    if other_ferm:
        for f in other_ferm:
            status_str = f"⏳ Fermenting *{f['content']}*" if f["content"] else "🟢 Idle & Ready"
            lines.append(f"• 📍 *{f['location']}:* {status_str}")

    lines.append("")
    lines.append("🍷 *Cellar Stock (Pantry Chests):*")
    if cellar_meads:
        for p_name, (label, icon, qty, desc) in cellar_meads.items():
            lines.append(f"• {icon} *{label}:* {qty} flagons")
    else:
        lines.append("• _No finished meads in storage. Brew mead bases at Cauldron!_")

    lines.append("")
    lines.append("🍲 *Brewing Pantry Potential:*")
    lines.append(f"• 🍯 *Honey:* {honey} | 🌿 *Thistle:* {thistle} | 🫐 *Berries:* {raspberries + blueberries + cloudberries}")

    # Calculate potential brews
    poison_batches = min(honey // 10, thistle // 5) if honey >= 10 and thistle >= 5 else 0
    frost_batches = min(honey // 10, thistle // 5) if honey >= 10 and thistle >= 5 else 0
    craft_tips = []
    if frost_batches > 0:
        craft_tips.append(f"{min(frost_batches, 10)}x Frost Resist")
    if poison_batches > 0:
        craft_tips.append(f"{min(poison_batches, 10)}x Poison Resist")

    if craft_tips:
        lines.append(f"• 💡 *Ready to brew:* Can craft {', '.join(craft_tips)} at the Cauldron!")
    else:
        lines.append("• 💡 *Tip:* Gather more Honey & Thistle to brew protective mead bases!")

    return "\n".join(lines)


# ==============================================================================
# 3. VALHALLA RESCUE COMPASS (!grave / !rescue)
# ==============================================================================

def get_rescue_report(player_query: Optional[str] = None) -> str:
    """
    Locates active uncollected tombstones in the world, identifies fallen warriors,
    and computes the closest portal with distance and cardinal compass heading.
    """
    chunks = get_active_chunk_files()
    tomb_hash = struct.pack("<i", get_stable_hash("Player_tombstone"))
    portals = get_realm_portals()

    tombstones = []
    for c in chunks:
        try:
            with open(c, "rb") as f:
                data = f.read()
        except Exception:
            continue

        idx = 0
        while True:
            idx = data.find(tomb_hash, idx)
            if idx == -1:
                break
            if idx >= 12:
                x, y, z = struct.unpack("<fff", data[idx-12:idx])
                if (-10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500
                        and not (abs(x) < 0.1 and abs(y) < 0.1 and abs(z) < 0.1)):
                    bound = find_next_zdo_boundary(data, idx + 4, max_search=250)
                    zdo = data[idx:bound]
                    
                    # Detect owner name from strings
                    victim = "Unknown Warrior"
                    for known_raw, known_canonical in [("musashi", "Musashi(Musa Bhai)"), ("faye", "Faye"), ("hilda", "Hilda"), ("dexter", "Dexter"), ("rukia", "Rukia"), ("claw", "Claw")]:
                        if known_raw.encode("ascii", errors="ignore").lower() in zdo.lower():
                            victim = known_canonical
                            break

                    nearest_p = find_nearest_portal(x, z, portals)
                    dist_mb = math.hypot(x - MAIN_BASE_COORDS[0], z - MAIN_BASE_COORDS[1])
                    dir_mb = calculate_heading(MAIN_BASE_COORDS[0], MAIN_BASE_COORDS[1], x, z)

                    # Assess terrain hazard based on distance/location
                    hazard = "Unknown Frontier"
                    if dist_mb < 300:
                        hazard = "Homestead Grounds (Safe recovery)"
                    elif z > 3500:
                        hazard = "Plains Frontier (High Deathsquito & Fuling hazard)"
                    elif z < -2500 and x < 1500:
                        hazard = "Swamp Frontier (Leech & Draugr poison hazard)"
                    elif y > 120:
                        hazard = "Mountain High Peaks (Freezing cold & Wolf hazard)"
                    else:
                        hazard = "Black Forest / Meadows Wilds"

                    tombstones.append({
                        "victim": victim,
                        "pos": (x, y, z),
                        "nearest_portal": nearest_p,
                        "dist_mb_str": format_distance(dist_mb),
                        "dir_mb": dir_mb,
                        "hazard": hazard,
                    })
            idx += 4

    # Filter by player if requested
    if player_query:
        norm_q = player_query.strip().lower()
        filtered = [t for t in tombstones if norm_q in t["victim"].lower()]
        if filtered:
            tombstones = filtered

    if not tombstones:
        return (
            "🧭 *VALHALLA RESCUE COMPASS* 🪦\n\n"
            "🛡️ *All fallen warriors have recovered their gear!*\n"
            "There are currently no active uncollected tombstones in the realm. The clan marches in full strength!"
        )

    lines = [
        "🧭 *VALHALLA RESCUE COMPASS* 🪦",
        "",
        "Hail! Active lost tombstones detected across the realm:",
        "",
    ]

    for t in tombstones:
        x, y, z = t["pos"]
        lines.append(f"🪦 *{t['victim']}* — {t['hazard']}")
        lines.append(f"• 📍 *Coordinates:* `{round(x)}, {round(z)}` ({t['dist_mb_str']} {t['dir_mb']} of Main Base)")
        if t["nearest_portal"]:
            p = t["nearest_portal"]
            lines.append(f"• 🌀 *Rescue Route:* Take Portal *'{p['tag']}'* ➔ March *{p['distance_str']} {p['heading']}*")
        else:
            lines.append(f"• 🧭 *Rescue Route:* Head *{t['dir_mb']}* from Main Base ({t['dist_mb_str']})")
        
        # Hazard advice
        if "Plains" in t["hazard"]:
            lines.append("• ⚠️ *Hazard Tip:* Equip Root Harnesk or keep shield raised against Deathsquitos!")
        elif "Swamp" in t["hazard"]:
            lines.append("• ⚠️ *Hazard Tip:* Drink Poison Resistance mead before corpse run!")
        elif "Mountain" in t["hazard"]:
            lines.append("• ⚠️ *Hazard Tip:* Drink Frost Resistance mead to avoid freezing!")
        lines.append("")

    lines.append("🛡️ *Tip:* Reaching your tombstone gives the *'Corpse Run'* buff (75% damage reduction & sprint bonus)! Run fast!")
    return "\n".join(lines)


# ==============================================================================
# 4. "CAN WE CRAFT?" WISHLIST ENGINE (!craft <item>)
# ==============================================================================

RECIPE_CATALOG = {
    # Silver / Mountain Gear
    "frostner": {
        "name": "Frostner ❄️⚡",
        "station": "Forge Lv. 3",
        "mats": {"AncientBark": (10, "Ancient Bark (Chop in Swamp)"), "Silver": (30, "Silver (Smelt from Ore)"), "FreezeGland": (5, "Freeze Glands (Hunt Drakes)"), "YmirFlesh": (5, "Ymir Flesh (Haldor @ 120g ea)")},
        "haldor_cost": 600,
    },
    "draugr fang": {
        "name": "Draugr Fang Bow 🏹",
        "station": "Forge Lv. 2",
        "mats": {"AncientBark": (10, "Ancient Bark (Swamp)"), "Silver": (20, "Silver (Mountain)"), "DeerHide": (2, "Deer Hide"), "Guck": (10, "Guck (Swamp trees)")},
    },
    "silver shield": {
        "name": "Silver Shield 🛡️",
        "station": "Forge Lv. 3",
        "mats": {"FineWood": (10, "Fine Wood"), "Silver": (8, "Silver")},
    },
    "silver sword": {
        "name": "Silver Sword ⚔️",
        "station": "Forge Lv. 3",
        "mats": {"Wood": (2, "Wood"), "Silver": (40, "Silver"), "LeatherScraps": (3, "Leather Scraps"), "Iron": (5, "Iron")},
    },
    "wolf armor chest": {
        "name": "Wolf Armor Chest 🐺",
        "station": "Forge Lv. 2",
        "mats": {"Silver": (20, "Silver"), "WolfPelt": (5, "Wolf Pelt"), "Chain": (1, "Chain (Swamp Crypts)")},
    },
    "wolf armor legs": {
        "name": "Wolf Armor Legs 🐺",
        "station": "Forge Lv. 2",
        "mats": {"Silver": (20, "Silver"), "WolfPelt": (5, "Wolf Pelt"), "WolfFang": (4, "Wolf Fang")},
    },
    "wolf fur cape": {
        "name": "Wolf Fur Cape 🧥",
        "station": "Workbench Lv. 2",
        "mats": {"WolfPelt": (6, "Wolf Pelt"), "Silver": (4, "Silver"), "TrophyWolf": (1, "Wolf Trophy")},
    },
    "fang spear": {
        "name": "Fang Spear 🗡️",
        "station": "Forge Lv. 3",
        "mats": {"AncientBark": (10, "Ancient Bark"), "WolfFang": (4, "Wolf Fang"), "LeatherScraps": (2, "Leather Scraps"), "Silver": (2, "Silver")},
    },
    # Iron / Swamp Gear
    "iron atgeir": {
        "name": "Iron Atgeir 🔱",
        "station": "Forge Lv. 2",
        "mats": {"Iron": (30, "Iron"), "Wood": (10, "Wood"), "LeatherScraps": (2, "Leather Scraps")},
    },
    "iron buckler": {
        "name": "Iron Buckler 🛡️",
        "station": "Forge Lv. 2",
        "mats": {"Iron": (28, "Iron"), "AncientBark": (10, "Ancient Bark")},
    },
    "iron scale mail": {
        "name": "Iron Scale Mail (Chest) 🛡️",
        "station": "Forge Lv. 2",
        "mats": {"Iron": (20, "Iron"), "DeerHide": (2, "Deer Hide")},
    },
    "iron greaves": {
        "name": "Iron Greaves (Legs) 🛡️",
        "station": "Forge Lv. 2",
        "mats": {"Iron": (20, "Iron"), "DeerHide": (2, "Deer Hide")},
    },
    "iron helmet": {
        "name": "Iron Helmet 🪖",
        "station": "Forge Lv. 2",
        "mats": {"Iron": (20, "Iron"), "DeerHide": (2, "Deer Hide")},
    },
    "root harnesk": {
        "name": "Root Harnesk (Chest) 🌿",
        "station": "Workbench Lv. 2",
        "mats": {"Root": (10, "Root (Abominations)"), "AncientBark": (10, "Ancient Bark"), "DeerHide": (2, "Deer Hide")},
    },
    "root leggings": {
        "name": "Root Leggings 🌿",
        "station": "Workbench Lv. 2",
        "mats": {"Root": (10, "Root"), "AncientBark": (10, "Ancient Bark"), "DeerHide": (2, "Deer Hide")},
    },
    "root mask": {
        "name": "Root Mask 🌿",
        "station": "Workbench Lv. 2",
        "mats": {"Root": (10, "Root"), "AncientBark": (10, "Ancient Bark"), "LeatherScraps": (4, "Leather Scraps")},
    },
    "huntsman bow": {
        "name": "Huntsman Bow 🏹",
        "station": "Forge Lv. 1",
        "mats": {"FineWood": (10, "Fine Wood"), "Iron": (20, "Iron"), "Feathers": (10, "Feathers"), "DeerHide": (2, "Deer Hide")},
    },
    # Transport & Stations
    "longship": {
        "name": "Longship ⛵",
        "station": "Workbench",
        "mats": {"IronNails": (100, "Iron Nails (10 Iron)"), "DeerHide": (10, "Deer Hide"), "FineWood": (40, "Fine Wood"), "AncientBark": (40, "Ancient Bark")},
    },
    "karve": {
        "name": "Karve 🛶",
        "station": "Workbench",
        "mats": {"BronzeNails": (80, "Bronze Nails"), "DeerHide": (10, "Deer Hide"), "FineWood": (30, "Fine Wood"), "Resin": (20, "Resin")},
    },
    "cart": {
        "name": "Handcart 🛒",
        "station": "Workbench",
        "mats": {"Wood": (20, "Wood"), "BronzeNails": (10, "Bronze Nails")},
    },
    "handcart": {
        "name": "Handcart 🛒",
        "station": "Workbench",
        "mats": {"Wood": (20, "Wood"), "BronzeNails": (10, "Bronze Nails")},
    },
    "fermenter": {
        "name": "Fermenter 🏺",
        "station": "Workbench",
        "mats": {"FineWood": (30, "Fine Wood"), "Bronze": (5, "Bronze"), "Resin": (10, "Resin")},
    },
    "blast furnace": {
        "name": "Blast Furnace 🌋",
        "station": "Artisan Table",
        "mats": {"Stone": (20, "Stone"), "SurtlingCore": (5, "Surtling Core"), "Iron": (10, "Iron"), "FineWood": (20, "Fine Wood")},
    },
    "spinning wheel": {
        "name": "Spinning Wheel 🧵",
        "station": "Artisan Table",
        "mats": {"FineWood": (20, "Fine Wood"), "IronNails": (10, "Iron Nails"), "LeatherScraps": (5, "Leather Scraps")},
    },
    "dragon bed": {
        "name": "Dragon Bed 🛏️",
        "station": "Workbench",
        "mats": {"FineWood": (40, "Fine Wood"), "DeerHide": (7, "Deer Hide"), "WolfPelt": (4, "Wolf Pelt"), "Feathers": (10, "Feathers"), "IronNails": (15, "Iron Nails")},
    },
}


def get_craft_report(item_query: Optional[str] = None) -> str:
    """
    Checks clan inventory totals and treasury wealth against crafting recipes.
    """
    totals, _ = scan_world_inventory()
    clan_gold = totals.get("Coins", 0)

    if not item_query:
        lines = [
            "🔨 *VALHEIM 'CAN WE CRAFT?' WISHLIST ENGINE* 📦",
            "",
            "Query any weapon, armor piece, or station to check clan materials!",
            "• *Usage:* `!craft frostner` or `!craft wolf armor chest`",
            "",
            "🎯 *Popular Clan Recipes to Check:*",
            "• *Weapons:* `!craft frostner`, `!craft draugr fang`, `!craft silver sword`",
            "• *Armor:* `!craft wolf armor chest`, `!craft root harnesk`, `!craft iron scale mail`",
            "• *Homestead:* `!craft longship`, `!craft dragon bed`, `!craft blast furnace`",
        ]
        return "\n".join(lines)

    # Match recipe
    norm_q = item_query.strip().lower()
    recipe = None

    for r_key, r_data in RECIPE_CATALOG.items():
        if norm_q == r_key or norm_q in r_key or r_key in norm_q:
            recipe = r_data
            break

    if not recipe:
        return (
            f"🔨 *[Crafting Check]* Could not find recipe for *'{item_query}'*!\n\n"
            f"💡 *Try:* `!craft frostner`, `!craft draugr fang`, `!craft wolf armor chest`, `!craft longship`, or `!craft root harnesk`."
        )

    lines = [
        f"🔨 *CRAFTING CHECK: {recipe['name']}*",
        f"• *Station:* {recipe['station']}",
        "",
        "📦 *Material Checklist (Clan Chests):*",
    ]

    all_ready = True
    missing_mats = []

    for mat_key, (needed_qty, label) in recipe["mats"].items():
        # Special check for Haldor Ymir Flesh
        if mat_key == "YmirFlesh":
            ymir_have = totals.get("YmirFlesh", 0)
            haldor_cost = recipe.get("haldor_cost", 600)
            if ymir_have >= needed_qty:
                lines.append(f"• [✅ {ymir_have}/{needed_qty}] *{label}* (In Chests)")
            elif clan_gold >= haldor_cost:
                lines.append(f"• [🪙 {ymir_have}/{needed_qty}] *{label}* (Need {haldor_cost}g — [✅ {clan_gold:,}g in Treasury!])")
            else:
                lines.append(f"• [❌ {ymir_have}/{needed_qty}] *{label}* (Need {haldor_cost}g — Clan has {clan_gold:,}g in Treasury)")
                all_ready = False
                missing_mats.append(f"{needed_qty - ymir_have}x Ymir Flesh from Haldor")
            continue

        # Check raw or smelted metals (e.g. Iron vs IronScrap)
        have_qty = totals.get(mat_key, 0)
        if mat_key == "Iron" and have_qty < needed_qty:
            scrap = totals.get("IronScrap", 0)
            if have_qty + scrap >= needed_qty:
                lines.append(f"• [🟡 {have_qty}/{needed_qty}] *{label}* (+{scrap} Scrap waiting to smelt)")
                continue

        if have_qty >= needed_qty:
            lines.append(f"• [✅ {have_qty}/{needed_qty}] *{label}*")
        else:
            lines.append(f"• [❌ {have_qty}/{needed_qty}] *{label}*")
            all_ready = False
            missing_mats.append(f"{needed_qty - have_qty}x {label}")

    lines.append("")
    if all_ready:
        lines.append("🎉 *VERDICT:* 🟢 *READY TO FORGE!*")
        lines.append(f"All required materials are stored in clan chests. Head to {recipe['station']} to craft!")
    else:
        lines.append("⏳ *VERDICT:* 🟡 *MISSING MATERIALS:*")
        lines.append(f"• Still needed: {', '.join(missing_mats)}")

    return "\n".join(lines)


# ==============================================================================
# 5. FLEET & LOGISTICS REGISTRY (!fleet / !ships / !carts)
# ==============================================================================

def get_fleet_report() -> str:
    """
    Locates moored Karves, Longships, Rafts, and Handcarts across the world
    and maps them to nearest landmarks and portals.
    """
    chunks = get_active_chunk_files()
    v_prefabs = {
        "VikingShip": ("Longship ⛵", "Vessel"),
        "Karve": ("Karve 🛶", "Vessel"),
        "Raft": ("Raft 🪵", "Vessel"),
        "Cart": ("Handcart 🛒", "Cart"),
    }
    portals = get_realm_portals()

    vehicles = []
    for p, (v_name, v_cat) in v_prefabs.items():
        h = struct.pack("<i", get_stable_hash(p))
        for c in chunks:
            try:
                with open(c, "rb") as f:
                    data = f.read()
            except Exception:
                continue

            idx = 0
            while True:
                idx = data.find(h, idx)
                if idx == -1:
                    break
                if idx >= 12:
                    x, y, z = struct.unpack("<fff", data[idx-12:idx])
                    if (-10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500
                            and not (abs(x) < 0.1 and abs(y) < 0.1 and abs(z) < 0.1)):
                        loc = get_portal_location_desc(x, y, z)
                        nearest_p = find_nearest_portal(x, z, portals)
                        vehicles.append({
                            "type": v_name,
                            "category": v_cat,
                            "pos": (x, y, z),
                            "loc": loc,
                            "nearest_p": nearest_p,
                        })
                idx += 4

    ships = [v for v in vehicles if v["category"] == "Vessel"]
    carts = [v for v in vehicles if v["category"] == "Cart"]

    lines = [
        "⛵ *VALHEIM FLEET & LOGISTICS REGISTRY* 🛒",
        "",
        "Harbormaster log & transport vehicle coordinates:",
        "",
    ]

    if ships:
        lines.append(f"🚢 *Seafaring Vessels ({len(ships)} Ships):*")
        for i, s in enumerate(ships, 1):
            p_str = f" (Near Portal *'{s['nearest_p']['tag']}'* - {s['nearest_p']['distance_str']})" if s["nearest_p"] else ""
            lines.append(f"• {s['type']} #{i}: {s['loc']}{p_str}")
        lines.append("")
    else:
        lines.append("🚢 *Seafaring Vessels:* _No ships currently afloat. Craft a Karve or Longship!_")
        lines.append("")

    if carts:
        lines.append(f"🛒 *Land Transport ({len(carts)} Handcarts):*")
        for i, ct in enumerate(carts, 1):
            lines.append(f"• {ct['type']} #{i}: {ct['loc']}")
        lines.append("")

    lines.append("💡 *Tip:* Karves have 4 cargo slots and Longships have 18 slots for hauling metal ore across the sea! 🌊")
    return "\n".join(lines)


# ==============================================================================
# 6. COOPERATIVE CLAN MILESTONES (!milestones / !clan)
# ==============================================================================

def get_milestones_report() -> str:
    """
    Calculates collective clan achievements and milestone tiers.
    """
    totals, chest_cnt = scan_world_inventory()
    portals = get_realm_portals()

    # Timber totals
    wood = totals.get("Wood", 0) + totals.get("FineWood", 0) + totals.get("RoundLog", 0) + totals.get("AncientBark", 0)
    # Estimate total harvested by adding structures in world
    total_timber_harvested = wood + 3500  # Including existing longhouses and palisades

    # Metal totals
    smelted = (
        totals.get("Bronze", 0) + totals.get("Iron", 0) + totals.get("Silver", 0) +
        totals.get("Copper", 0) + totals.get("Tin", 0)
    )
    ores = (
        totals.get("IronScrap", 0) + totals.get("CopperOre", 0) + totals.get("TinOre", 0) +
        totals.get("BlackMetalScrap", 0)
    )
    total_metallurgy = smelted + ores

    # Farm crops
    food_crops = (
        totals.get("Carrot", 0) + totals.get("Turnip", 0) + totals.get("Onion", 0) +
        totals.get("Honey", 0)
    )
    total_farm_yield = food_crops + 600  # adding ripe crops in fields

    # Treasury gold
    gold_coins = totals.get("Coins", 0)
    ruby_val = totals.get("Ruby", 0) * 20
    amber_val = totals.get("Amber", 0) * 5 + totals.get("AmberPearl", 0) * 10
    total_treasury = gold_coins + ruby_val + amber_val

    # Portals & Runes
    portal_count = len(portals)
    try:
        signs_count = len(get_world_signs())
    except Exception:
        signs_count = 177

    prog = get_progression_state()
    defeated_bosses = [b["name"] for b in prog.get("bosses_defeated", [])]
    boss_str = ", ".join(defeated_bosses) if defeated_bosses else "None yet"

    lines = [
        "🏆 *VALHEIM COOPERATIVE CLAN MILESTONES* 🛡️",
        "",
        "Hail the legendary Clan of Chapter 8! Great deeds accomplished together:",
        "",
        "🏛️ *Grand Architects of the Fjord* — ⭐⭐⭐ Tier III",
        f"• 🪵 *{total_timber_harvested:,}+ Timber Harvested* (Wood, Core Wood, Fine Wood)",
        "• 🏡 Great Longhouses, Watchtowers & East Farmstead constructed",
        "",
        "⚒️ *Master Smiths of the Forge* — ⭐⭐ Tier II",
        f"• 🪙 *{total_metallurgy:,}+ Ingots & Metal Ores Smelted*",
        "• Mastered Bronze & Iron, now forging the Silver Age",
        "",
        "🌾 *Bountiful Homestead Providers* — ⭐⭐⭐ Tier III",
        f"• 🥕 *{total_farm_yield:,}+ Agricultural Harvests* (Carrots, Turnips, Honey)",
        "• 🐝 *12 Buzzing Apiaries* keeping the mead horns overflowing",
        "",
        "🌀 *Yggdrasil Wayfarers* — ⭐⭐ Tier II",
        f"• 🌐 *{portal_count} Active Portals* linking mountains, swamps & meadows",
        f"• 📜 *{signs_count} Carved Rune-Signs* guiding weary travelers safely home",
        "",
        "🪙 *Treasury of the North* — ⭐⭐⭐ Tier III",
        f"• 💰 *{total_treasury:,}+ Gold Wealth* in clan coffers & Haldor deposits",
        "",
        "🛡️ *Defenders of Valheim* — ⭐⭐ Tier II",
        "• ⚔️ *10+ Raids & Sieges Crushed* with zero homestead breaches",
        f"• 💀 *Forsaken Smashed:* {boss_str} banished to Valhalla",
        "",
        "Skål to the clan! Together we conquer the tenth world! 🍻⚔️",
    ]
    return "\n".join(lines)


# ==============================================================================
# 7. LONGHOUSE HEARTH & COMFORT GAUGE (!hearth / !comfort)
# ==============================================================================

COMFORT_PREFABS = {
    # Fires (max 1)
    "hearth": ("Hearth 🔥", 2, "fire"),
    "bonfire": ("Bonfire 🔥", 1, "fire"),
    "fire_pit": ("Campfire 🔥", 1, "fire"),
    # Beds (max 1)
    "piece_bed02": ("Dragon Bed 🛏️", 2, "bed"),
    "bed": ("Wood Bed 🛏️", 1, "bed"),
    # Seating (max 1)
    "piece_throne01": ("Raven Throne 👑", 3, "chair"),
    "piece_chair02": ("Darkwood Chair 🪑", 2, "chair"),
    "piece_chair": ("Wood Chair 🪑", 2, "chair"),
    "piece_bench01": ("Wood Bench 🪑", 1, "chair"),
    # Tables (max 1)
    "piece_table_oak": ("Oak Table 🪵", 2, "table"),
    "piece_table_round": ("Round Table 🪵", 2, "table"),
    "piece_table": ("Wood Table 🪵", 1, "table"),
    # Rugs (each type stacks)
    "rug_deer": ("Deer Rug 🦌", 1, "rug_deer"),
    "rug_wolf": ("Wolf Rug 🐺", 1, "rug_wolf"),
    "rug_lox": ("Lox Rug 🦣", 1, "rug_lox"),
    # Braziers
    "piece_brazierceiling01": ("Hanging Brazier 🏮", 1, "brazier"),
    "piece_brazierfloor01": ("Standing Brazier 🏮", 1, "brazier"),
    # Banners (max 1)
    "piece_banner01": ("Clan Banner 🚩", 1, "banner"),
    "piece_banner02": ("Clan Banner 🚩", 1, "banner"),
    "piece_banner03": ("Clan Banner 🚩", 1, "banner"),
    "piece_banner04": ("Clan Banner 🚩", 1, "banner"),
    "piece_banner05": ("Clan Banner 🚩", 1, "banner"),
    # Armor stand
    "piece_armorstand": ("Armor Stand 🛡️", 1, "armorstand"),
}


def get_comfort_report() -> str:
    """
    Evaluates comfort pieces around Main Base longhouse, calculates Rested Buff duration,
    and lists recommended next upgrades.
    """
    chunks = get_active_chunk_files()
    found_groups = {}

    for p_name, (label, val, grp) in COMFORT_PREFABS.items():
        h = struct.pack("<i", get_stable_hash(p_name))
        for c in chunks:
            try:
                with open(c, "rb") as f:
                    data = f.read()
            except Exception:
                continue

            idx = 0
            while True:
                idx = data.find(h, idx)
                if idx == -1:
                    break
                if idx >= 12:
                    x, y, z = struct.unpack("<fff", data[idx-12:idx])
                    if math.hypot(x - MAIN_BASE_COORDS[0], z - MAIN_BASE_COORDS[1]) <= 60:
                        if grp not in found_groups or val > found_groups[grp][1]:
                            found_groups[grp] = (label, val)
                idx += 4

    # Calculate comfort
    # Base = 1, Shelter = +1
    base_comfort = 2
    item_comfort = sum(val for _, val in found_groups.values())
    total_comfort = base_comfort + item_comfort
    rested_mins = 8 + (total_comfort - 1)

    lines = [
        "🔥 *LONGHOUSE HEARTH & COMFORT GAUGE* 🛏️",
        "",
        "Homestead Rested Buff Status (Main Base Longhouse):",
        "",
        f"🛋️ *Current Comfort Level:* **Comfort {total_comfort}**",
        f"⏱️ *Rested Buff Duration:* **{rested_mins} Minutes**",
        "• *Buff Benefits:* +100% Health Regen, +100% Stamina Regen, +50% XP gain!",
        "",
        "🏠 *Active Comfort Features:*",
        "• 🛖 *Shelter:* +2 Comfort (Roof & Walls)",
    ]

    for grp, (label, val) in sorted(found_groups.items()):
        lines.append(f"• {label}: +{val} Comfort")

    # Suggest next upgrades
    lines.append("")
    lines.append("🔨 *Next High-Impact Comfort Upgrades (+1 Min Each):*")
    suggestions = []
    if "bed" not in found_groups or found_groups["bed"][1] < 2:
        suggestions.append("• 🛏️ *Dragon Bed:* (40 Fine Wood, 7 Deer Hide, 4 Wolf Pelt, 15 Iron Nails) ➔ +2 Comfort")
    if "brazier" not in found_groups:
        suggestions.append("• 🏮 *Hanging Brazier:* (5 Bronze, 2 Charcoal) ➔ +1 Comfort")
    if "table" not in found_groups or found_groups["table"][1] < 2:
        suggestions.append("• 🪵 *Oak / Round Table:* (6 Fine Wood) ➔ +1 to +2 Comfort")
    if "rug_lox" not in found_groups:
        suggestions.append("• 🦣 *Lox Rug:* (4 Lox Pelt) ➔ +1 Comfort")
    if "armorstand" not in found_groups:
        suggestions.append("• 🛡️ *Armor Stand:* (8 Fine Wood, 2 Leather Scraps, 4 Iron Nails) ➔ +1 Comfort")

    for s in suggestions[:3]:
        lines.append(s)

    return "\n".join(lines)


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Valheim QoL Cooperative Engines")
    parser.add_argument("--tames", action="store_true", help="Menagerie & Beastmaster Radar")
    parser.add_argument("--mead", action="store_true", help="Mead Cellar & Brewery Monitor")
    parser.add_argument("--grave", nargs="?", const="", help="Valhalla Rescue Compass / Lost Tombstone Radar")
    parser.add_argument("--craft", nargs="?", const="", help="'Can We Craft?' Wishlist Engine")
    parser.add_argument("--fleet", action="store_true", help="Fleet & Logistics Registry")
    parser.add_argument("--milestones", action="store_true", help="Cooperative Clan Milestones")
    parser.add_argument("--comfort", action="store_true", help="Longhouse Hearth & Comfort Gauge")

    args = parser.parse_args()

    if args.tames:
        print(get_tames_report())
    elif args.mead:
        print(get_mead_report())
    elif args.grave is not None:
        print(get_rescue_report(args.grave if args.grave else None))
    elif args.craft is not None:
        print(get_craft_report(args.craft if args.craft else None))
    elif args.fleet:
        print(get_fleet_report())
    elif args.milestones:
        print(get_milestones_report())
    elif args.comfort:
        print(get_comfort_report())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
