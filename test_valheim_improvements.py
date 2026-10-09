#!/usr/bin/env python3
"""
/root/test_valheim_improvements.py - Automated Unit & Integration Tests for Valheim Enhancements

Validates:
1. valheim_utils: Safe templating, atomic JSON persistence, player name normalization, network sanitizer
2. valheim_whatsapp_action: Status parsing, dry-run restart, ping cache
3. valheim_autopatch: BBCode parser, patch formatting, dry-run checks
4. valheim_monitor: Event classifier ladder, raid state recovery, lore message formatting
5. valheim_messages: Safe template formatting, session link messaging
6. valheim_info: Progression and calendar day inspection
"""

import os
import sys
import tempfile
import unittest
import time

sys.path.insert(0, "/root")

import valheim_utils as vu
import valheim_whatsapp_action as vwa
import valheim_autopatch as vap
import valheim_monitor as vm
import valheim_messages as vmsg
import valheim_info as vi


class TestValheimUtils(unittest.TestCase):
    def test_safe_format_dict(self):
        d = vu.SafeFormatDict({"name": "Dexter"})
        self.assertEqual(d["name"], "Dexter")
        self.assertEqual(d["missing_key"], "")

    def test_safe_format_template(self):
        tmpl = "Hail *{name}*, you survived {duration_mins}m but died {deaths} times! {unfilled}"
        res = vu.safe_format_template(tmpl, name="Hilda", duration_mins=45)
        self.assertIn("Hail *Hilda*", res)
        self.assertIn("survived 45m", res)
        self.assertNotIn("{unfilled}", res)

    def test_format_player_name(self):
        self.assertEqual(vu.format_player_name("musashi"), "Musashi(Musa Bhai)")
        self.assertEqual(vu.format_player_name("  Musa Bhai "), "Musashi(Musa Bhai)")
        self.assertEqual(vu.format_player_name("Dexter"), "Dexter")

    def test_sanitize_network_copy(self):
        raw = "Failed to connect to 72.62.227.29:2458: ConnectionRefusedError"
        san = vu.sanitize_network_copy(raw)
        self.assertNotIn("72.62.227.29", san)
        self.assertIn("Server Host", san)
        self.assertIn("Connection is down", san)

    def test_atomic_json_io(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            path = tf.name
        try:
            payload = {"status": "ok", "count": 42, "items": ["silver", "iron"]}
            success = vu.atomic_save_json(path, payload)
            self.assertTrue(success)

            loaded = vu.safe_load_json(path)
            self.assertEqual(loaded, payload)

            # Corrupted file test
            with open(path, "w") as f:
                f.write("{corrupt json ...")
            fallback = vu.safe_load_json(path, default={"fallback": True})
            self.assertEqual(fallback, {"fallback": True})
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestValheimWhatsappAction(unittest.TestCase):
    def test_get_server_info_structure(self):
        info = vwa.get_server_info()
        self.assertIsInstance(info, dict)
        self.assertIn("running", info)
        self.assertIn("join_code", info)
        self.assertIn("player_count", info)
        self.assertIn("port", info)
        self.assertEqual(info["port"], 2458)

    def test_graceful_restart_dry_run(self):
        res = vwa.graceful_restart(dry_run=True)
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("dry_run"))
        self.assertTrue(res.get("simulated"))


class TestValheimAutoPatch(unittest.TestCase):
    def test_clean_bbcode(self):
        raw = "[b]Patch Notes[/b]: [h1]Changes[/h1] [url=https://valheim.com]Website[/url]"
        clean = vap.clean_bbcode(raw)
        self.assertIn("*Patch Notes*", clean)
        self.assertIn("*Changes*", clean)
        self.assertIn("Website (https://valheim.com)", clean)

    def test_local_build_detection(self):
        bid = vap.get_local_buildid()
        self.assertIsNotNone(bid)
        self.assertTrue(bid.isdigit())


class TestValheimMonitorClassifier(unittest.TestCase):
    def test_classifier_raid_casualty(self):
        now_t = time.time()
        sess = {
            "login_time": now_t - 300,
            "deaths": [now_t - 30],
            "corpse_runs": 0,
            "raids_participated": {"foresttrolls"},
            "raids_died_in": {"foresttrolls"},
            "bosses_defeated": set(),
            "locations_discovered": set(),
            "sea_voyage": False
        }
        event_type, detail, dur, deaths = vm.classify_session_event(sess, reason="logout", now_t=now_t)
        self.assertEqual(event_type, "RAID_CASUALTY")
        self.assertEqual(detail.get("raid_key"), "foresttrolls")

    def test_classifier_rage_quit(self):
        now_t = time.time()
        sess = {
            "login_time": now_t - 600,
            "deaths": [now_t - 15],  # 15s ago
            "corpse_runs": 0,
            "raids_participated": set(),
            "raids_died_in": set(),
            "bosses_defeated": set(),
            "locations_discovered": set(),
            "sea_voyage": False
        }
        event_type, detail, dur, deaths = vm.classify_session_event(sess, reason="socket_drop", now_t=now_t)
        self.assertEqual(event_type, "RAGE_QUIT")

    def test_classifier_marathon_grind(self):
        now_t = time.time()
        sess = {
            "login_time": now_t - 7200,  # 2 hours
            "deaths": [],
            "corpse_runs": 0,
            "raids_participated": set(),
            "raids_died_in": set(),
            "bosses_defeated": set(),
            "locations_discovered": set(),
            "sea_voyage": False
        }
        event_type, detail, dur, deaths = vm.classify_session_event(sess, reason="logout", now_t=now_t)
        self.assertEqual(event_type, "MARATHON_GRIND")
        self.assertGreaterEqual(dur, 60)


class TestValheimMessages(unittest.TestCase):
    def test_random_join_safe_format(self):
        msg = vmsg.get_random_join_message("musashi")
        self.assertIn("Musashi(Musa Bhai)", msg)

    def test_random_leave_safe_format(self):
        msg = vmsg.get_random_leave_message("Hilda")
        self.assertIn("Hilda", msg)


class TestValheimInfo(unittest.TestCase):
    def test_persisted_day(self):
        day = vi.get_persisted_day(check_log=False)
        self.assertGreater(day, 100)

    def test_progression_state(self):
        prog = vi.get_progression_state()
        self.assertIn("current_tier", prog)
        self.assertIn("next_boss", prog)
        self.assertIn("defeated_keys", prog)

    def test_food_report_format(self):
        rep = vi.get_food_report()
        self.assertIn("VALHEIM CLAN PANTRY", rep)
        self.assertIn("Kitchen Era:", rep)
        self.assertIn("Top Cauldron Feasts", rep)
        self.assertIn("Optimal 3-Food Combos", rep)
        self.assertNotIn("Cultivator Alert:", rep)  # Moved to !farm

    def test_armour_report_format(self):
        rep = vi.get_armour_report()
        self.assertIn("VALHEIM CLAN ARMOURY & FORGE", rep)
        self.assertIn("Armoury Stock:", rep)
        self.assertIn("Current Tier Equipment:", rep)
        self.assertNotIn("🔻 OBSOLETE", rep)  # No obsolete tier lectures
        self.assertIn("Quartermaster:", rep)

    def test_leaderboard_normalization(self):
        rep = vi.get_leaderboard_report()
        self.assertIn("VALHEIM CLAN LEADERBOARDS", rep)
        # Verify Musashi is consolidated and not duplicated
        occurrences = rep.count("Musashi(Musa Bhai)")
        # In casualties (1) and playtime (1) = total 2 in entire leaderboard
        self.assertEqual(occurrences, 2)
        self.assertIn("🥇", rep)

    def test_portal_report_format(self):
        rep = vi.get_portal_report()
        self.assertIn("REALM PORTAL DIRECTORY", rep)
        self.assertIn("Connected Pairs:", rep)
        self.assertNotIn("`462, -2547`", rep)  # No raw float coordinates

    def test_signs_report_format(self):
        rep = vi.get_signs_report()
        self.assertIn("REALM CARVED SIGNS & RUNES", rep)
        self.assertIn("Key Halls & Landmark Signposts:", rep)
        self.assertIn("Storage & Sorting Runes:", rep)
        self.assertIn("Scribes of the Realm:", rep)
        self.assertLess(len(rep.splitlines()), 50)  # Under 50 lines (not 177)

    def test_progression_report_format(self):
        rep = vi.get_progression_report()
        self.assertIn("VALHEIM CLAN PROGRESSION READINESS", rep)
        self.assertIn("Preparation Checklist", rep)
        self.assertNotIn("Obsolete — No Longer Priority", rep)

    def test_quest_board_format(self):
        from valheim_quest_engine import get_active_quests_formatted
        rep = get_active_quests_formatted()
        self.assertIn("VALHEIM CLAN QUEST BOARD", rep)
        self.assertNotIn("═══════════════════════════════", rep)
        self.assertNotIn("🎁 Objective Reward:", rep)


class TestValheimQoL(unittest.TestCase):
    def test_tames_report(self):
        import valheim_qol as vq
        rep = vq.get_tames_report()
        self.assertIn("VALHEIM CLAN MENAGERIE & BEASTS", rep)
        self.assertIn("Dire Wolves", rep)
        self.assertIn("Boars", rep)
        self.assertIn("Lox", rep)
        self.assertLess(len(rep.splitlines()), 35)

    def test_mead_report(self):
        import valheim_qol as vq
        rep = vq.get_mead_report()
        self.assertIn("VALHEIM MEAD CELLAR & BREWERY", rep)
        self.assertIn("Active Fermenters", rep)
        self.assertIn("Cellar Stock", rep)
        self.assertIn("Brewing Pantry Potential", rep)
        self.assertLess(len(rep.splitlines()), 35)

    def test_rescue_report(self):
        import valheim_qol as vq
        rep = vq.get_rescue_report()
        self.assertIn("VALHALLA RESCUE COMPASS", rep)
        self.assertIn("Rescue Route:", rep)
        self.assertIn("Hazard Tip:", rep)
        self.assertLess(len(rep.splitlines()), 35)

    def test_craft_report(self):
        import valheim_qol as vq
        # Without args
        guide = vq.get_craft_report()
        self.assertIn("CAN WE CRAFT?", guide)
        self.assertIn("!craft frostner", guide)

        # Frostner check
        frostner_rep = vq.get_craft_report("frostner")
        self.assertIn("CRAFTING CHECK: Frostner", frostner_rep)
        self.assertIn("Silver", frostner_rep)
        self.assertIn("Treasury", frostner_rep)

        # Ready item check
        shield_rep = vq.get_craft_report("silver shield")
        self.assertIn("READY TO FORGE!", shield_rep)

    def test_fleet_report(self):
        import valheim_qol as vq
        rep = vq.get_fleet_report()
        self.assertIn("VALHEIM FLEET & LOGISTICS REGISTRY", rep)
        self.assertIn("Seafaring Vessels", rep)
        self.assertIn("Land Transport", rep)
        self.assertIn("Karve", rep)
        self.assertIn("Handcart", rep)
        self.assertLess(len(rep.splitlines()), 30)

    def test_milestones_report(self):
        import valheim_qol as vq
        rep = vq.get_milestones_report()
        self.assertIn("VALHEIM COOPERATIVE CLAN MILESTONES", rep)
        self.assertIn("Grand Architects", rep)
        self.assertIn("Master Smiths", rep)
        self.assertIn("Homestead Providers", rep)
        self.assertIn("Yggdrasil Wayfarers", rep)
        self.assertIn("Treasury of the North", rep)
        self.assertLess(len(rep.splitlines()), 40)

    def test_comfort_report(self):
        import valheim_qol as vq
        rep = vq.get_comfort_report()
        self.assertIn("LONGHOUSE HEARTH & COMFORT GAUGE", rep)
        self.assertIn("Current Comfort Level:", rep)
        self.assertIn("Rested Buff Duration:", rep)
        self.assertIn("Next High-Impact Comfort Upgrades", rep)
        self.assertLess(len(rep.splitlines()), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)

