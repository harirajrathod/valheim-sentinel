"""
telemetry/world_state.py - Era, Day/Night Cycle, and Boss Roadmap Progression
"""

import os
import glob
import re
import zlib
import json
from typing import Dict, Any, Tuple, List, Optional
from datetime import datetime

from core import config

BOSS_PROGRESSION = [
    ('defeated_eikthyr', 'Eikthyr ⚡', 'Meadows', 'Hard Antlers / Pickaxe', 'The Meadows Awakening'),
    ('defeated_gdking', 'The Elder 🌲', 'Black Forest', 'Swamp Key', 'The Bronze Age'),
    ('defeated_bonemass', 'Bonemass ☣️', 'Swamps', 'Wishbone', 'The Swamp Era (The Iron Age)'),
    ('defeated_dragon', 'Moder ❄️', 'Mountains', 'Artisan Table Tear', 'The Mountain Age (The Silver Era)'),
    ('defeated_goblinking', 'Yagluth ⚔️', 'Plains', 'Torn Spirit', 'The Plains Conquest (The Black Metal Era)'),
    ('defeated_queen', 'The Queen 🪲', 'Mistlands', 'Majestic Carapace', 'The Mistlands Epoch (The Eitr Era)'),
    ('defeated_fader', 'Fader 🔥', 'Ashlands', 'Lord of Cinder', 'The Ashlands Crusade (The Flametal Era)')
]

def get_current_day() -> int:
    """Extracts in-game day from server log."""
    day = 1
    if not os.path.exists(config.VALHEIM_LOG_FILE):
        return day
    try:
        with open(config.VALHEIM_LOG_FILE, 'r', errors='ignore') as f:
            for line in reversed(f.readlines()[-2000:]):
                m = re.search(r'Time\s+[\d\.]+,\s*day:(\d+)\s+nextm:[\d\.]+', line)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return day

def get_defeated_bosses() -> List[str]:
    """Inspects world .db2 state for defeated boss global keys."""
    defeated = []
    world_dir = os.path.join(config.VALHEIM_WORLDS_DIR, config.VALHEIM_WORLD_NAME)
    db_files = glob.glob(os.path.join(world_dir, '_main.*.db2'))
    if not db_files:
        return defeated

    def extract_id(p: str) -> int:
        m = re.search(r'_main\.(\d+)\.db2$', p)
        return int(m.group(1)) if m else 0

    latest_db = max(db_files, key=extract_id)
    try:
        with open(latest_db, 'rb') as f:
            data = f.read()
        idx = data.find(b'\x1f\x8b\x08')
        if idx != -1:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decomp = d.decompress(data[idx:])
            for b_key, name, _, _, _ in BOSS_PROGRESSION:
                if b_key.encode() in decomp:
                    defeated.append(b_key)
    except Exception:
        pass
    return defeated

def get_world_progress() -> Dict[str, Any]:
    """Computes active epoch, next boss target, and defeated conquer list."""
    day = get_current_day()
    defeated = get_defeated_bosses()

    next_boss = None
    next_biome = "Deep North"
    active_era = "The Deep North Frontier"
    target_unlock = "Unknown"

    for b_key, name, biome, unlock, era in BOSS_PROGRESSION:
        if b_key not in defeated:
            next_boss = name
            next_biome = biome
            target_unlock = unlock
            active_era = era
            break

    return {
        "in_game_day": day,
        "active_era": active_era,
        "next_boss": next_boss or "All Forsaken Vanquished! 🏆",
        "target_biome": next_biome,
        "key_unlock": target_unlock,
        "defeated_bosses_count": len(defeated),
        "conquered": [name for b_key, name, _, _, _ in BOSS_PROGRESSION if b_key in defeated]
    }
