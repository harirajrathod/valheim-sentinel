#!/usr/bin/env python3
from valheim_utils import get_stable_hash, safe_send_whatsapp
"""
/root/valheim_weekly_sync.py
Automated Weekly Valheim Exploration, Trader & Progress Synchronization Engine.

Runs weekly (Sunday evening) or on-demand to:
1. Audit newly explored biomes, dungeon placements, and locations from chunk files.
2. Synchronize trader contact states (Haldor, Hildir, The Bog Witch) & portal links.
3. Synchronize boss defeats and Hildir quest completions from DB2 save state.
4. Scan world chests for newly stockpiled progression materials (e.g. Ancient Seeds).
5. Refresh world state files and log any changes.

Usage:
  python3 /root/valheim_weekly_sync.py --check     # Dry-run audit
  python3 /root/valheim_weekly_sync.py --sync      # Update states & sync
  python3 /root/valheim_weekly_sync.py --cron      # Scheduled weekly run
"""

import os
import sys
import re
import json
import glob
import zlib
import struct
import ctypes
import argparse
import subprocess
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

TRADER_STATE_FILE   = "/root/valheim_traders_state.json"
KNOWN_TRADERS_FILE  = "/root/valheim_known_traders.json"
BOSS_STATE_FILE     = "/root/valheim_bosses_defeated.json"
HILDIR_STATE_FILE   = "/root/valheim_hildir_quests.json"
WEEKLY_AUDIT_FILE   = "/root/valheim_weekly_audit.json"

sys.path.insert(0, "/root")
try:
    import valheim_info
except Exception as e:
    print(f"Error importing valheim_info: {e}")
    valheim_info = None


def run_weekly_sync(dry_run=False):
    now_utc = datetime.now(timezone.utc)
    now_ist = now_utc.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")

    print(f"=== VALHEIM WEEKLY SYNCHRONIZATION [{now_ist}] ===")

    audit = {
        "timestamp": now_ist,
        "traders": {},
        "bosses": [],
        "hildir_quests": [],
        "portals": [],
        "key_stockpiles": {},
        "changes_detected": []
    }

    # 1. Audit Traders & Portals via valheim_info
    if valheim_info:
        try:
            traders = valheim_info.get_traders_status()
            audit["traders"] = traders
            print(f"✓ Traders Audited ({len(traders)}):")
            for t_key, t_data in traders.items():
                status_str = "🟢 Contacted" if t_data.get("interacted") else ("⏳ Discovered" if t_data.get("discovered") else "🔒 Undiscovered")
                portal_str = f"(Portal: `{t_data.get('portal')}`)" if t_data.get("portal") else "(No Portal)"
                print(f"  • {t_data.get('icon', '📍')} {t_data.get('name')}: {status_str} {portal_str}")
        except Exception as e:
            print(f"✗ Trader audit failed: {e}")

        try:
            totals, _ = valheim_info.scan_world_inventory()
            ancient_seeds = totals.get("AncientSeed", 0)
            withered_bones = totals.get("WitheredBone", 0)
            dragon_eggs = totals.get("DragonEgg", 0)
            goblin_totems = totals.get("GoblinTotem", 0)
            coins = totals.get("Coins", 0)
            rubies = totals.get("Ruby", 0)
            amber = totals.get("Amber", 0)
            cop = totals.get("Copper", 0) + totals.get("CopperOre", 0)
            tin = totals.get("Tin", 0) + totals.get("TinOre", 0)
            brz = totals.get("Bronze", 0)
            iron = totals.get("Iron", 0) + totals.get("IronScrap", 0)
            silver = totals.get("Silver", 0) + totals.get("SilverOre", 0)
            black_metal = totals.get("BlackMetal", 0) + totals.get("BlackMetalScrap", 0)
            obsidian = totals.get("Obsidian", 0)

            audit["key_stockpiles"] = {
                "AncientSeed": ancient_seeds,
                "WitheredBone": withered_bones,
                "DragonEgg": dragon_eggs,
                "GoblinTotem": goblin_totems,
                "Coins": coins,
                "Ruby": rubies,
                "Amber": amber,
                "CopperTotal": cop,
                "TinTotal": tin,
                "Bronze": brz,
                "IronTotal": iron,
                "SilverTotal": silver,
                "BlackMetalTotal": black_metal,
                "Obsidian": obsidian
            }
            print(f"✓ Key Stockpiles Audited:")
            print(f"  • Yagluth Summon (Fuling Totems): {goblin_totems}/5 ({'🔥 Ready' if goblin_totems >= 5 else 'Need more'})")
            print(f"  • Treasury: {coins} Coins, {rubies} Rubies, {amber} Amber")
            print(f"  • Metallurgy: {iron} Iron, {silver} Silver, {cop} Copper, {tin} Tin, {brz} Bronze, {obsidian} Obsidian")

            # Check if any active quest has been completed by inventory
            try:
                from valheim_quest_engine import check_quest_inventory_completion
                completed_msgs = check_quest_inventory_completion(totals)
                for cmsg in completed_msgs:
                    print(f"✓ Quest Auto-Completed by Vault Stockpiles!")
                    try:
                        safe_send_whatsapp(cmsg)
                    except Exception as wa_err:
                        print(f"Failed to post quest completion to WhatsApp: {wa_err}")
            except Exception as q_err:
                print(f"Quest auto-check error: {q_err}")
        except Exception as e:
            print(f"✗ Inventory audit failed: {e}")

    # 2. Audit Boss Defeats & Hildir Quests from DB2
    db_bosses = set()
    db_hildir = set()
    db_files = sorted(glob.glob('/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/_main.*.db2'))
    if db_files:
        try:
            with open(db_files[-1], 'rb') as f:
                db_data = f.read()
            idx = db_data.find(b'\x1f\x8b\x08')
            if idx != -1:
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                decomp = d.decompress(db_data[idx:])
                found_bosses = re.findall(rb'defeated_\w+', decomp)
                for b in found_bosses:
                    db_bosses.add(b.decode('latin1').lower())
                for q in [b'hildir1', b'hildir2', b'hildir3']:
                    if q in decomp.lower():
                        db_hildir.add(q.decode('latin1').lower())
        except Exception as e:
            print(f"✗ DB2 inspection error: {e}")

    audit["bosses"] = sorted(list(db_bosses))
    audit["hildir_quests"] = sorted(list(db_hildir))
    print(f"✓ Boss Progress: {sorted(list(db_bosses))}")
    print(f"✓ Hildir Quests: {sorted(list(db_hildir)) if db_hildir else 'None completed yet'}")

    # 3. Synchronize state files if not dry-run
    if not dry_run:
        # Sync traders state
        try:
            with open(TRADER_STATE_FILE, "w") as f:
                json.dump(audit["traders"], f, indent=2)
            print(f"✓ Saved updated trader state to {TRADER_STATE_FILE}")
        except Exception as e:
            print(f"✗ Failed saving {TRADER_STATE_FILE}: {e}")

        # Sync known traders list for monitor
        try:
            known_camps = set()
            if os.path.exists(KNOWN_TRADERS_FILE):
                try:
                    with open(KNOWN_TRADERS_FILE, "r") as f:
                        known_camps = set(json.load(f))
                except Exception:
                    pass
            for t_key, t_data in audit["traders"].items():
                if t_data.get("discovered"):
                    if t_key == "Haldor": known_camps.add("Vendor_BlackForest")
                    elif t_key == "Hildir": known_camps.add("Hildir_camp")
                    elif t_key == "BogWitch": known_camps.add("BogWitch_Camp")
            with open(KNOWN_TRADERS_FILE, "w") as f:
                json.dump(sorted(list(known_camps)), f, indent=2)
            print(f"✓ Synchronized {KNOWN_TRADERS_FILE}")
        except Exception as e:
            print(f"✗ Failed saving {KNOWN_TRADERS_FILE}: {e}")

        # Sync boss state
        try:
            with open(BOSS_STATE_FILE, "w") as f:
                json.dump(audit["bosses"], f, indent=2)
            print(f"✓ Synchronized {BOSS_STATE_FILE}")
        except Exception as e:
            print(f"✗ Failed saving {BOSS_STATE_FILE}: {e}")

        # Sync Hildir quests state
        try:
            with open(HILDIR_STATE_FILE, "w") as f:
                json.dump(audit["hildir_quests"], f, indent=2)
            print(f"✓ Synchronized {HILDIR_STATE_FILE}")
        except Exception as e:
            print(f"✗ Failed saving {HILDIR_STATE_FILE}: {e}")

        # Save audit snapshot
        try:
            with open(WEEKLY_AUDIT_FILE, "w") as f:
                json.dump(audit, f, indent=2)
            print(f"✓ Saved audit snapshot to {WEEKLY_AUDIT_FILE}")
        except Exception as e:
            print(f"✗ Failed saving {WEEKLY_AUDIT_FILE}: {e}")

    print("=== SYNCHRONIZATION COMPLETE ===")
    return audit

def main():
    parser = argparse.ArgumentParser(description="Valheim Synchronization Engine")
    parser.add_argument("--check", action="store_true", help="Perform dry-run audit without saving")
    parser.add_argument("--sync", action="store_true", help="Perform full audit and synchronize all states")
    parser.add_argument("--cron", action="store_true", help="Scheduled cron mode with quiet change detection")
    args = parser.parse_args()

    prev_audit = {}
    if os.path.exists(WEEKLY_AUDIT_FILE):
        try:
            with open(WEEKLY_AUDIT_FILE, "r") as f:
                prev_audit = json.load(f)
        except Exception:
            pass

    dry_run = args.check and not (args.sync or args.cron)
    audit = run_weekly_sync(dry_run=dry_run)

    if args.cron:
        # Detect actual changes between runs to prevent log spam
        changes = []
        
        # 1. Check trader changes
        prev_traders = prev_audit.get("traders", {})
        curr_traders = audit.get("traders", {})
        for t_key, t_data in curr_traders.items():
            prev_t = prev_traders.get(t_key, {})
            if t_data.get("interacted") and not prev_t.get("interacted"):
                changes.append(f"Trader {t_data.get('name')} contacted (Portal: {t_data.get('portal')})")
            elif t_data.get("discovered") and not prev_t.get("discovered"):
                changes.append(f"Trader {t_data.get('name')} camp discovered")

        # 2. Check boss changes
        prev_bosses = set(prev_audit.get("bosses", []))
        curr_bosses = set(audit.get("bosses", []))
        new_bosses = curr_bosses - prev_bosses
        if new_bosses:
            changes.append(f"New boss slain: {', '.join(sorted(list(new_bosses)))}")

        # 3. Check Hildir quests
        prev_hildir = set(prev_audit.get("hildir_quests", []))
        curr_hildir = set(audit.get("hildir_quests", []))
        new_hildir = curr_hildir - prev_hildir
        if new_hildir:
            changes.append(f"Hildir quest completed: {', '.join(sorted(list(new_hildir)))}")

        # 4. Check active summon tributes threshold crossing (only if boss is NOT yet slain!)
        boss_alias_map = {
            "defeated_dragon": {"defeated_dragon", "defeated_writhan"},
            "defeated_queen": {"defeated_queen", "defeated_seekerking"},
        }
        tribute_thresholds = [
            ("AncientSeed", 3, "defeated_gdking", "The Elder"),
            ("WitheredBone", 10, "defeated_bonemass", "Bonemass"),
            ("DragonEgg", 3, "defeated_dragon", "Moder"),
            ("GoblinTotem", 5, "defeated_goblinking", "Yagluth"),
            ("SealbreakerFragment", 9, "defeated_queen", "The Queen"),
            ("BellFragment", 3, "defeated_fader", "Fader")
        ]
        prev_stock = prev_audit.get("key_stockpiles", {})
        curr_stock = audit.get("key_stockpiles", {})
        for item_key, needed, boss_key, boss_name in tribute_thresholds:
            keys_to_check = boss_alias_map.get(boss_key, {boss_key})
            if not (keys_to_check & curr_bosses):
                prev_c = prev_stock.get(item_key, 0)
                curr_c = curr_stock.get(item_key, 0)
                if prev_c < needed and curr_c >= needed:
                    changes.append(f"{boss_name} Summon Tributes ready ({curr_c}/{needed} {item_key})")

        if changes:
            log_msg = f"Valheim Auto-Sync: Progress detected — {'; '.join(changes)}. World state synchronized."
            try:
                subprocess.run(["bash", "/root/log.sh", "add", log_msg], capture_output=True)
                print(f"✓ Logged change: {log_msg}")
            except Exception:
                pass

if __name__ == "__main__":
    main()
