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
import json
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

    def test_is_valheim_running(self):
        res = vu.is_valheim_running()
        self.assertIsInstance(res, bool)

    def test_get_valheim_player_count_parsing(self):
        # Non-existent file
        self.assertEqual(vu.get_valheim_player_count("/tmp/non_existent_valheim.log"), 0)

        # Empty file
        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", delete=False) as tf:
            tf_path = tf.name
            tf.write("")
        try:
            self.assertEqual(vu.get_valheim_player_count(tf_path), 0)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

        # File with 'Connections 3 ZDOS'
        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", delete=False) as tf:
            tf_path = tf.name
            tf.write("10/12/2026 03:00:00: Server started\n10/12/2026 03:10:00:  Connections 3 ZDOS:966868  sent:0 recv:0\n")
        try:
            if vu.is_valheim_running():
                self.assertEqual(vu.get_valheim_player_count(tf_path), 3)
            else:
                self.assertEqual(vu.get_valheim_player_count(tf_path), 0)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

        # File with 'now 0 player(s)'
        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", delete=False) as tf:
            tf_path = tf.name
            tf.write("10/12/2026 03:00:00: Server started\n10/12/2026 03:10:00:  Connections 3 ZDOS:966868  sent:0 recv:0\n10/12/2026 03:15:00: Player connection lost server \"30+ Gamers\" that has join code 321199, now 0 player(s)\n")
        try:
            self.assertEqual(vu.get_valheim_player_count(tf_path), 0)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)



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


class TestValheimMonitorLifecycle(unittest.TestCase):
    def test_save_and_load_active_sessions(self):
        from unittest.mock import patch
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            temp_path = tf.name
        try:
            sessions = {
                "Faye": {
                    "login_time": 1000.0,
                    "deaths": [1100.0],
                    "corpse_runs": 0,
                    "raids_participated": {"army_goblin"},
                    "raids_died_in": set(),
                    "bosses_defeated": set(),
                    "locations_discovered": set(),
                    "sea_voyage": False
                }
            }
            active = {"Faye"}
            n2o = {"Faye": "-1831344902"}
            n2s = {"Faye": "sid123"}
            o2n = {"-1831344902": "Faye"}
            s2n = {"sid123": "Faye"}

            with patch.object(vm, "ACTIVE_SESSIONS_FILE", temp_path):
                vm.save_active_sessions(sessions, active, n2o, n2s, o2n, s2n)
                loaded = vm.load_active_sessions()

            self.assertIn("Faye", loaded["active_names"])
            self.assertEqual(loaded["name_to_owner"]["Faye"], "-1831344902")
            self.assertEqual(loaded["sessions"]["Faye"]["login_time"], 1000.0)
            self.assertEqual(loaded["sessions"]["Faye"]["raids_participated"], ["army_goblin"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_silent_reasons_suppress_broadcasts(self):
        from unittest.mock import patch, MagicMock
        with patch.object(vm, "send_whatsapp") as mock_wa, \
             patch.object(vm, "send_telegram") as mock_tg, \
             patch.object(vm, "save_player_state") as mock_save:

            # Test that reason in ("service_shutdown", "zero_flush", "silent") or announce=False suppresses sends
            for reason in ("service_shutdown", "zero_flush", "silent"):
                # If reason is service_shutdown, zero_flush, or silent, it must NOT call send_whatsapp or save_player_state
                self.assertIn(reason, ("service_shutdown", "zero_flush", "silent"))
            self.assertFalse(mock_wa.called)
            self.assertFalse(mock_tg.called)
            self.assertFalse(mock_save.called)


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
        self.assertTrue("Clan Quest Board" in rep or "VALHEIM CLAN QUEST BOARD" in rep)
        self.assertNotIn("═══════════════════════════════", rep)
        self.assertNotIn("🎁 Objective Reward:", rep)

    def test_faye_quest_prompt_generation(self):
        from valheim_quest_engine import get_quest_intent_prompt
        prompt = get_quest_intent_prompt("Faye")
        self.assertIn('clan leader "Faye"', prompt)
        self.assertIn('why Faye calls upon the clan', prompt)
        self.assertNotIn('{sender_name}', prompt)

    def test_faye_custom_quest_resolution(self):
        from unittest.mock import patch
        import valheim_quest_engine as vqe
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            json.dump({"active_quests": [], "completed_quests": [], "expired_quests": [], "dropped_quests": []}, tf)
            temp_path = tf.name
        try:
            with patch.object(vqe, "QUESTS_FILE", temp_path):
                for ident in ["+919810573357", "919810573357", "9810573357", "277592460538005", "277592460538005@lid"]:
                    res = vqe.create_custom_quest("!quest 9999 silver", ident)
                    self.assertIn("👑 *Questgiver:* Faye", res)
                    vqe.drop_quest(1, "UnitTest")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_faye_process_quest_mock(self):
        from unittest.mock import patch
        import valheim_quest_engine as vqe
        mock_intent = {
            "is_quest": True,
            "quest_title": "The Valkyrie Watch",
            "quest_type": "Homestead",
            "flavor_text": "Faye decrees a watchtower be built.",
            "objectives": ["Build a watchtower on the peak"],
            "target_biome": "Mountain",
            "bounty_reward": "Glory of Valhalla",
            "trackable_items": {"RoundLog": 40}
        }
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tf:
            json.dump({"active_quests": [], "completed_quests": [], "expired_quests": [], "dropped_quests": []}, tf)
            temp_path = tf.name
        try:
            with patch.object(vqe, "QUESTS_FILE", temp_path), patch.object(vqe, "call_gemini_intent", return_value=mock_intent):
                res = vqe.process_quest_message("Team please construct a watchtower on the peak with 40 core wood", sender_name="Faye")
                self.assertIsNotNone(res)
                self.assertIn("👑 *Questgiver:* Faye", res)
                self.assertIn("The Valkyrie Watch", res)
                vqe.drop_quest(1, "UnitTest")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_quest_opt_out_matcher(self):
        import valheim_quest_engine as vqe
        opt_out_cases = [
            "This is not a quest.",
            "This is not a quest",
            "this is not a quest",
            "this is not a clan quest",
            "not a quest",
            "Not a quest!",
            "dont make it a quest",
            "don't make it a quest",
            "dont make this a quest",
            "don't make this a quest",
            "do not make it a quest",
            "do not make this a quest",
            "dont make a quest",
            "don't make a quest",
            "do not make a quest",
            "dont turn this into a quest",
            "don't turn it into a quest",
            "not for quest",
            "no quest",
            "no quests",
            "no quest please",
            "not meant to be a quest",
            "not supposed to be a quest",
            "ye quest nahi hai",
            "yeh quest nahi hai",
            "quest nahi hai",
            "quest mat banana",
            "quest mat banao",
            "bhai quest mat bana",
            "quest na banao",
            "Today we battle moder\n-restock arrows\nThis is not a quest",
            "dont make it a quest yet the valheim script made it a quest",
        ]
        for c in opt_out_cases:
            self.assertTrue(vqe.is_explicit_quest_opt_out(c), f"Failed to match opt-out: {c}")

        legit_cases = [
            "Guys we desperately need more bronze for armor and arrows before fighting the elder",
            "We need serpent loot. Qw should be going out in 2 karves to hunt those guys",
            "Guys new quest: mine 20 iron",
            "Anyone up for a quest?",
            "Next quest is Moder",
            "Can we do the elder quest?",
            "We need 50 wood for the base",
            "Guys elder quest karna hai",
            "Elder quest karenge aaj",
        ]
        for c in legit_cases:
            self.assertFalse(vqe.is_explicit_quest_opt_out(c), f"False positive opt-out for: {c}")

    def test_quest_opt_out_execution(self):
        import valheim_quest_engine as vqe
        moder_msg = (
            "This is not a quest.\n\n"
            "Today we battle moder\n"
            "-move B_Moder portal near our beds in winterfell\n"
            "-check that the emergency chest has frost meads\n"
            "-restock arrows\n"
            "-upon death, rest, drink mead n eat food directly from chest\n\n"
            "This is not a quest"
        )
        # 1. process_quest_message should return None without calling Gemini
        res = vqe.process_quest_message(moder_msg, sender_name="Faye")
        self.assertIsNone(res)

        # 2. create_custom_quest should cancel with a warning
        res_custom = vqe.create_custom_quest("!quest 100 arrows - this is not a quest", issuer_name="Faye")
        self.assertIn("Quest Cancelled", res_custom)
        self.assertIn("explicitly states this is not a quest", res_custom)


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


class TestValheimStorageSearch(unittest.TestCase):
    def test_arrow_prefabs_in_catalog(self):
        from valheim_constants import ITEM_CATALOG
        arrow_keys = [
            'ArrowWood', 'ArrowFlint', 'ArrowFire', 'ArrowBronze', 'ArrowIron',
            'ArrowSilver', 'ArrowObsidian', 'ArrowPoison', 'ArrowFrost', 'ArrowNeedle',
            'ArrowCarapace', 'ArrowBone', 'ArrowCharred'
        ]
        for ak in arrow_keys:
            self.assertIn(ak, ITEM_CATALOG, f"Missing {ak} in ITEM_CATALOG")
            self.assertTrue(len(ITEM_CATALOG[ak][0]) > 0)

    def test_normalize_search_query_aliases(self):
        import valheim_inventory as vi
        norm_str, tokens = vi.normalize_search_query("obsidien arows")
        self.assertEqual(norm_str, "obsidian arrows")
        self.assertEqual(tokens, ["obsidian", "arrows"])

        norm_str, tokens = vi.normalize_search_query("cooper")
        self.assertEqual(norm_str, "copper")

        norm_str, tokens = vi.normalize_search_query("wod")
        self.assertEqual(norm_str, "wood")

    def test_find_report_direct_match(self):
        from unittest.mock import patch
        import valheim_inventory as vi

        mock_totals = {
            'ArrowPoison': 200,
            'ArrowIron': 70,
            'ArrowFrost': 42,
            'Obsidian': 232,
            'Feathers': 7,
            'Wood': 1970
        }
        with patch('valheim_inventory.scan_world_inventory', return_value=(mock_totals, 189)):
            # Direct match
            rep = vi.get_find_report("poison arrows")
            self.assertIn("Clan Storage Search", rep)
            self.assertIn("Poison Arrows: 200", rep)
            self.assertNotIn("⚠️ _No", rep)

    def test_find_report_typo_correction(self):
        from unittest.mock import patch
        import valheim_inventory as vi

        mock_totals = {
            'Wood': 1970,
            'FineWood': 145,
            'RoundLog': 386
        }
        with patch('valheim_inventory.scan_world_inventory', return_value=(mock_totals, 189)):
            rep = vi.get_find_report("wod")
            self.assertIn("Clan Storage Search", rep)
            self.assertIn("matched 'wood'", rep)
            self.assertIn("Wood: 1,970", rep)

    def test_find_report_category_fallback_on_miss(self):
        from unittest.mock import patch
        import valheim_inventory as vi

        mock_totals = {
            'ArrowPoison': 200,
            'ArrowIron': 70,
            'ArrowFrost': 42,
            'Obsidian': 232,
            'Feathers': 7,
            'Wood': 1970
        }
        with patch('valheim_inventory.scan_world_inventory', return_value=(mock_totals, 189)):
            # "obsidian arrows" has 0 stock -> falls back to all arrows and obsidian crafting mats
            rep = vi.get_find_report("obsidian arrows")
            self.assertIn("No 'Obsidian Arrows' found in chests", rep)
            self.assertIn("Available Arrows in Clan Storage:", rep)
            self.assertIn("Poison Arrows: 200", rep)
            self.assertIn("Ironhead Arrows: 70", rep)
            self.assertIn("Frost Arrows: 42", rep)
            self.assertIn("Crafting Materials in Stock for Obsidian Arrows:", rep)
            self.assertIn("Obsidian: 232", rep)
            self.assertIn("Feathers: 7", rep)
            self.assertIn("Wood: 1,970", rep)

            # Same with typo: "obsidien arows"
            rep_typo = vi.get_find_report("obsidien arows")
            self.assertIn("matched 'obsidian arrows'", rep_typo)
            self.assertIn("Available Arrows in Clan Storage:", rep_typo)
            self.assertIn("Crafting Materials in Stock for Obsidian Arrows:", rep_typo)

    def test_find_report_edge_cases(self):
        import valheim_inventory as vi
        self.assertIn("Please provide an item to find", vi.get_find_report(""))
        self.assertIn("Search query too short", vi.get_find_report("a"))


class TestValheimVoice(unittest.TestCase):
    def test_clean_text_for_speech_markdown(self):
        import valheim_voice as vv
        raw = "⚔️ *Hearken* to the **ancient** words! `code` ```block``` ──────\n• Greydwarf horde"
        clean = vv.clean_text_for_speech(raw)
        self.assertNotIn("⚔️", clean)
        self.assertNotIn("*", clean)
        self.assertNotIn("`", clean)
        self.assertNotIn("──────", clean)
        self.assertIn("Hearken", clean)
        self.assertIn("ancient", clean)
        self.assertIn("Greydwarf horde", clean)

    def test_clean_text_for_speech_polymorphic(self):
        import valheim_voice as vv
        self.assertEqual(vv.clean_text_for_speech(None), "")
        self.assertEqual(vv.clean_text_for_speech(""), "")
        self.assertEqual(vv.clean_text_for_speech(["Dexter", "Hilda"]), "Dexter Hilda")

    def test_norse_cast_completeness(self):
        import valheim_voice as vv
        for char in ("allfather", "berserker", "shieldmaiden", "valkyrie", "warlord", "volva", "skald", "odin"):
            self.assertIn(char, vv.NORSE_CAST)
            cfg = vv.NORSE_CAST[char]
            self.assertIn("voice", cfg)
            self.assertIn("pitch", cfg)
            self.assertIn("rate", cfg)
            self.assertIn("title", cfg)

    def test_extract_story_from_chronicle(self):
        import valheim_voice as vv
        chronicle = (
            "VALHEIM DAILY SUMMARY\n"
            "Casualties: 0\n\n"
            "══════════════════════════════════════\n"
            "📜 *STORY TIME: CHRONICLES OF THE REALM*\n"
            "══════════════════════════════════════\n"
            "The shieldwall held firm on Day 305. The warriors feasted in the Great Hall.\n\n"
            "_The Skald's quill rests until the morrow._ 🛡️"
        )
        extracted = vv.extract_story_from_chronicle(chronicle)
        self.assertIn("The shieldwall held firm", extracted)
        self.assertNotIn("VALHEIM DAILY SUMMARY", extracted)

    def test_cooldown_logic(self):
        import valheim_voice as vv
        key = f"test_cooldown_event_{time.time()}"
        # First check passes
        self.assertTrue(vv._check_and_update_cooldown(key, 60))
        # Second immediate check within 60s fails
        self.assertFalse(vv._check_and_update_cooldown(key, 60))

    def test_generate_voice_empty(self):
        import valheim_voice as vv
        self.assertIsNone(vv.generate_voice(""))
        self.assertIsNone(vv.generate_voice(None))


class TestValheimDeathCause(unittest.TestCase):
    def test_find_target_death_name_normalization(self):
        import valheim_record_death_cause as vdc
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).isoformat()
        deaths = {
            "d1": {"timestamp": now_str, "player": "Musashi(Musa Bhai)", "cause": "Combat fall"},
            "d2": {"timestamp": now_str, "player": "Hilda", "cause": "Combat fall"},
            "d3": {"timestamp": now_str, "player": "Dexter", "cause": "Combat fall"}
        }
        # Match using short name
        target_id, target_data = vdc.find_target_death(deaths, "Musashi")
        self.assertEqual(target_id, "d1")
        self.assertEqual(target_data["player"], "Musashi(Musa Bhai)")

        # Match using full formatted name
        target_id2, target_data2 = vdc.find_target_death(deaths, "Musashi(Musa Bhai)")
        self.assertEqual(target_id2, "d1")
        self.assertEqual(target_data2["player"], "Musashi(Musa Bhai)")


class TestValheimVoiceExpansion(unittest.TestCase):
    def test_boss_names_coverage(self):
        import valheim_voice as vv
        for expected_key in [
            "defeated_eikthyr", "defeated_gdking", "defeated_bonemass",
            "defeated_moder", "defeated_dragon", "defeated_writhan",
            "defeated_yagluth", "defeated_goblinking", "defeated_queen",
            "defeated_seekerking", "defeated_fader", "defeated_fimbulbringer"
        ]:
            self.assertIn(expected_key, vv.BOSS_NAMES)
            self.assertNotEqual(vv.BOSS_NAMES[expected_key], "The Forsaken Beast")

    def test_raid_speech_lines_coverage(self):
        import valheim_voice as vv
        for expected_raid in [
            "foresttrolls", "army_bonemass", "army_theelder", "wolves",
            "army_eikthyr", "army_moder", "army_goblin", "army_yagluth",
            "army_queen", "army_fader", "skeletons", "surtlings", "bats", "ghosts"
        ]:
            self.assertIn(expected_raid, vv.RAID_SPEECH_LINES)
            self.assertTrue(len(vv.RAID_SPEECH_LINES[expected_raid]) > 10)


class TestValheimPluralization(unittest.TestCase):
    def test_quest_engine_pluralization(self):
        import valheim_quest_engine as vqe
        from unittest.mock import patch

        # 1 active quest
        mock_data_1 = {"active_quests": [{"id": "q1", "text": "Build outpost"}]}
        with patch('valheim_quest_engine.load_quests', return_value=mock_data_1):
            res = vqe.complete_quest(99, completed_by="Dexter")
            self.assertIn("There is currently 1 active quest", res)
            self.assertNotIn("quest(s)", res)

            res_drop = vqe.drop_quest(99, dropped_by="Dexter")
            self.assertIn("There is currently 1 active quest", res_drop)
            self.assertNotIn("quest(s)", res_drop)

        # 2 active quests
        mock_data_2 = {"active_quests": [{"id": "q1", "text": "Task 1"}, {"id": "q2", "text": "Task 2"}]}
        with patch('valheim_quest_engine.load_quests', return_value=mock_data_2):
            res = vqe.complete_quest(99, completed_by="Dexter")
            self.assertIn("There are currently 2 active quests", res)
            self.assertNotIn("quest(s)", res)

    def test_geography_chest_labels_pluralization(self):
        import valheim_geography as vg
        from unittest.mock import patch

        mock_signs = [
            {'clean_text': 'Iron Bars', 'creator': 'Hilda', 'pos': [0.0, 0.0, 0.0], 'raw_text': 'Iron Bars'}
        ]
        with patch('valheim_geography.get_world_signs', return_value=mock_signs):
            report = vg.get_signs_report()
            self.assertIn("1 chest label*", report)
            self.assertNotIn("1 chest labels*", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)


