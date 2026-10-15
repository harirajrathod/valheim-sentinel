#!/usr/bin/env python3
"""
/root/valheim_info.py
Fast informational modules for Valheim WhatsApp group integration.

Provides:
  --wealth       : Haldor trader purchasing power, gems, gold & metal stockpiles
  --era / --day  : Current in-game day, day/night cycle, boss conquest roadmap
  --leaderboard  : All-time casualties, 24h playtimes, and survival streaks
  --progress     : Progression-aware biome readiness, next-stage prep checklist
"""

import sys
import argparse

sys.path.insert(0, "/root")
from valheim_utils import get_stable_hash
from valheim_constants import TARGET_S_ITEMS
from valheim_progression import (
    get_era_report,
    get_leaderboard_report,
    get_raid_report,
    get_patch_report,
    get_progression_report,
    get_persisted_day,
    get_progression_state,
    get_active_boss_and_era,
)
from valheim_geography import (
    get_portal_report,
    get_signs_report,
    get_world_signs,
    get_portal_location_desc,
    find_next_zdo_boundary,
)
from valheim_inventory import (
    get_wealth_report,
    get_metal_report,
    get_food_report,
    get_armour_report,
    get_find_report,
    scan_world_inventory,
    get_traders_status,
)

__all__ = [
    "get_wealth_report",
    "get_metal_report",
    "get_food_report",
    "get_armour_report",
    "get_find_report",
    "get_era_report",
    "get_leaderboard_report",
    "get_raid_report",
    "get_patch_report",
    "get_progression_report",
    "get_portal_report",
    "get_signs_report",
    "scan_world_inventory",
    "get_traders_status",
    "get_persisted_day",
    "get_progression_state",
    "get_active_boss_and_era",
    "get_world_signs",
    "get_portal_location_desc",
    "find_next_zdo_boundary",
    "get_stable_hash",
    "TARGET_S_ITEMS",
]


def main():
    parser = argparse.ArgumentParser(description="Valheim Clan Info")
    parser.add_argument("--wealth", "--treasury", dest="wealth", action="store_true", help="Print clan treasury and buying power")
    parser.add_argument("--metal", "--metals", "--metalcount", dest="metal", action="store_true", help="Print metal reserves, smelter economics and forge potential")
    parser.add_argument("--food", "--foods", "--foodcount", "--bestfood", dest="food", action="store_true", help="Print pantry stock, cauldron recipes and top 3-food combos")
    parser.add_argument("--armour", "--armourus", "--armor", "--gear", dest="armour", action="store_true", help="Print armourcraft, troll vs bronze sets and squad loadouts")
    parser.add_argument("--era", "--day", dest="era", action="store_true", help="Print in-game day and boss roadmap")
    parser.add_argument("--leaderboard", "--deaths", dest="leaderboard", action="store_true", help="Print casualty and playtime leaderboard")
    parser.add_argument("--raid", "--victory", dest="raid", action="store_true", help="Print active invasion status or last victory shout out")
    parser.add_argument("--portals", "--portal", dest="portals", action="store_true", help="Print active portal network, tags and pairing status")
    parser.add_argument("--signs", "--sign", "--runes", "--rune", dest="signs", action="store_true", help="Print active signs and runes")
    parser.add_argument("--quests", "--objectives", "--bounties", "--quest", "--objective", dest="quests", action="store_true", help="Print active clan quests and objectives")
    parser.add_argument("--patch", "--patchnotes", "--notes", dest="patch", action="store_true", help="Print latest game patch notes")
    parser.add_argument("--progress", "--prep", "--readiness", "--next", dest="progress", action="store_true", help="Print full progression readiness & next-biome prep checklist")
    parser.add_argument("--find", "--stock", dest="find", type=str, help="Search clan storage for an item")
    parser.add_argument("--farm", "--farming", "--harvest", "--crops", dest="farm", action="store_true", help="Print clan farm fields, crops and seed cycle status")
    parser.add_argument("--tames", "--wolves", "--beasts", dest="tames", action="store_true", help="Print menagerie and tamed beasts")
    parser.add_argument("--mead", "--brew", "--cellar", dest="mead", action="store_true", help="Print mead cellar and brewery barrels")
    parser.add_argument("--grave", "--rescue", dest="grave", nargs="?", const="", help="Print rescue compass for lost tombstones")
    parser.add_argument("--craft", "--canwecraft", dest="craft", nargs="?", const="", help="Check if clan can craft an item")
    parser.add_argument("--fleet", "--ships", "--carts", dest="fleet", action="store_true", help="Print fleet and logistics registry")
    parser.add_argument("--milestones", "--clan", dest="milestones", action="store_true", help="Print cooperative clan milestones")
    parser.add_argument("--comfort", "--hearth", dest="comfort", action="store_true", help="Print Longhouse hearth and comfort gauge")
    args = parser.parse_args()

    if args.wealth:
        print(get_wealth_report())
    elif args.metal:
        print(get_metal_report())
    elif args.food:
        print(get_food_report())
    elif args.armour:
        print(get_armour_report())
    elif args.era:
        print(get_era_report())
    elif args.leaderboard:
        print(get_leaderboard_report())
    elif args.raid:
        print(get_raid_report())
    elif args.portals:
        print(get_portal_report())
    elif args.signs:
        print(get_signs_report())
    elif args.quests:
        from valheim_quest_engine import get_active_quests_formatted
        print(get_active_quests_formatted())
    elif args.patch:
        print(get_patch_report())
    elif args.progress:
        print(get_progression_report())
    elif args.find:
        print(get_find_report(args.find))
    elif args.farm:
        from valheim_farm import format_farm_report
        print(format_farm_report())
    elif args.tames:
        from valheim_qol import get_tames_report
        print(get_tames_report())
    elif args.mead:
        from valheim_qol import get_mead_report
        print(get_mead_report())
    elif args.grave is not None:
        from valheim_qol import get_rescue_report
        print(get_rescue_report(args.grave if args.grave else None))
    elif args.craft is not None:
        from valheim_qol import get_craft_report
        print(get_craft_report(args.craft if args.craft else None))
    elif args.fleet:
        from valheim_qol import get_fleet_report
        print(get_fleet_report())
    elif args.milestones:
        from valheim_qol import get_milestones_report
        print(get_milestones_report())
    elif args.comfort:
        from valheim_qol import get_comfort_report
        print(get_comfort_report())
    else:
        print(get_era_report())

if __name__ == "__main__":
    main()
