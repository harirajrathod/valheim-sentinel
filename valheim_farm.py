#!/usr/bin/env python3
"""
/root/valheim_farm.py - Valheim Homestead Farming, Seed Cycle Tracker & Apiary Engine

Features:
- Scans active world chunks for planted crops, seed plants, and beehives
- Tracks seed cycles (growing -> ripe) and detects cycle completion
- Emits celebratory, friendly WhatsApp announcements when crops are ready for harvest
- Integrates with valheim_info.py for !farm, !farming, !harvest commands
- Atomic persistence with /root/valheim_farm_state.json and cooldown guards
"""

import os
import sys
import time
import glob
import re
import struct
import ctypes
import argparse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, List, Optional

sys.path.insert(0, "/root")
from valheim_utils import (
    LOG_FILE,
    VALHEIM_WHATSAPP_GROUP,
    IST,
    safe_load_json,
    atomic_save_json,
    safe_send_whatsapp,
    get_stable_hash,
    get_active_chunk_files,
)

STATE_FILE = "/root/valheim_farm_state.json"
ANNOUNCEMENT_COOLDOWN_SEC = 2700  # 45-minute cooldown between automated announcements
MIN_HARVEST_THRESHOLD = 15       # Minimum ready crops to warrant a cycle announcement

# Supported Crops & Agricultural Prefabs across all game biomes
FARM_PREFABS = {
    # Seed Plants (Ready to harvest for 3x seeds)
    'Pickable_SeedCarrot': ('seed_carrots', 'Seed Carrots', 'seed', 3, '🥕'),
    'Pickable_SeedTurnip': ('seed_turnips', 'Seed Turnips', 'seed', 3, '🌿'),
    'Pickable_SeedOnion':  ('seed_onions',  'Seed Onions',  'seed', 3, '🧅'),
    
    # Ripe Vegetables / Grains (Ready to pick)
    'Pickable_Carrot':     ('ready_carrots', 'Carrots',      'crop', 1, '🥕'),
    'Pickable_Turnip':     ('ready_turnips', 'Turnips',      'crop', 1, '🌿'),
    'Pickable_Onion':      ('ready_onions',  'Onions',       'crop', 1, '🧅'),
    'Pickable_Barley':     ('ready_barley',  'Barley',       'crop', 1, '🌾'),
    'Pickable_Flax':       ('ready_flax',    'Flax',         'crop', 1, '🧵'),
    'Pickable_Magecap':    ('ready_magecap', 'Magecaps',     'crop', 1, '🍄'),
    'Pickable_JotunPuffs': ('ready_puffs',   'Jötun Puffs',  'crop', 1, '🪨'),

    # Currently Growing Plants (Cultivated and maturing)
    'Carrot':              ('growing_carrots', 'Carrot Plants',   'growing', 0, '🌱'),
    'Turnip':              ('growing_turnips', 'Turnip Plants',   'growing', 0, '🌱'),
    'Onion':               ('growing_onions',  'Onion Plants',    'growing', 0, '🌱'),
    'Barley':              ('growing_barley',  'Barley Plants',   'growing', 0, '🌱'),
    'Flax':                ('growing_flax',    'Flax Plants',     'growing', 0, '🌱'),
    'Magecap':             ('growing_magecap', 'Magecap Plants',  'growing', 0, '🌱'),
    'JotunPuffs':          ('growing_puffs',   'Jötun Puff Plants','growing', 0, '🌱'),

    # Apiary
    'piece_beehive':       ('beehives',        'Beehives',        'hive',    0, '🐝'),
}

HASH_TO_PREFAB = {struct.pack('<i', get_stable_hash(k)): k for k in FARM_PREFABS}

def get_active_chunk_files() -> List[str]:
    """Returns list of active, deduplicated world chunk files."""
    raw_chunks = glob.glob('/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/*.chunk')
    chunks_by_prefix = {}
    for c in raw_chunks:
        m = re.match(r'^(.*__\d+)_(\d+)\.chunk$', c)
        if m:
            prefix, ver = m.group(1), int(m.group(2))
            if prefix not in chunks_by_prefix or ver > chunks_by_prefix[prefix][0]:
                chunks_by_prefix[prefix] = (ver, c)
        else:
            chunks_by_prefix[c] = (0, c)
    return [c for _, c in chunks_by_prefix.values()]

def scan_farm_world() -> Dict[str, Any]:
    """
    Scans active world chunks for all placed agricultural entities.
    Returns categorized counts of ready crops, seed plants, growing plants, and beehives.
    """
    chunks = get_active_chunk_files()
    raw_counts = {k: 0 for k in FARM_PREFABS}
    
    for c in chunks:
        try:
            with open(c, 'rb') as f:
                data = f.read()
            for p_bytes, prefab_name in HASH_TO_PREFAB.items():
                idx = 0
                while True:
                    idx = data.find(p_bytes, idx)
                    if idx == -1:
                        break
                    if idx >= 12:
                        x, y, z = struct.unpack('<fff', data[idx-12:idx])
                        # Filter valid placed coordinates within world boundaries (excluding origin 0,0,0)
                        if (-10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500
                            and not (abs(x) < 0.1 and abs(y) < 0.1 and abs(z) < 0.1)):
                            raw_counts[prefab_name] += 1
                    idx += 4
        except Exception:
            pass

    # Aggregate into high-level categories
    ready_seeds = {
        'seed_carrots': raw_counts.get('Pickable_SeedCarrot', 0),
        'seed_turnips': raw_counts.get('Pickable_SeedTurnip', 0),
        'seed_onions':  raw_counts.get('Pickable_SeedOnion', 0),
    }
    ready_crops = {
        'carrots':     raw_counts.get('Pickable_Carrot', 0),
        'turnips':     raw_counts.get('Pickable_Turnip', 0),
        'onions':      raw_counts.get('Pickable_Onion', 0),
        'barley':      raw_counts.get('Pickable_Barley', 0),
        'flax':        raw_counts.get('Pickable_Flax', 0),
        'magecap':     raw_counts.get('Pickable_Magecap', 0),
        'jotun_puffs': raw_counts.get('Pickable_JotunPuffs', 0),
    }
    growing = {
        'carrots':     raw_counts.get('Carrot', 0),
        'turnips':     raw_counts.get('Turnip', 0),
        'onions':      raw_counts.get('Onion', 0),
        'barley':      raw_counts.get('Barley', 0),
        'flax':        raw_counts.get('Flax', 0),
        'magecap':     raw_counts.get('Magecap', 0),
        'jotun_puffs': raw_counts.get('JotunPuffs', 0),
    }
    beehives = raw_counts.get('piece_beehive', 0)

    total_ready_seeds = sum(ready_seeds.values())
    total_ready_crops = sum(ready_crops.values())
    total_ready = total_ready_seeds + total_ready_crops
    total_growing = sum(growing.values())

    return {
        'raw_counts': raw_counts,
        'ready_seeds': ready_seeds,
        'ready_crops': ready_crops,
        'growing': growing,
        'beehives': beehives,
        'total_ready_seeds': total_ready_seeds,
        'total_ready_crops': total_ready_crops,
        'total_ready': total_ready,
        'total_growing': total_growing,
        'timestamp': time.time()
    }

def get_clan_pantry_stocks() -> Dict[str, int]:
    """Retrieves chest pantry stocks using valheim_info.scan_world_inventory."""
    try:
        from valheim_info import scan_world_inventory
        totals, _ = scan_world_inventory()
        return totals
    except Exception:
        return {}

def format_farm_report() -> str:
    """Formats a comprehensive, friendly status report for the WhatsApp !farm command."""
    farm = scan_farm_world()
    pantry = get_clan_pantry_stocks()

    lines = [
        "🌾 *VALHEIM HOMESTEAD & FARM REPORT* 🌾",
        ""
    ]

    # 1. In the ground: Seed Plants
    if farm['total_ready_seeds'] > 0:
        lines.append("🌱 *Seed Plants Ready for Harvest (3x Yield):*")
        rs = farm['ready_seeds']
        if rs['seed_carrots'] > 0:
            lines.append(f"• 🥕 *Seed Carrots:* {rs['seed_carrots']:,} plants (~{rs['seed_carrots']*3:,} seeds)")
        if rs['seed_turnips'] > 0:
            lines.append(f"• 🌿 *Seed Turnips:* {rs['seed_turnips']:,} plants (~{rs['seed_turnips']*3:,} seeds)")
        if rs['seed_onions'] > 0:
            lines.append(f"• 🧅 *Seed Onions:* {rs['seed_onions']:,} plants (~{rs['seed_onions']*3:,} seeds)")
        lines.append("")

    # 2. In the ground: Mature Vegetables & Grains
    if farm['total_ready_crops'] > 0:
        lines.append("🧺 *Ripe Vegetables & Crops in the Ground:*")
        rc = farm['ready_crops']
        if rc['onions'] > 0:
            lines.append(f"• 🧅 *Onions:* {rc['onions']:,} ripe")
        if rc['carrots'] > 0:
            lines.append(f"• 🥕 *Carrots:* {rc['carrots']:,} ripe")
        if rc['turnips'] > 0:
            lines.append(f"• 🌿 *Turnips:* {rc['turnips']:,} ripe")
        if rc['barley'] > 0:
            lines.append(f"• 🌾 *Barley:* {rc['barley']:,} ripe")
        if rc['flax'] > 0:
            lines.append(f"• 🧵 *Flax:* {rc['flax']:,} ripe")
        lines.append("")

    # 3. Growing Crops (if any)
    if farm['total_growing'] > 0:
        lines.append("⏳ *Currently Growing in Fields:*")
        gw = farm['growing']
        for k, v in gw.items():
            if v > 0:
                lines.append(f"• 🌱 *{k.title()}:* {v:,} planted (maturing...)")
        lines.append("")

    if farm['total_ready'] == 0 and farm['total_growing'] == 0:
        lines.append("🍂 _The fields are currently resting. Till the soil with the Cultivator and sow new seeds!_")
        lines.append("")

    # 4. Apiary
    lines.append("🍯 *Homestead Apiary:*")
    lines.append(f"• 🐝 *{farm['beehives']} Active Beehives* buzzing with golden honey")
    lines.append("")

    # 5. Clan Storage (Chests)
    lines.append("📦 *Clan Pantry Stock (In Chests):*")
    c_car = pantry.get('Carrot', 0)
    c_car_s = pantry.get('CarrotSeeds', 0)
    c_tur = pantry.get('Turnip', 0)
    c_tur_s = pantry.get('TurnipSeeds', 0)
    c_oni = pantry.get('Onion', 0)
    c_oni_s = pantry.get('OnionSeeds', 0)
    c_hon = pantry.get('Honey', 0)
    c_blu = pantry.get('Blueberries', 0)
    c_ras = pantry.get('Raspberry', 0)

    lines.append(f"• 🥕 *Carrots:* {c_car:,} | *Seeds:* {c_car_s:,}")
    lines.append(f"• 🌿 *Turnips:* {c_tur:,} | *Seeds:* {c_tur_s:,}")
    lines.append(f"• 🧅 *Onions:* {c_oni:,} | *Seeds:* {c_oni_s:,}")
    lines.append(f"• 🍯 *Honey:* {c_hon:,} jars")
    lines.append(f"• 🫐 *Berries:* {c_blu:,} Blueberries | {c_ras:,} Raspberries")
    lines.append("")

    # Summary
    if farm['total_ready'] > 0:
        lines.append(f"✨ *Field Status:* Ripe & Abundant ({farm['total_ready']:,} total crops ready for harvest)!")
    else:
        lines.append("✨ *Field Status:* Freshly gathered / Awaiting next planting.")

    return "\n".join(lines)

def format_cycle_complete_announcement(farm: Dict[str, Any]) -> str:
    """Formats the celebratory WhatsApp announcement when a seed cycle finishes."""
    lines = [
        "🌾✨ *[HOMESTEAD HARVEST] SEED CYCLE COMPLETE!* ✨🌾",
        "",
        "Hail, Clan! The crops at the homestead farm have finished their growth cycle and are fully ripe for gathering!",
        ""
    ]

    lines.append("🌱 *Harvest Bounty in the Fields:*")
    rs = farm['ready_seeds']
    if rs['seed_carrots'] > 0:
        lines.append(f"• 🥕 *Seed Carrots:* {rs['seed_carrots']:,} plants (~{rs['seed_carrots']*3:,} seeds yield)")
    if rs['seed_turnips'] > 0:
        lines.append(f"• 🌿 *Seed Turnips:* {rs['seed_turnips']:,} plants (~{rs['seed_turnips']*3:,} seeds yield)")
    if rs['seed_onions'] > 0:
        lines.append(f"• 🧅 *Seed Onions:* {rs['seed_onions']:,} plants (~{rs['seed_onions']*3:,} seeds yield)")

    rc = farm['ready_crops']
    if rc['onions'] > 0:
        lines.append(f"• 🧅 *Onions:* {rc['onions']:,} vegetables")
    if rc['carrots'] > 0:
        lines.append(f"• 🥕 *Carrots:* {rc['carrots']:,} vegetables")
    if rc['turnips'] > 0:
        lines.append(f"• 🌿 *Turnips:* {rc['turnips']:,} vegetables")
    if rc['barley'] > 0:
        lines.append(f"• 🌾 *Barley:* {rc['barley']:,} bundles")

    lines.append(f"• 🌾 *Total Ready:* {farm['total_ready']:,} crops")
    lines.append(f"• 🐝 *Apiary:* {farm['beehives']} active beehives producing sweet honey")
    lines.append("")
    lines.append("Grab your Cultivator, bring in the golden harvest, and re-sow the fields! 🧺🥕🧅 Skål! 🍻")

    return "\n".join(lines)

def check_and_announce_seed_cycle(force: bool = False, dry_run: bool = False) -> bool:
    """
    Checks if a seed cycle has completed and sends the WhatsApp announcement if appropriate.
    Returns True if an announcement was sent.
    """
    farm = scan_farm_world()
    state = safe_load_json(STATE_FILE, default=None)
    now_t = time.time()

    if state is None:
        # First-time initialization: save baseline state without spamming
        init_state = {
            'last_total_ready': farm['total_ready'],
            'last_total_growing': farm['total_growing'],
            'last_announced_ready': farm['total_ready'],
            'last_announcement_time': 0,
            'last_updated': now_t
        }
        if not dry_run:
            atomic_save_json(STATE_FILE, init_state)
        print(f"[valheim_farm] Initialized farm baseline state ({farm['total_ready']} ready, {farm['total_growing']} growing)")
        if not force:
            return False

    last_announced_time = state.get('last_announcement_time', 0) if state else 0
    last_announced_ready = state.get('last_announced_ready', 0) if state else 0
    last_growing = state.get('last_total_growing', 0) if state else 0
    time_since_announcement = now_t - last_announced_time

    # Trigger conditions:
    # 1. Force flag passed
    # 2. Previous batch was growing and now matured to ready
    # 3. Ready count jumped by >= 20 crops and cooldown expired
    matured_transition = (last_growing > 0 and farm['total_growing'] == 0 and farm['total_ready'] >= MIN_HARVEST_THRESHOLD)
    count_jump = (farm['total_ready'] - last_announced_ready >= 20)
    cooldown_ok = (time_since_announcement >= ANNOUNCEMENT_COOLDOWN_SEC)

    should_announce = force or (matured_transition and cooldown_ok) or (count_jump and cooldown_ok)

    # Save updated monitoring state
    new_state = {
        'last_total_ready': farm['total_ready'],
        'last_total_growing': farm['total_growing'],
        'last_announced_ready': farm['total_ready'] if should_announce else last_announced_ready,
        'last_announcement_time': now_t if should_announce else last_announced_time,
        'last_updated': now_t
    }

    if should_announce and farm['total_ready'] >= MIN_HARVEST_THRESHOLD:
        msg = format_cycle_complete_announcement(farm)
        print(f"[valheim_farm] Seed cycle complete detected ({farm['total_ready']} ready)! Sending announcement...")
        if not dry_run:
            atomic_save_json(STATE_FILE, new_state)
            safe_send_whatsapp(msg)
        else:
            print("[DRY-RUN] Would announce:")
            print(msg)
        return True
    else:
        if not dry_run:
            atomic_save_json(STATE_FILE, new_state)
        return False

def main():
    parser = argparse.ArgumentParser(description="Valheim Farm & Seed Cycle Tracker")
    parser.add_argument("--report", action="store_true", help="Print farm status report for WhatsApp")
    parser.add_argument("--check", action="store_true", help="Check for seed cycle completion")
    parser.add_argument("--force-announce", action="store_true", help="Force send harvest announcement")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without network calls or state mutations")
    args = parser.parse_args()

    if args.report:
        print(format_farm_report())
    elif args.force_announce:
        check_and_announce_seed_cycle(force=True, dry_run=args.dry_run)
    elif args.check:
        check_and_announce_seed_cycle(force=False, dry_run=args.dry_run)
    else:
        print(format_farm_report())

if __name__ == "__main__":
    main()
