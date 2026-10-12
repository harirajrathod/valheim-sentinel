#!/usr/bin/env python3
"""
/root/valheim_voice.py - Valheim Norse Voice Engine & Audio Dispatcher
Powered by Edge-TTS (Zero-CPU, 100% Free Cloud Neural Synthesis)

Features:
- Norse Character Cast: Skald (Lorekeeper), Odin (Allfather), Valkyrie (Combat), Blacksmith (Forge)
- Audio generation with pitch/rate cadence tuning
- Direct WhatsApp native voice note (PTT) dispatch via Hermes bridge (/send-media)
- Daily Chronicle Saga narration
- Real-Time Gameplay Alerts: Horn of War Raid Sirens, Boss Defeat War-Cries, and Odin's Eulogies
- Cooldown-protected to ensure zero chat spam
"""

import os
import sys
import re
import time
import tempfile
import asyncio
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional, Union

sys.path.insert(0, "/root")
from valheim_utils import (
    VALHEIM_WHATSAPP_GROUP,
    WHATSAPP_BRIDGE_URL,
    format_player_name,
    safe_load_json,
    atomic_save_json,
    safe_urlopen,
    IST
)

VOICE_CACHE_DIR = "/root/.cache/valheim_voice"

# --- Norse Character Cast & Voice Profiles ---
NORSE_CAST = {
    # 1. Allfather — Ancient, commanding, ominous
    "allfather": {
        "voice": "en-US-ChristopherNeural",
        "pitch": "-20Hz",
        "rate": "-18%",
        "volume": "+0%",
        "title": "Odin the Allfather",
        "role": "Ancient, commanding, ominous — Slow, gravelly, deliberate pauses"
    },
    "odin": {  # Alias
        "voice": "en-US-ChristopherNeural",
        "pitch": "-20Hz",
        "rate": "-18%",
        "volume": "+0%",
        "title": "Odin the Allfather",
        "role": "Ancient, commanding, ominous"
    },
    "skald": {  # Alias
        "voice": "en-US-ChristopherNeural",
        "pitch": "-20Hz",
        "rate": "-18%",
        "volume": "+0%",
        "title": "The Ancient Skald",
        "role": "Ancient saga chronicler & lore-keeper"
    },

    # 2. Male Viking Warrior — Berserker
    "berserker": {
        "voice": "en-US-GuyNeural",
        "pitch": "-12Hz",
        "rate": "-5%",
        "volume": "+5%",
        "title": "The Berserker",
        "role": "Male Viking Warrior — Rugged, forceful, battle-ready"
    },
    "warrior": {  # Alias
        "voice": "en-US-GuyNeural",
        "pitch": "-12Hz",
        "rate": "-5%",
        "volume": "+5%",
        "title": "The Berserker",
        "role": "Male Viking Warrior"
    },

    # 3. Female Viking Warrior — Shieldmaiden
    "shieldmaiden": {
        "voice": "en-US-AriaNeural",
        "pitch": "-5Hz",
        "rate": "-8%",
        "volume": "+0%",
        "title": "The Shieldmaiden",
        "role": "Female Viking Warrior — Strong, grounded, crisp emphasis"
    },

    # 4. Valkyrie — Celestial Warrior
    "valkyrie": {
        "voice": "en-GB-SoniaNeural",
        "pitch": "+5Hz",
        "rate": "-12%",
        "volume": "+0%",
        "title": "The Valkyrie",
        "role": "Celestial Warrior — Majestic, ethereal, otherworldly"
    },

    # 5. Dark Norse God — Grim Warlord
    "warlord": {
        "voice": "en-GB-RyanNeural",
        "pitch": "-15Hz",
        "rate": "-12%",
        "volume": "+0%",
        "title": "Tyr the Grim Warlord",
        "role": "Dark Norse God — Grave, intimidating, authoritative"
    },
    "tyr": {  # Alias
        "voice": "en-GB-RyanNeural",
        "pitch": "-15Hz",
        "rate": "-12%",
        "volume": "+0%",
        "title": "Tyr the Grim Warlord",
        "role": "Dark Norse God"
    },

    # 6. Norse Seeress — Völva
    "volva": {
        "voice": "en-US-MichelleNeural",
        "pitch": "-8Hz",
        "rate": "-18%",
        "volume": "-3%",
        "title": "The Völva",
        "role": "Norse Seeress — Mystical, whispered prophecy & fate"
    },
    "seeress": {  # Alias
        "voice": "en-US-MichelleNeural",
        "pitch": "-8Hz",
        "rate": "-18%",
        "volume": "-3%",
        "title": "The Völva",
        "role": "Norse Seeress"
    },

    # Bonus: Master Smith
    "blacksmith": {
        "voice": "en-IE-ConnorNeural",
        "pitch": "-4Hz",
        "rate": "-6%",
        "volume": "+0%",
        "title": "The Master Smith",
        "role": "Gruff Celtic forge master & resource updates"
    }
}

VOICE_STATE_FILE = "/root/valheim_voice_state.json"
DEFAULT_EULOGY_COOLDOWN = 900  # 15 minutes between audio eulogies
DEFAULT_RAID_COOLDOWN = 300    # 5 minutes between audio raid horns


# --- Text Sanitization for Speech ---

def clean_text_for_speech(text: str) -> str:
    """
    Cleans raw markdown and game formatting into natural spoken English.
    Strips dividers, formatting markers, and decorative emojis so the TTS
    engine reads smooth narrative sentences without stumbling.
    """
    if not text:
        return ""
    
    # If list/iterable passed, normalize
    if isinstance(text, (list, tuple)):
        text = " ".join(str(item) for item in text)
    else:
        text = str(text)

    # Remove code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`.*?`", "", text)

    # Remove headers and divider lines
    text = re.sub(r"^[=\-_#*~]{3,}.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[═─━▬]{3,}", "", text)

    # Remove specific chronicle structural markers
    text = re.sub(r"📜\s*\*?STORY TIME:[^\n]*\*?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"_The Skald's quill rests until the morrow\._[^\n]*", "", text, flags=re.IGNORECASE)

    # Strip emoji & symbol characters that don't pronounce cleanly
    # (Matches common unicode emoji ranges)
    text = re.sub(
        r"[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf\ufe00-\ufe0f\u200d\u25a0-\u25ff\u2b50-\u2b59]",
        "",
        text
    )

    # Strip bold / italics / strikethrough markers
    text = re.sub(r"[*_~]", "", text)

    # Clean bullet points
    text = re.sub(r"^\s*[•\-\*]\s*", "", text, flags=re.MULTILINE)

    # Normalize whitespace
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text).strip()

    return text


# --- Synthesis Engine (edge-tts) ---

async def _synthesize_async(
    text: str,
    character: str = "skald",
    output_path: Optional[str] = None
) -> Optional[str]:
    """
    Async edge-tts synthesis worker with timeout guard.
    """
    import edge_tts

    char_key = character.lower().strip() if character else "skald"
    profile = NORSE_CAST.get(char_key, NORSE_CAST["skald"])

    if not output_path:
        os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
        fd, output_path = tempfile.mkstemp(prefix=f"valheim_{char_key}_", suffix=".mp3", dir=VOICE_CACHE_DIR)
        os.close(fd)

    communicate = edge_tts.Communicate(
        text=text,
        voice=profile["voice"],
        pitch=profile.get("pitch", "+0Hz"),
        rate=profile.get("rate", "+0%"),
        volume=profile.get("volume", "+0%")
    )
    await communicate.save(output_path)
    return output_path


def generate_voice(
    text: str,
    character: str = "skald",
    output_path: Optional[str] = None,
    timeout: int = 25
) -> Optional[str]:
    """
    Generates a spoken audio clip using Edge-TTS.
    Runs synchronously and returns the absolute path to the generated MP3 file,
    or None if generation fails.
    """
    cleaned = clean_text_for_speech(text)
    if not cleaned:
        sys.stderr.write("[valheim_voice] Error: Empty text after cleaning.\n")
        return None

    try:
        # Run async worker cleanly in current or new loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                target_path = pool.submit(
                    lambda: asyncio.run(asyncio.wait_for(_synthesize_async(cleaned, character, output_path), timeout=timeout))
                ).result()
        else:
            target_path = asyncio.run(
                asyncio.wait_for(_synthesize_async(cleaned, character, output_path), timeout=timeout)
            )

        if target_path and os.path.exists(target_path) and os.path.getsize(target_path) > 0:
            return target_path
        return None
    except Exception as e:
        sys.stderr.write(f"[valheim_voice] Synthesis failed ({character}): {e}\n")
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        return None


# --- WhatsApp Audio Dispatcher ---

def send_voice_to_whatsapp(
    file_path: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP,
    bridge_url: str = WHATSAPP_BRIDGE_URL,
    timeout: int = 20,
    retries: int = 2
) -> bool:
    """
    Dispatches an audio file to the WhatsApp group via Hermes gateway /send-media.
    The bridge automatically converts the audio to Opus OGG and delivers it as
    a native playable WhatsApp Voice Bubble (PTT).
    """
    if not file_path or not os.path.exists(file_path):
        sys.stderr.write(f"[valheim_voice] Cannot dispatch: audio file not found {file_path}\n")
        return False

    media_endpoint = bridge_url.replace("/send", "/send-media")
    payload = {
        "chatId": chat_id,
        "filePath": os.path.abspath(file_path),
        "mediaType": "audio"
    }
    encoded = json.dumps(payload).encode("utf-8")

    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(
                media_endpoint,
                data=encoded,
                headers={"Content-Type": "application/json"}
            )
            with safe_urlopen(req, timeout=timeout) as resp:
                if 200 <= resp.status < 300:
                    print(f"[valheim_voice] Successfully dispatched voice note to {chat_id}")
                    return True
        except Exception as e:
            sys.stderr.write(f"[valheim_voice] Dispatch attempt {attempt} failed: {e}\n")
            if attempt <= retries:
                time.sleep(1.5)

    return False


def speak_to_whatsapp(
    text: str,
    character: str = "skald",
    chat_id: str = VALHEIM_WHATSAPP_GROUP,
    auto_cleanup: bool = True
) -> bool:
    """
    End-to-end helper: synthesizes speech and immediately posts it
    as a WhatsApp voice bubble. Cleans up temporary audio file on completion.
    """
    audio_path = generate_voice(text, character=character)
    if not audio_path:
        return False

    try:
        success = send_voice_to_whatsapp(audio_path, chat_id=chat_id)
        return success
    finally:
        if auto_cleanup and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception:
                pass


# --- Feature 2: Daily Chronicle Narration ---

def extract_story_from_chronicle(chronicle_text: str) -> str:
    """
    Extracts the narrative saga portion from a full daily chronicle.
    """
    if not chronicle_text:
        return ""

    # Look for STORY TIME section
    m = re.search(r"📜\s*\*?STORY TIME:[^\n]*\*?\n[═─━▬\n]*(.*?)(?:\n\s*_The Skald's quill rests|\Z)", chronicle_text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Fallback: if no STORY TIME header found, return chronicle text
    return chronicle_text.strip()


def narrate_daily_chronicle(
    chronicle_text: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Synthesizes the morning story section into a spoken Skald saga and
    delivers it directly as a native voice note into WhatsApp.
    """
    story = extract_story_from_chronicle(chronicle_text)
    if not story:
        print("[valheim_voice] No narrative story found to narrate in chronicle.")
        return False

    print(f"[valheim_voice] Narrating Daily Chronicle Saga with {NORSE_CAST['skald']['title']}...")
    return speak_to_whatsapp(story, character="skald", chat_id=chat_id, auto_cleanup=True)


# --- Feature 3: Real-Time Gameplay Event Voice Proclamations ---

def _check_and_update_cooldown(event_key: str, cooldown_seconds: int) -> bool:
    """
    Helper to prevent audio alert spam.
    Returns True if allowed to proceed, False if cooldown active.
    """
    state = safe_load_json(VOICE_STATE_FILE, default={})
    last_t = state.get(event_key, 0)
    now_t = time.time()
    if now_t - last_t < cooldown_seconds:
        return False
    state[event_key] = now_t
    atomic_save_json(VOICE_STATE_FILE, state)
    return True


RAID_SPEECH_LINES = {
    "foresttrolls": "Sound the Horn of War! The earth shakes beneath our feet! Trolls march upon the Longhouse! To arms, warriors!",
    "army_bonemass": "A foul stench rises from the swamp! Blobs and skeletons swarm the gates! Draw your maces and hold the line!",
    "army_theelder": "The forest is moving! Greydwarves and brutes pour from the woods! Defend the hearth!",
    "wolves": "Hunters beware! You are being hunted! The wolf pack circles the clearing! Stand together!",
    "army_eikthyr": "Eikthyr rallies the beasts of the woods! Boars charge the gates! Stand firm!",
    "army_moder": "A freezing wind howls from the peaks! Mountain drakes descend upon our halls! Ready your bows!",
    "army_goblin": "The goblin horde attacks! Fulings with torches swarm the perimeter! Protect the farm!",
    "army_yagluth": "The goblin horde attacks! Fulings with torches swarm the perimeter! Protect the farm!",
    "army_queen": "They sought you out! Seekers and brood swarm from the mists! Brace your shields!",
    "army_fader": "The Charred march! Ashlands legions surge with fire and bone! Extinguish their advance!",
    "skeletons": "Skeleton surprise! The undead rise from the soil! Smash them back into the earth!",
    "surtlings": "A stench of sulfur in the air! Surtlings advance with fire! Extinguish the invaders!",
    "bats": "You stirred the cauldron! A swarm of cave bats descends from the gloom! Swat them from the sky!",
    "ghosts": "A cold chill runs down your spine! Spectres and wraiths glide from the darkness! Hold fast against the dead!"
}

def speak_raid_alert(
    raid_key: str,
    defenders: Optional[List[str]] = None,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Fires the Valkyrie's 'Horn of War' audio battle siren into WhatsApp.
    Protected by cooldown to ensure zero duplicate alerts.
    """
    if not _check_and_update_cooldown("raid_horn", DEFAULT_RAID_COOLDOWN):
        print(f"[valheim_voice] Raid horn cooldown active, skipping voice alert for {raid_key}.")
        return False

    line = RAID_SPEECH_LINES.get(
        raid_key,
        "Warriors of Valheim! The Horn of War sounds! Hostile forces assault the stronghold! Defend the Longhouse!"
    )
    
    if defenders:
        clean_defenders = [format_player_name(d) for d in defenders if d]
        if clean_defenders:
            if len(clean_defenders) == 1:
                line += f" {clean_defenders[0]}, the defense of the realm rests upon your shoulders!"
            else:
                line += f" {', '.join(clean_defenders[:-1])} and {clean_defenders[-1]}, to the battlements!"

    print(f"[valheim_voice] Valkyrie War Horn triggered for raid: {raid_key}")
    return speak_to_whatsapp(line, character="valkyrie", chat_id=chat_id, auto_cleanup=True)


BOSS_NAMES = {
    "defeated_eikthyr": "Eikthyr the Great Stag",
    "defeated_gdking": "The Elder of the Forest",
    "defeated_bonemass": "Bonemass of the Sunken Crypts",
    "defeated_moder": "Moder the Dragon Queen",
    "defeated_dragon": "Moder the Dragon Queen",
    "defeated_writhan": "Moder the Dragon Queen",
    "defeated_yagluth": "Yagluth the Goblin Sorcerer",
    "defeated_goblinking": "Yagluth the Goblin Sorcerer",
    "defeated_queen": "The Seeker Queen of the Mistlands",
    "defeated_seekerking": "The Seeker Queen of the Mistlands",
    "defeated_fader": "Fader the Charred Titan",
    "defeated_fimbulbringer": "Kall Fimbulbringer of the Deep North"
}

def speak_boss_defeat(
    boss_key: str,
    active_players: Optional[List[str]] = None,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Fires Odin's thunderous victory proclamation into WhatsApp upon boss defeat.
    """
    if not _check_and_update_cooldown(f"boss_{boss_key.lower()}", 600):
        print(f"[valheim_voice] Boss defeat proclamation cooldown active for {boss_key}.")
        return False

    boss_name = BOSS_NAMES.get(boss_key.lower(), "The Forsaken Beast")
    
    warriors_str = "our brave warriors"
    if active_players:
        clean_p = [format_player_name(p) for p in active_players if p]
        if clean_p:
            warriors_str = ", ".join(clean_p[:-1]) + (" and " if len(clean_p) > 1 else "") + clean_p[-1]

    proclamation = (
        f"By the thunder of Thor and the glory of Valhalla! "
        f"The mighty beast, {boss_name}, has fallen before {warriors_str}! "
        f"Hang its head upon the sacrificial stones and drink deep from the horn of mead! Skål!"
    )

    print(f"[valheim_voice] Odin Victory Proclamation triggered for {boss_key}")
    return speak_to_whatsapp(proclamation, character="odin", chat_id=chat_id, auto_cleanup=True)


def speak_eulogy(
    player_name: str,
    event_type: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Fires Odin's comedic audio eulogy / roast on high-severity goofy casualties:
    - RAGE_QUIT: Died and immediately disconnected
    - CORPSE_RUN_FAIL: Repeated deaths within 3 minutes
    - SEA_CASUALTY: Shipwreck or drowning in deep waters
    """
    if not _check_and_update_cooldown(f"eulogy_{player_name}", DEFAULT_EULOGY_COOLDOWN):
        return False

    name = format_player_name(player_name)

    if event_type == "CORPSE_RUN_FAIL":
        line = (
            f"The Valkyries weep with exhaustion! {name} charged naked across the plains "
            f"only to donate yet another tombstone to Odin! Put on some troll armor, warrior!"
        )
    elif event_type == "RAGE_QUIT":
        line = (
            f"A warrior has fled the field! {name} tasted combat defeat and vanished into the shadows! "
            f"Rest your blade, warrior, and return when your temper cools!"
        )
    elif event_type == "SEA_CASUALTY":
        line = (
            f"The deep waters have claimed {name}! "
            f"The sea serpents feast upon your gear while your raft floats away into the fog!"
        )
    else:
        return False

    print(f"[valheim_voice] Odin Eulogy triggered for {name} ({event_type})")
    return speak_to_whatsapp(line, character="warlord", chat_id=chat_id, auto_cleanup=True)


def speak_raid_victory(
    raid_key: str,
    flawless: bool = True,
    defenders: Optional[List[str]] = None,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Fires victory speech upon raid completion.
    If flawless: Berserker war shout.
    If casualties suffered: Shieldmaiden rally.
    """
    if not _check_and_update_cooldown("raid_victory", 180):
        return False

    if flawless:
        line = "The invaders are broken! Flawless defense! Raise your shields and drink deep, you magnificent disasters!"
        char = "berserker"
    else:
        line = "The siege has ended. Tend your wounds and repair the palisades. The shieldwall of Midgard stands unbroken."
        char = "shieldmaiden"

    print(f"[valheim_voice] Raid victory voice triggered ({char}, flawless={flawless})")
    return speak_to_whatsapp(line, character=char, chat_id=chat_id, auto_cleanup=True)


def speak_discovery(
    trader_name: str,
    biome: str,
    finder: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Fires the Völva's mystical prophecy whisper upon Trader camp discovery.
    """
    if not _check_and_update_cooldown(f"disc_{trader_name.lower()}", 600):
        return False

    line = f"The mists of the {biome} part... The sanctuary of {trader_name} has revealed itself to {finder}. Seek their goods, warriors of Midgard."
    print(f"[valheim_voice] Völva discovery prophecy triggered for {trader_name}")
    return speak_to_whatsapp(line, character="volva", chat_id=chat_id, auto_cleanup=True)


def speak_hildir_quest(
    dungeon_title: str,
    reward_desc: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Fires the Völva's mystical voice upon returning a lost brass chest to Hildir.
    """
    if not _check_and_update_cooldown(f"hildir_{dungeon_title.lower()}", 600):
        return False

    line = f"The lost brass chest of the {dungeon_title} has returned to Hildir's hearth. New wares of power awaken in her shop."
    print(f"[valheim_voice] Völva Hildir quest completion voice triggered for {dungeon_title}")
    return speak_to_whatsapp(line, character="volva", chat_id=chat_id, auto_cleanup=True)


POI_PROPHECIES = {
    "SunkenCrypt": "The ancient dead stir beneath the bogs... A Sunken Crypt has revealed its shadows to {finder}. Ancient iron and draugr await within.",
    "MountainCave": "Ice clings to the mountain stone... A Frost Cave has been unveiled to {finder}. The howling depths call.",
    "FrostCave": "Ice clings to the mountain stone... A Frost Cave has been unveiled to {finder}. The howling depths call.",
    "GoblinCamp": "Torches flicker across the golden grass... A Fuling war-camp has been uncovered in the Plains by {finder}. Danger brews on the frontier.",
    "Fuling": "Torches flicker across the golden grass... A Fuling war-camp has been uncovered in the Plains by {finder}. Danger brews on the frontier.",
    "InfestedMine": "The mist-shrouded ruins crack open... An Infested Mine has been unearthed by {finder}. The black brood slumbers below."
}

def speak_poi_discovery(
    poi_key: str,
    finder: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Option A: Fires the Völva's mystical whispered prophecy upon ancient dungeon / frontier discovery.
    """
    if not _check_and_update_cooldown(f"poi_{poi_key.lower()}", 300):
        return False

    template = POI_PROPHECIES.get(
        poi_key,
        "The veil of the realm thins... An ancient landmark has been revealed to {finder}. Tread carefully in the shadows."
    )
    line = template.format(finder=finder)
    print(f"[valheim_voice] Völva dungeon prophecy triggered for {poi_key} by {finder}")
    return speak_to_whatsapp(line, character="volva", chat_id=chat_id, auto_cleanup=True)


def speak_quest_prophecy(
    issuer: str,
    task: str,
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Option B: Fires the Völva's mystical prophecy decree when a clan quest is issued.
    """
    clean_task = clean_text_for_speech(task)
    words = clean_task.split()
    if len(words) > 25:
        clean_task = " ".join(words[:25]) + "..."
    line = f"A decree is etched into the threads of fate. {issuer} commands: {clean_task}."
    print(f"[valheim_voice] Völva quest decree triggered ({issuer})")
    return speak_to_whatsapp(line, character="volva", chat_id=chat_id, auto_cleanup=True)


def speak_quest_completed(
    completed_by: str,
    quest_num: str = "1",
    chat_id: str = VALHEIM_WHATSAPP_GROUP
) -> bool:
    """
    Option B: Fires the Völva's mystical proclamation when a clan quest is completed.
    """
    line = f"The threads of fate have aligned. The bounty of Midgard is fulfilled by {completed_by}. Honor is recorded upon the runes."
    print(f"[valheim_voice] Völva quest completed voice triggered ({completed_by})")
    return speak_to_whatsapp(line, character="volva", chat_id=chat_id, auto_cleanup=True)


# --- CLI Test / Manual Execution Interface ---

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Valheim Norse Voice Engine")
    parser.add_argument("--speak", type=str, help="Text to synthesize")
    parser.add_argument("--char", type=str, default="skald", choices=list(NORSE_CAST.keys()), help="Norse character persona")
    parser.add_argument("--out", type=str, help="Output MP3 file path")
    parser.add_argument("--post", action="store_true", help="Post directly to WhatsApp group as a voice note")
    parser.add_argument("--test-all", action="store_true", help="Test audio synthesis for all 6 character personas")
    parser.add_argument("--chat-id", type=str, default=VALHEIM_WHATSAPP_GROUP, help="Target WhatsApp Chat ID")
    args = parser.parse_args()

    if args.test_all:
        print("Testing all 6 Norse character personas...")
        for c_key, c_info in NORSE_CAST.items():
            test_line = f"Greetings warriors. I am {c_info['title']}. My role is {c_info['role']}."
            path = generate_voice(test_line, character=c_key)
            if path:
                print(f"[OK] {c_key.upper()} synthesized: {path} ({os.path.getsize(path)} bytes)")
                if args.post:
                    send_voice_to_whatsapp(path, chat_id=args.chat_id)
                try:
                    os.remove(path)
                except Exception:
                    pass
            else:
                print(f"[FAIL] {c_key.upper()} synthesis failed")
        sys.exit(0)

    if args.speak:
        if args.post:
            res = speak_to_whatsapp(args.speak, character=args.char, chat_id=args.chat_id)
            sys.exit(0 if res else 1)
        else:
            path = generate_voice(args.speak, character=args.char, output_path=args.out)
            if path:
                print(f"Generated: {path}")
                sys.exit(0)
            else:
                sys.exit(1)

    parser.print_help()
