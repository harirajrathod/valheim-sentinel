"""
skald/weekly_superlatives.py - Valheim Weekly Hall of Fame & Clan Accolades
Calculates weekly superlatives from server logs and save telemetry:
  • The Iron Jarl (Apex Survivor: highest hours lived per combat fall)
  • The Grand Beaver (Homestead Architect: most overall playtime)
  • Tombstone Magnate (Valhalla's VIP: most combat falls)
  • Homestead Defender (Raid Vanguard: most base sieges defended)
  • The Naked Sprinter (Daredevil Corpse Runner: rapid succession deaths)
  • The Night Owl (Midnight Raider: most late-night playtime)
"""

import os
import re
import argparse
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Any, Optional

from core import config
from core import notifier
from telemetry.db_parser import ValheimWorldParser

LOG_TS_PATTERN = re.compile(r'^(\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}):')
LOG_TS_FORMAT = "%m/%d/%Y %H:%M:%S"

def parse_log_timestamp(line: str) -> Optional[datetime]:
    m = LOG_TS_PATTERN.match(line)
    if m:
        try:
            return datetime.strptime(m.group(1), LOG_TS_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None

def compute_weekly_stats(days: int = 7) -> Dict[str, Any]:
    """Parses server log over the past N days to aggregate player telemetry."""
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc - timedelta(days=days)

    active_since: Dict[str, datetime] = {}
    player_sessions: Dict[str, List[Tuple[datetime, datetime]]] = defaultdict(list)
    deaths_by_player: Dict[str, int] = defaultdict(int)
    all_deaths: List[Tuple[datetime, str]] = []
    raids: List[Tuple[datetime, str]] = []

    if os.path.exists(config.VALHEIM_LOG_FILE):
        try:
            with open(config.VALHEIM_LOG_FILE, 'r', errors='ignore') as f:
                for line in f:
                    dt = parse_log_timestamp(line)
                    if not dt or dt < cutoff_utc:
                        continue

                    # Check join / alive vs death
                    m_zdoid = re.search(r'Got character ZDOID from ([^:]+) : (-?\d+):(\d+)', line)
                    if m_zdoid:
                        pname = m_zdoid.group(1).strip()
                        za, zb = m_zdoid.group(2), m_zdoid.group(3)
                        if za == "0" and zb == "0":
                            if pname and pname != "0":
                                deaths_by_player[pname] += 1
                                all_deaths.append((dt, pname))
                        else:
                            if pname in active_since:
                                st = active_since.pop(pname)
                                dur = (dt - st).total_seconds()
                                if 0 < dur <= 14400:
                                    player_sessions[pname].append((st, dt))
                            active_since[pname] = dt

                    # Check disconnect
                    m_leave = re.search(r'Destroying abandoned non persistent zdo.*for player ([^ \n]+)', line)
                    if m_leave:
                        pname = m_leave.group(1).strip()
                        if pname in active_since:
                            st = active_since.pop(pname)
                            dur = (dt - st).total_seconds()
                            if 0 < dur <= 14400:
                                player_sessions[pname].append((st, dt))

                    # Check raid
                    m_raid = re.search(r'Random event set:([a-zA-Z0-9_]+)', line)
                    if m_raid:
                        raids.append((dt, m_raid.group(1).strip()))
        except Exception as e:
            print(f"[Superlatives] Log read error: {e}")

    # Close still-active sessions
    for pname, st in active_since.items():
        dur = (now_utc - st).total_seconds()
        if 0 < dur <= 43200:
            player_sessions[pname].append((st, now_utc))

    # Total playtime & night owl calculation
    playtimes: Dict[str, float] = defaultdict(float)
    night_playtimes: Dict[str, float] = defaultdict(float)

    for pname, sessions in player_sessions.items():
        for st, et in sessions:
            dur = (et - st).total_seconds()
            playtimes[pname] += dur

            cur = st
            while cur < et:
                cur_local = cur.astimezone(config.CURRENT_TZ)
                step = min(et, cur + timedelta(minutes=15))
                if 0 <= cur_local.hour < 6:
                    night_playtimes[pname] += (step - cur).total_seconds()
                cur = step

    # Rapid succession deaths (<180s)
    naked_runs: Dict[str, int] = defaultdict(int)
    deaths_map: Dict[str, List[datetime]] = defaultdict(list)
    for dt, pname in sorted(all_deaths, key=lambda x: x[0]):
        deaths_map[pname].append(dt)
    for pname, d_times in deaths_map.items():
        for i in range(1, len(d_times)):
            if (d_times[i] - d_times[i - 1]).total_seconds() <= 180:
                naked_runs[pname] += 1

    # Raids defended
    raid_defenders: Dict[str, int] = defaultdict(int)
    for r_dt, _ in raids:
        for pname, sessions in player_sessions.items():
            for st, et in sessions:
                if st - timedelta(seconds=60) <= r_dt <= et + timedelta(seconds=60):
                    raid_defenders[pname] += 1
                    break

    return {
        "cutoff_utc": cutoff_utc,
        "now_utc": now_utc,
        "playtimes": {p: round(s / 3600, 1) for p, s in playtimes.items()},
        "night_playtimes": {p: round(s / 3600, 1) for p, s in night_playtimes.items()},
        "deaths": dict(deaths_by_player),
        "naked_runs": dict(naked_runs),
        "raid_defenders": dict(raid_defenders),
        "total_raids": len(raids),
        "total_deaths": len(all_deaths)
    }

def generate_superlatives_report(days: int = 7) -> str:
    """Compiles the weekly superlatives and Hall of Fame digest."""
    stats = compute_weekly_stats(days)
    playtimes = stats["playtimes"]
    deaths = stats["deaths"]
    night = stats["night_playtimes"]
    naked = stats["naked_runs"]
    defenders = stats["raid_defenders"]

    start_str = stats["cutoff_utc"].astimezone(config.CURRENT_TZ).strftime("%b %d")
    end_str = stats["now_utc"].astimezone(config.CURRENT_TZ).strftime("%b %d, %Y")

    lines = [
        f"🏆 **VALHEIM WEEKLY HALL OF FAME & SHAME** ⚡",
        f"📅 **Expedition Window:** {start_str} – {end_str} ({days} Days)",
        f"🏰 **Realm:** `{config.VALHEIM_SERVER_NAME}`",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🎖️ **CLAN HONORS & SUPERLATIVES:**"
    ]

    # 1. The Grand Beaver (Most Playtime)
    if playtimes:
        beaver_winner, beaver_hrs = max(playtimes.items(), key=lambda x: x[1])
        lines.append(f"• 🦫 **The Grand Beaver (Homestead Architect):** **{beaver_winner}** ({beaver_hrs}h in the realm)")
    else:
        lines.append("• 🦫 **The Grand Beaver:** *No contenders this week.*")

    # 2. The Iron Jarl (Best Survival Ratio)
    all_players = set(playtimes.keys()) | set(deaths.keys())
    survival_ratios = {}
    for p in all_players:
        hrs = playtimes.get(p, 0.0)
        p_deaths = deaths.get(p, 0)
        ratio = hrs / max(1, p_deaths)
        survival_ratios[p] = (ratio, hrs, p_deaths)

    if survival_ratios:
        jarl_winner, (j_ratio, j_hrs, j_d) = max(survival_ratios.items(), key=lambda x: x[1][0])
        lines.append(f"• 🛡️ **The Iron Jarl (Apex Survivor):** **{jarl_winner}** ({j_hrs}h lived, {j_d} falls • {j_ratio:.1f}h/fall)")
    else:
        lines.append("• 🛡️ **The Iron Jarl:** *No contenders this week.*")

    # 3. Tombstone Magnate (Most Deaths)
    if deaths:
        magnate_winner, magnate_count = max(deaths.items(), key=lambda x: x[1])
        lines.append(f"• 💀 **Tombstone Magnate (Valhalla's VIP):** **{magnate_winner}** ({magnate_count} combat falls)")

    # 4. Homestead Defender (Most Raids Defended)
    if defenders:
        def_winner, def_count = max(defenders.items(), key=lambda x: x[1])
        lines.append(f"• ⚔️ **Homestead Defender (Raid Vanguard):** **{def_winner}** ({def_count} sieges defended)")

    # 5. The Naked Sprinter (Corpse Runs)
    if naked:
        sprinter_winner, sprinter_count = max(naked.items(), key=lambda x: x[1])
        lines.append(f"• 🏃 **The Naked Sprinter (Daredevil Runner):** **{sprinter_winner}** ({sprinter_count} rapid 25-HP tombstone dashes)")

    # 6. The Night Owl (Late Night Raider)
    if night:
        owl_winner, owl_hrs = max(night.items(), key=lambda x: x[1])
        if owl_hrs > 0.5:
            lines.append(f"• 🦉 **The Night Owl (Midnight Raider):** **{owl_winner}** ({owl_hrs}h between 00:00–06:00)")

    # Summary metrics
    total_hours = sum(playtimes.values())
    parser = ValheimWorldParser()
    wealth = parser.get_wealth_summary()

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 **REALM WEEKLY METRICS:**")
    lines.append(f"• **Combined Clan Playtime:** `{total_hours:.1f} hours`")
    lines.append(f"• **Total Combat Casualties:** `{stats['total_deaths']} falls`")
    lines.append(f"• **Hostile Raids Repelled:** `{stats['total_raids']} sieges`")
    lines.append(f"• **Tribal Treasury:** `{wealth['total_purchasing_power']:,} Gold` ({wealth['coins']:,} coins)")

    return "\n".join(lines)

def main():
    parser = argparse.ArgumentParser(description="Valheim Weekly Hall of Fame & Superlatives")
    parser.add_argument("--post", action="store_true", help="Broadcast to Discord/Telegram/WhatsApp")
    parser.add_argument("--dry-run", action="store_true", help="Print superlatives locally")
    parser.add_argument("--days", type=int, default=7, help="Days of history to analyze (default: 7)")
    args = parser.parse_args()

    report = generate_superlatives_report(days=args.days)

    if args.dry_run or not args.post:
        print(report)
    else:
        print("[Superlatives] Broadcasting weekly clan accolades...")
        notifier.broadcast(report)

if __name__ == "__main__":
    main()
