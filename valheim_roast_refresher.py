#!/usr/bin/env python3
"""
/root/valheim_roast_refresher.py
Weekly AI Valheim Roast Refresher.

Uses Gemini 2.5 Flash to generate fresh, razor-sharp Viking roasts
for player session events and appends them to /root/valheim_dynamic_roasts.json.
Runs weekly (Sunday nights) so login/logout roasts continuously evolve and never get stale.

Features:
- Atomic, corruption-free JSON persistence
- Safe schema validation and normalization
- Multi-model retry & exponential back-off
- Comprehensive --dry-run preview mode
"""

import os
import sys
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.error
import re
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

sys.path.insert(0, "/root")
from valheim_utils import (
    load_env,
    safe_load_json,
    atomic_save_json,
    safe_urlopen,
    IST
)

DYNAMIC_ROASTS_FILE = "/root/valheim_dynamic_roasts.json"

CATEGORIES: List[Tuple[str, str]] = [
    ("RAID_CASUALTY_army_theelder", "Greydwarf horde/brutes raid death, rock-throwing pinecone harassment"),
    ("RAID_CASUALTY_foresttrolls", "Troll tree-trunk club flattening, smashed longhouse, blue brute humiliation"),
    ("RAID_CASUALTY_wolves", "Wolf pack hunt on freezing mountain, becoming wolf puppy chow"),
    ("RAID_CASUALTY_skeletons", "Skeleton Surprise, clobbered by smiling bones and calcium enthusiasts"),
    ("RAID_CASUALTY_bats", "Stirred the Cauldron, nibbled to death in dark by annoying flying cave bats"),
    ("RAID_CASUALTY_army_bonemass", "Swamp raid, toxic green blob poison, smelling like rotting sewage"),
    ("RAID_SURVIVOR", "Flawless raid defense, holding the shieldwall with zero casualties, drinking horns raised"),
    ("CORPSE_RUN_FAIL", "Naked corpse run death with 25 HP, running in panic without pants to retrieve tombstone"),
    ("RAGE_QUIT", "Violent Alt+F4 or sudden ethernet yank seconds after taking a fatal hit"),
    ("WILDERNESS_DEATH", "Falling birch tree 1v1, starvation cliff fall, or accidental environmental death"),
    ("SEA_VOYAGE", "Paddling Karve/Longship against headwind for an hour, wet boots, sea serpent paranoia"),
    ("SEA_CASUALTY", "Capsized in ocean waves, drowned in sea, or boat wrecked on ocean voyage"),
    ("MARATHON_GRIND", "Obsessive 2-hour OCD building/roof snapping or mining copper in the pitch black rain"),
    ("QUICK_DIP", "Cowardly <5 min retreat, peeked in, saw dark/rain, and noped out to desktop immediately")
]


def load_dynamic_roasts() -> Dict[str, Any]:
    return safe_load_json(DYNAMIC_ROASTS_FILE, default={})


def save_dynamic_roasts(data: Dict[str, Any]) -> bool:
    return atomic_save_json(DYNAMIC_ROASTS_FILE, data)


def query_gemini(prompt: str, api_key: str) -> Optional[str]:
    models = ["gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-flash-latest"]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        gen_config: Dict[str, Any] = {
            "response_mime_type": "application/json",
            "maxOutputTokens": 2048,
            "temperature": 0.85
        }
        if "2.5" in model:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        for attempt in range(1, 3):
            try:
                with safe_urlopen(req, timeout=25) as resp:
                    res = json.loads(resp.read())
                    text = res["candidates"][0]["content"]["parts"][0]["text"]
                    return text.strip()
            except urllib.error.HTTPError as e:
                sys.stderr.write(f"[RoastRefresher] {model} API error ({e.code}): {e.reason}\n")
                if e.code == 429:
                    break
                if attempt < 2:
                    time.sleep(2 * attempt)
            except Exception as e:
                sys.stderr.write(f"[RoastRefresher] Error on {model} (attempt {attempt}/2): {e}\n")
                if attempt < 2:
                    time.sleep(2 * attempt)
    return None


def refresh_roasts(dry_run: bool = False) -> bool:
    env = load_env()
    api_key = env.get("GEMINI_API_KEY")
    if not api_key:
        sys.stderr.write("ERROR: GEMINI_API_KEY not found in /root/.env\n")
        return False

    cat_desc = "\n".join([f"- {k}: {desc}" for k, desc in CATEGORIES])
    prompt = f"""You are an elite, irreverent Viking skald generating comedic roasts for a private Valheim gaming server WhatsApp group.
Write 1 fresh, highly creative, razor-sharp roast pair (one "leave" message and one "resume" message) for each of these 14 player situations:

{cat_desc}

Strict Requirements:
- WhatsApp formatting: Always include *{{name}}* for the player name. Optional placeholders: {{duration_mins}}, {{deaths}}.
- Start each message with a relevant emoji (e.g. 🪦, ⚔️, 🧌, 🐺, ⛵, 🌊, 🔨, 💀, 🔌).
- Maximum 1 sentence per message. Punchy, witty, dry Norse/Viking humor. Roasting the player with sensory details.
- Return a JSON object mapping each situation key to an object with "leave": ["<leave roast>"] and "resume": ["<resume roast>"]. Do NOT output markdown code fences or placeholder dots.
"""

    print(f"[{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}] Requesting fresh weekly roasts from Gemini (dry_run={dry_run})...")
    response_text = query_gemini(prompt, api_key)
    if not response_text:
        sys.stderr.write("Failed to get response from Gemini API.\n")
        return False

    # Extract JSON from markdown fences if present
    clean_json = response_text
    m_fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
    if m_fence:
        clean_json = m_fence.group(1).strip()

    try:
        new_roasts = json.loads(clean_json)
    except Exception as e:
        sys.stderr.write(f"Failed to parse JSON: {e}\nRaw output:\n{response_text[:300]}...\n")
        return False

    current_data = load_dynamic_roasts()
    added_leave = 0
    added_resume = 0

    valid_keys = {k for k, _ in CATEGORIES}

    def normalize_roast(text: str) -> str:
        s = text.strip()
        if "*{name}*" not in s and "{name}" in s:
            s = re.sub(r'(?<!\*)\{name\}(?!\*)', '*{name}*', s)
        return s

    for cat_key, pair in new_roasts.items():
        if not isinstance(pair, dict) or cat_key not in valid_keys:
            continue
        if cat_key not in current_data:
            current_data[cat_key] = {"leave": [], "resume": []}

        leaves = pair.get("leave", [])
        if isinstance(leaves, str):
            leaves = [leaves]
        elif not isinstance(leaves, list):
            leaves = []

        for l_msg in leaves:
            if isinstance(l_msg, str) and len(l_msg.strip()) > 5:
                clean_m = normalize_roast(l_msg)
                if clean_m not in current_data[cat_key]["leave"]:
                    if dry_run:
                        print(f"  [DRY RUN] +LEAVE ({cat_key}): {clean_m}")
                    else:
                        current_data[cat_key]["leave"].append(clean_m)
                    added_leave += 1

        resumes = pair.get("resume", [])
        if isinstance(resumes, str):
            resumes = [resumes]
        elif not isinstance(resumes, list):
            resumes = []

        for r_msg in resumes:
            if isinstance(r_msg, str) and len(r_msg.strip()) > 5:
                clean_m = normalize_roast(r_msg)
                if clean_m not in current_data[cat_key]["resume"]:
                    if dry_run:
                        print(f"  [DRY RUN] +RESUME ({cat_key}): {clean_m}")
                    else:
                        current_data[cat_key]["resume"].append(clean_m)
                    added_resume += 1

        # Cap each pool to top 25 recent roasts
        if not dry_run:
            current_data[cat_key]["leave"] = current_data[cat_key]["leave"][-25:]
            current_data[cat_key]["resume"] = current_data[cat_key]["resume"][-25:]

    total_dynamic = sum(
        len(v.get("leave", [])) + len(v.get("resume", []))
        for k, v in current_data.items()
        if isinstance(v, dict)
    )

    if dry_run:
        print(f"\n[DRY RUN] Would add {added_leave} leave and {added_resume} resume roasts. Total in pool would be: {total_dynamic}")
        return True

    current_data["_last_refreshed_at"] = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    save_dynamic_roasts(current_data)
    print(f"Successfully added {added_leave} leave and {added_resume} resume roasts. Total dynamic roasts in pool: {total_dynamic}")

    log_msg = f"Valheim Weekly Roast Refresh: Injected {added_leave + added_resume} fresh AI roasts into template pool (total dynamic: {total_dynamic})"
    subprocess.run(["bash", "/root/log.sh", "add", log_msg], check=False)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly AI Valheim Roast Refresher")
    parser.add_argument("--dry-run", action="store_true", help="Preview generated roasts without saving")
    parser.add_argument("--force", action="store_true", help="Force refresh immediately")
    args = parser.parse_args()

    success = refresh_roasts(dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
