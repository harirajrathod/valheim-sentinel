"""
skald/daily_chronicle.py - 24-Hour Battle Journal & Automated Realm Digest
Compiles playtimes, casualties, raids, and stockpiles, optionally appending AI Skald lore.
"""

import os
import re
import argparse
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Tuple, Optional
from collections import defaultdict

from core import config
from core import notifier
from telemetry.db_parser import ValheimWorldParser
from telemetry.world_state import get_world_progress
from skald.saga_engine import generate_saga_chronicle

# Valheim server log timestamp format: MM/DD/YYYY HH:MM:SS
LOG_TS_PATTERN = re.compile(r'^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}):')
LOG_TS_FORMAT = "%m/%d/%Y %H:%M:%S"

def parse_log_timestamp(line: str) -> Optional[datetime]:
    """Extracts UTC timestamp from a Valheim server log line."""
    m = LOG_TS_PATTERN.match(line)
    if m:
        try:
            return datetime.strptime(m.group(1), LOG_TS_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def analyze_recent_activity(hours: int = 24) -> Dict[str, Any]:
    """Parses server log for warrior sessions, casualties, and raids over the past N hours."""
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=hours)

    # Session tracking
    active_since: Dict[str, datetime] = {}   # name -> join timestamp
    player_sessions: Dict[str, List[Tuple[datetime, datetime]]] = defaultdict(list)
    casualties: Dict[str, int] = defaultdict(int)
    raids: List[Tuple[datetime, str]] = []
    all_deaths: List[Tuple[datetime, str]] = []
    active_warriors: List[str] = []
    join_code = "Unknown"

    if not os.path.exists(config.VALHEIM_LOG_FILE):
        return {
            "playtimes": {},
            "casualties": {},
            "raids": [],
            "active_warriors": [],
            "join_code": join_code,
            "all_deaths": []
        }

    try:
        with open(config.VALHEIM_LOG_FILE, 'r', errors='ignore') as f:
            for line in f:
                # Extract join code (always update to latest)
                m_code = re.search(r'Session \"[^\"]+\" with join code\s+([A-Za-z0-9]+)', line)
                if m_code:
                    join_code = m_code.group(1)

                dt = parse_log_timestamp(line)
                if not dt:
                    continue
                if dt < cutoff:
                    continue

                # Player join: "Got character ZDOID from PlayerName : ..."
                # Non-zero ZDOID = alive join, 0:0 ZDOID = death
                m_join = re.search(r'Got character ZDOID from ([^:]+) : (-?\d+):(\d+)', line)
                if m_join:
                    pname = m_join.group(1).strip()
                    zdoid_a = m_join.group(2)
                    zdoid_b = m_join.group(3)

                    if zdoid_a == "0" and zdoid_b == "0":
                        # ZDOID 0:0 = player death
                        if pname and pname != "0":
                            casualties[pname] = casualties.get(pname, 0) + 1
                            all_deaths.append((dt, pname))
                    else:
                        # Live join / respawn
                        if pname not in active_warriors:
                            active_warriors.append(pname)
                        # Close any existing session (reconnect)
                        if pname in active_since:
                            start_t = active_since.pop(pname)
                            dur = (dt - start_t).total_seconds()
                            if 0 < dur <= 14400:  # Cap sessions at 4h
                                player_sessions[pname].append((start_t, dt))
                        active_since[pname] = dt

                # Player disconnect patterns
                # Pattern 1: "Destroying abandoned non persistent zdo"
                m_leave1 = re.search(r'Destroying abandoned non persistent zdo.*', line)

                if m_leave1:
                    m_pname = re.search(r'for player ([^ \n]+)', line)
                    if m_pname:
                        pname = m_pname.group(1).strip()
                        if pname in active_since:
                            start_t = active_since.pop(pname)
                            dur = (dt - start_t).total_seconds()
                            if 0 < dur <= 14400:
                                player_sessions[pname].append((start_t, dt))

                # Pattern 2: Player count drop to 0 — close all remaining sessions
                m_count = re.search(r'now (\d+) player\(s\)', line)
                if m_count and int(m_count.group(1)) == 0:
                    for pname in list(active_since.keys()):
                        start_t = active_since.pop(pname)
                        dur = (dt - start_t).total_seconds()
                        if 0 < dur <= 14400:
                            player_sessions[pname].append((start_t, dt))

                # Raids
                m_raid = re.search(r'Random event set:([a-zA-Z0-9_]+)', line)
                if m_raid:
                    rname = m_raid.group(1).strip()
                    raids.append((dt, rname))

    except Exception as e:
        print(f"[Chronicle] Log parsing error: {e}")

    # Credit still-active sessions (players currently online)
    for pname, start_t in active_since.items():
        dur = (now_utc - start_t).total_seconds()
        if 0 < dur <= 43200:  # Cap at 12h for still-online players
            player_sessions[pname].append((start_t, now_utc))

    # Compute total playtimes in hours
    playtimes = {}
    for pname, sessions in player_sessions.items():
        total_secs = sum((end - start).total_seconds() for start, end in sessions)
        playtimes[pname] = round(total_secs / 3600, 1)

    # Deduplicate raids
    unique_raids = []
    seen_raids = set()
    for _, rname in raids:
        if rname not in seen_raids:
            unique_raids.append(rname)
            seen_raids.add(rname)

    return {
        "playtimes": playtimes,
        "casualties": dict(casualties),
        "raids": unique_raids,
        "active_warriors": active_warriors,
        "join_code": join_code,
        "all_deaths": all_deaths
    }

def build_daily_digest(hours: int = 24, include_ai: bool = True) -> str:
    """Builds the comprehensive daily battle chronicle markdown."""
    activity = analyze_recent_activity(hours)
    progress = get_world_progress()
    day = progress["in_game_day"]
    era = progress["active_era"]
    next_boss = progress["next_boss"]

    # Parse stockpiles from save
    parser = ValheimWorldParser()
    wealth = parser.get_wealth_summary()

    lines = [
        f"⚔️ **VALHEIM DAILY CHRONICLE — DAY {day}** 📜",
        f"**Realm:** `{config.VALHEIM_SERVER_NAME}` | **Era:** {era}",
        f"**Active Objective:** Defeat {next_boss}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🛡️ **WARRIORS ON THE FRONTIER:**"
    ]

    warriors = activity["active_warriors"]
    if warriors:
        for w in warriors:
            hrs = activity["playtimes"].get(w, 0.0)
            lines.append(f"• **{w}** — {hrs}h active expedition")
    else:
        lines.append("• *The realm rested in tranquil silence today.*")

    # Casualties (Hall of Valhalla)
    casualties = activity["casualties"]
    if casualties:
        total_falls = sum(casualties.values())
        lines.append("")
        lines.append("💀 **HALL OF VALHALLA (CASUALTIES):**")
        for name, count in sorted(casualties.items(), key=lambda x: -x[1]):
            lines.append(f"• **{name}** — {count} combat fall{'s' if count > 1 else ''}")
        lines.append(f"*Total: {total_falls} fall{'s' if total_falls > 1 else ''} in {hours}h*")

    lines.append("")
    lines.append("🏰 **CLAN TREASURY & STOCKPILES:**")
    lines.append(f"• **Coins & Gems:** `{wealth['total_purchasing_power']}` gold value ({wealth['coins']} coins)")
    lines.append(f"• **Containers Scanned:** `{wealth['containers_scanned']}` player chests")

    if activity["raids"]:
        lines.append("")
        lines.append("🔥 **INVASIONS & RAIDS REPELLED:**")
        for r in activity["raids"]:
            lines.append(f"• Siege Event: `{r}` (Defended)")

    lines.append("")
    lines.append(f"🔑 **JOIN CODE:** `{activity['join_code']}` (Port: `{config.VALHEIM_SERVER_PORT}`)")

    # AI Skald Narrative
    if include_ai and config.GEMINI_API_KEY:
        casualty_text = ""
        if casualties:
            casualty_text = "Casualties: " + ", ".join(
                f"{name} ({count} falls)" for name, count in casualties.items()
            )

        fact_sheet = (
            f"Day {day} of the realm.\n"
            f"Era: {era}\n"
            f"Target Boss: {next_boss}\n"
            f"Active Warriors: {', '.join(warriors) if warriors else 'Clan resting'}\n"
            f"Wealth: {wealth['total_purchasing_power']} gold\n"
            f"Raids: {', '.join(activity['raids']) if activity['raids'] else 'None'}\n"
            f"{casualty_text}"
        )
        saga = generate_saga_chronicle(fact_sheet, warriors)
        if saga:
            lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("📜 **THE SKALD'S SONG:**")
            lines.append(f"*{saga}*")

    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Valheim Daily Battle Chronicle")
    parser.add_argument("--post", action="store_true", help="Broadcast daily chronicle to Discord/Telegram/WhatsApp")
    parser.add_argument("--dry-run", action="store_true", help="Print chronicle to stdout without sending")
    parser.add_argument("--hours", type=int, default=24, help="Hours of history to analyze (default: 24)")
    args = parser.parse_args()

    digest = build_daily_digest(hours=args.hours, include_ai=True)

    if args.dry_run or not args.post:
        print(digest)
    else:
        print("[Chronicle] Broadcasting daily battle digest...")
        notifier.broadcast(digest)

if __name__ == "__main__":
    main()
