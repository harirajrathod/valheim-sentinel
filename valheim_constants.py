import struct
import sys
import re
sys.path.insert(0, '/root')
from valheim_utils import get_stable_hash

# ---------------------------------------------------------------------------
# Centralized log-pattern registry (single source of truth).
# All regexes for parsing the Valheim dedicated-server log live here so the
# suite parses casualty/network events consistently. Consumers import PATTERNS
# from this module and use the pre-compiled objects instead of recompiling
# their own literals.
# ---------------------------------------------------------------------------
PATTERNS = {
    # --- ZDO / character lifecycle ---
    # Full join line: "Got character ZDOID from PlayerName : <zid>:<seq>"
    "zdo_join":          re.compile(r"Got character ZDOID from ([^:]+) : (-?\d+):(\d+)"),
    # Owner lookup variant: id component only (used when the seq tail is
    # followed by other content, e.g. "(... npc)" annotations)
    "zdo_join_owner":    re.compile(r"Got character ZDOID from ([^:]+) : (-?\d+):"),
    # Any ZDO line (broad match; used for loose name detection)
    "zdo_any":           re.compile(r"Got character ZDOID from ([^:]+) :"),
    # Casualty signal — the ONLY authoritative death marker in the log
    "zdo_death":         re.compile(r"Got character ZDOID from ([^:]+) : 0:0"),
    # Timestamped casualty line (used when replaying the full log)
    "zdo_death_ts":      re.compile(
        r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}): Got character ZDOID from ([^:]+) : 0:0"),
    # Platform attribution variant: captures a bare name without ":"
    "zdo_name_only":     re.compile(r"Got character ZDOID from ([^ :]+)"),
    # Legacy alias kept for safe migrations
    "zdo_death_legacy":  re.compile(r"Got character ZDOID from ([^:]+) : 0:0"),

    # --- Network / session ---
    "handshake":          re.compile(r"Got handshake from client (\S+)"),
    "socket_close":       re.compile(r"Closing socket\s+(\S+)"),
    "player_count":       re.compile(r"now (\d+) player\(s\)"),
    "connections":        re.compile(r"Connections (\d+) ZDOS"),
    "zero_players":       re.compile(r"(?:Connections 0 ZDOS|now 0 player\(s\))"),
    "join_code":          re.compile(r"registered with join code\s+(\d+)"),
    "join_code_loose":    re.compile(r"join code\s+(\d+)"),
    "version":            re.compile(r"Valheim\s+(?:version:\s*)?(l-[\d\.]+.*?\(network version \d+\))"),
    "pre_seeded":         re.compile(r"Pre-seeded active players:\s*(\{[^}]*}|set\(\))"),
    "platform_id":        re.compile(r"Platform ID ((?:Steam|PlayStation|Xbox)_[a-zA-Z0-9_-]+)"),

    # --- Hostile / world events ---
    "raid_event":         re.compile(r"Random event set:(\w+)"),
    "world_save":         re.compile(r"World save \((\d+)/(\d+)\)"),
    "placed_location":    re.compile(r"Placed location (\w+) in zone (-?\d+),(-?\d+)"),
    "join_cli":           re.compile(r"Join:\s+([^\s\(]+)"),
    "leave_cli":          re.compile(r"Leave(?:\s+\([^\)]+\))?:\s+([^\s]+)"),
    "boss_defeat_monitor": re.compile(r"\b(defeated_\w+)\b", re.IGNORECASE),
    "boss_defeat_chronicle": re.compile(
        r"\b(defeated_(?:eikthyr|gdking|bonemass|dragon|writhan|goblinking|queen|fader|fimbulbringer))\b",
        re.IGNORECASE),

    # --- Npc despawn / world save markers ---
    "destroy_zdo":        re.compile(r"Destroying abandoned non persistent zdo \S+ owner (-?\d+)"),
    "portal_connect":     re.compile(
        r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}): Connected portals (-?\d+):(\d+) <-> (-?\d+):(\d+)"),

    # --- Log line timestamp variants ---
    "ts_line":            re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}):"),
    "ts_plain":           re.compile(r"^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})"),
}

# Boss chain in order. 'aliases' covers alternate keys the game may record.
BOSS_CHAIN = [
    {
        'key': 'defeated_eikthyr',
        'aliases': [],
        'name': 'Eikthyr ⚡',
        'biome': 'Meadows',
        'next_biome': 'Black Forest',
        'reward': 'Hard Antler (Pickaxe)',
        'tier': 1,
        'icon': '⚡',
    },
    {
        'key': 'defeated_gdking',
        'aliases': [],
        'name': 'The Elder 🌲',
        'biome': 'Black Forest',
        'next_biome': 'Swamps',
        'reward': 'Swamp Crypt Key',
        'tier': 2,
        'icon': '🌲',
    },
    {
        'key': 'defeated_bonemass',
        'aliases': [],
        'name': 'Bonemass ☣️',
        'biome': 'Swamps',
        'next_biome': 'Mountains',
        'reward': 'Wishbone (Silver Finder)',
        'tier': 3,
        'icon': '☣️',
    },
    {
        'key': 'defeated_dragon',
        'aliases': ['defeated_writhan'],   # Game records Moder as 'defeated_writhan'
        'name': 'Moder ❄️',
        'biome': 'Mountains',
        'next_biome': 'Plains',
        'reward': 'Dragon Tear (Artisan Table)',
        'tier': 4,
        'icon': '❄️',
    },
    {
        'key': 'defeated_goblinking',
        'aliases': [],
        'name': 'Yagluth ⚔️',
        'biome': 'Plains',
        'next_biome': 'Mistlands',
        'reward': 'Torn Spirit',
        'tier': 5,
        'icon': '⚔️',
    },
    {
        'key': 'defeated_queen',
        'aliases': [],
        'name': 'The Queen 🪲',
        'biome': 'Mistlands',
        'next_biome': 'Ashlands',
        'reward': 'Majestic Carapace',
        'tier': 6,
        'icon': '🪲',
    },
    {
        'key': 'defeated_fader',
        'aliases': [],
        'name': 'Fader 🔥',
        'biome': 'Ashlands',
        'next_biome': 'Deep North',
        'reward': 'Bell Fragment & Lord of Cinder',
        'tier': 7,
        'icon': '🔥',
    },
    {
        'key': 'defeated_fimbulbringer',
        'aliases': [],
        'name': 'Kall Fimbulbringer ❄️',
        'biome': 'Deep North',
        'next_biome': None,
        'reward': 'Heart of the Jotun',
        'tier': 8,
        'icon': '❄️',
    },
]

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
    'IronScrap': ('Scrap Iron', 0, 'metal'),
    'IronOre': ('Bog Iron Ore', 0, 'metal'),
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
    # Foraged / Raw Food Ingredients
    'Honey': ('Honey', 0, 'food'),
    'Mushroom': ('Red Mushrooms', 0, 'food'),
    'MushroomYellow': ('Yellow Mushrooms', 0, 'food'),
    'MushroomBlue': ('Blue Mushrooms', 0, 'food'),
    'Raspberry': ('Raspberries', 0, 'food'),
    'Blueberries': ('Blueberries', 0, 'food'),
    'Dandelion': ('Dandelions', 0, 'food'),
    'Thistle': ('Thistle', 0, 'food'),
    'Carrot': ('Carrots', 0, 'food'),
    'CarrotSeeds': ('Carrot Seeds', 0, 'food'),
    'Turnip': ('Turnips', 0, 'food'),
    'TurnipSeeds': ('Turnip Seeds', 0, 'food'),
    'Onion': ('Onions', 0, 'food'),
    'OnionSeeds': ('Onion Seeds', 0, 'food'),
    'RawMeat': ('Raw Boar Meat', 0, 'food'),
    'BoarMeat': ('Raw Boar Meat', 0, 'food'),
    'DeerMeat': ('Raw Deer Meat', 0, 'food'),
    'NeckTail': ('Neck Tails', 0, 'food'),
    'FishRaw': ('Raw Fish', 0, 'food'),
    'WolfMeat': ('Raw Wolf Meat', 0, 'food'),
    'LoxMeat': ('Raw Lox Meat', 0, 'food'),
    'SerpentMeat': ('Raw Serpent Meat', 0, 'food'),
    'Entrails': ('Entrails', 0, 'food'),
    'Cloudberry': ('Cloudberries', 0, 'food'),
    'Barley': ('Barley', 0, 'food'),
    'BarleyFlour': ('Barley Flour', 0, 'food'),
    # Armor, Crafting & Construction Materials
    'LeatherScraps': ('Leather Scraps', 0, 'mat'),
    'DeerHide': ('Deer Hide', 0, 'mat'),
    'TrollHide': ('Troll Hide', 0, 'mat'),
    'WolfPelt': ('Wolf Pelt', 0, 'mat'),
    'WolfFang': ('Wolf Fang', 0, 'mat'),
    'LoxPelt': ('Lox Pelt', 0, 'mat'),
    'BoneFragments': ('Bone Fragments', 0, 'mat'),
    'Feathers': ('Feathers', 0, 'mat'),
    'Root': ('Root', 0, 'mat'),
    'AncientBark': ('Ancient Bark', 0, 'mat'),
    'LinenThread': ('Linen Thread', 0, 'mat'),
    'Chain': ('Chain', 0, 'mat'),
    'Chitin': ('Chitin', 0, 'mat'),
    'Wood': ('Wood', 0, 'res'),
    'FineWood': ('Fine Wood', 0, 'res'),
    'RoundLog': ('Core Wood', 0, 'res'),
    'YggdrasilWood': ('Yggdrasil Wood', 0, 'res'),
    'Stone': ('Stone', 0, 'res'),
    'Flint': ('Flint', 0, 'res'),
    'Resin': ('Resin', 0, 'res'),
    'GreydwarfEye': ('Greydwarf Eyes', 0, 'mat'),
    # Boss Summon & Key Progression
    'AncientSeed': ('Ancient Seeds (Elder Summon)', 0, 'boss_mat'),
    'HardAntler': ('Hard Antlers (Eikthyr Pickaxe)', 0, 'boss_mat'),
    'CryptKey': ('Swamp Crypt Keys', 0, 'boss_mat'),
    'Wishbone': ('Wishbones (Silver/Buried Treasure)', 0, 'boss_mat'),
    'DragonEgg': ('Dragon Eggs (Moder Summon)', 0, 'boss_mat'),
    'DragonTear': ('Dragon Tears (Artisan Table)', 0, 'boss_mat'),
    'GoblinTotem': ('Fuling Totems (Yagluth Summon)', 0, 'boss_mat'),
    'WitheredBone': ('Withered Bones (Bonemass Summon)', 0, 'boss_mat'),
    # Swamps, Plains & Biome Crafting Materials
    'Needle': ('Deathsquito Needles', 0, 'mat'),
    'Bloodbag': ('Leech Bloodbags', 0, 'mat'),
    'Guck': ('Guck', 0, 'mat'),
    'Ooze': ('Ooze', 0, 'mat'),
    'Tar': ('Tar', 0, 'mat'),
    'FreezeGland': ('Freeze Glands', 0, 'mat'),
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
    'TrophySerpent': ('Serpent Trophies', 0, 'trophy'),
    # Mistlands & Ashlands Foods & Raw Items
    'ChickenMeat': ('Raw Chicken Meat', 0, 'food'),
    'ChickenMeatCooked': ('Cooked Chicken Meat', 0, 'food'),
    'HareMeat': ('Raw Hare Meat', 0, 'food'),
    'HareMeatCooked': ('Cooked Hare Meat', 0, 'food'),
    'SeekerMeat': ('Raw Seeker Meat', 0, 'food'),
    'SeekerMeatCooked': ('Cooked Seeker Meat', 0, 'food'),
    'JotunPuffs': ('Jotun Puffs', 0, 'food'),
    'Magecap': ('Magecap Mushrooms', 0, 'food'),
    'RoyalJelly': ('Royal Jelly', 0, 'food'),
    'Sap': ('Yggdrasil Sap', 0, 'food'),
    'Egg': ('Eggs', 0, 'food'),
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
    'SerpentScale': ('Serpent Scales', 0, 'mat'),
    'WolfClaw': ('Wolf Claws', 0, 'mat'),
    'Sealbreaker': ('Sealbreaker', 0, 'boss_mat'),
    'BellFragment': ('Bell Fragments', 0, 'boss_mat'),
    'Bloodgold': ('Bloodgold Bars', 0, 'metal'),
    'BloodgoldOre': ('Bloodgold Ore', 0, 'metal'),
    'MaliciousBlood': ('🩸 Malicious Blood', 0, 'boss_mat'),
    'IntricateKey': ('Intricate Keys', 0, 'boss_mat'),
    'TrophyFimbulbringer': ('Kall Fimbulbringer Trophy', 0, 'boss_mat'),
    # Ammunition & Arrows
    'ArrowWood': ('Wood Arrows', 0, 'arrow'),
    'ArrowFlint': ('Flinthead Arrows', 0, 'arrow'),
    'ArrowFire': ('Fire Arrows', 0, 'arrow'),
    'ArrowBronze': ('Bronzehead Arrows', 0, 'arrow'),
    'ArrowIron': ('Ironhead Arrows', 0, 'arrow'),
    'ArrowSilver': ('Silver Arrows', 0, 'arrow'),
    'ArrowObsidian': ('Obsidian Arrows', 0, 'arrow'),
    'ArrowPoison': ('Poison Arrows', 0, 'arrow'),
    'ArrowFrost': ('Frost Arrows', 0, 'arrow'),
    'ArrowNeedle': ('Needle Arrows', 0, 'arrow'),
    'ArrowCarapace': ('Carapace Arrows', 0, 'arrow'),
    'ArrowBone': ('Bone Arrows', 0, 'arrow'),
    'ArrowCharred': ('Charred Arrows', 0, 'arrow'),
    'OozeBomb': ('Ooze Bombs', 0, 'weapon'),
    'Bilebomb': ('Bilebombs', 0, 'weapon'),
    'FishingBait': ('Fishing Bait', 0, 'tool'),
    'BarleyWine': ('Fire Resistance Barley Wine', 0, 'potion'),
}

HASH_TO_KEY = {get_stable_hash(k): k for k in ITEM_CATALOG}
TARGET_S_ITEMS = struct.pack('<i', -938864442)

# Player-built container prefabs (chests, carts, ships)
PLAYER_CONTAINER_PREFABS = [
    'piece_chest_wood', 'piece_chest', 'piece_chest_blackmetal', 'piece_chest_private',
    'piece_chestwood', 'piece_chestblackmetal', 'piece_chestprivate',
    'piece_chestbarrel', 'piece_chestgrausten', 'piece_chestwarderobe', 'piece_chesttreasure',
    'Cart', 'VikingShip', 'Karve', 'Drakkar'
]
PACKED_PLAYER_HASHES = [struct.pack('<i', get_stable_hash(p)) for p in PLAYER_CONTAINER_PREFABS]

FOOD_CATALOG = {
    # Tier 1 - Meadows
    'Honey': {
        'name': 'Honey', 'icon': '🍯', 'hp': 8, 'stam': 35, 'eitr': 0, 'dur': 15, 'tier': 1, 'tier_name': 'Meadows',
        'type': 'stamina', 'station': 'Beehive', 'recipe': None, 'yield': 1, 'raw': None
    },
    'Raspberry': {
        'name': 'Raspberries', 'icon': '🍓', 'hp': 7, 'stam': 20, 'eitr': 0, 'dur': 10, 'tier': 1, 'tier_name': 'Meadows',
        'type': 'stamina', 'station': 'Foraged', 'recipe': None, 'yield': 1, 'raw': None
    },
    'Mushroom': {
        'name': 'Red Mushroom', 'icon': '🍄', 'hp': 15, 'stam': 15, 'eitr': 0, 'dur': 15, 'tier': 1, 'tier_name': 'Meadows',
        'type': 'balanced', 'station': 'Foraged', 'recipe': None, 'yield': 1, 'raw': None
    },
    'GrilledNeckTail': {
        'name': 'Grilled Neck Tail', 'icon': '🦎', 'hp': 25, 'stam': 8, 'eitr': 0, 'dur': 20, 'tier': 1, 'tier_name': 'Meadows',
        'type': 'health', 'station': 'Cooking Rack', 'recipe': None, 'yield': 1, 'raw': 'NeckTail'
    },
    'CookedMeat': {
        'name': 'Cooked Boar Meat', 'icon': '🍖', 'hp': 30, 'stam': 10, 'eitr': 0, 'dur': 20, 'tier': 1, 'tier_name': 'Meadows',
        'type': 'health', 'station': 'Cooking Rack', 'recipe': None, 'yield': 1, 'raw': 'RawMeat'
    },
    'CookedDeerMeat': {
        'name': 'Cooked Deer Meat', 'icon': '🥩', 'hp': 35, 'stam': 12, 'eitr': 0, 'dur': 20, 'tier': 1, 'tier_name': 'Meadows',
        'type': 'health', 'station': 'Cooking Rack', 'recipe': None, 'yield': 1, 'raw': 'DeerMeat'
    },
    'CookedFish': {
        'name': 'Cooked Fish', 'icon': '🐟', 'hp': 45, 'stam': 15, 'eitr': 0, 'dur': 20, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'health', 'station': 'Cooking Rack', 'recipe': None, 'yield': 1, 'raw': 'FishRaw'
    },

    # Tier 2 - Black Forest (Cauldron 1)
    'Blueberries': {
        'name': 'Blueberries', 'icon': '🫐', 'hp': 8, 'stam': 25, 'eitr': 0, 'dur': 10, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'stamina', 'station': 'Foraged', 'recipe': None, 'yield': 1, 'raw': None
    },
    'MushroomYellow': {
        'name': 'Yellow Mushroom', 'icon': '🍄', 'hp': 10, 'stam': 30, 'eitr': 0, 'dur': 10, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'stamina', 'station': 'Burial Chambers', 'recipe': None, 'yield': 1, 'raw': None
    },
    'Carrot': {
        'name': 'Carrot', 'icon': '🥕', 'hp': 10, 'stam': 32, 'eitr': 0, 'dur': 15, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'stamina', 'station': 'Cultivator', 'recipe': None, 'yield': 1, 'raw': None
    },
    'QueensJam': {
        'name': "Queen's Jam", 'icon': '🍯', 'hp': 14, 'stam': 40, 'eitr': 0, 'dur': 20, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'stamina', 'station': 'Cauldron', 'recipe': {'Raspberry': 8, 'Blueberries': 8}, 'yield': 4, 'raw': None
    },
    'BoarJerky': {
        'name': 'Boar Jerky', 'icon': '🥓', 'hp': 23, 'stam': 23, 'eitr': 0, 'dur': 30, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'balanced', 'station': 'Cauldron', 'recipe': {'RawMeat': 1, 'Honey': 1}, 'yield': 2, 'raw': None
    },
    'DeerJerky': {
        'name': 'Deer Jerky', 'icon': '🥓', 'hp': 21, 'stam': 21, 'eitr': 0, 'dur': 30, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'balanced', 'station': 'Cauldron', 'recipe': {'DeerMeat': 1, 'Honey': 1}, 'yield': 2, 'raw': None
    },
    'DeerStew': {
        'name': 'Deer Stew', 'icon': '🍲', 'hp': 45, 'stam': 15, 'eitr': 0, 'dur': 25, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'health', 'station': 'Cauldron', 'recipe': {'CookedDeerMeat': 1, 'Blueberries': 1, 'Carrot': 1}, 'yield': 1, 'raw': None,
        'alt_recipe': {'DeerMeat': 1, 'Blueberries': 1, 'Carrot': 1}
    },
    'MincedMeatSauce': {
        'name': 'Minced Meat Sauce', 'icon': '🍝', 'hp': 40, 'stam': 13, 'eitr': 0, 'dur': 25, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'health', 'station': 'Cauldron', 'recipe': {'RawMeat': 1, 'DeerMeat': 1, 'Carrot': 1}, 'yield': 1, 'raw': None
    },
    'CarrotSoup': {
        'name': 'Carrot Soup', 'icon': '🥣', 'hp': 15, 'stam': 45, 'eitr': 0, 'dur': 25, 'tier': 2, 'tier_name': 'Black Forest',
        'type': 'stamina', 'station': 'Cauldron', 'recipe': {'Carrot': 3, 'Mushroom': 1}, 'yield': 1, 'raw': None
    },

    # Tier 3 - Swamps (Cauldron 2 - Spice Rack)
    'Turnip': {
        'name': 'Turnip', 'icon': '🌱', 'hp': 10, 'stam': 30, 'eitr': 0, 'dur': 15, 'tier': 3, 'tier_name': 'Swamps',
        'type': 'stamina', 'station': 'Cultivator', 'recipe': None, 'yield': 1, 'raw': None
    },
    'Sausages': {
        'name': 'Sausages', 'icon': '🌭', 'hp': 55, 'stam': 18, 'eitr': 0, 'dur': 25, 'tier': 3, 'tier_name': 'Swamps',
        'type': 'health', 'station': 'Cauldron 2', 'recipe': {'RawMeat': 1, 'Entrails': 2, 'Thistle': 4}, 'yield': 4, 'raw': None
    },
    'TurnipStew': {
        'name': 'Turnip Stew', 'icon': '🍲', 'hp': 18, 'stam': 55, 'eitr': 0, 'dur': 25, 'tier': 3, 'tier_name': 'Swamps',
        'type': 'stamina', 'station': 'Cauldron 2', 'recipe': {'Turnip': 3, 'RawMeat': 1}, 'yield': 1, 'raw': None
    },
    'BlackSoup': {
        'name': 'Black Soup', 'icon': '🥣', 'hp': 50, 'stam': 17, 'eitr': 0, 'dur': 20, 'tier': 3, 'tier_name': 'Swamps',
        'type': 'health', 'station': 'Cauldron 2', 'recipe': {'Bloodbag': 1, 'Honey': 1, 'Turnip': 1}, 'yield': 1, 'raw': None
    },
    'Muckshake': {
        'name': 'Muckshake', 'icon': '🧋', 'hp': 16, 'stam': 50, 'eitr': 0, 'dur': 20, 'tier': 3, 'tier_name': 'Swamps',
        'type': 'stamina', 'station': 'Cauldron 2', 'recipe': {'Ooze': 1, 'Raspberry': 2, 'Blueberries': 2}, 'yield': 1, 'raw': None
    },
    'CookedSerpentMeat': {
        'name': 'Cooked Serpent Meat', 'icon': '🥩', 'hp': 70, 'stam': 23, 'eitr': 0, 'dur': 25, 'tier': 3, 'tier_name': 'Ocean/Swamps',
        'type': 'health', 'station': 'Iron Cooking Station', 'recipe': None, 'yield': 1, 'raw': 'SerpentMeat'
    },
    'SerpentStew': {
        'name': 'Serpent Stew', 'icon': '🍲', 'hp': 80, 'stam': 26, 'eitr': 0, 'dur': 30, 'tier': 3, 'tier_name': 'Ocean/Swamps',
        'type': 'health', 'station': 'Cauldron 2', 'recipe': {'CookedSerpentMeat': 1, 'Mushroom': 1, 'Honey': 2}, 'yield': 1, 'raw': None,
        'alt_recipe': {'SerpentMeat': 1, 'Mushroom': 1, 'Honey': 2}
    },

    # Tier 4 - Mountains (Cauldron 3 - Butcher's Table)
    'Onion': {
        'name': 'Onion', 'icon': '🧅', 'hp': 13, 'stam': 40, 'eitr': 0, 'dur': 15, 'tier': 4, 'tier_name': 'Mountains',
        'type': 'stamina', 'station': 'Cultivator', 'recipe': None, 'yield': 1, 'raw': None
    },
    'CookedWolfMeat': {
        'name': 'Cooked Wolf Meat', 'icon': '🥩', 'hp': 45, 'stam': 15, 'eitr': 0, 'dur': 20, 'tier': 4, 'tier_name': 'Mountains',
        'type': 'health', 'station': 'Iron Cooking Station', 'recipe': None, 'yield': 1, 'raw': 'WolfMeat'
    },
    'WolfJerky': {
        'name': 'Wolf Jerky', 'icon': '🥓', 'hp': 33, 'stam': 33, 'eitr': 0, 'dur': 30, 'tier': 4, 'tier_name': 'Mountains',
        'type': 'balanced', 'station': 'Cauldron 3', 'recipe': {'WolfMeat': 1, 'Honey': 1}, 'yield': 2, 'raw': None
    },
    'WolfSkewers': {
        'name': 'Wolf Skewer', 'icon': '🍢', 'hp': 65, 'stam': 21, 'eitr': 0, 'dur': 25, 'tier': 4, 'tier_name': 'Mountains',
        'type': 'health', 'station': 'Cauldron 3', 'recipe': {'WolfMeat': 1, 'Mushroom': 2, 'Onion': 1}, 'yield': 1, 'raw': None
    },
    'OnionSoup': {
        'name': 'Onion Soup', 'icon': '🥣', 'hp': 20, 'stam': 60, 'eitr': 0, 'dur': 20, 'tier': 4, 'tier_name': 'Mountains',
        'type': 'stamina', 'station': 'Cauldron 3', 'recipe': {'Onion': 3}, 'yield': 1, 'raw': None
    },
    'Eyescream': {
        'name': 'Eyescream', 'icon': '🍨', 'hp': 21, 'stam': 65, 'eitr': 0, 'dur': 25, 'tier': 4, 'tier_name': 'Mountains',
        'type': 'stamina', 'station': 'Cauldron 3', 'recipe': {'FreezeGland': 1, 'GreydwarfEye': 3}, 'yield': 1, 'raw': None
    },

    # Tier 5 - Plains (Cauldron 4 - Pots and Pans, Oven)
    'Cloudberry': {
        'name': 'Cloudberry', 'icon': '🫐', 'hp': 13, 'stam': 40, 'eitr': 0, 'dur': 15, 'tier': 5, 'tier_name': 'Plains',
        'type': 'stamina', 'station': 'Foraged', 'recipe': None, 'yield': 1, 'raw': None
    },
    'CookedLoxMeat': {
        'name': 'Cooked Lox Meat', 'icon': '🥩', 'hp': 50, 'stam': 16, 'eitr': 0, 'dur': 20, 'tier': 5, 'tier_name': 'Plains',
        'type': 'health', 'station': 'Iron Cooking Station', 'recipe': None, 'yield': 1, 'raw': 'LoxMeat'
    },
    'Bread': {
        'name': 'Bread', 'icon': '🍞', 'hp': 23, 'stam': 70, 'eitr': 0, 'dur': 25, 'tier': 5, 'tier_name': 'Plains',
        'type': 'stamina', 'station': 'Stone Oven', 'recipe': {'BarleyFlour': 10}, 'yield': 1, 'raw': None,
        'alt_recipe': {'Barley': 10}
    },
    'FishWraps': {
        'name': 'Fish Wraps', 'icon': '🌯', 'hp': 70, 'stam': 23, 'eitr': 0, 'dur': 25, 'tier': 5, 'tier_name': 'Plains',
        'type': 'health', 'station': 'Stone Oven', 'recipe': {'CookedFish': 2, 'BarleyFlour': 4}, 'yield': 1, 'raw': None,
        'alt_recipe': {'FishRaw': 2, 'BarleyFlour': 4}
    },
    'LoxPie': {
        'name': 'Lox Meat Pie', 'icon': '🥧', 'hp': 75, 'stam': 24, 'eitr': 0, 'dur': 30, 'tier': 5, 'tier_name': 'Plains',
        'type': 'health', 'station': 'Stone Oven', 'recipe': {'CookedLoxMeat': 2, 'BarleyFlour': 4, 'Cloudberry': 2}, 'yield': 1, 'raw': None,
        'alt_recipe': {'LoxMeat': 2, 'BarleyFlour': 4, 'Cloudberry': 2}
    },
    'BloodPudding': {
        'name': 'Blood Pudding', 'icon': '🍮', 'hp': 25, 'stam': 75, 'eitr': 0, 'dur': 30, 'tier': 5, 'tier_name': 'Plains',
        'type': 'stamina', 'station': 'Cauldron 4', 'recipe': {'Bloodbag': 2, 'BarleyFlour': 4, 'Thistle': 2}, 'yield': 1, 'raw': None
    },

    # Tier 6 - Mistlands (Cauldron 5, Oven)
    'Salad': {
        'name': 'Salad', 'icon': '🥗', 'hp': 26, 'stam': 80, 'eitr': 0, 'dur': 25, 'tier': 6, 'tier_name': 'Mistlands',
        'type': 'stamina', 'station': 'Cauldron 5', 'recipe': {'JotunPuffs': 3, 'Onion': 3, 'Cloudberry': 3}, 'yield': 3, 'raw': None
    },
    'MisthareSupreme': {
        'name': 'Misthare Supreme', 'icon': '🍲', 'hp': 85, 'stam': 28, 'eitr': 0, 'dur': 25, 'tier': 6, 'tier_name': 'Mistlands',
        'type': 'health', 'station': 'Stone Oven', 'recipe': {'HareMeat': 1, 'JotunPuffs': 2, 'Carrot': 1}, 'yield': 1, 'raw': None,
        'alt_recipe': {'CookedHareMeat': 1, 'JotunPuffs': 2, 'Carrot': 1}
    },
    'MeatPlatter': {
        'name': 'Meat Platter', 'icon': '🍱', 'hp': 80, 'stam': 26, 'eitr': 0, 'dur': 25, 'tier': 6, 'tier_name': 'Mistlands',
        'type': 'health', 'station': 'Stone Oven', 'recipe': {'SeekerMeat': 1, 'LoxMeat': 1, 'HareMeat': 1}, 'yield': 1, 'raw': None
    },
    'HoneyGlazedChicken': {
        'name': 'Honey Glazed Chicken', 'icon': '🍗', 'hp': 80, 'stam': 26, 'eitr': 0, 'dur': 25, 'tier': 6, 'tier_name': 'Mistlands',
        'type': 'health', 'station': 'Stone Oven', 'recipe': {'ChickenMeat': 1, 'Honey': 3, 'JotunPuffs': 2}, 'yield': 1, 'raw': None
    },
    'MushroomOmelette': {
        'name': 'Mushroom Omelette', 'icon': '🍳', 'hp': 28, 'stam': 85, 'eitr': 0, 'dur': 25, 'tier': 6, 'tier_name': 'Mistlands',
        'type': 'stamina', 'station': 'Cauldron 5', 'recipe': {'Egg': 3, 'MushroomYellow': 3}, 'yield': 1, 'raw': None
    },
    'FishAndBread': {
        'name': 'Fish and Bread', 'icon': '🥪', 'hp': 30, 'stam': 90, 'eitr': 0, 'dur': 25, 'tier': 6, 'tier_name': 'Mistlands',
        'type': 'stamina', 'station': 'Stone Oven', 'recipe': {'CookedFish': 2, 'Bread': 2}, 'yield': 1, 'raw': None
    },
}
