#!/usr/bin/env python3
"""
Valheim Quest & Intent Engine
-----------------------------
Intercepts messages from key clan leaders (e.g., Hilda) in the WhatsApp group,
evaluates actionable intent using Gemini AI, generates themed Norse Quests/Objectives,
and manages active clan quest boards and completion tracking.
"""

import os
import sys
import json
import time
import random
import re
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/root")
from valheim_utils import safe_urlopen

class SafeFormatDict(dict):
    """Guards against Anti-Pattern #2 (Safe Dynamic String Formatting)."""
    def __missing__(self, key):
        return ""

IST = timezone(timedelta(hours=5, minutes=30))
ENV_FILE = "/root/.env"
QUESTS_FILE = "/root/valheim_active_quests.json"
EXPIRY_SECONDS = 72 * 3600  # 72 hours auto-expiry

# Canonical Valheim Item Prefabs Mapping for Trackable Items
ITEM_ALIASES = {
    "wood": "Wood",
    "regular wood": "Wood",
    "core wood": "RoundLog",
    "corewood": "RoundLog",
    "round log": "RoundLog",
    "roundlog": "RoundLog",
    "fine wood": "FineWood",
    "finewood": "FineWood",
    "stone": "Stone",
    "flint": "Flint",
    "copper": "Copper",
    "copper bar": "Copper",
    "copper bars": "Copper",
    "copper ore": "CopperOre",
    "tin": "Tin",
    "tin bar": "Tin",
    "tin bars": "Tin",
    "tin ore": "TinOre",
    "bronze": "Bronze",
    "bronze bar": "Bronze",
    "bronze bars": "Bronze",
    "bronze nail": "BronzeNails",
    "bronze nails": "BronzeNails",
    "bronzenails": "BronzeNails",
    "iron": "Iron",
    "iron bar": "Iron",
    "iron bars": "Iron",
    "scrap iron": "IronScrap",
    "iron scrap": "IronScrap",
    "iron nail": "IronNails",
    "iron nails": "IronNails",
    "ironnails": "IronNails",
    "silver": "Silver",
    "silver bar": "Silver",
    "silver bars": "Silver",
    "silver ore": "SilverOre",
    "black metal": "BlackMetal",
    "blackmetal": "BlackMetal",
    "black metal scrap": "BlackMetal",
    "flametal": "Flametal",
    "flametal bar": "Flametal",
    "bloodgold": "Bloodgold",
    "ancient seed": "AncientSeed",
    "ancient seeds": "AncientSeed",
    "ancientseed": "AncientSeed",
    "deer meat": "RawMeat",
    "cooked deer meat": "CookedDeerMeat",
    "boar meat": "RawMeat",
    "cooked boar meat": "CookedMeat",
    "honey": "Honey",
    "carrot": "Carrot",
    "carrots": "Carrot",
    "yellow mushroom": "MushroomYellow",
    "yellow mushrooms": "MushroomYellow",
    "red mushroom": "Mushroom",
    "redmushroom": "Mushroom",
    "red mushrooms": "Mushroom",
    "troll hide": "TrollHide",
    "trollhide": "TrollHide",
    "needle": "Needle",
    "needles": "Needle",
    "chitin": "Chitin",
    "deer hide": "DeerHide",
    "deerhide": "DeerHide",
    "deer skins": "DeerHide",
    "deer skin": "DeerHide",
    "wolf pelt": "WolfPelt",
    "wolfpelt": "WolfPelt",
    "wolf pelts": "WolfPelt",
    "wolfpelts": "WolfPelt",
    "wolf hide": "WolfPelt",
    "feather": "Feathers",
    "feathers": "Feathers",
    "chain": "Chain",
    "chains": "Chain",
    "ancient bark": "AncientBark",
    "ancientbark": "AncientBark",
    "tar": "Tar",
    "wolf fang": "WolfFang",
    "wolffang": "WolfFang",
    "wolf fangs": "WolfFang",
    "lox pelt": "LoxPelt",
    "loxpelt": "LoxPelt",
    "leather scraps": "LeatherScraps",
    "leatherscraps": "LeatherScraps",
    "root": "Root",
    "roots": "Root",
    "guck": "Guck",
    "ooze": "Ooze",
    "bone fragments": "BoneFragments",
    "bonefragments": "BoneFragments",
    "freeze gland": "FreezeGland",
    "freezegland": "FreezeGland",
    "serpent meat": "SerpentMeat",
    "serpentmeat": "SerpentMeat",
    "serpent scale": "SerpentScale",
    "serpentscale": "SerpentScale",
    "serpent scales": "SerpentScale",
    "linen thread": "LinenThread",
    "linenthread": "LinenThread",
    "linen": "LinenThread",
    "dragon egg": "DragonEgg",
    "dragonegg": "DragonEgg",
    "withered bone": "WitheredBone",
    "withered bones": "WitheredBone",
    "surtling core": "SurtlingCore",
    "surtling cores": "SurtlingCore",
    "bloodbag": "Bloodbag",
    "bloodbags": "Bloodbag",
    "sausages": "Sausages",
    "sausage": "Sausages",
    "turnip": "Turnip",
    "turnips": "Turnip",
    "turnip stew": "TurnipStew",
    "turnipstew": "TurnipStew",
}

SORTED_ALIAS_KEYS = sorted(ITEM_ALIASES.keys(), key=lambda k: len(k), reverse=True)

ITEM_DISPLAY_NAMES = {
    "FineWood": "🌲 Fine Wood",
    "RoundLog": "🪵 Core Wood",
    "Wood": "🪵 Wood",
    "Stone": "🪨 Stone",
    "Flint": "🪨 Flint",
    "Copper": "🥉 Copper Bars",
    "CopperOre": "🥉 Copper Ore",
    "Tin": "⚪ Tin Bars",
    "TinOre": "⚪ Tin Ore",
    "Bronze": "🛡️ Bronze Bars",
    "BronzeNails": "🔩 Bronze Nails",
    "Iron": "⚔️ Iron Bars",
    "IronScrap": "⛓️ Iron Scrap",
    "IronNails": "🔩 Iron Nails",
    "Silver": "🗡️ Silver Bars",
    "SilverOre": "⛏️ Silver Ore",
    "BlackMetal": "🖤 Black Metal Bars",
    "Flametal": "🔥 Flametal Bars",
    "Bloodgold": "🩸 Bloodgold Bars",
    "DeerHide": "🦌 Deer Hide",
    "WolfPelt": "🐺 Wolf Pelt",
    "WolfFang": "🦷 Wolf Fang",
    "LoxPelt": "🦬 Lox Pelt",
    "LeatherScraps": "🟫 Leather Scraps",
    "Feathers": "🪶 Feathers",
    "Chain": "⛓️ Chains",
    "AncientBark": "🪵 Ancient Bark",
    "Tar": "⬛ Tar",
    "Root": "🌱 Roots",
    "Guck": "🟢 Guck",
    "Ooze": "🟣 Ooze",
    "BoneFragments": "🦴 Bone Fragments",
    "FreezeGland": "❄️ Freeze Glands",
    "SerpentMeat": "🥩 Serpent Meat",
    "SerpentScale": "🛡️ Serpent Scales",
    "LinenThread": "🧵 Linen Thread",
    "DragonEgg": "🥚 Dragon Eggs",
    "AncientSeed": "🌱 Ancient Seeds",
    "WitheredBone": "🦴 Withered Bones",
    "SurtlingCore": "🔥 Surtling Cores",
    "Bloodbag": "🩸 Bloodbags",
    "Needle": "🦟 Needles",
    "Chitin": "🐚 Chitin",
    "RawMeat": "🥩 Raw Meat",
    "CookedDeerMeat": "🍖 Cooked Deer Meat",
    "CookedMeat": "🍖 Cooked Boar Meat",
    "Sausages": "🌭 Sausages",
    "Turnip": "🥬 Turnips",
    "TurnipStew": "🍲 Turnip Stew",
    "Carrot": "🥕 Carrots",
    "Honey": "🍯 Honey",
}

ITEM_BIOME_MAP = {
    "FineWood": "Meadows & Black Forest",
    "RoundLog": "Black Forest",
    "Wood": "Meadows",
    "Stone": "Meadows",
    "Flint": "Meadows (Shores)",
    "Copper": "Black Forest",
    "CopperOre": "Black Forest",
    "Tin": "Black Forest (Shores)",
    "TinOre": "Black Forest (Shores)",
    "Bronze": "Black Forest",
    "BronzeNails": "Black Forest",
    "Iron": "Swamp",
    "IronScrap": "Swamp",
    "IronNails": "Swamp",
    "Silver": "Mountains",
    "SilverOre": "Mountains",
    "BlackMetal": "Plains",
    "Flametal": "Ashlands",
    "Bloodgold": "Deep North",
    "DeerHide": "Meadows",
    "WolfPelt": "Mountains",
    "WolfFang": "Mountains",
    "LoxPelt": "Plains",
    "LeatherScraps": "Meadows",
    "Feathers": "Black Forest & Meadows",
    "Chain": "Swamp",
    "AncientBark": "Swamp",
    "Tar": "Plains",
    "Root": "Swamp",
    "Guck": "Swamp",
    "Ooze": "Swamp",
    "BoneFragments": "Black Forest & Swamp",
    "FreezeGland": "Mountains",
    "SerpentMeat": "Ocean",
    "SerpentScale": "Ocean",
    "LinenThread": "Plains",
    "DragonEgg": "Mountains",
    "AncientSeed": "Black Forest",
    "WitheredBone": "Swamp",
    "SurtlingCore": "Black Forest & Swamp",
    "Bloodbag": "Swamp",
    "Needle": "Plains",
    "Chitin": "Ocean",
}

# Explicit Quest Opt-Out Directives (Anti-Pattern #4: Hierarchical Condition Priority)
QUEST_OPT_OUT_PATTERNS = [
    r"\b(?:this\s+is\s+|it(?:\x27s|\s+is)\s+)?not\s+(?:meant\s+to\s+be\s+|supposed\s+to\s+be\s+)?(?:an?\s+)?(?:clan\s+|active\s+|server\s+|in[- ]game\s+)?quest\b",
    r"\b(?:this\s+|it\s+)?isn\x27?t\s+(?:meant\s+to\s+be\s+)?(?:an?\s+)?(?:clan\s+|active\s+)?quest\b",
    r"\bnot\s+meant\s+(?:as|for)\s+(?:an?\s+)?quest\b",
    r"\bnot\s+for\s+(?:an?\s+)?quest\b",
    r"\bno\s+quest(?:s)?(?:\s+(?:needed|please|pls|bro|yaar))?\b",
    r"\b(?:don\x27?t|do\s+not)\s+(?:make|turn|add|create|log|register|post)(?:\s+(?:it|this))?(?:\s+into|\s+as)?\s+(?:an?\s+)?quest\b",
    r"\b(?:skip|ignore|bypass)\s+quest(?:s)?\b",
    r"\b(?:ye|yeh|yea|isko|isse)?\s*quest\s+(?:nahi|nai)\s+hai\b",
    r"\bquest\s+mat\s+(?:bana|banao|banana|karna|karo)\b",
    r"\bquest\s+na\s+(?:bana|banao|banana)\b",
    r"\bmat\s+(?:bana|banao|banana)\s+quest\b",
]
QUEST_OPT_OUT_REGEX = re.compile("|".join(QUEST_OPT_OUT_PATTERNS), re.IGNORECASE)

def is_explicit_quest_opt_out(text: str) -> bool:
    """
    Checks if message explicitly requests NOT to be a quest (e.g. 'This is not a quest', 'dont make it a quest').
    Guards against Anti-Pattern #4 (Hierarchical Condition Priority).
    """
    if not text or not isinstance(text, str):
        return False
    return bool(QUEST_OPT_OUT_REGEX.search(text))

def load_api_key():
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return api_key
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return None

def prune_expired_quests(data):
    """
    Checks all active quests. If older than 72 hours, moves them to expired_quests.
    """
    now_t = time.time()
    active = data.get("active_quests", [])
    valid_active = []
    expired = data.setdefault("expired_quests", [])

    for q in active:
        ts = q.get("created_timestamp")
        if not ts and "issued_at" in q:
            try:
                clean_dt = q["issued_at"].replace(" IST", "")
                dt = datetime.strptime(clean_dt, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
                ts = dt.timestamp()
            except Exception:
                ts = now_t

        if ts and (now_t - ts > EXPIRY_SECONDS):
            q["status"] = "EXPIRED"
            q["expired_at"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
            expired.insert(0, q)
        else:
            valid_active.append(q)

    data["active_quests"] = valid_active
    data["expired_quests"] = expired[:20]  # Bound expired to 20
    return data

def load_quests():
    if os.path.exists(QUESTS_FILE):
        try:
            with open(QUESTS_FILE, "r") as f:
                data = json.load(f)
                return prune_expired_quests(data)
        except Exception:
            pass
    return {"active_quests": [], "completed_quests": [], "expired_quests": [], "dropped_quests": []}

def save_quests(data):
    # Bound active quests to 10, completed to 20, expired to 20, dropped to 20
    data["active_quests"] = data.get("active_quests", [])[:10]
    data["completed_quests"] = data.get("completed_quests", [])[:20]
    data["expired_quests"] = data.get("expired_quests", [])[:20]
    data["dropped_quests"] = data.get("dropped_quests", [])[:20]
    with open(QUESTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_quest_intent_prompt(sender_name="Hilda"):
    sender_name = str(sender_name or "Hilda").strip()
    return f"""You are the Norse Questmaster of the Valheim 10 realm (30+ Gamers clan).
Your task is to analyze messages sent by clan leader "{sender_name}" in the clan WhatsApp group.

Determine if the message contains a GENUINE, EXPLICIT CALL-TO-ARMS, collective clan objective, or resource request directed at OTHER clan members.

CRITICAL ANTI-SPAM & INTENT GUARDRAILS:
You MUST return {{"is_quest": false}} if the message matches ANY of the following:
0. EXPLICIT OPT-OUT OR DISCLAIMER: If the message contains ANY statement indicating it is NOT a quest (e.g., "This is not a quest", "dont make it a quest", "don't make this a quest", "not a quest", "no quest"), you MUST return {{"is_quest": false}} immediately. NEVER override the sender's explicit instruction!
1. SOLO / FIRST-PERSON INTENT: {sender_name} talking about what THEY personally intend to do (e.g., "I'll farm blood bags today", "I'm going to mine copper", "Will nurse seeds to 100 first", "logging on in 20 mins"). Personal tasks are NOT clan quests!
2. CASUAL CONVERSATION & BANTER: Greetings, laughs ("haha", "lol", "lmao", laughing emojis 🤣), Hinglish chatter ("arre bhai", "chalo done", "sahi hai"), or scheduling ("brb", "gn", "will join at 9").
3. GAME THEORY & MECHANICS DISCUSSION: Comparing base designs, discussing mob stats ("golems are trolls on steroids", "double resources from 1 star boars", "making pen bigger is inefficient", "carrying 6 copper for forge"). General gaming talk is NOT a decree!
4. META-COMMENTARY: Any mention of AI, bots, Jira, story points, project managers, or discussing previous quest notifications.

WHEN TO CREATE A QUEST:
ONLY return {{"is_quest": true, ...}} when {sender_name} is CLEARLY and INTENTIONALLY asking the clan or teammates to complete a shared objective (e.g., "Guys, can someone gather 50 bronze?", "We need everyone to stockpile wood at the mountain base before tonight", "Team, let's prep for the Elder raid").

FEW-SHOT CONTRAST EXAMPLES:
- "This is not a quest. Today we battle moder, restock arrows, tankers be tankin, archers be archin. This is not a quest"
  -> {{"is_quest": false}}
- "Dont make it a quest, but guys let us collect some wood for the fire"
  -> {{"is_quest": false}}
- "Ok let's give the mountains meadhall a shot. Arre bhai This AI is like a over enthu project manager Har cheez ke pehle story points daal so Do 🤣🤣🤣"
  -> {{"is_quest": false}}
- "We can't use onions for food anyway I think. Will nurse the seeds to 100+ first. I'll farm blood bags today. Need to find daytime wolves."
  -> {{"is_quest": false}}
- "Wait you mean a full on base? Those guys are trolls on steroids. So when exploring we need to carry 6 copper to upgrade the forge."
  -> {{"is_quest": false}}
- "We need 1 star or 2 star boars. Double resources from 1 star. Making the pen bigger makes it inefficient."
  -> {{"is_quest": false}}
- "Guys we desperately need more bronze for armor and arrows before fighting the Elder tomorrow, can someone mine tin and copper?"
  -> {{"is_quest": true, "quest_title": "The Elder's Reckoning", "quest_type": "Metallurgy", "flavor_text": "{sender_name} calls upon the clan to forge bronze and craft arrows for the coming battle against the Elder.", "objectives": ["Mine copper and tin to smelt bronze", "Craft bronze armor and fire arrows"], "target_biome": "Black Forest", "bounty_reward": "Glory of Valhalla and Elder spoils", "trackable_items": {{"Bronze": 30}}}}

If the message IS a genuine clan request, return a JSON object with this EXACT structure:
{{
  "is_quest": true,
  "quest_title": "Epic Norse Title (e.g. The Bronze Vanguard, Decree of {sender_name})",
  "quest_type": "Metallurgy" | "Homestead" | "Boss Raid" | "Pantry" | "Odyssey" | "Armoury" | "Hunting",
  "flavor_text": "1-2 sentence dramatic Norse context explaining why {sender_name} calls upon the clan",
  "objectives": [
    "Clear, concise bullet point 1",
    "Clear, concise bullet point 2 (optional)"
  ],
  "target_biome": "Meadows" | "Black Forest" | "Swamp" | "Ocean" | "Mountain" | "Plains",
  "bounty_reward": "Thematic Norse reward (e.g. Glory of Valhalla + First pick of Crypt spoils)",
  "trackable_items": {{
    "ItemPrefab": target_amount_int
  }}
}}

Output ONLY the JSON object. No extra text, no markdown wrappers outside valid JSON."""

QUEST_INTENT_SYSTEM_PROMPT = get_quest_intent_prompt("Hilda")

def normalize_objectives(raw_objs):
    """
    Guards against Anti-Pattern #1 (Polymorphic input normalization).
    Ensures objectives is strictly a list of non-empty strings.
    """
    if isinstance(raw_objs, str):
        raw_objs = [raw_objs]
    elif not isinstance(raw_objs, list):
        raw_objs = []

    cleaned = []
    for x in raw_objs:
        if isinstance(x, (str, int, float)):
            s = str(x).strip()
            if len(s) > 0:
                cleaned.append(s)
    if not cleaned:
        cleaned = ["Carry out the decree of the Valkyrie"]
    return cleaned

def normalize_trackable_items(raw_items):
    """
    Normalizes trackable items dictionary and maps aliases to canonical Valheim item keys.
    """
    if not isinstance(raw_items, dict):
        return {}
    normalized = {}
    for k, v in raw_items.items():
        if not isinstance(k, str):
            continue
        clean_key = k.strip().lower()
        canonical_key = ITEM_ALIASES.get(clean_key, k.strip())
        try:
            val = int(v)
            if val > 0:
                normalized[canonical_key] = val
        except (ValueError, TypeError):
            continue
    return normalized

def call_gemini_intent(message_text, sender_name="Hilda"):
    api_key = load_api_key()
    if not api_key:
        return None

    sender_name = str(sender_name or "Hilda").strip()
    system_prompt = get_quest_intent_prompt(sender_name)
    models = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-flash-latest"]
    user_prompt = f"Sender: {sender_name}\nMessage: {message_text}"

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        gen_config = {
            "maxOutputTokens": 1024,
            "temperature": 0.2
        }
        if "2.5" in model:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\n---\nMESSAGE TO ANALYZE:\n{user_prompt}"}]
                }
            ],
            "generationConfig": gen_config
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        for attempt in range(1, 3):
            try:
                with safe_urlopen(req, timeout=12) as response:
                    res_body = response.read().decode("utf-8")
                    res_json = json.loads(res_body)
                    text = res_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

                    # Clean json markdown wrappers if present
                    text = text.strip()
                    if text.startswith("```json"):
                        text = text[7:]
                    elif text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
            except Exception as e:
                time.sleep(1)
    return None

def process_quest_message(message_text, sender_name="Hilda"):
    """
    Analyzes message from an authorized clan leader (Hilda, Faye, etc.). If actionable intent is found,
    creates and registers a new quest, returning the formatted WhatsApp text.
    Returns None if not a quest or error.
    """
    clean_text = message_text.strip()
    if not clean_text or len(clean_text) < 5:
        return None

    sender_name = str(sender_name or "Hilda").strip()
    if is_explicit_quest_opt_out(clean_text):
        sys.stderr.write(f"[quest-engine] Explicit opt-out detected from {sender_name} ('not a quest'): skipping quest creation.\n")
        return None

    intent = call_gemini_intent(clean_text, sender_name)
    if not intent or not intent.get("is_quest"):
        return None

    now_ist = datetime.now(IST)
    quest_id = f"Q_{int(time.time())}"
    quest = {
        "id": quest_id,
        "title": str(intent.get("quest_title", f"Decree of {sender_name}")).strip(),
        "type": str(intent.get("quest_type", "Homestead")).strip(),
        "issuer": sender_name,
        "issued_at": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "created_timestamp": time.time(),
        "raw_message": clean_text,
        "flavor_text": str(intent.get("flavor_text", "")).strip(),
        "objectives": normalize_objectives(intent.get("objectives", [])),
        "target_biome": str(intent.get("target_biome", "Black Forest")).strip(),
        "bounty_reward": str(intent.get("bounty_reward", "Honor of Valhalla")).strip(),
        "trackable_items": normalize_trackable_items(intent.get("trackable_items", {})),
        "status": "ACTIVE"
    }

    # Save to storage
    data = load_quests()
    data["active_quests"].insert(0, quest)
    save_quests(data)

    # Format WhatsApp Announcement
    objectives_str = "\n".join([f"   • {obj}" for obj in quest["objectives"]])
    wa_text = (
        f"📜 ⚔️ *[CLAN QUEST ISSUED]* ⚔️ 📜\n"
        f"═══════════════════════════════\n"
        f"👑 *Questgiver:* {quest['issuer']}\n"
        f"🏷️ *Quest:* \"{quest['title']}\" ({quest['type']})\n\n"
        f"_{quest['flavor_text']}_\n\n"
        f"🎯 *Objectives:*\n{objectives_str}\n\n"
        f"🌲 *Target Biome:* {quest['target_biome']}\n"
        f"🎁 *Objective Reward:* {quest['bounty_reward']}\n"
        f"═══════════════════════════════\n"
        f"💡 _Type `!quests` anytime to view active clan objectives._\n"
        f"🗑️ _Was this casual banter or a false alarm? Type `!drop` to discard!_"
    )
    return wa_text

process_hilda_message = process_quest_message

def parse_quest_line(line):
    if line is None or not isinstance(line, str):
        return None, 0
    line = line.strip().strip('-*• ')
    if not line:
        return None, 0

    # Pattern A: "item ... = total" or "item ... * ... = total"
    # e.g. "finewood 40 *6= 240" or "finewood 40*6 = 240" or "feathers 10 *6= 60"
    m_eq = re.search(r'=\s*(\d+)\s*$', line)
    if m_eq:
        total = int(m_eq.group(1))
        prefix = line[:m_eq.start()].strip()
        for k in SORTED_ALIAS_KEYS:
            if k in prefix.lower():
                return ITEM_ALIASES[k], total

    # Pattern B: "item count * mult" or "item count x mult"
    # e.g. "finewood 40 * 6" or "finewood 40x6"
    m_mult = re.search(r'(\d+)\s*[\*xX]\s*(\d+)', line)
    if m_mult:
        calc_total = int(m_mult.group(1)) * int(m_mult.group(2))
        for k in SORTED_ALIAS_KEYS:
            if k in line.lower():
                return ITEM_ALIASES[k], calc_total

    # Pattern C: "count * mult = total item"
    # e.g. "40 * 6 = 240 finewood" or "240 finewood"
    m_count_item = re.search(r'(?:=\s*)?(\d+)\s*([a-zA-Z\s]+)$', line)
    if m_count_item:
        cnt = int(m_count_item.group(1))
        item_part = m_count_item.group(2).strip().lower()
        for k in SORTED_ALIAS_KEYS:
            if k in item_part:
                return ITEM_ALIASES[k], cnt

    # Pattern D: "item : count" or "item count"
    for k in SORTED_ALIAS_KEYS:
        pattern = rf'\b{re.escape(k)}\b\s*[:=\-]?\s*(\d+)'
        m_item_cnt = re.search(pattern, line, re.IGNORECASE)
        if m_item_cnt:
            return ITEM_ALIASES[k], int(m_item_cnt.group(1))

    # Pattern E: "count item" at start
    for k in SORTED_ALIAS_KEYS:
        pattern = rf'(\d+)\s*(?:x\s*)?\b{re.escape(k)}\b'
        m_cnt_item = re.search(pattern, line, re.IGNORECASE)
        if m_cnt_item:
            return ITEM_ALIASES[k], int(m_cnt_item.group(1))

    return None, 0

def parse_full_quest_input(text):
    if text is None or not isinstance(text, str):
        return None
    text = text.strip()
    if not text:
        return None
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not raw_lines:
        return None

    first_line = raw_lines[0]
    title = ""
    lines_to_parse = []

    if ':' in first_line:
        parts = first_line.split(':', 1)
        title = parts[0].strip()
        rest = parts[1].strip()
        if rest:
            lines_to_parse.append(rest)
        lines_to_parse.extend(raw_lines[1:])
    elif len(raw_lines) > 1:
        title = first_line
        lines_to_parse.extend(raw_lines[1:])
    else:
        title = first_line
        lines_to_parse = [first_line]

    sub_lines = []
    for l in lines_to_parse:
        if ',' in l and '\n' not in text:
            sub_lines.extend(l.split(','))
        else:
            sub_lines.append(l)

    trackable = {}
    for sl in sub_lines:
        item, cnt = parse_quest_line(sl)
        if item and cnt > 0:
            trackable[item] = trackable.get(item, 0) + cnt

    # Clean title from any leading !quest
    title = re.sub(r'^[!\/]+\s*(?:quests?|givequest|addquest|newquest)\s*', '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r':$', '', title).strip()
    if not title:
        title = "Clan Objective"

    return {
        "title": title.title(),
        "trackable_items": trackable,
        "raw_text": text
    }

def create_custom_quest(raw_text, issuer_name="A Viking Warrior"):
    """
    Parses a manually issued clan quest, extracts multipliers/materials,
    compares against live clan chest stock, registers it to valheim_active_quests.json,
    and returns a formatted WhatsApp announcement.
    """
    if issuer_name is None or not isinstance(issuer_name, str):
        issuer_name = str(issuer_name or "A Viking Warrior")
    clean_iss = str(issuer_name).strip().replace("@s.whatsapp.net", "").replace("@lid", "").replace("@g.us", "").lstrip("+")
    clean_iss = re.sub(r':\d+$', '', clean_iss)
    clan_map = {
        "919810573357": "Faye", "9810573357": "Faye", "277592460538005": "Faye",
        "917815011234": "Hilda", "7815011234": "Hilda", "6778179829957": "Hilda",
        "917016862977": "Dexter", "7016862977": "Dexter", "91049112391871": "Dexter",
        "918971274710": "Musashi(Musa Bhai)", "8971274710": "Musashi(Musa Bhai)",
    }
    if clean_iss in clan_map:
        issuer_name = clan_map[clean_iss]
    elif clean_iss.isdigit() or clean_iss.startswith("12036") or clean_iss in ("Viking", "A Viking Warrior"):
        issuer_name = "Dexter" if clean_iss in ("120363426206773037", "917016862977", "91049112391871", "7016862977") else "A Viking Warrior"
    else:
        issuer_name = clean_iss

    if is_explicit_quest_opt_out(raw_text):
        return "⚠️ *[Quest Cancelled]* The decree explicitly states this is not a quest."

    parsed = parse_full_quest_input(raw_text)
    if not parsed:
        return "⚠️ *[Valheim Quest Error]* Could not understand quest details."

    title = parsed["title"]
    trackable = parsed["trackable_items"]

    # Infer quest type
    lower_text = raw_text.lower()
    if any(k in lower_text for k in ["bed", "beds", "furniture", "hearth", "table", "chair", "rug", "banner", "homestead", "base", "cabin", "hall", "farm", "pen", "gate", "wall", "roof", "dock", "house"]):
        quest_type = "Homestead"
    elif any(k in lower_text for k in ["armor", "armour", "shield", "helmet", "sword", "mace", "bow", "arrows", "spear"]):
        quest_type = "Armoury"
    elif any(k in lower_text for k in ["iron", "copper", "tin", "bronze", "silver", "blackmetal", "smelt", "forge", "ore", "bars"]):
        quest_type = "Metallurgy"
    elif any(k in lower_text for k in ["meat", "food", "sausage", "stew", "soup", "honey", "turnip", "carrot", "pantry", "feast"]):
        quest_type = "Pantry"
    elif any(k in lower_text for k in ["boat", "karve", "longship", "sail", "ocean", "sea", "island", "voyage", "explore", "map"]):
        quest_type = "Odyssey"
    elif any(k in lower_text for k in ["elder", "bonemass", "moder", "yagluth", "eikthyr", "queen", "boss", "raid"]):
        quest_type = "Boss Raid"
    elif any(k in lower_text for k in ["wolf", "boar", "deer", "troll", "serpent", "hunt", "kill", "slay"]):
        quest_type = "Hunting"
    else:
        quest_type = "Homestead"

    # Infer biomes (clean & canonical order)
    canonical_biomes = ["Meadows", "Black Forest", "Swamp", "Mountains", "Plains", "Mistlands", "Ashlands", "Deep North", "Ocean"]
    biomes_present = set()
    for item_key in trackable.keys():
        b_str = ITEM_BIOME_MAP.get(item_key, "")
        for cb in canonical_biomes:
            if cb.lower() in b_str.lower():
                biomes_present.add(cb)
    sorted_biomes = [b for b in canonical_biomes if b in biomes_present]
    target_biome = ", ".join(sorted_biomes) if sorted_biomes else "The Realm"

    # Objectives list
    objectives = []
    if trackable:
        for k, v in trackable.items():
            name = ITEM_DISPLAY_NAMES.get(k, k)
            clean_name = re.sub(r'^[^\w\s]+\s*', '', name)
            objectives.append(f"Stockpile {v}x {clean_name}")
    else:
        first_clean = re.sub(r'^[!\/]+\s*(?:quests?|givequest|addquest|newquest)\s*', '', raw_text.strip().split('\n')[0], flags=re.IGNORECASE).strip()
        objectives.append(first_clean or "Carry out the clan objective")

    # Scan current inventory
    inventory_totals = {}
    try:
        from valheim_info import scan_world_inventory
        inv_res = scan_world_inventory()
        inventory_totals = inv_res[0] if isinstance(inv_res, tuple) else (inv_res or {})
    except Exception:
        inventory_totals = {}

    all_fulfilled = False
    if trackable:
        all_fulfilled = all(inventory_totals.get(k, 0) >= req for k, req in trackable.items())

    now_ist = datetime.now(IST)
    quest_id = f"Q_{int(time.time())}"
    flavor_text = f"Decree issued by {issuer_name}. Gather the requested supplies and stockpile them into clan chests!"
    bounty_reward = "Glory of Valhalla & Clan Renown"

    quest = {
        "id": quest_id,
        "title": title,
        "type": quest_type,
        "issuer": issuer_name,
        "issued_at": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
        "created_timestamp": time.time(),
        "raw_message": raw_text.strip(),
        "flavor_text": flavor_text,
        "objectives": objectives,
        "target_biome": target_biome,
        "bounty_reward": bounty_reward,
        "trackable_items": trackable,
        "status": "COMPLETED" if all_fulfilled else "ACTIVE"
    }

    data = load_quests()
    if all_fulfilled:
        quest["completed_at"] = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
        quest["completed_by"] = "The Clan"
        data.setdefault("completed_quests", []).insert(0, quest)
        save_quests(data)

        lines = [
            "🎉 ⚔️ *[CLAN QUEST ALREADY FULFILLED!]* ⚔️ 🎉",
            "═══════════════════════════════",
            f"👑 *Questgiver:* {issuer_name}",
            f"🏷️ *Quest:* \"{title}\" ({quest_type})",
            "",
            f"_{issuer_name} issued a decree, but clan chests already hold all requested materials!_",
            "",
            "🎯 *Vault Stockpile Verification:*"
        ]
        for k, req in trackable.items():
            have = inventory_totals.get(k, 0)
            disp_name = ITEM_DISPLAY_NAMES.get(k, k)
            lines.append(f"   • {disp_name}: {have}/{req} [100%] ✅ (Ready in Chests)")
        lines.append("═══════════════════════════════")
        lines.append("🏆 _All materials accounted for! The decree is fulfilled._")
        return "\n".join(lines)

    data["active_quests"].insert(0, quest)
    save_quests(data)

    lines = [
        "📜 ⚔️ *[CLAN QUEST ISSUED]* ⚔️ 📜",
        "═══════════════════════════════",
        f"👑 *Questgiver:* {issuer_name}",
        f"🏷️ *Quest:* \"{title}\" ({quest_type})",
        "",
        f"_{flavor_text}_",
        ""
    ]

    if trackable:
        lines.append("🎯 *Required Materials & Vault Progress:*")
        for k, req in trackable.items():
            have = inventory_totals.get(k, 0)
            disp_name = ITEM_DISPLAY_NAMES.get(k, k)
            pct = min(100, int((have / req) * 100)) if req > 0 else 100
            if have >= req:
                status = "✅ (Stockpile Ready!)"
            else:
                status = f"⏳ (Need {req - have} more)"
            lines.append(f"   • {disp_name}: {have}/{req} [{pct}%] {status}")
        lines.append("")

    lines.append(f"🌲 *Target Biome:* {target_biome}")
    lines.append(f"🎁 *Objective Reward:* {bounty_reward}")
    lines.append("═══════════════════════════════")
    lines.append("💡 _Type `!quest` to check progress. When deposited into chests, the quest auto-completes!_")
    lines.append("🗑️ _Need to cancel? Type `!drop`_")
    return "\n".join(lines)

def get_active_quests_formatted():
    data = load_quests()
    active = data.get("active_quests", [])
    if not active:
        return (
            "📜 *[Clan Quest Board]*\n\n"
            "The Great Hall is quiet. No active clan objectives currently open.\n"
            "👑 _Type `!quest <mats or task>` to issue a decree anytime!_"
        )

    # Pre-fetch inventory once for live progress display
    inventory_totals = {}
    try:
        from valheim_info import scan_world_inventory
        inv_res = scan_world_inventory()
        inventory_totals = inv_res[0] if isinstance(inv_res, tuple) else (inv_res or {})
    except Exception:
        inventory_totals = {}

    lines = [
        "📜 ⚔️ *VALHEIM CLAN QUEST BOARD* ⚔️ 📜",
        ""
    ]
    for idx, q in enumerate(active, 1):
        title = q.get('title', 'Clan Quest').strip()
        issuer = q.get('issuer', 'Clan Leader').strip()
        issued_at = q.get('issued_at', '')
        date_str = ""
        if issued_at:
            try:
                parts = issued_at.split()
                if parts:
                    dt = datetime.strptime(parts[0], "%Y-%m-%d")
                    date_str = f" ({dt.strftime('%d %b')})"
            except Exception:
                date_str = ""

        objs = " | ".join(q.get("objectives", [])).strip()
        lines.append(f"• *#{idx} — {title}*")
        if objs and objs.lower() != title.lower():
            lines.append(f"  _{issuer}{date_str}:_ {objs}")
        else:
            lines.append(f"  _Issued by {issuer}{date_str}_")

        trackable = q.get("trackable_items", {})
        if trackable:
            progress_parts = []
            for item_key, req_amt in trackable.items():
                have_amt = inventory_totals.get(item_key, 0)
                disp_name = ITEM_DISPLAY_NAMES.get(item_key, item_key)
                status = "✅ Ready" if have_amt >= req_amt else f"⏳ Need {req_amt - have_amt} more"
                progress_parts.append(f"{disp_name}: {have_amt}/{req_amt} ({status})")
            lines.append(f"  📦 *Progress:* {', '.join(progress_parts)}")

        lines.append("")

    lines.append("💡 _Type `!done <number>` to complete, or `!drop <number>` to discard._")
    return "\n".join(lines)

def complete_quest(index=1, completed_by="A Viking Warrior"):
    """
    Marks an active quest as completed by index (1-based).
    Moves it to completed_quests archive and returns celebration text.
    """
    data = load_quests()
    active = data.get("active_quests", [])
    if not active:
        return (
            "📜 *[Clan Quest Board]*\n\n"
            "There are currently no active quests to complete!\n"
            "💡 _Type `!quests` to check the quest board._"
        )

    if index < 1 or index > len(active):
        return (
            f"⚠️ *[Invalid Quest Number]*\n\n"
            f"Quest #{index} does not exist. There are currently {len(active)} active quest(s).\n"
            f"💡 _Type `!quests` to see active quest numbers._"
        )

    idx = index - 1
    now_ist = datetime.now(IST)
    quest = active.pop(idx)
    quest["status"] = "COMPLETED"
    quest["completed_at"] = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    quest["completed_by"] = completed_by

    data.setdefault("completed_quests", []).insert(0, quest)
    save_quests(data)

    return (
        f"🎉 ⚔️ *[CLAN QUEST COMPLETED]* ⚔️ 🎉\n"
        f"═══════════════════════════════\n"
        f"🏆 *Quest:* \"{quest.get('title', 'Clan Quest')}\"\n"
        f"👑 *Issued By:* {quest.get('issuer', 'Clan Leader')}\n"
        f"🛡️ *Fulfilled By:* {completed_by}\n"
        f"🎁 *Objective Reward Claimed:* {quest.get('bounty_reward', 'Honor of Valhalla')}\n"
        f"═══════════════════════════════\n"
        f"💡 _Type `!quests` to view remaining active objectives._"
    )

HILARIOUS_DROP_ROASTS = [
    (
        "🗑️ 📜 *[QUEST EXPUNGED & TORN FROM THE SAGA]* 📜 🗑️\n"
        "═══════════════════════════════\n"
        "🏆 *Discarded Quest:* \"{title}\"\n"
        "👑 *Revoked By:* {dropped_by}\n\n"
        "🧙‍♂️ *The Skald's Apology:*\n"
        "\"Odin forgive us—the AI Skald acted like an over-enthusiastic Agile Project Manager assigning story points to tavern banter! 🤦‍♂️📋\n\n"
        "The parchment has been cast into the great hearth fire. The Ravens have been ordered to stand down, and no warrior shall be dispatched into the cold for mere casual chit-chat!\"\n"
        "═══════════════════════════════\n"
        "{remaining_text}"
    ),
    (
        "🗑️ 📜 *[DECREE REVOKED: TAVERN GOSSIP]* 📜 🗑️\n"
        "═══════════════════════════════\n"
        "🏆 *Discarded Quest:* \"{title}\"\n"
        "👑 *Revoked By:* {dropped_by}\n\n"
        "🧙‍♂️ *The Skald's Apology:*\n"
        "\"By Thor's hammer, the scribe overheard idle mead-hall talk and drafted a 5-chapter blood oath! 📜🔥\n\n"
        "The scribes have been whipped with wet kelp, the Jira sprint has been wiped clean, and Hilda's peace is restored. Resume drinking, Vikings!\"\n"
        "═══════════════════════════════\n"
        "{remaining_text}"
    ),
    (
        "🗑️ 📜 *[ODIN CANCELS THE SPRINT]* 📜 🗑️\n"
        "═══════════════════════════════\n"
        "🏆 *Discarded Quest:* \"{title}\"\n"
        "👑 *Revoked By:* {dropped_by}\n\n"
        "🧙‍♂️ *The Skald's Apology:*\n"
        "\"Alert: The over-caffeinated Valkyrie has been forcefully dragged away from the quest scroll board! 🦅🏃💨\n\n"
        "It was just normal longhouse talk, not a holy crusade. The quest has been fed to the wolves, the story points refunded, and order reigns once more in Midgard.\"\n"
        "═══════════════════════════════\n"
        "{remaining_text}"
    ),
    (
        "🗑️ 📜 *[SCRAPED OFF THE RUNESTONE]* 📜 🗑️\n"
        "═══════════════════════════════\n"
        "🏆 *Discarded Quest:* \"{title}\"\n"
        "👑 *Revoked By:* {dropped_by}\n\n"
        "🧙‍♂️ *The Skald's Apology:*\n"
        "\"Hugin and Munin flew down from Asgard shaking their feathered heads: *'Bro, she was just spitballing base ideas, chill out.'* 🤦‍♀️🦅\n\n"
        "The fresh chisel marks have been buffed out with beeswax. No bronze will be wasted today!\"\n"
        "═══════════════════════════════\n"
        "{remaining_text}"
    ),
    (
        "🗑️ 📜 *[FALSE ALARM: WARRIORS STAND DOWN]* 📜 🗑️\n"
        "═══════════════════════════════\n"
        "🏆 *Discarded Quest:* \"{title}\"\n"
        "👑 *Revoked By:* {dropped_by}\n\n"
        "🧙‍♂️ *The Skald's Apology:*\n"
        "\"The AI Skald mistook casual mead-fueled brainstorming for a royal decree from the High Throne. 👑➡️🗑️\n\n"
        "Order of the Day: Sheath your swords, extinguish the war torches, and put the over-eager scribe in timeout.\"\n"
        "═══════════════════════════════\n"
        "{remaining_text}"
    ),
    (
        "🗑️ 📜 *[RETRACTED TO THE MEAD BENCH]* 📜 🗑️\n"
        "═══════════════════════════════\n"
        "🏆 *Discarded Quest:* \"{title}\"\n"
        "👑 *Revoked By:* {dropped_by}\n\n"
        "🧙‍♂️ *The Skald's Apology:*\n"
        "\"Turns out nobody actually needed to risk their life in the snow for that. The AI has been dunked into a trough of icy mountain water to sober up. 🍺❄️\n\n"
        "False alarm expunged from clan memory!\"\n"
        "═══════════════════════════════\n"
        "{remaining_text}"
    )
]

def drop_quest(index=1, dropped_by="A Viking Warrior"):
    """
    Drops/cancels an active quest by index (1-based, defaults to 1 / most recent).
    Moves it to dropped_quests archive and returns a hilarious Skald apology roast.
    """
    data = load_quests()
    active = data.get("active_quests", [])
    if not active:
        return (
            "📜 *[Clan Quest Board]*\n\n"
            "There are currently no active quests to drop! The questboard is already clean.\n"
            "💡 _Type `!quests` to check active clan objectives._"
        )

    if index < 1 or index > len(active):
        return (
            f"⚠️ *[Invalid Quest Number]*\n\n"
            f"Quest #{index} does not exist. There are currently {len(active)} active quest(s).\n"
            f"💡 _Type `!quests` to see active quest numbers, or type `!drop` to discard the latest quest._"
        )

    idx = index - 1
    now_ist = datetime.now(IST)
    quest = active.pop(idx)
    quest["status"] = "DROPPED"
    quest["dropped_at"] = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    quest["dropped_by"] = dropped_by

    data.setdefault("dropped_quests", []).insert(0, quest)
    save_quests(data)

    rem_count = len(active)
    if rem_count == 0:
        remaining_text = "🍻 _The Great Hall is now quiet. Zero active quests remain._"
    elif rem_count == 1:
        remaining_text = "🍻 _1 active clan quest remains. Type `!quests` to view._"
    else:
        remaining_text = f"🍻 _{rem_count} active clan quests remain. Type `!quests` to view._"

    template = random.choice(HILARIOUS_DROP_ROASTS)
    safe_data = SafeFormatDict({
        "title": quest.get("title", "Clan Quest"),
        "dropped_by": dropped_by,
        "remaining_text": remaining_text
    })
    formatted = template.format_map(safe_data)
    # Clean any leftover braces per Anti-Pattern #2
    return re.sub(r'\{[a-zA-Z0-9_]+\}', '', formatted)

def check_quest_inventory_completion(inventory_totals):
    """
    Checks if any active quest with trackable_items has been completed
    by the current inventory in clan chests.
    Returns list of formatted completion messages if any quest was fulfilled.
    """
    if isinstance(inventory_totals, tuple):
        inventory_totals = inventory_totals[0] if len(inventory_totals) > 0 else {}
    if not isinstance(inventory_totals, dict):
        inventory_totals = {}

    data = load_quests()
    active = data.get("active_quests", [])
    completed_messages = []
    remaining_active = []

    # Pre-normalize inventory keys to lower-case for robust lookup
    inv_lower = {str(k).lower(): v for k, v in inventory_totals.items()}

    for q in active:
        trackable = q.get("trackable_items", {})
        if isinstance(trackable, dict) and trackable:
            fulfilled = True
            for item, req_count in trackable.items():
                # Check exact key first, then lowercase match
                cnt = inventory_totals.get(item, inv_lower.get(str(item).lower(), 0))
                if cnt < req_count:
                    fulfilled = False
                    break

            if fulfilled:
                now_ist = datetime.now(IST)
                q["status"] = "COMPLETED"
                q["completed_at"] = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
                q["completed_by"] = "The Clan"
                data.setdefault("completed_quests", []).insert(0, q)

                msg = (
                    f"🎉 ⚔️ *[CLAN QUEST COMPLETED]* ⚔️ 🎉\n"
                    f"═══════════════════════════════\n"
                    f"🏆 *Quest:* \"{q.get('title', 'Clan Quest')}\"\n"
                    f"👑 *Issued By:* {q.get('issuer', 'Clan Leader')}\n"
                    f"🛡️ *Fulfilled By:* The Clan (Vault Stockpiles Verified)\n"
                    f"🎁 *Objective Reward Claimed:* {q.get('bounty_reward', 'Honor of Valhalla')}\n"
                    f"═══════════════════════════════\n"
                    f"💡 _Type `!quests` to view remaining active objectives._"
                )
                completed_messages.append(msg)
                continue

        remaining_active.append(q)

    if completed_messages:
        data["active_quests"] = remaining_active
        save_quests(data)

    return completed_messages

if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--list":
            print(get_active_quests_formatted())
        elif arg in ("--complete", "--done"):
            q_num = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 1
            by_user = sys.argv[3] if len(sys.argv) > 3 else "A Viking Warrior"
            print(complete_quest(q_num, by_user))
        elif arg in ("--drop", "--cancel", "--discard", "--abandon"):
            q_num = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 1
            by_user = sys.argv[3] if len(sys.argv) > 3 else "A Viking Warrior"
            print(drop_quest(q_num, by_user))
        elif arg in ("--create", "--add", "--give"):
            issuer = "A Viking Warrior"
            text_args = []
            i = 2
            while i < len(sys.argv):
                if sys.argv[i] in ("--issuer", "-i") and i + 1 < len(sys.argv):
                    issuer = sys.argv[i + 1]
                    i += 2
                else:
                    text_args.append(sys.argv[i])
                    i += 1

            if text_args and text_args[0] == "-":
                msg = sys.stdin.read().strip()
            elif text_args:
                msg = " ".join(text_args).strip()
            else:
                msg = sys.stdin.read().strip()
            print(create_custom_quest(msg, issuer))
        elif arg == "--process":
            # Direct processing mode for bridge.js (outputs only WhatsApp text or NO_QUEST)
            issuer = "Hilda"
            text_args = []
            i = 2
            while i < len(sys.argv):
                if sys.argv[i] in ("--issuer", "-i") and i + 1 < len(sys.argv):
                    issuer = sys.argv[i + 1]
                    i += 2
                else:
                    text_args.append(sys.argv[i])
                    i += 1

            if text_args and text_args[0] == "-":
                msg = sys.stdin.read().strip()
            elif text_args:
                msg = "\n".join(text_args).strip()
            else:
                msg = sys.stdin.read().strip()
            res = process_quest_message(msg, issuer)
            if res:
                print(res)
            else:
                print("NO_QUEST")
        elif arg == "--test":
            issuer = "Hilda"
            text_args = []
            i = 2
            while i < len(sys.argv):
                if sys.argv[i] in ("--issuer", "-i") and i + 1 < len(sys.argv):
                    issuer = sys.argv[i + 1]
                    i += 2
                else:
                    text_args.append(sys.argv[i])
                    i += 1

            test_msg = " ".join(text_args) or "Guys we desperately need more bronze for armor and arrows before fighting the elder"
            print(f"Testing message from {issuer}: {test_msg}")
            res = process_quest_message(test_msg, issuer)
            print("\nResult:")
            print(res or "Ignored (Not a quest)")
    else:
        print("Usage: valheim_quest_engine.py [--list | --create <text> [--issuer <name>] | --complete <num> [user] | --drop <num> [user] | --process <message> [--issuer <name>] | --test <message> [--issuer <name>]]")
