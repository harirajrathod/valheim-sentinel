import os
import sys
import time
import re
import struct
import difflib
from itertools import combinations

sys.path.insert(0, '/root')
from valheim_utils import (
    safe_load_json,
    atomic_save_json,
    get_active_chunk_files,
)

from valheim_constants import ITEM_CATALOG, HASH_TO_KEY, TARGET_S_ITEMS, PACKED_PLAYER_HASHES, FOOD_CATALOG
from valheim_geography import get_traders_status
from valheim_progression import get_progression_state


_INVENTORY_CACHE_FILE = '/root/.cache/valheim_inventory_cache.json'
_INVENTORY_CACHE_TTL = 15

def scan_world_inventory(force_refresh: bool = False):
    if not force_refresh and os.path.exists(_INVENTORY_CACHE_FILE):
        if time.time() - os.path.getmtime(_INVENTORY_CACHE_FILE) < _INVENTORY_CACHE_TTL:
            try:
                data = safe_load_json(_INVENTORY_CACHE_FILE, default=None)
                if data and 'totals' in data and 'container_count' in data:
                    return data['totals'], data['container_count']
            except Exception:
                pass
                
    totals, container_count = _scan_world_inventory_uncached()
    try:
        atomic_save_json(_INVENTORY_CACHE_FILE, {'totals': totals, 'container_count': container_count})
    except Exception:
        pass
    return totals, container_count

def _scan_world_inventory_uncached():
    totals = {}
    container_count = 0
    chunks = get_active_chunk_files()
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
                            container_count += 1
                            for i in range(6, payload_len - 5):
                                cand_hash = struct.unpack('<i', payload[i+2:i+6])[0]
                                if cand_hash in HASH_TO_KEY:
                                    stack = struct.unpack('<H', payload[i:i+2])[0]
                                    if 1 <= stack <= 999:
                                        k = HASH_TO_KEY[cand_hash]
                                        totals[k] = totals.get(k, 0) + stack
                idx += 4
        except Exception:
            pass
    return totals, container_count

def get_wealth_report():
    totals, container_count = scan_world_inventory()
    coins = totals.get('Coins', 0)
    amber = totals.get('Amber', 0)
    pearls = totals.get('AmberPearl', 0)
    rubies = totals.get('Ruby', 0)
    necklaces = totals.get('SilverNecklace', 0)

    gems_value = (amber * 5) + (pearls * 10) + (rubies * 20) + (necklaces * 30)
    net_worth = coins + gems_value
    traders = get_traders_status()

    gem_items = []
    if rubies > 0: gem_items.append(f"{rubies} Rubies ({rubies*20}g)")
    if pearls > 0: gem_items.append(f"{pearls} Pearls ({pearls*10}g)")
    if amber > 0: gem_items.append(f"{amber} Amber ({amber*5}g)")
    if necklaces > 0: gem_items.append(f"{necklaces} Necklaces ({necklaces*30}g)")
    gem_str = ", ".join(gem_items) if gem_items else "None"

    lines = [
        "🪙 *TRIBAL TREASURY & REALM MERCHANTS* 💰",
        "",
        "💰 *Clan Coffers:*",
        f"• *Liquid Gold Coins:* {coins:,} 🪙",
        f"• *Uncut Gemstones:* ~{gems_value:,} Gold ({gem_str})",
        f"🔥 *Total Clan Net Worth:* *~{net_worth:,} Gold*",
        "",
        "🏪 *Realm Traders & Purchasing Power:*",
    ]

    # 1. Haldor
    h_info = traders.get('Haldor', {})
    if h_info.get('interacted'):
        p_str = f"`{h_info['portal']}`" if h_info.get('portal') else "No Portal"
        lines.append(f"• 🪙 *Haldor* (Black Forest • Portal: {p_str})")
        meg_count = net_worth // 950
        lines.append(f"  ├ {'✅' if net_worth >= 950 else '❌'} *Megingjord* (+150 Weight): 950g ({'Can buy ' + str(meg_count) if meg_count > 0 else 'Need ' + str(950 - net_worth) + 'g'})")
        lines.append(f"  ├ {'✅' if net_worth >= 620 else '❌'} *Dvergr Circlet* (Headlamp): 620g")
        lines.append(f"  ├ {'✅' if net_worth >= 350 else '❌'} *Fishing Rod & 50 Bait*: 350g")
        lines.append(f"  └ {'✅' if net_worth >= 120 else '❌'} *Ymir Flesh*: 120g (Can buy {net_worth // 120})")
    elif h_info.get('discovered'):
        lines.append("• 🪙 *Haldor* (Black Forest • ⏳ Discovered, needs portal link)")
    else:
        lines.append("• 🪙 *Haldor* (Black Forest • 🔒 Undiscovered)")

    # 2. Hildir
    hi_info = traders.get('Hildir', {})
    if hi_info.get('interacted'):
        p_str = f"`{hi_info['portal']}`" if hi_info.get('portal') else "No Portal"
        q_count = len(hi_info.get('quests', []))
        lines.append(f"• 👗 *Hildir* (Meadows • Portal: {p_str})")
        lines.append(f"  ├ 🎯 *Quests:* {q_count}/3 Brass Chests recovered")
        lines.append("  └ ℹ️ *Wares:* Vanity Apparel & Fireworks unlocked")
    elif hi_info.get('discovered'):
        lines.append("• 👗 *Hildir* (Meadows • ⏳ Discovered, needs portal link)")
    else:
        lines.append("• 👗 *Hildir* (Meadows • 🔒 Undiscovered)")

    # 3. Bog Witch
    bw_info = traders.get('BogWitch', {})
    if bw_info.get('interacted'):
        p_str = f"`{bw_info['portal']}`" if bw_info.get('portal') else "No Portal"
        lines.append(f"• 🧙‍♀️ *The Bog Witch* (Swamp • Portal: {p_str})")
        lines.append("  └ ℹ️ *Wares:* Alchemy Draughts, Cauldron Spices & Reaping Scythe")
    elif bw_info.get('discovered'):
        lines.append("• 🧙‍♀️ *The Bog Witch* (Swamp • ⏳ Discovered, needs portal link)")
    else:
        lines.append("• 🧙‍♀️ *The Bog Witch* (Swamp • 🔒 Undiscovered)")

    return "\n".join(lines)

def get_metal_report():
    totals, container_count = scan_world_inventory()
    prog = get_progression_state()
    current_tier = prog['current_tier']
    next_biome = prog['next_biome']

    cop_bars = totals.get('Copper', 0)
    cop_ore  = totals.get('CopperOre', 0)
    cop_total = cop_bars + cop_ore

    tin_bars = totals.get('Tin', 0)
    tin_ore  = totals.get('TinOre', 0)
    tin_total = tin_bars + tin_ore

    bronze_bars = totals.get('Bronze', 0)
    iron_bars   = totals.get('Iron', 0)
    iron_scrap  = totals.get('IronScrap', 0)
    iron_ore    = totals.get('IronOre', 0)
    iron_total  = iron_bars + iron_scrap + iron_ore

    silver_bars = totals.get('Silver', 0)
    silver_ore  = totals.get('SilverOre', 0)
    silver_total = silver_bars + silver_ore

    black_bars  = totals.get('BlackMetal', 0)
    black_scrap = totals.get('BlackMetalScrap', 0)
    black_total = black_bars + black_scrap

    flametal_bars = totals.get('Flametal', 0)
    flametal_ore  = totals.get('FlametalOre', 0)
    flametal_total = flametal_bars + flametal_ore

    obsidian = totals.get('Obsidian', 0)
    cores = totals.get('SurtlingCore', 0)
    coal  = totals.get('Coal', 0)
    linen = totals.get('LinenThread', 0)

    # ── Era label from boss progression (not material heuristic) ─────────────
    ERA_LABELS = {
        0: '🏕️ Stone & Flint (Meadows Era)',
        1: '🏕️ Stone & Flint (Meadows Era)',
        2: '🌲 Bronze (Black Forest Era)',
        3: '☣️ Iron (Swamps Era)',
        4: '❄️ Silver (Mountains Era)',
        5: '🌾 Black Metal (Plains Era)',
        6: '🪲 Eitr & Black Marble (Mistlands Era)',
        7: '🔥 Flametal (Ashlands Era)',
        8: '❄️ Bloodgold (Deep North Era)',
    }
    active_metal_era = ERA_LABELS.get(current_tier, f'Tier {current_tier}')

    lines = [
        "⛏️ *VALHEIM CLAN METALLURGY & SMELTER RESERVES*",
        f"🏆 *Active Metal Era:* *{active_metal_era}* | *Next: {next_biome}*",
        "",
        f"📦 *Current Metal Stockpile ({container_count} Base Chests):*",
    ]

    if silver_total > 0:
        lines.append(f"• ❄️ *Silver:* {silver_total} ({silver_bars} bars + {silver_ore} ore)")
    if black_total > 0:
        lines.append(f"• 🌾 *Black Metal:* {black_total} ({black_bars} bars + {black_scrap} scrap)")
    if iron_total > 0:
        lines.append(f"• ☣️ *Iron:* {iron_total} ({iron_bars} bars + {iron_scrap + iron_ore} scrap/ore)")
    if cop_total > 0 or tin_total > 0:
        lines.append(f"• 🌲 *Copper & Tin:* {cop_total} Copper ({cop_bars} bars) | {tin_total} Tin ({tin_bars} bars)")
    if bronze_bars > 0:
        lines.append(f"• 🌲 *Bronze:* {bronze_bars} bars")
    if obsidian > 0:
        lines.append(f"• 🏹 *Obsidian:* {obsidian} (Mountains arrows & crafting)")
    if flametal_total > 0:
        lines.append(f"• 🔥 *Flametal:* {flametal_total} ({flametal_bars} bars + {flametal_ore} ore)")
    if linen > 0:
        lines.append(f"• 🧵 *Linen Thread:* {linen} (Plains armor/weapons)")

    lines.append("")
    lines.append("🔨 *Forge & Equipment Readiness:*")
    if current_tier <= 4:
        wolf_sets = silver_bars // 40
        if wolf_sets > 0:
            set_plural = "set" if wolf_sets == 1 else "sets"
            lines.append(f"• ❄️ *Wolf Armor:* ✅ {wolf_sets} {set_plural} craftable now from {silver_bars} Silver bars (40 Silver/set)!")
        else:
            lines.append(f"• ❄️ *Wolf Armor:* {silver_bars}/40 Silver bars")
        lines.append(f"• ⚔️ *Silver Weapons:* {silver_bars} Silver bars ready for Silver Sword / Frostner")
        lines.append(f"• ⛵ *Iron Infrastructure:* {iron_bars} Iron bars ready for nails & tools")
        if black_total > 0:
            lines.append(f"• 🌾 *Black Metal ({black_total} scrap):* Stockpiling for Blast Furnace (Plains)")
    elif current_tier >= 5:
        padded_possible = min(iron_bars // 10, linen // 20) if linen > 0 else 0
        piece_plural = "piece" if padded_possible == 1 else "pieces"
        lines.append(f"• 🌾 *Padded Armor:* {padded_possible} {piece_plural} craftable ({linen} Linen, {iron_bars} Iron bars)")
        lines.append(f"• ⚔️ *Black Metal Weapons:* {black_scrap} scrap ready for Blast Furnace")

    # Flametal (Ashlands)
    if flametal_total > 0:
        lines.append("")
        lines.append(f"🔥 *Flametal ({flametal_total}) — Ashlands Metal:* Requires Smelter on Ashlands ground to process.")

    # Smelting fuel & infrastructure
    raw_ores = cop_ore + tin_ore + iron_scrap + iron_ore + silver_ore
    coal_needed = raw_ores * 2
    lines.append("")
    lines.append("🪵 *Smelting Infrastructure & Fuel:*")
    lines.append(f"• *Raw Ores/Scrap to Smelt:* {raw_ores} ({cop_ore} Cu + {tin_ore} Sn + {iron_scrap + iron_ore} Iron + {silver_ore} Silver)")
    lines.append(f"• *Coal Stock:* {coal} | *Coal Required:* ~{coal_needed} (~{coal_needed * 2} Wood in Charcoal Kiln)")
    lines.append(f"• *Surtling Cores:* {cores} ({'✅ Ready for new station' if cores >= 5 else f'⏳ Need {5-cores} more for Smelter/Kiln'})")
    if black_scrap > 0 and current_tier >= 4:
        lines.append("• *Blast Furnace:* Required to smelt Black Metal Scrap (needs Artisan Table + Dragon Tear)")

    return "\n".join(lines)

def get_inventory_stock(key, totals):
    cnt = totals.get(key, 0)
    if key == 'RawMeat':
        cnt += totals.get('BoarMeat', 0)
    return cnt

def calc_recipe_batches(recipe, totals):
    if not recipe: return 0
    batches = 999999
    for ing, req in recipe.items():
        avail = get_inventory_stock(ing, totals)
        b = avail // req
        if b < batches:
            batches = b
    return batches if batches != 999999 else 0

def get_food_report():
    totals, _ = scan_world_inventory()

    available_foods = {}
    for fid, data in FOOD_CATALOG.items():
        ready = totals.get(fid, 0)
        craftable = 0
        raw_convertible = 0

        if data.get('raw'):
            raw_key = data['raw']
            raw_convertible = get_inventory_stock(raw_key, totals)

        if data.get('recipe'):
            b = calc_recipe_batches(data['recipe'], totals)
            if b == 0 and data.get('alt_recipe'):
                b = calc_recipe_batches(data['alt_recipe'], totals)
            craftable = b * data.get('yield', 1)

        total_avail = ready + craftable + raw_convertible
        if total_avail > 0:
            available_foods[fid] = {
                'fid': fid,
                'name': data['name'],
                'icon': data['icon'],
                'hp': data['hp'],
                'stam': data['stam'],
                'eitr': data['eitr'],
                'dur': data['dur'],
                'tier': data['tier'],
                'tier_name': data['tier_name'],
                'type': data['type'],
                'ready': ready,
                'craftable': craftable,
                'raw_convertible': raw_convertible,
                'total': total_avail,
                'station': data['station']
            }

    # Determine highest unlocked nutrition tier
    highest_tier = max((f['tier'] for f in available_foods.values() if f['craftable'] > 0 or f['ready'] > 0), default=1)
    tier_labels = {
        1: "🏕️ Tier 1: Meadows Campfire Provisions",
        2: "🌲 Tier 2: Black Forest Stews & Jam",
        3: "☣️ Tier 3: Swamps Feasts & Delicacies",
        4: "❄️ Tier 4: Mountain Skewers & Frost Feasts",
        5: "🌾 Tier 5: Plains Hearth & Bakery",
        6: "🪲 Tier 6: Mistlands Royal Feasts & Magic",
        7: "🔥 Tier 7: Ashlands Fiery Banquet"
    }

    lines = [
        "🍖 *VALHEIM CLAN PANTRY & NUTRITION*",
        f"🏆 *Kitchen Era:* *{tier_labels.get(highest_tier, f'Tier {highest_tier}')}*",
        "",
        "📦 *Pantry Reserves:*",
    ]

    # Ready foods (meats + cooked dishes)
    ready_items = []
    for fid in ['CookedWolfMeat', 'CookedLoxMeat', 'CookedSerpentMeat', 'CookedFish', 'CookedDeerMeat', 'CookedMeat', 'GrilledNeckTail']:
        cnt = totals.get(fid, 0)
        if cnt > 0:
            meta = FOOD_CATALOG.get(fid, {})
            ready_items.append(f"{cnt} {meta.get('name', fid)} ({meta.get('hp', 0)} HP)")
    for fid in ['WolfSkewers', 'Eyescream', 'OnionSoup', 'Sausages', 'TurnipStew', 'BlackSoup', 'Muckshake', 'Bread', 'FishWraps', 'LoxPie', 'BloodPudding']:
        cnt = totals.get(fid, 0)
        if cnt > 0:
            meta = FOOD_CATALOG.get(fid, {})
            ready_items.append(f"{cnt} {meta.get('name', fid)} ({meta.get('hp', 0)}h/{meta.get('stam', 0)}s)")
    if ready_items:
        lines.append(f"• *Prepared Food:* {', '.join(ready_items)}")

    # Key Foraged & Farmed Stock (compact summary of top items)
    produce_items = []
    for fid, label in [('Honey', 'Honey 🍯 (35s)'), ('Onion', 'Onions 🧅 (40s)'), ('Turnip', 'Turnips (30s)'),
                       ('Carrot', 'Carrots (32s)'), ('Cloudberry', 'Cloudberries 🫐 (40s)'),
                       ('MushroomYellow', 'Yellow Mush 🍄 (30s)'), ('Blueberries', 'Blueberries 🫐'),
                       ('Raspberry', 'Raspberries'), ('Mushroom', 'Red Mush 🍄')]:
        cnt = totals.get(fid, 0)
        if cnt > 0:
            produce_items.append(f"{cnt} {label}")
    if produce_items:
        lines.append(f"• *Farmed & Foraged:* {', '.join(produce_items[:6])}")

    # Raw Cooking Meat & Alchemy Reserves
    raw_reserves = []
    for fid, label in [('WolfMeat', 'Raw Wolf Meat'), ('RawMeat', 'Raw Boar Meat'), ('NeckTail', 'Neck Tails'),
                       ('Entrails', 'Entrails'), ('Thistle', 'Thistle 🌿'), ('Bloodbag', 'Bloodbags'),
                       ('Ooze', 'Ooze'), ('FreezeGland', 'Freeze Glands')]:
        cnt = get_inventory_stock(fid, totals)
        if cnt > 0:
            raw_reserves.append(f"{cnt} {label}")
    if raw_reserves:
        lines.append(f"• *Cooking Reserves:* {', '.join(raw_reserves[:6])}")

    # Cauldron Craftable - Top 6 highest tier / stats
    lines.append("")
    lines.append("🍲 *Top Cauldron Feasts Craftable Now:*")
    craftable_list = []
    for fid, data in FOOD_CATALOG.items():
        rec = data.get('recipe')
        if not rec: continue
        b = calc_recipe_batches(rec, totals)
        if b == 0 and data.get('alt_recipe'):
            b = calc_recipe_batches(data['alt_recipe'], totals)
            rec = data.get('alt_recipe')
        yield_total = b * data.get('yield', 1)
        if yield_total > 0:
            craftable_list.append((data['tier'], yield_total, fid, data, b, rec))

    sorted_craftables = sorted(craftable_list, key=lambda x: (x[0], x[3]['hp'] + x[3]['stam']), reverse=True)
    for tier, yield_total, fid, data, b, rec in sorted_craftables[:6]:
        stat_str = f"{data['hp']}h / {data['stam']}s" if data['eitr'] == 0 else f"{data['hp']}h / {data['stam']}s / {data['eitr']}e"
        lines.append(f"• {data['icon']} *{data['name']}* ({stat_str}, {data['dur']}m) — *{yield_total} craftable*")

    # 3-Food Combos
    lines.append("")
    lines.append("🏆 *Optimal 3-Food Combos (Today's Stock):*")

    # 1. Tank
    health_sorted = sorted(available_foods.values(), key=lambda x: (x['hp'], x['stam']), reverse=True)
    tank_combo = health_sorted[:3]
    if tank_combo:
        tank_hp = 25 + sum(x['hp'] for x in tank_combo)
        tank_stam = 50 + sum(x['stam'] for x in tank_combo)
        tank_rations = min((x['total'] for x in tank_combo), default=0)
        tank_names = " + ".join(f"{x['name']} ({x['hp']} HP)" for x in tank_combo)
        lines.append(f"⚔️ *Tank:* {tank_names}")
        lines.append(f"   ↳ 🔥 *{tank_hp} HP | {tank_stam} Stam* ({tank_rations} rations ready)")
    else:
        lines.append("⚔️ *Tank:* _No food in stock — forage meat & veggies!_")

    # 2. Stamina
    stam_sorted = sorted(available_foods.values(), key=lambda x: (x['stam'], x['hp']), reverse=True)
    stam_combo = stam_sorted[:3]
    if stam_combo:
        stam_st = 50 + sum(x['stam'] for x in stam_combo)
        stam_hp = 25 + sum(x['hp'] for x in stam_combo)
        stam_rations = min((x['total'] for x in stam_combo), default=0)
        stam_names = " + ".join(f"{x['name']} ({x['stam']} Stam)" for x in stam_combo)
        lines.append(f"⚡ *Stamina:* {stam_names}")
        lines.append(f"   ↳ ⚡ *{stam_st} Stam | {stam_hp} HP* ({stam_rations} rations ready)")
    else:
        lines.append("⚡ *Stamina:* _No stamina food in stock — forage berries & honey!_")

    # 3. Balanced
    best_bal = None
    best_bal_score = -1
    for combo in combinations(available_foods.values(), 3):
        hp_sum = 25 + sum(x['hp'] for x in combo)
        st_sum = 50 + sum(x['stam'] for x in combo)
        has_hp = any(x['hp'] > x['stam'] for x in combo)
        has_st = any(x['stam'] > x['hp'] for x in combo)
        if not (has_hp and has_st): continue
        score = (hp_sum + st_sum) - (abs(hp_sum - st_sum) * 0.4)
        if score > best_bal_score:
            best_bal_score = score
            best_bal = (combo, hp_sum, st_sum, min(x['total'] for x in combo))

    if best_bal:
        combo, b_hp, b_st, b_rat = best_bal
        bal_names = " + ".join(f"{x['name']}" for x in combo)
        lines.append(f"⚖️ *Balanced:* {bal_names}")
        lines.append(f"   ↳ ✨ *{b_hp} HP | {b_st} Stam* ({b_rat} rations ready)")

    return "\n".join(lines)

def get_armour_report():
    totals, _ = scan_world_inventory()
    prog = get_progression_state()
    current_tier = prog['current_tier']
    current_biome = prog['current_biome']
    next_biome = prog['next_biome']
    next_boss = prog['next_boss']

    # ── Material stock ────────────────────────────────────────────────────────
    troll_hide   = totals.get('TrollHide', 0)
    deer_hide    = totals.get('DeerHide', 0)
    roots        = totals.get('Root', 0)
    chain        = totals.get('Chain', 0)
    chitin       = totals.get('Chitin', 0)

    iron_bars    = totals.get('Iron', 0)
    iron_scrap   = totals.get('IronScrap', 0) + totals.get('IronOre', 0)
    iron_total   = iron_bars + iron_scrap

    silver_bars  = totals.get('Silver', 0)
    silver_ore   = totals.get('SilverOre', 0)
    silver_total = silver_bars + silver_ore
    wolf_pelt    = totals.get('WolfPelt', 0)
    wolf_fang    = totals.get('WolfFang', 0)
    fine_wood    = totals.get('FineWood', 0)
    drake_trophy = totals.get('TrophyHatchling', 0)

    black_bars   = totals.get('BlackMetal', 0)
    black_scrap  = totals.get('BlackMetalScrap', 0)
    black_total  = black_bars + black_scrap
    linen        = totals.get('LinenThread', 0)
    needle       = totals.get('Needle', 0)
    lox_pelt     = totals.get('LoxPelt', 0)

    TIER_LABELS = {
        0: '🏕️ Meadows',
        1: '🏕️ Meadows (Leather)',
        2: '🌲 Black Forest (Troll & Bronze)',
        3: '☣️ Swamps (Iron & Root)',
        4: '❄️ Mountains (Wolf & Silver)',
        5: '🌾 Plains (Padded & Black Metal)',
        6: '🪲 Mistlands (Carapace)',
        7: '🔥 Ashlands (Flametal)',
        8: '❄️ Deep North (Bloodgold)',
    }
    active_tier_name = TIER_LABELS.get(current_tier, f'Tier {current_tier}')

    lines = [
        "🛡️ *VALHEIM CLAN ARMOURY & FORGE*",
        f"🏆 *Era:* *{active_tier_name}* ➔ *Preparing for: {next_biome}*",
        "",
        "📦 *Armoury Stock:*",
        f"• *Metals:* {silver_total} Silver ({silver_bars}b+{silver_ore}o) | {iron_total} Iron ({iron_bars}b+{iron_scrap}s) | {black_total} Black Metal ({black_scrap}s)",
        f"• *Pelts & Hides:* {wolf_pelt} Wolf Pelts, {wolf_fang} Wolf Fangs, {troll_hide} Troll, {deer_hide} Deer",
    ]
    if linen > 0 or needle > 0 or lox_pelt > 0:
        lines.append(f"• *Plains Stock:* {linen} Linen Thread | {needle} Needles | {lox_pelt} Lox Pelts")
    if chain > 0 or roots > 0 or chitin > 0:
        lines.append(f"• *Special:* {chain} Chain | {roots} Roots | {chitin} Chitin")

    lines.append("")
    lines.append("⚔️ *Current Tier Equipment:*")

    if current_tier == 4:
        lines.append("• ❄️ *Wolf Armor Set* (Chest & Legs: 40 Silver + 10 Wolf Pelt + 4 Wolf Fang + 1 Chain)")
        if silver_bars >= 40 and wolf_pelt >= 10 and wolf_fang >= 4 and chain >= 1:
            craftable_sets = min(silver_bars // 40, wolf_pelt // 10, wolf_fang // 4, chain)
            c_set_plural = "set" if craftable_sets == 1 else "sets"
            lines.append(f"  ✅ *Wolf Armor Chest & Legs craftable now!* ({craftable_sets} {c_set_plural} ready)")
        else:
            missing = []
            if silver_bars < 40: missing.append(f"{40-silver_bars} Silver")
            if wolf_pelt < 10: missing.append(f"{10-wolf_pelt} Wolf Pelt")
            if wolf_fang < 4: missing.append(f"{4-wolf_fang} Wolf Fang")
            if chain < 1: missing.append(f"{1-chain} Chain")
            lines.append(f"  ⏳ _Missing:_ {', '.join(missing)}")
        helm_status = "✅ Craftable!" if silver_bars >= 20 and drake_trophy >= 2 and wolf_pelt >= 2 else f"⏳ Stock: {silver_bars}/20 Silver, {drake_trophy}/2 Drake Trophies"
        lines.append(f"• 🔱 *Drake Helmet* (20 armor) — 20 Silver + 2 Wolf Pelt + 2 Drake Trophies ({helm_status})")
        shield_status = "✅ Craftable!" if silver_bars >= 8 and fine_wood >= 10 else f"⏳ Stock: {silver_bars}/8 Silver, {fine_wood}/10 Fine Wood"
        lines.append(f"• 🛡️ *Silver Shield* (75 block) — 8 Silver + 10 Fine Wood ({shield_status})")
    elif current_tier == 5:
        lines.append("• 🌾 *Padded Armor Set* (100 armor)")
        lines.append("  _Cost:_ ~30 Iron + 60 Linen Thread (Spinning Wheel + Flax)")
        if linen >= 60 and iron_bars >= 30:
            lines.append("  ✅ *Full Padded Armor craftable now!*")
        elif linen > 0:
            pieces = min(linen // 20, iron_bars // 10)
            pieces_plural = "piece" if pieces == 1 else "pieces"
            lines.append(f"  → {pieces} {pieces_plural} craftable now ({linen}/60 Linen).")
        else:
            lines.append("  ⏳ _Need Flax from Plains Fuling camps + Spinning Wheel._")
        lines.append("• ⚔️ *Black Metal Weapons* (Sword/Atgeir) — Smelt scrap at Blast Furnace")
        lines.append("• 🌾 *Black Metal Shield* (90 block) — 10 BM + 8 Fine Wood + 5 Linen")
    elif current_tier <= 3:
        lines.append("• ☣️ *Iron Scale Armor* (42 armor) — 60 Iron + 6 Deer Hide")
        lines.append("• 🌿 *Root Armor* (24 armor, Pierce Resist) — 10 Root + 10 Bark/piece")

    if next_boss and next_biome != current_biome:
        lines.append("")
        lines.append(f"🎯 *Next Target — {next_biome} (Boss: {next_boss['name']}):*")
        if next_biome == 'Plains':
            lines.append("• 🌾 *Goal:* Padded Armor (100 armor) & Black Metal Weapons")
            lines.append("• 🏗️ *Station:* Artisan Table (Dragon Tear) ➔ Spinning Wheel & Blast Furnace")
            lines.append("• ⚠️ *Hazard:* Deathsquito pierce damage — never explore in light armor!")
        elif next_biome == 'Mistlands':
            lines.append("• 🪲 *Goal:* Carapace Armor (Seeker drops) & Wisplight (Wisp Fountain)")
            lines.append("• 🏗️ *Station:* Galdr Table (Black Marble + Yggdrasil Wood)")

    lines.append("")
    if current_tier == 4:
        lines.append("🎖️ *Quartermaster:* Ensure all warriors have Wolf Armor (78 armor). Next, build the Artisan Table from Moder's Dragon Tears to unlock Flax spinning for Plains Padded Armor!")
    elif current_tier == 5:
        lines.append("🎖️ *Quartermaster:* Forge full Padded sets (100 armor) and Black Metal weapons before challenging Yagluth!")
    else:
        lines.append(f"🎖️ *Quartermaster:* Upgrade frontline armor before entering {next_biome}!")

    return "\n".join(lines)

# Canonical category item groups for broad & fallback search
CATEGORY_MAP = {
    'arrow': [
        'ArrowWood', 'ArrowFlint', 'ArrowFire', 'ArrowBronze', 'ArrowIron',
        'ArrowSilver', 'ArrowObsidian', 'ArrowPoison', 'ArrowFrost', 'ArrowNeedle',
        'ArrowCarapace', 'ArrowBone', 'ArrowCharred'
    ],
    'arrows': [
        'ArrowWood', 'ArrowFlint', 'ArrowFire', 'ArrowBronze', 'ArrowIron',
        'ArrowSilver', 'ArrowObsidian', 'ArrowPoison', 'ArrowFrost', 'ArrowNeedle',
        'ArrowCarapace', 'ArrowBone', 'ArrowCharred'
    ],
    'ammo': [
        'ArrowWood', 'ArrowFlint', 'ArrowFire', 'ArrowBronze', 'ArrowIron',
        'ArrowSilver', 'ArrowObsidian', 'ArrowPoison', 'ArrowFrost', 'ArrowNeedle',
        'ArrowCarapace', 'ArrowBone', 'ArrowCharred'
    ],
    'ammunition': [
        'ArrowWood', 'ArrowFlint', 'ArrowFire', 'ArrowBronze', 'ArrowIron',
        'ArrowSilver', 'ArrowObsidian', 'ArrowPoison', 'ArrowFrost', 'ArrowNeedle',
        'ArrowCarapace', 'ArrowBone', 'ArrowCharred'
    ],
    'mead': [
        'MeadHealthMinor', 'MeadHealthMedium', 'MeadStaminaMinor', 'MeadStaminaMedium',
        'MeadPoisonResist', 'MeadFrostResist', 'MeadTasty', 'BarleyWine'
    ],
    'meads': [
        'MeadHealthMinor', 'MeadHealthMedium', 'MeadStaminaMinor', 'MeadStaminaMedium',
        'MeadPoisonResist', 'MeadFrostResist', 'MeadTasty', 'BarleyWine'
    ],
    'potion': [
        'MeadHealthMinor', 'MeadHealthMedium', 'MeadStaminaMinor', 'MeadStaminaMedium',
        'MeadPoisonResist', 'MeadFrostResist', 'MeadTasty', 'BarleyWine'
    ],
    'potions': [
        'MeadHealthMinor', 'MeadHealthMedium', 'MeadStaminaMinor', 'MeadStaminaMedium',
        'MeadPoisonResist', 'MeadFrostResist', 'MeadTasty', 'BarleyWine'
    ],
    'metal': [
        'Copper', 'CopperOre', 'Tin', 'TinOre', 'Bronze', 'Iron', 'IronScrap',
        'Silver', 'SilverOre', 'BlackMetal', 'BlackMetalScrap', 'Flametal', 'FlametalOre'
    ],
    'metals': [
        'Copper', 'CopperOre', 'Tin', 'TinOre', 'Bronze', 'Iron', 'IronScrap',
        'Silver', 'SilverOre', 'BlackMetal', 'BlackMetalScrap', 'Flametal', 'FlametalOre'
    ],
    'ore': ['CopperOre', 'TinOre', 'SilverOre', 'BlackMetalScrap', 'FlametalOre'],
    'ores': ['CopperOre', 'TinOre', 'SilverOre', 'BlackMetalScrap', 'FlametalOre'],
    'bars': ['Copper', 'Tin', 'Bronze', 'Iron', 'Silver', 'BlackMetal', 'Flametal'],
    'bar': ['Copper', 'Tin', 'Bronze', 'Iron', 'Silver', 'BlackMetal', 'Flametal'],
    'wood': ['Wood', 'FineWood', 'RoundLog', 'YggdrasilWood'],
    'seed': ['CarrotSeeds', 'TurnipSeeds', 'OnionSeeds', 'AncientSeed'],
    'seeds': ['CarrotSeeds', 'TurnipSeeds', 'OnionSeeds', 'AncientSeed'],
    'mushroom': ['Mushroom', 'MushroomYellow', 'MushroomBlue', 'Magecap', 'StuffedMushroom'],
    'mushrooms': ['Mushroom', 'MushroomYellow', 'MushroomBlue', 'Magecap', 'StuffedMushroom'],
    'trophy': [
        'TrophyDeer', 'TrophyBoar', 'TrophyGreydwarf', 'TrophyGreydwarfBrute',
        'TrophyGreydwarfShaman', 'TrophySkeleton', 'TrophyTroll', 'TrophyEikthyr',
        'TrophyTheElder', 'TrophyBonemass', 'TrophyDrake', 'TrophyDragonQueen',
        'TrophyGoblinKing', 'TrophyTheQueen', 'TrophySerpent'
    ],
    'trophies': [
        'TrophyDeer', 'TrophyBoar', 'TrophyGreydwarf', 'TrophyGreydwarfBrute',
        'TrophyGreydwarfShaman', 'TrophySkeleton', 'TrophyTroll', 'TrophyEikthyr',
        'TrophyTheElder', 'TrophyBonemass', 'TrophyDrake', 'TrophyDragonQueen',
        'TrophyGoblinKing', 'TrophyTheQueen', 'TrophySerpent'
    ],
    'gems': ['Coins', 'Amber', 'AmberPearl', 'Ruby', 'SilverNecklace'],
    'gem': ['Coins', 'Amber', 'AmberPearl', 'Ruby', 'SilverNecklace'],
    'treasure': ['Coins', 'Amber', 'AmberPearl', 'Ruby', 'SilverNecklace'],
}

# Key craftable item recipe associations for misses/alternatives
CRAFTING_RECIPES = {
    'obsidian arrow': {'Obsidian': 4, 'Feathers': 2, 'Wood': 8},
    'obsidian arrows': {'Obsidian': 4, 'Feathers': 2, 'Wood': 8},
    'frost arrow': {'Obsidian': 4, 'FreezeGland': 1, 'Feathers': 2, 'Wood': 8},
    'frost arrows': {'Obsidian': 4, 'FreezeGland': 1, 'Feathers': 2, 'Wood': 8},
    'poison arrow': {'Obsidian': 4, 'Ooze': 2, 'Feathers': 2, 'Wood': 8},
    'poison arrows': {'Obsidian': 4, 'Ooze': 2, 'Feathers': 2, 'Wood': 8},
    'needle arrow': {'Needle': 4, 'Feathers': 2},
    'needle arrows': {'Needle': 4, 'Feathers': 2},
    'fire arrow': {'Wood': 8, 'Resin': 8, 'Feathers': 2},
    'fire arrows': {'Wood': 8, 'Resin': 8, 'Feathers': 2},
    'iron arrow': {'Iron': 1, 'Wood': 8, 'Feathers': 2},
    'iron arrows': {'Iron': 1, 'Wood': 8, 'Feathers': 2},
    'silver arrow': {'Silver': 1, 'Wood': 8, 'Feathers': 2},
    'silver arrows': {'Silver': 1, 'Wood': 8, 'Feathers': 2},
    'flint arrow': {'Flint': 2, 'Wood': 8, 'Feathers': 2},
    'flint arrows': {'Flint': 2, 'Wood': 8, 'Feathers': 2},
    'wood arrow': {'Wood': 8},
    'wood arrows': {'Wood': 8},
    'bone arrow': {'BoneFragments': 3, 'Wood': 8, 'Feathers': 2},
    'bone arrows': {'BoneFragments': 3, 'Wood': 8, 'Feathers': 2},
    'carapace arrow': {'Carapace': 4, 'Feathers': 2},
    'carapace arrows': {'Carapace': 4, 'Feathers': 2},
    'wolf armor': {'Silver': 20, 'WolfPelt': 5, 'WolfFang': 4, 'Chain': 1},
    'frost mead': {'Honey': 10, 'Thistle': 5, 'Bloodbag': 2, 'GreydwarfEye': 1},
    'poison mead': {'Honey': 10, 'Thistle': 5, 'NeckTail': 1, 'Coal': 10},
    'healing mead': {'Honey': 10, 'Blueberries': 10, 'Raspberry': 10, 'Dandelion': 1},
    'stamina mead': {'Honey': 10, 'Raspberry': 10, 'MushroomYellow': 10},
}

COMMON_SEARCH_ALIASES = {
    'arow': 'arrow', 'arows': 'arrows', 'arroww': 'arrow', 'arrowws': 'arrows',
    'obsidien': 'obsidian', 'obsidion': 'obsidian', 'obsid': 'obsidian',
    'cooper': 'copper', 'copr': 'copper',
    'broze': 'bronze', 'bronz': 'bronze',
    'irn': 'iron', 'ironn': 'iron',
    'silvr': 'silver', 'silve': 'silver',
    'wod': 'wood', 'wodd': 'wood',
    'stne': 'stone', 'ston': 'stone',
    'posion': 'poison', 'poisen': 'poison',
    'fether': 'feather', 'fethers': 'feathers',
    'surting': 'surtling', 'surtin': 'surtling',
    'serptent': 'serpent', 'serpant': 'serpent',
    'dargon': 'dragon',
    'shroom': 'mushroom', 'shrooms': 'mushrooms',
    'pot': 'mead', 'pots': 'mead', 'potion': 'mead', 'potions': 'mead',
    'resit': 'resist', 'resitance': 'resistance',
    'needle': 'needle', 'nedle': 'needle',
    'wolf': 'wolf', 'wlfe': 'wolf',
    'flnt': 'flint',
    'barli': 'barley',
    'onon': 'onion',
}

def normalize_search_query(search_term):
    clean_str = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(search_term).lower()).strip()
    raw_tokens = [t for t in clean_str.split() if t]
    if not raw_tokens:
        return '', []
    
    vocab = set(COMMON_SEARCH_ALIASES.keys()) | set(COMMON_SEARCH_ALIASES.values()) | set(CATEGORY_MAP.keys())
    for k, val in ITEM_CATALOG.items():
        vocab.add(k.lower())
        for w in re.findall(r'[a-zA-Z]+', val[0].lower()):
            if len(w) >= 3:
                vocab.add(w)
                
    corrected_tokens = []
    for t in raw_tokens:
        if t in COMMON_SEARCH_ALIASES:
            corrected_tokens.append(COMMON_SEARCH_ALIASES[t])
        elif t in vocab:
            corrected_tokens.append(t)
        else:
            matches = difflib.get_close_matches(t, list(vocab), n=1, cutoff=0.72)
            if matches:
                matched_word = matches[0]
                corrected_tokens.append(COMMON_SEARCH_ALIASES.get(matched_word, matched_word))
            else:
                corrected_tokens.append(t)
                
    return ' '.join(corrected_tokens), corrected_tokens

def get_find_report(search_term):
    """
    Intelligent fuzzy & category-fallback clan storage search engine.
    Handles spelling mistakes, typo correction, and returns category alternatives
    (e.g., all arrows in storage if obsidian arrows are missing).
    """
    if not search_term or not isinstance(search_term, str):
        return "⚠️ *[Valheim Search]* Please provide an item to find (e.g. `!find arrows` or `!find obsidian`)."

    search_clean = search_term.strip()
    if len(search_clean) < 2:
        return "⚠️ *[Valheim Search]* Search query too short. Please provide at least 2 characters."

    totals, container_count = scan_world_inventory()
    norm_str, tokens = normalize_search_query(search_clean)

    # 1. Direct exact & token-subset match on in-stock items
    direct_results = {}
    for k, count in totals.items():
        name = ITEM_CATALOG.get(k, (k,))[0]
        name_clean = re.sub(r'^[^\w\s]+\s*', '', name)
        k_lower = k.lower()
        name_lower = name_clean.lower()
        if (norm_str in k_lower or norm_str in name_lower or
            (len(tokens) > 1 and all(t in name_lower or t in k_lower for t in tokens))):
            direct_results[name] = count

    # 2. Fuzzy match on in-stock items if direct matching is empty and query is single token
    if not direct_results and len(tokens) == 1:
        for k, count in totals.items():
            name = ITEM_CATALOG.get(k, (k,))[0]
            name_clean = re.sub(r'^[^\w\s]+\s*', '', name)
            ratio = difflib.SequenceMatcher(None, norm_str, name_clean.lower()).ratio()
            if ratio >= 0.72:
                direct_results[name] = count

    match_note = f" _(matched '{norm_str}')_" if norm_str and norm_str != search_clean.lower() else ""

    if direct_results:
        lines = [f"🔍 *Clan Storage Search:* '{search_clean}'{match_note}"]
        for name, count in sorted(direct_results.items(), key=lambda x: -x[1]):
            lines.append(f"• {name}: {count:,}")
        lines.append(f"\n_Scanned {container_count} chests._")
        return "\n".join(lines)

    # 3. Fallback / Category matching (e.g. 'obsidian arrows' missed -> share all arrows & obsidian materials)
    cat_items = {}
    detected_cat = None
    for t in tokens:
        if t in CATEGORY_MAP:
            detected_cat = t
            for ck in CATEGORY_MAP[t]:
                if ck in totals:
                    cname = ITEM_CATALOG.get(ck, (ck,))[0]
                    cat_items[cname] = totals[ck]

    # Check for recipe crafting materials in stock
    matched_recipe_mats = {}
    for r_key, r_mats in CRAFTING_RECIPES.items():
        r_tokens = r_key.split()
        if all(rt in tokens or difflib.get_close_matches(rt, tokens, cutoff=0.8) for rt in r_tokens):
            for mat_k, req in r_mats.items():
                if mat_k in totals:
                    mname = ITEM_CATALOG.get(mat_k, (mat_k,))[0]
                    matched_recipe_mats[mname] = totals[mat_k]

    if cat_items or matched_recipe_mats:
        target_name = norm_str.title() if norm_str else search_clean.title()
        lines = [f"🔍 *Clan Storage Search:* '{search_clean}'{match_note}"]
        lines.append(f"⚠️ _No '{target_name}' found in chests._\n")

        if cat_items:
            cat_label = "Arrows" if "arrow" in (detected_cat or "") else (detected_cat.title() if detected_cat else "Related Items")
            lines.append(f"🏹 *Available {cat_label} in Clan Storage:*")
            for name, count in sorted(cat_items.items(), key=lambda x: -x[1]):
                lines.append(f"• {name}: {count:,}")
            lines.append("")

        if matched_recipe_mats:
            lines.append(f"⛏️ *Crafting Materials in Stock for {target_name}:*")
            for name, count in sorted(matched_recipe_mats.items(), key=lambda x: -x[1]):
                lines.append(f"• {name}: {count:,}")
            lines.append("")

        lines.append(f"_Scanned {container_count} chests._")
        return "\n".join(lines)

    return (
        f"🔍 No items matching '{search_clean}' found in clan storage (scanned {container_count} chests).\n"
        f"💡 _Tip: Try searching for a resource or category (e.g. `!find arrows`, `!find obsidian`, `!find mead`, `!find iron`)._"
    )

