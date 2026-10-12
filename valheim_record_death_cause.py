#!/usr/bin/env python3
"""
/root/valheim_record_death_cause.py
Records and updates casualty causes in /root/valheim_deaths_history.json.
Invoked via WhatsApp command (!died, !rip, !death) or directly via CLI.
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone, timedelta

DEATHS_HISTORY_FILE = "/root/valheim_deaths_history.json"
IST = timezone(timedelta(hours=5, minutes=30))
KNOWN_PLAYERS = ["Faye", "Rukia", "Claw", "Hilda", "Dexter", "Musashi", "Musa Bhai", "Musashi(Musa Bhai)"]
PHONE_TO_PLAYER = {
    "919810573357": "Faye",
    "277592460538005": "Faye",
    "917815011234": "Hilda",
    "6778179829957": "Hilda",
    "917016862977": "Dexter",
    "91049112391871": "Dexter",
    "918971274710": "Musashi",
    "8971274710": "Musashi",
}

from valheim_utils import safe_load_json, atomic_save_json, format_player_name

def load_deaths():
    return safe_load_json(DEATHS_HISTORY_FILE, default={})

def save_deaths(data):
    return atomic_save_json(DEATHS_HISTORY_FILE, data)

def parse_iso_or_custom(ts_str):
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    for fmt in ("%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def find_target_death(history, target_player=None, max_age_hours=36):
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=max_age_hours)
    
    candidates = []
    for k, v in history.items():
        ts_str = v.get("timestamp")
        p_name = v.get("player")
        if not ts_str or not p_name:
            continue
        dt = parse_iso_or_custom(ts_str)
        if not dt:
            continue
        if dt < cutoff:
            continue
        if target_player and format_player_name(p_name).lower() != format_player_name(target_player).lower():
            continue
        candidates.append((dt, k, v))
        
    if not candidates:
        return None, None
        
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]

def record_cause(raw_text, sender=None, explicit_player=None):
    history = load_deaths()
    if not history:
        return "⚠️ *[Valheim]* No death history found on server."
        
    text = (raw_text or "").strip()
    
    # Check if text contains a known player name at the beginning
    detected_player = explicit_player
    clean_cause = text
    
    if not detected_player:
        parts = text.split(maxsplit=1)
        if parts:
            first_word = parts[0].strip(":,")
            for kp in KNOWN_PLAYERS:
                if first_word.lower() == kp.lower():
                    detected_player = kp
                    clean_cause = parts[1].strip() if len(parts) > 1 else ""
                    break

    # If still not detected, check sender name against known players or phone numbers
    if not detected_player and sender:
        clean_s = "".join(filter(str.isdigit, str(sender)))
        if clean_s in PHONE_TO_PLAYER:
            detected_player = PHONE_TO_PLAYER[clean_s]
        else:
            for kp in KNOWN_PLAYERS:
                if kp.lower() in sender.lower():
                    detected_player = kp
                    break

    if detected_player:
        detected_player = format_player_name(detected_player)

    # If no cause was given, list recent un-annotated deaths
    if not clean_cause:
        return (
            "⚔️ *[Valheim Casualty Log]*\n\n"
            "To record the cause of death for the chronicle, type:\n"
            "👉 `!died <cause>` (e.g. `!died blob poison in swamp`)\n"
            "👉 `!died <player> <cause>` (e.g. `!died Rukia blob poison in swamp`)"
        )

    # Locate the target death
    target_key, target_entry = find_target_death(history, detected_player)
    
    # If not found with specific player, fall back to the most recent realm death
    if not target_entry and detected_player:
        target_key, target_entry = find_target_death(history, None)

    if not target_entry:
        return (
            f"⚠️ *[Valheim]* No recent death records found in the last 36 hours"
            + (f" for *{format_player_name(detected_player)}*." if detected_player else ".")
        )

    player_name = target_entry.get("player", "Unknown")
    ts_str = target_entry.get("timestamp", "")
    dt = parse_iso_or_custom(ts_str)
    ist_time = dt.astimezone(IST).strftime("%H:%M IST (%d %b)") if dt else ts_str

    target_entry["cause"] = clean_cause
    history[target_key] = target_entry
    
    if save_deaths(history):
        return (
            f"💀 *Casualty Cause Recorded!* 📜\n"
            f"• *Warrior:* *{format_player_name(player_name)}*\n"
            f"• *Time:* _{ist_time}_\n"
            f"• *Fell To:* {clean_cause}\n\n"
            f"_The Skald will weave this true sacrifice into the chronicle annals!_ ⚔️"
        )
    else:
        return "⚠️ *[Valheim]* Failed to save death record to disk."

def main():
    parser = argparse.ArgumentParser(description="Record Valheim casualty cause")
    parser.add_argument("--cause", type=str, help="Cause of death")
    parser.add_argument("--player", type=str, default=None, help="Player name")
    parser.add_argument("--sender", type=str, default=None, help="Sender name from chat")
    parser.add_argument("--list", action="store_true", help="List recent deaths")
    args = parser.parse_args()

    if args.list or not args.cause:
        history = load_deaths()
        recent = []
        now_utc = datetime.now(timezone.utc)
        for k, v in history.items():
            dt = parse_iso_or_custom(v.get("timestamp", ""))
            if dt and (now_utc - dt).total_seconds() <= 86400:
                recent.append((dt, v))
        recent.sort(key=lambda x: x[0], reverse=True)
        if not recent:
            print("No casualties recorded in the last 24h.")
        else:
            lines = ["💀 Recent Valheim Casualties (Last 24h):"]
            for dt, v in recent:
                ist_str = dt.astimezone(IST).strftime("%H:%M IST")
                cause_str = f" — {v.get('cause')}" if v.get("cause") else " — (cause unrecorded)"
                lines.append(f"• {ist_str}: *{format_player_name(v.get('player'))}*{cause_str}")
            print("\n".join(lines))
        return

    result = record_cause(args.cause, sender=args.sender, explicit_player=args.player)
    print(result)

if __name__ == "__main__":
    main()
