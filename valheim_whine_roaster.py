#!/usr/bin/env python3
"""
/root/valheim_whine_roaster.py
------------------------------
Viking Whine & Complaint Roaster:
Delivers savage, hilarious, smart Viking roasts (~25 words) when players
complain or whine about the game.
"""

import sys
import os
import re
import json
import random
import urllib.request

sys.path.insert(0, "/root")
from valheim_utils import safe_urlopen

# Curated, Lore-Accurate Viking Roasts — EVERY SINGLE ONE IS AROUND 25 WORDS (SMART & WITTY)
CURATED_25_WORD_ROASTS = {
    "tree": [
        "You challenged a stationary piece of timber to a duel, forgot gravity existed, and somehow managed to let the tree win. Newton remains undefeated in Valheim.",
        "Felling ancient pines requires basic spatial awareness, warrior. Standing downhill while the trunk snaps like an angry battering ram is just aggressive natural selection at work.",
        "The tree had zero armor, zero movement speed, and telegraphed its fall with loud creaking. Yet here you are, picking splinters out of your dented helmet.",
        "You survived trolls and burial crypts only to get squashed by a falling birch branch because you were staring at your stamina bar. Pure tactical comedy.",
    ],
    "mosquito": [
        "A winged bug the size of a teacup punctured your entire Viking lineage because you sprinted across the Plains in leather pants with zero stamina remaining.",
        "Deathsquitos don't care about your brave reputation. Next time, try raising a bronze buckler or eating real food instead of foraging for yellow mushrooms like a lost toddler.",
        "You heard the buzzing, panicked like a fresh fawn, drained your stamina jumping over barley, and took a two-hundred damage needle straight between the shoulder blades.",
        "Running naked into the Plains to recover your corpse without eating sausages was your own brilliant tactical plan. Don't blame the needle bug for your foolishness.",
    ],
    "stamina": [
        "You entered combat with three raspberries in your stomach, no Rested buff, and soaking wet. Your stamina bar crawled like a slug and you blame Odin?",
        "Stamina management is not complicated, warrior. Stop bunny-hopping across the meadows in full iron armor like an over-caffeinated goat, and cook some actual wolf skewers.",
        "You swung three times, exhausted your lungs, and stood frozen like a wooden statue while a greydwarf threw a common stone directly into your forehead.",
        "Cold, wet, hungry, and out of breath. You didn't die in battle; you died of gross negligence. Build a campfire and learn how nutrition works.",
    ],
    "swamp": [
        "Your gravestone has spent more time marinating in murky swamp water than your actual character. Brew some poison resistance mead before swimming with hungry leeches!",
        "You waded knee-deep into dark water without a hoe, got your boots stuck in the muck, and let a floating green blob dissolve your health bar.",
        "Bonemass is laughing in his bubbling cauldron while you sprint through the rain with wet socks, no poison mead, and zero stamina. Peak swamp tactics.",
        "Leeches consider your naked corpse run an all-you-can-eat buffet. Level the ground with a hoe next time, or keep feeding the muck your finest gear.",
    ],
    "iron": [
        "Real Vikings haul muddy scrap iron through the rain in dignified silence. Whining in WhatsApp will not smelt twenty bars or repair your chipped bronze pickaxe.",
        "You sailed across the ocean for three muddy scrap, broke your only pickaxe on the first vein, and forgot wood for a workbench. Absolute masterclass in logistics.",
        "The Sunken Crypts don't care about your aching spine. Grab your antler pickaxe, clear the ancient muck, and row the Karve home like a true champion.",
        "You mined four hundred pounds of heavy scrap, realized you cannot teleport raw ore through portals, and sat sobbing on your cart in the pouring rain.",
    ],
    "boat": [
        "The wind turned against you because the Allfather grew tired of listening to your naval whining. Drop your sail and learn how tacking actually works, sailor.",
        "Your Karve is currently resting at the seabed feeding barnacles because you sailed into an ocean storm with half durability and no cooked meat aboard.",
        "A sea serpent nibbled on your rudder and you panicked, jumped into deep water, and drowned with a full inventory of coins. Poseidon is deeply embarrassed.",
        "You beached your longship on a shallow rock at full speed, broke the hull into floating planks, and blamed the tide. Truly inspirational Viking seamanship.",
    ],
    "boss": [
        "You summoned an ancient Forsaken entity, brought wooden arrows to a blunt-damage fight, and wondered why the titan turned your shieldwall into decorative firewood.",
        "The altar demanded a sacrifice, and clearly you volunteered yourself. Next time read the biome scrolls, drink your potions, and learn how to dodge roll properly.",
        "Standing directly inside Bonemass's toxic vomit cloud without poison resistance mead is not bravery, warrior; it is just a very fast shortcut to a naked corpse run.",
        "The boss telegraphed that massive attack for three full seconds, and you chose to stand there admiring your stamina bar. Valhalla is weeping with laughter.",
    ],
    "general": [
        "Blaming game physics and hitboxes will not drag your tombstone out of that draugr nest. Eat proper food, check your armor, and swing with purpose.",
        "You died again because you panic-rolled five times, ran out of breath, and took a club to the skull. Try breathing between attacks next time.",
        "Even the greydwarves outside your palisade have better battle discipline than you. Put on some pants, eat some sausages, and reclaim your dignity from the dirt.",
        "Odin surveyed your recent combat log, shook his head in solemn disappointment, and ordered the Valkyries to take their sweet time picking up your soul.",
    ]
}
CURATED_10_WORD_ROASTS = CURATED_25_WORD_ROASTS

# Regex patterns to detect game whining/complaining in passive chat
COMPLAINT_PATTERNS = [
    r'\b(?:lost|losted)\s+(?:all\s+)?(?:my\s+)?(?:stuff|gear|items|inventory|loot|boat|tombstone)\b',
    r'\bdied\s+(?:again|to\s+a\s+tree|to\s+deathsquito|to\s+mosquito|to\s+poison|to\s+blobs?|to\s+fall)\b',
    r'\b(?:hate|sucks?|fuck|fucking|broken|annoying|unfair|trash|garbage)\s+(?:this\s+)?(?:game|valheim|stamina|swamp|plains|mistlands|physics|mechanics?)\b',
    r'\b(?:stamina\s+sucks|out\s+of\s+stamina|running\s+out\s+of\s+stamina|no\s+stamina|zero\s+stamina)\b',
    r'\b(?:stupid|damn|cursed|annoying)\s+(?:deathsquito|mosquito|tree|trees|golem|serpent|leech|troll)\b',
    r'\b(?:falling\s+tree|tree\s+fell\s+on\s+me|crushed\s+by\s+tree)\b',
    r'\b(?:boat\s+sank|karve\s+sank|longship\s+sank|ship\s+destroyed)\b',
    r'\b(?:iron\s+grind|grinding\s+iron|mining\s+copper\s+is\s+torture|too\s+much\s+grind)\b',
    r'\b(?:skill\s+drain|corpse\s+run\s+sucks|death\s+run|tombstone\s+recovery)\b',
    r'\b(?:rage\s*quit|uninstalled|uninstalling|done\s+with\s+this\s+game)\b',
]

def is_game_complaint(text):
    """
    Returns True if the text matches a Valheim complaint pattern.
    """
    if not text or len(text.strip()) < 5:
        return False
    lower = text.lower()
    for pattern in COMPLAINT_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False

def categorize_complaint(text):
    lower = text.lower()
    if re.search(r'\b(?:tree|trees|falling|log|timber)\b', lower):
        return "tree"
    if re.search(r'\b(?:mosquito|deathsquito|needle|plains)\b', lower):
        return "mosquito"
    if re.search(r'\b(?:stamina|exhausted|tired|run out of stamina|hunger|food|starv)\b', lower):
        return "stamina"
    if re.search(r'\b(?:swamp|poison|leech|blob|bonemass|wet|crypt)\b', lower):
        return "swamp"
    if re.search(r'\b(?:iron|mine|mining|ore|smelt|grind|scrap)\b', lower):
        return "iron"
    if re.search(r'\b(?:boat|ship|karve|sail|sailing|sink|sank|serpent|ocean|drown)\b', lower):
        return "boat"
    return "general"

def load_api_key():
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return api_key
    env_file = "/root/.env"
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return None

def generate_ai_roast(complaint_text, sender_name="Viking"):
    """
    Attempts to generate a savage, smart, witty ~25-word roast via Gemini Flash (0 thinking).
    Enforces a strict word count range (18 to 30 words) referencing Valheim mechanics.
    If it fails, returns None for curated fallback.
    """
    api_key = load_api_key()
    if not api_key:
        return None

    prompt = (
        f"A Valheim warrior named {sender_name} just whined or complained: \"{complaint_text}\".\n"
        "You are an ancient, sarcastic Viking Skald. Write a savage, hilarious, smart, and witty roast addressing them.\n"
        "Reference real Valheim survival mechanics (e.g. food tiers, Rested buff, stamina management, hoe leveling, parry timing, poison mead, dodge rolling, portal restrictions, or gravity).\n"
        "CRITICAL LENGTH RULE: Your output MUST be around 25 words (STRICTLY between 18 and 30 words total). Count your words carefully.\n"
        "Do not include quotes, markdown formatting, or preamble. Return ONLY the raw roast text."
    )

    models = ["gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-flash-latest"]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 128,
                "temperature": 0.8,
                "thinkingConfig": {"thinkingBudget": 0} if "2.5" in model else {}
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with safe_urlopen(req, timeout=6) as response:
                res_body = response.read().decode("utf-8")
                res_json = json.loads(res_body)
                text = res_json.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                clean = re.sub(r'["\n\r]', ' ', text).strip()
                clean = re.sub(r'\s+', ' ', clean)
                words = clean.split()
                if 18 <= len(words) <= 30:
                    return clean
        except Exception:
            pass
    return None

# Backward compatibility alias
generate_ai_10_word_roast = generate_ai_roast

def get_roast(complaint_text="", sender_name="Viking"):
    """
    Returns a smart, witty ~25-word Viking roast.
    Checks AI first; if not within 18-30 words or times out, uses curated ~25-word list.
    """
    category = categorize_complaint(complaint_text)
    
    # Try dynamic generation if non-empty complaint provided
    if complaint_text and len(complaint_text.strip()) > 8:
        ai_roast = generate_ai_roast(complaint_text, sender_name)
        if ai_roast:
            words = ai_roast.split()
            if 18 <= len(words) <= 30:
                return ai_roast

    # Curated fallback guaranteed around 25 words
    pool = CURATED_25_WORD_ROASTS.get(category, CURATED_25_WORD_ROASTS["general"])
    roast = random.choice(pool)
    return roast

# Backward compatibility alias
get_10_word_roast = get_roast

CLAN_MEMBER_NAMES = {
    "919810573357": "Faye",
    "277592460538005": "Faye",
    "917815011234": "Hilda",
    "6778179829957": "Hilda",
    "917016862977": "Dexter",
    "91049112391871": "Dexter",
    "918971274710": "Musashi(Musa Bhai)",
    "8971274710": "Musashi(Musa Bhai)",
}

def clean_sender_name(sender_name: str) -> str:
    if not sender_name:
        return ""
    clean = str(sender_name).strip().replace("@s.whatsapp.net", "").replace("@lid", "").replace("@g.us", "")
    clean = re.sub(r':\d+$', '', clean)
    if clean in CLAN_MEMBER_NAMES:
        return CLAN_MEMBER_NAMES[clean]
    # If it's a group ID, pure digits, or generic title, do not output raw numbers
    if clean.isdigit() or clean.startswith("12036") or clean in ("Viking", "A Viking Warrior"):
        return ""
    return clean

def format_whatsapp_roast(roast_text, sender_name=""):
    """
    Formats the ~25-word roast for WhatsApp.
    Never exposes raw phone numbers, group IDs, or socket IDs.
    """
    clean_name = clean_sender_name(sender_name)
    if clean_name:
        return f"⚔️ *[Skald's Rebuke]*\n*{clean_name}*: \"{roast_text}\""
    return f"⚔️ *[Skald's Rebuke]*\n\"{roast_text}\""

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Valheim Whine & Complaint Roaster (~25 words)")
    parser.add_argument("complaint", nargs="*", help="Complaint text to roast (positional)")
    parser.add_argument("--roast", nargs="*", help="Complaint text to roast (flag)")
    parser.add_argument("--sender", default="Viking", help="Name of the complaining warrior")
    parser.add_argument("--detect", nargs="*", help="Check if text is a game complaint")
    args = parser.parse_args()

    if args.detect is not None:
        det_text = " ".join(args.detect)
        print("COMPLAINT" if is_game_complaint(det_text) else "NOT_COMPLAINT")
    else:
        text = " ".join(args.complaint) if args.complaint else (" ".join(args.roast) if args.roast else "")
        resolved_name = clean_sender_name(args.sender) or "Viking"
        roast = get_roast(text, resolved_name)
        print(format_whatsapp_roast(roast, args.sender))


