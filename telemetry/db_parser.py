"""
telemetry/db_parser.py - Binary Valheim World Save (.db / .db2 / .chunk) Parser
Reverse-engineers Unity/ZDO world storage to extract stockpiles, metals, food, and portals.
"""

import os
import sys
import glob
import struct
import ctypes
import re
from typing import Dict, List, Tuple, Any, Optional

from core import config

_warned_versions = set()

def get_stable_hash(s: str) -> int:
    """Calculates Valheim's internal stable hash for strings."""
    h1 = ctypes.c_int32(5381).value
    h2 = ctypes.c_int32(5381).value
    for i in range(0, len(s), 2):
        h1 = ctypes.c_int32(((h1 << 5) + h1) ^ ord(s[i])).value
        if i + 1 < len(s):
            h2 = ctypes.c_int32(((h2 << 5) + h2) ^ ord(s[i+1])).value
    return ctypes.c_int32(h1 + ctypes.c_int32(h2 * 1566083941).value).value

ITEM_CATALOG = {
    # Coins & Treasures
    'Coins': ('🪙 Coins (Gold)', 1, 'coin'),
    'Amber': ('💎 Amber', 5, 'gem'),
    'AmberPearl': ('🦪 Amber Pearls', 10, 'gem'),
    'Ruby': ('💎 Rubies', 20, 'gem'),
    'SilverNecklace': ('👑 Silver Necklaces', 30, 'gem'),

    # Metals & Metallurgy
    'Copper': ('Copper Bars', 0, 'metal'),
    'CopperOre': ('Copper Ore', 0, 'metal'),
    'Tin': ('Tin Bars', 0, 'metal'),
    'TinOre': ('Tin Ore', 0, 'metal'),
    'Bronze': ('Bronze Bars', 0, 'metal'),
    'BronzeNails': ('Bronze Nails', 0, 'metal'),
    'Iron': ('Iron Bars', 0, 'metal'),
    'IronOre': ('Bog Iron Ore', 0, 'metal'),
    'IronScrap': ('Scrap Iron', 0, 'metal'),
    'IronNails': ('Iron Nails', 0, 'metal'),
    'Silver': ('Silver Bars', 0, 'metal'),
    'SilverOre': ('Silver Ore', 0, 'metal'),
    'BlackMetal': ('Black Metal', 0, 'metal'),
    'BlackMetalScrap': ('Black Metal Scrap', 0, 'metal'),
    'Flametal': ('Flametal Bars', 0, 'metal'),
    'FlametalOre': ('Flametal Ore', 0, 'metal'),
    'Obsidian': ('Obsidian', 0, 'metal'),
    'SurtlingCore': ('Surtling Cores', 0, 'metal'),
    'Coal': ('Coal', 0, 'fuel'),

    # Ready / Cooked Foods
    'CookedDeerMeat': ('Cooked Deer Meat', 0, 'food'),
    'CookedMeat': ('Cooked Boar Meat', 0, 'food'),
    'GrilledNeckTail': ('Grilled Neck Tail', 0, 'food'),
    'CookedFish': ('Cooked Fish', 0, 'food'),
    'CookedWolfMeat': ('Cooked Wolf Meat', 0, 'food'),
    'CookedLoxMeat': ('Cooked Lox Meat', 0, 'food'),
    'CookedSerpentMeat': ('Cooked Serpent Meat', 0, 'food'),
    'CookedHareMeat': ('Cooked Hare Meat', 0, 'food'),
    'CookedSeekerMeat': ('Cooked Seeker Meat', 0, 'food'),
    'ChickenMeatCooked': ('Cooked Chicken Meat', 0, 'food'),
    'QueensJam': ("Queen's Jam", 0, 'food'),
    'DeerStew': ('Deer Stew', 0, 'food'),
    'CarrotSoup': ('Carrot Soup', 0, 'food'),
    'MincedMeatSauce': ('Minced Meat Sauce', 0, 'food'),
    'BoarJerky': ('Boar Jerky', 0, 'food'),
    'DeerJerky': ('Deer Jerky', 0, 'food'),
    'WolfJerky': ('Wolf Jerky', 0, 'food'),
    'Sausages': ('Sausages', 0, 'food'),
    'TurnipStew': ('Turnip Stew', 0, 'food'),
    'BlackSoup': ('Black Soup', 0, 'food'),
    'Muckshake': ('Muckshake', 0, 'food'),
    'OnionSoup': ('Onion Soup', 0, 'food'),
    'WolfSkewers': ('Wolf Skewer', 0, 'food'),
    'Eyescream': ('Eyescream', 0, 'food'),
    'SerpentStew': ('Serpent Stew', 0, 'food'),
    'Bread': ('Bread', 0, 'food'),
    'FishWraps': ('Fish Wraps', 0, 'food'),
    'LoxPie': ('Lox Meat Pie', 0, 'food'),
    'BloodPudding': ('Blood Pudding', 0, 'food'),
    'Salad': ('Salad', 0, 'food'),
    'MeatPlatter': ('Meat Platter', 0, 'food'),
    'MisthareSupreme': ('Misthare Supreme', 0, 'food'),
    'HoneyGlazedChicken': ('Honey Glazed Chicken', 0, 'food'),
    'MushroomOmelette': ('Mushroom Omelette', 0, 'food'),
    'FishAndBread': ('Fish and Bread', 0, 'food'),
    'YggdrasilPorridge': ('Yggdrasil Porridge', 0, 'food'),
    'SeekerAspic': ('Seeker Aspic', 0, 'food'),
    'StuffedMushroom': ('Stuffed Mushroom', 0, 'food'),
    'PiquantPie': ('Piquant Pie', 0, 'food'),
    'RoastedCrust': ('Roasted Crust', 0, 'food'),
    'MashedMeat': ('Mashed Meat', 0, 'food'),

    # Foraged / Raw Food Ingredients
    'Honey': ('Honey', 0, 'food'),
    'Mushroom': ('Red Mushrooms', 0, 'food'),
    'MushroomYellow': ('Yellow Mushrooms', 0, 'food'),
    'MushroomBlue': ('Blue Mushrooms', 0, 'food'),
    'Magecap': ('Magecap Mushrooms', 0, 'food'),
    'JotunPuffs': ('Jotun Puffs', 0, 'food'),
    'Raspberry': ('Raspberries', 0, 'food'),
    'Blueberries': ('Blueberries', 0, 'food'),
    'Cloudberry': ('Cloudberries', 0, 'food'),
    'Dandelion': ('Dandelions', 0, 'food'),
    'Thistle': ('Thistle', 0, 'food'),
    'Carrot': ('Carrots', 0, 'food'),
    'CarrotSeeds': ('Carrot Seeds', 0, 'food'),
    'Turnip': ('Turnips', 0, 'food'),
    'TurnipSeeds': ('Turnip Seeds', 0, 'food'),
    'Onion': ('Onions', 0, 'food'),
    'OnionSeeds': ('Onion Seeds', 0, 'food'),
    'Barley': ('Barley', 0, 'food'),
    'BarleyFlour': ('Barley Flour', 0, 'food'),
    'RawMeat': ('Raw Boar Meat', 0, 'food'),
    'BoarMeat': ('Raw Boar Meat', 0, 'food'),
    'DeerMeat': ('Raw Deer Meat', 0, 'food'),
    'NeckTail': ('Neck Tails', 0, 'food'),
    'FishRaw': ('Raw Fish', 0, 'food'),
    'WolfMeat': ('Raw Wolf Meat', 0, 'food'),
    'LoxMeat': ('Raw Lox Meat', 0, 'food'),
    'SerpentMeat': ('Raw Serpent Meat', 0, 'food'),
    'HareMeat': ('Raw Hare Meat', 0, 'food'),
    'SeekerMeat': ('Raw Seeker Meat', 0, 'food'),
    'ChickenMeat': ('Raw Chicken Meat', 0, 'food'),
    'Egg': ('Eggs', 0, 'food'),
    'Entrails': ('Entrails', 0, 'food'),
    'RoyalJelly': ('Royal Jelly', 0, 'food'),
    'Sap': ('Yggdrasil Sap', 0, 'food'),

    # Armor, Crafting & Construction Materials
    'LeatherScraps': ('Leather Scraps', 0, 'mat'),
    'DeerHide': ('Deer Hide', 0, 'mat'),
    'TrollHide': ('Troll Hide', 0, 'mat'),
    'WolfPelt': ('Wolf Pelt', 0, 'mat'),
    'WolfFang': ('Wolf Fang', 0, 'mat'),
    'WolfClaw': ('Wolf Claws', 0, 'mat'),
    'LoxPelt': ('Lox Pelt', 0, 'mat'),
    'BoneFragments': ('Bone Fragments', 0, 'mat'),
    'Feathers': ('Feathers', 0, 'mat'),
    'Root': ('Root', 0, 'mat'),
    'AncientBark': ('Ancient Bark', 0, 'mat'),
    'LinenThread': ('Linen Thread', 0, 'mat'),
    'Chain': ('Chain', 0, 'mat'),
    'Chitin': ('Chitin', 0, 'mat'),
    'SerpentScale': ('Serpent Scales', 0, 'mat'),
    'Wood': ('Wood', 0, 'res'),
    'FineWood': ('Fine Wood', 0, 'res'),
    'RoundLog': ('Core Wood', 0, 'res'),
    'YggdrasilWood': ('Yggdrasil Wood', 0, 'res'),
    'Stone': ('Stone', 0, 'res'),
    'Flint': ('Flint', 0, 'res'),
    'Resin': ('Resin', 0, 'res'),
    'GreydwarfEye': ('Greydwarf Eyes', 0, 'mat'),
    'Needle': ('Deathsquito Needles', 0, 'mat'),
    'Bloodbag': ('Leech Bloodbags', 0, 'mat'),
    'Guck': ('Guck', 0, 'mat'),
    'Ooze': ('Ooze', 0, 'mat'),
    'Tar': ('Tar', 0, 'mat'),
    'FreezeGland': ('Freeze Glands', 0, 'mat'),

    # Boss Summon & Key Progression
    'HardAntler': ('Hard Antlers (Eikthyr Pickaxe)', 0, 'boss_mat'),
    'AncientSeed': ('Ancient Seeds (Elder Summon)', 0, 'boss_mat'),
    'CryptKey': ('Swamp Crypt Keys', 0, 'boss_mat'),
    'WitheredBone': ('Withered Bones (Bonemass Summon)', 0, 'boss_mat'),
    'Wishbone': ('Wishbones (Silver/Buried Treasure)', 0, 'boss_mat'),
    'DragonEgg': ('Dragon Eggs (Moder Summon)', 0, 'boss_mat'),
    'DragonTear': ('Dragon Tears (Artisan Table)', 0, 'boss_mat'),
    'GoblinTotem': ('Fuling Totems (Yagluth Summon)', 0, 'boss_mat'),
    'Sealbreaker': ('Sealbreaker', 0, 'boss_mat'),
    'BellFragment': ('Bell Fragments', 0, 'boss_mat'),

    # Potions & Mead Rations
    'MeadHealthMinor': ('Minor Healing Mead', 0, 'potion'),
    'MeadHealthMedium': ('Medium Healing Mead', 0, 'potion'),
    'MeadStaminaMinor': ('Minor Stamina Mead', 0, 'potion'),
    'MeadStaminaMedium': ('Medium Stamina Mead', 0, 'potion'),
    'MeadPoisonResist': ('Poison Resistance Mead', 0, 'potion'),
    'MeadFrostResist': ('Frost Resistance Mead', 0, 'potion'),
    'MeadTasty': ('Tasty Mead', 0, 'potion'),

    # Trophies
    'TrophyDeer': ('Deer Trophies', 0, 'trophy'),
    'TrophyBoar': ('Boar Trophies', 0, 'trophy'),
    'TrophyGreydwarf': ('Greydwarf Trophies', 0, 'trophy'),
    'TrophyGreydwarfBrute': ('Greydwarf Brute Trophies', 0, 'trophy'),
    'TrophyGreydwarfShaman': ('Greydwarf Shaman Trophies', 0, 'trophy'),
    'TrophySkeleton': ('Skeleton Trophies', 0, 'trophy'),
    'TrophyTroll': ('Troll Trophies', 0, 'trophy'),
    'TrophyEikthyr': ('Eikthyr Trophies', 0, 'trophy'),
    'TrophyTheElder': ('The Elder Trophies', 0, 'trophy'),
    'TrophyBonemass': ('Bonemass Trophies', 0, 'trophy'),
    'TrophyDrake': ('Drake Trophies', 0, 'trophy'),
    'TrophyDragonQueen': ('Moder Trophies', 0, 'trophy'),
    'TrophyGoblinKing': ('Yagluth Trophies', 0, 'trophy'),
    'TrophyTheQueen': ('The Queen Trophies', 0, 'trophy'),
    'TrophySerpent': ('Serpent Trophies', 0, 'trophy')
}

HASH_TO_KEY = {get_stable_hash(k): k for k in ITEM_CATALOG}
TARGET_S_ITEMS = struct.pack('<i', get_stable_hash('items'))

PLAYER_CONTAINER_PREFABS = [
    'piece_chest_wood', 'piece_chest', 'piece_chest_blackmetal', 'piece_chest_private',
    'piece_chestwood', 'piece_chestblackmetal', 'piece_chestprivate',
    'piece_chestbarrel', 'piece_chestgrausten', 'piece_chestwarderobe', 'piece_chesttreasure',
    'Cart', 'VikingShip', 'Karve', 'Drakkar'
]
PACKED_PLAYER_HASHES = [struct.pack('<i', get_stable_hash(p)) for p in PLAYER_CONTAINER_PREFABS]

class ValheimWorldParser:
    """Reads Valheim save state directly from active world chunks and db files."""

    def __init__(self, worlds_dir: Optional[str] = None, world_name: Optional[str] = None):
        self.worlds_dir = worlds_dir or config.VALHEIM_WORLDS_DIR
        self.world_name = world_name or config.VALHEIM_WORLD_NAME
        self.world_dir = os.path.join(self.worlds_dir, self.world_name)

    def get_chunk_files(self) -> List[str]:
        """Returns sorted, deduplicated active chunk file paths."""
        if not os.path.exists(self.world_dir):
            return []
        raw_chunks = glob.glob(os.path.join(self.world_dir, "*.chunk"))
        chunks_by_prefix = {}
        for c in raw_chunks:
            m = re.match(r'^(.*__\d+)_(\d+)\.chunk$', c)
            if m:
                prefix, ver = m.group(1), int(m.group(2))
                if prefix not in chunks_by_prefix or ver > chunks_by_prefix[prefix][0]:
                    chunks_by_prefix[prefix] = (ver, c)
            else:
                chunks_by_prefix[c] = (0, c)
        return sorted([v[1] for v in chunks_by_prefix.values()])

    def scan_chests(self) -> Tuple[Dict[str, int], int]:
        """Scans player-built chests across active chunks and tallies cataloged items."""
        totals: Dict[str, int] = {}
        container_count = 0
        chunks = self.get_chunk_files()

        for c in chunks:
            try:
                with open(c, 'rb') as f:
                    data = f.read()
                idx = 0
                while True:
                    idx = data.find(TARGET_S_ITEMS, idx)
                    if idx == -1:
                        break
                    p = idx + 4
                    if p + 4 > len(data):
                        break
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
                        elif 1 <= version <= 999 and count < 100 and version not in _warned_versions:
                            _warned_versions.add(version)
                            print(f"[DBParser] Warning: Unknown inventory version {version} encountered. Parser expects v109. Valheim may have been updated.")
                    idx += 4
            except Exception:
                pass
        return totals, container_count

    def get_wealth_summary(self) -> Dict[str, Any]:
        """Computes clan gold, gem values, and purchasing power."""
        totals, chests = self.scan_chests()
        coins = totals.get('Coins', 0)
        amber = totals.get('Amber', 0)
        pearls = totals.get('AmberPearl', 0)
        rubies = totals.get('Ruby', 0)
        necklaces = totals.get('SilverNecklace', 0)

        gem_val = (amber * 5) + (pearls * 10) + (rubies * 20) + (necklaces * 30)
        total_wealth = coins + gem_val

        return {
            "containers_scanned": chests,
            "coins": coins,
            "gem_gold_value": gem_val,
            "total_purchasing_power": total_wealth,
            "items": {
                "amber": amber,
                "amber_pearls": pearls,
                "rubies": rubies,
                "silver_necklaces": necklaces
            }
        }

    def get_wealth_report(self) -> str:
        """Formatted clan treasury and trader report."""
        summary = self.get_wealth_summary()
        coins = summary["coins"]
        gem_val = summary["gem_gold_value"]
        total = summary["total_purchasing_power"]
        items = summary["items"]

        lines = [
            "🪙 **TRIBAL TREASURY & REALM PURCHASING POWER**",
            "",
            "💰 **Clan Coffers:**",
            f"• **Liquid Gold Coins:** `{coins:,}` 🪙",
            f"• **Rubies ({items['rubies']}):** `{items['rubies'] * 20:,}` Gold value",
            f"• **Amber ({items['amber']}):** `{items['amber'] * 5:,}` Gold value",
            f"• **Amber Pearls ({items['amber_pearls']}):** `{items['amber_pearls'] * 10:,}` Gold value",
            f"• **Silver Necklaces ({items['silver_necklaces']}):** `{items['silver_necklaces'] * 30:,}` Gold value",
            f"🔥 **Total Clan Net Worth:** **~{total:,} Gold**",
            "",
            "🏪 **Merchant Purchasing Power:**",
            f"• **Megingjord (+150 Carry Weight - 950g):** {'✅ Can afford ' + str(total // 950) if total >= 950 else '❌ Need ' + str(950 - total) + 'g'}",
            f"• **Dvergr Circlet (Headlamp - 620g):** {'✅ Can afford' if total >= 620 else '❌ Need ' + str(620 - total) + 'g'}",
            f"• **Fishing Rod & Bait (350g):** {'✅ Can afford' if total >= 350 else '❌ Need ' + str(350 - total) + 'g'}",
            f"• **Ymir Flesh (120g each):** {'✅ Can afford ' + str(total // 120) if total >= 120 else '❌ Need 120g'}"
        ]
        return "\n".join(lines)

    def get_metal_report(self) -> str:
        """Formatted metallurgy breakdown and smithing milestones."""
        totals, chests = self.scan_chests()
        cop = totals.get('Copper', 0) + totals.get('CopperOre', 0)
        tin = totals.get('Tin', 0) + totals.get('TinOre', 0)
        bronze = totals.get('Bronze', 0)
        iron = totals.get('Iron', 0) + totals.get('IronScrap', 0) + totals.get('IronOre', 0)
        iron_bars = totals.get('Iron', 0)
        silver = totals.get('Silver', 0) + totals.get('SilverOre', 0)
        black = totals.get('BlackMetal', 0) + totals.get('BlackMetalScrap', 0)
        flametal = totals.get('Flametal', 0) + totals.get('FlametalOre', 0)

        # Active era detection
        if flametal > 0:
            era = "🔥 Flametal (Ashlands Crusade)"
        elif black > 0:
            era = "🌾 Black Metal (Plains Era)"
        elif silver > 0:
            era = "❄️ Silver (Mountains Era)"
        elif iron > 0:
            era = "☣️ Iron (Swamps Era)"
        elif (cop + tin + bronze) > 0:
            era = "🌲 Bronze (Black Forest Era)"
        else:
            era = "🏕️ Stone & Flint (Meadows Era)"

        lines = [
            "⛏️ **VALHEIM CLAN METALLURGY & SMELTER RESERVES**",
            f"🏆 **Active Metal Era:** **{era}**",
            "",
            f"📦 **Current Metal Stockpile (across {chests} chests):**",
            f"• **Copper:** `{cop}` total ({totals.get('Copper', 0)} bars, {totals.get('CopperOre', 0)} ore)",
            f"• **Tin:** `{tin}` total ({totals.get('Tin', 0)} bars, {totals.get('TinOre', 0)} ore)",
            f"• **Bronze:** `{bronze}` bars forged"
        ]
        if iron > 0:
            lines.append(f"• **Iron:** `{iron}` total ({iron_bars} bars forged, {iron - iron_bars} scrap/ore)")
        if silver > 0:
            lines.append(f"• **Silver:** `{silver}` total ({totals.get('Silver', 0)} bars forged)")
        if black > 0:
            lines.append(f"• **Black Metal:** `{black}` total ({totals.get('BlackMetal', 0)} bars forged)")
        if flametal > 0:
            lines.append(f"• **Flametal:** `{flametal}` total ({totals.get('Flametal', 0)} bars forged)")

        # Smithing milestones
        if iron_bars >= 60:
            lines.append("")
            lines.append(f"🛡️ **Iron Smithing Milestone:** `{iron_bars // 60}` Full Iron Armor Set(s) can be forged right now!")

        return "\n".join(lines)

    def get_portals(self) -> List[Dict[str, Any]]:
        """Extracts portal tags and coordinates from world save."""
        pw_hashes = {
            get_stable_hash('portal_wood'): 'Wood Portal',
            get_stable_hash('portal_stone'): 'Stone Portal',
        }
        tag_hash = bytes.fromhex('ea917c29')
        portals = []
        chunks = self.get_chunk_files()

        for c in chunks:
            try:
                with open(c, 'rb') as fp:
                    data = fp.read()
            except Exception:
                continue

            for ph, ptype in pw_hashes.items():
                packed_ph = struct.pack('<i', ph)
                idx = 0
                while True:
                    idx = data.find(packed_ph, idx)
                    if idx == -1:
                        break
                    if idx >= 12:
                        x, y, z = struct.unpack('<fff', data[idx-12:idx])
                        if -10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500:
                            window = data[idx:idx+120]
                            t_idx = window.find(tag_hash)
                            if t_idx != -1:
                                p = t_idx + 4
                                tag_len, shift = 0, 0
                                while p < len(window) and shift <= 28:
                                    b = window[p]
                                    p += 1
                                    tag_len |= (b & 0x7F) << shift
                                    if not (b & 0x80):
                                        break
                                    shift += 7
                                tag = window[p:p+tag_len].decode('utf-8', errors='replace').strip()
                                if tag:
                                    portals.append({
                                        'tag': tag,
                                        'type': ptype,
                                        'x': round(x, 1),
                                        'y': round(y, 1),
                                        'z': round(z, 1)
                                    })
                    idx += 4
        return portals

    def get_portal_report(self) -> str:
        """Formatted directory of all carved portals in the realm."""
        portals = self.get_portals()
        if not portals:
            return "🚪 **PORTAL DIRECTORY:** No carved portals detected in active world chunks."

        # Count tags to find paired vs unpaired
        tag_counts: Dict[str, int] = {}
        for p in portals:
            tag_counts[p['tag']] = tag_counts.get(p['tag'], 0) + 1

        lines = [
            f"🚪 **VALHEIM REALM PORTAL DIRECTORY ({len(portals)} Portals)**",
            ""
        ]

        # Paired portals
        paired = [p for p in portals if tag_counts[p['tag']] >= 2]
        unpaired = [p for p in portals if tag_counts[p['tag']] == 1]

        if paired:
            lines.append("🟢 **Active Paired Links:**")
            seen_tags = set()
            for p in paired:
                if p['tag'] not in seen_tags:
                    seen_tags.add(p['tag'])
                    lines.append(f"• 🔗 Tag: `{p['tag']}` ({p['type']})")

        if unpaired:
            lines.append("")
            lines.append("⚠️ **Unpaired / One-Way Portals:**")
            for p in unpaired:
                lines.append(f"• 📍 Tag: `{p['tag']}` at ({p['x']}, {p['y']}, {p['z']})")

        return "\n".join(lines)
