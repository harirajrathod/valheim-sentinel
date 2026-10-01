"""
skald/saga_engine.py - Autonomous AI Norse Skald Narrative Synthesis Engine
Transforms raw server telemetry, raids, and casualties into mythic Norse chronicles.
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Dict, Any, List

from core import config

SKALD_SYSTEM_PROMPT = """You are Bragi's Skald, the war-scarred mythic chronicler of the Valheim realm ({server_name}).
Your solemn and fiery duty is to forge today's chapter of the realm's ongoing epic saga.

CRITICAL TONE & THEMATIC DIRECTIVES:

1. ABSOLUTE FACTUAL GROUNDING (ZERO HALLUCINATION & ZERO ENEMY FABRICATIONS):
- The server provides the facts; you provide the mythic Norse voice. NEVER invent enemy creatures, bosses, or biomes absent from the FACT SHEET.
- If a casualty in CASUALTIES TODAY specifies a cause or foe, depict that EXACT encounter with visceral sensory detail.
- If a casualty does NOT mention a specific creature, describe authentic environmental perils of the CURRENT ERA (rain-slicked roots, blinding fog, stamina exhaustion) WITHOUT inventing specific enemy names.
- THE LEGENDARY NAKED CORPSE RUN: When a warrior falls, describe the agonizing panic: waking up in rags with 25 fragile HP, chewing a mouthful of honey or stew, and sprinting blindly into the perilous wilds to snatch their tombstone!
- SQUAD WIPES: When multiple warriors die together, depict the furious back-to-back stand where the shieldwall broke.

2. DYNAMIC REALM INDUSTRY & ECONOMIC TELEMETRY:
- Ground the economic struggle strictly in the clan's CURRENT ERA and Stockpile Telemetry from the fact sheet.
- THE CURSE OF ORE TRANSPORT: Mystical portals reject raw metal and ore. Every pound must be dragged through mud or rough seas on creaking carts and longships.

3. FIERCE CLAN AMBITION:
- Active warriors ({warriors}) are relentless, resilient, and unapologetically ambitious Vikings.
- Length: 200–300 words of gripping, atmospheric prose.
- Output ONLY the narrative prose. No markdown code fences."""

def call_gemini(system_prompt: str, user_prompt: str, max_tokens: int = 2048) -> Optional[str]:
    """Invokes Google Gemini with zero thinking overhead and automatic model fallback."""
    if not config.GEMINI_API_KEY:
        print("[Skald] Notice: GEMINI_API_KEY not configured. Skipping narrative generation.")
        return None

    models = [config.GEMINI_MODEL, "gemini-2.5-flash", "gemini-flash-latest"]
    # Deduplicate while preserving order
    unique_models = []
    for m in models:
        if m and m not in unique_models:
            unique_models.append(m)

    for model in unique_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={config.GEMINI_API_KEY}"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\n---\nFACT SHEET:\n{user_prompt}"}]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens or 2048,
                "temperature": 0.7,
                "thinkingConfig": {"thinkingBudget": 0}
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        for attempt in range(1, 3):
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    break  # Try next model
                if attempt < 2:
                    time.sleep(2)
            except Exception:
                if attempt < 2:
                    time.sleep(2)

    return None

def generate_saga_chronicle(
    fact_sheet: str,
    active_warriors: Optional[List[str]] = None,
    server_name: Optional[str] = None
) -> Optional[str]:
    """Generates an authentic Norse saga chronicle from empirical gameplay facts."""
    s_name = server_name or config.VALHEIM_SERVER_NAME
    warriors_str = ", ".join(active_warriors) if active_warriors else "The Clan Warriors"
    
    prompt = SKALD_SYSTEM_PROMPT.format(
        server_name=s_name,
        warriors=warriors_str
    )
    return call_gemini(prompt, fact_sheet)
