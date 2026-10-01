"""
tests/test_parser.py - Regression & Unit Tests for Valheim Sentinel
"""

import unittest
import os
import sys

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import SafeFormatDict
from telemetry.db_parser import get_stable_hash, ValheimWorldParser, ITEM_CATALOG
from monitor.roasts import (
    format_roast,
    get_random_join,
    get_random_leave,
    get_session_leave_message,
    get_session_resume_message,
    JOIN_TEMPLATES,
    LEAVE_TEMPLATES,
    MACRO_ROASTS
)
from telemetry.world_state import BOSS_PROGRESSION
from skald.weekly_superlatives import generate_superlatives_report
from skald.daily_chronicle import build_daily_digest

class TestValheimSentinel(unittest.TestCase):

    def test_stable_hash_consistency(self):
        """Valheim string hashes must match engine expectations."""
        h_items = get_stable_hash("items")
        self.assertIsInstance(h_items, int)
        self.assertEqual(get_stable_hash("items"), h_items)
        self.assertEqual(get_stable_hash("Coins"), get_stable_hash("Coins"))
        self.assertNotEqual(get_stable_hash("Copper"), get_stable_hash("Tin"))

    def test_safe_format_dict(self):
        """Templates must never crash on missing formatting keys."""
        d = SafeFormatDict(name="Ragnar")
        formatted = "Hail {name}! You have {missing_key} gold.".format_map(d)
        self.assertEqual(formatted, "Hail Ragnar! You have  gold.")

    def test_format_roast_hermetic(self):
        """Roasts must safely inject character name and strip residual braces."""
        tmpl = "⚔️ {name} joined the fray! Rested: {duration} min."
        res = format_roast(tmpl, "Lagertha")
        self.assertIn("Lagertha", res)
        self.assertNotIn("{name}", res)
        self.assertNotIn("{duration}", res)

    def test_random_messages_generation(self):
        """Join and leave generators must output valid strings."""
        join_msg = get_random_join("Bjorn")
        self.assertTrue(len(join_msg) > 10)
        self.assertIn("Bjorn", join_msg)

        leave_msg = get_random_leave("Bjorn")
        self.assertTrue(len(leave_msg) > 10)
        self.assertIn("Bjorn", leave_msg)

    def test_session_context_roasts(self):
        """Session-context roasts must properly format with session metadata."""
        corpse_msg = get_session_leave_message(
            "Torstein",
            "CORPSE_RUN_FAIL",
            {"duration_mins": 12, "deaths_count": 3}
        )
        self.assertIn("Torstein", corpse_msg)
        self.assertNotIn("{name}", corpse_msg)

        resume_msg = get_session_resume_message(
            "Torstein",
            {"event_type": "CORPSE_RUN_FAIL", "deaths_count": 3}
        )
        self.assertIn("Torstein", resume_msg)

    def test_roast_template_pool_size(self):
        """Must satisfy the 100+ roasts standard."""
        leaves = sum(len(v.get("leave", [])) for v in MACRO_ROASTS.values())
        resumes = sum(len(v.get("resume", [])) for v in MACRO_ROASTS.values())
        total = len(JOIN_TEMPLATES) + len(LEAVE_TEMPLATES) + leaves + resumes
        self.assertGreaterEqual(total, 100)

    def test_item_catalog_completeness(self):
        """Catalog must contain comprehensive metal, food, and boss materials."""
        self.assertGreaterEqual(len(ITEM_CATALOG), 150)
        self.assertIn("Copper", ITEM_CATALOG)
        self.assertIn("Iron", ITEM_CATALOG)
        self.assertIn("Silver", ITEM_CATALOG)
        self.assertIn("BlackMetal", ITEM_CATALOG)
        self.assertIn("Flametal", ITEM_CATALOG)
        self.assertIn("AncientSeed", ITEM_CATALOG)
        self.assertIn("WitheredBone", ITEM_CATALOG)

    def test_world_parser_reports_hermetic(self):
        """Reports must generate cleanly even when no world file is present."""
        parser = ValheimWorldParser(worlds_dir="/tmp/nonexistent_worlds", world_name="MockWorld")
        wealth_rep = parser.get_wealth_report()
        self.assertIn("TRIBAL TREASURY", wealth_rep)

        metal_rep = parser.get_metal_report()
        self.assertIn("METALLURGY", metal_rep)

        portal_rep = parser.get_portal_report()
        self.assertIn("PORTAL DIRECTORY", portal_rep)

    def test_boss_progression_structure(self):
        """Boss progression hierarchy must contain all 7 Forsaken bosses."""
        self.assertEqual(len(BOSS_PROGRESSION), 7)
        keys = [b[0] for b in BOSS_PROGRESSION]
        self.assertIn("defeated_eikthyr", keys)
        self.assertIn("defeated_gdking", keys)
        self.assertIn("defeated_bonemass", keys)
        self.assertIn("defeated_dragon", keys)
        self.assertIn("defeated_goblinking", keys)
        self.assertIn("defeated_queen", keys)
        self.assertIn("defeated_fader", keys)

    def test_daily_digest_generation(self):
        """Daily battle digest must generate formatted markdown without errors."""
        digest = build_daily_digest(hours=24, include_ai=False)
        self.assertIn("VALHEIM DAILY CHRONICLE", digest)
        self.assertIn("WARRIORS ON THE FRONTIER", digest)
        self.assertIn("CLAN TREASURY", digest)

    def test_weekly_superlatives_generation(self):
        """Weekly Hall of Fame report must compile cleanly."""
        report = generate_superlatives_report(days=7)
        self.assertIn("VALHEIM WEEKLY HALL OF FAME", report)
        self.assertIn("The Grand Beaver", report)
        self.assertIn("The Iron Jarl", report)


from unittest.mock import patch, MagicMock
from monitor.sentinel import ValheimSentinel


class TestSentinelProcessLine(unittest.TestCase):
    """Unit tests for the real-time log line parser."""

    def setUp(self):
        self.sentinel = ValheimSentinel(log_path="/tmp/fake.log")

    @patch('monitor.sentinel.notifier')
    def test_player_join_valid_zdoid(self, mock_notifier):
        """Non-zero ZDOID triggers join announcement."""
        self.sentinel.process_line("Got character ZDOID from Ragnar : 1234:5678")
        self.assertIn("Ragnar", self.sentinel.active_players)
        mock_notifier.broadcast.assert_called_once()

    @patch('monitor.sentinel.notifier')
    def test_player_join_zero_zdoid_ignored(self, mock_notifier):
        """ZDOID 0:0 (death) should NOT trigger a join announcement."""
        self.sentinel.process_line("Got character ZDOID from Ragnar : 0:0")
        self.assertNotIn("Ragnar", self.sentinel.active_players)
        mock_notifier.broadcast.assert_not_called()

    @patch('monitor.sentinel.notifier')
    def test_player_leave_destroy_zdo(self, mock_notifier):
        """Destroying abandoned ZDO triggers leave announcement."""
        self.sentinel.active_players["Lagertha"] = "Lagertha"
        self.sentinel.process_line("Destroying abandoned non persistent zdo 1234 for player Lagertha")
        self.assertNotIn("Lagertha", self.sentinel.active_players)
        mock_notifier.broadcast.assert_called_once()

    @patch('monitor.sentinel.notifier')
    def test_player_count_zero_clears_all(self, mock_notifier):
        """Player count dropping to 0 announces all remaining players leaving."""
        self.sentinel.active_players["Bjorn"] = "Bjorn"
        self.sentinel.active_players["Floki"] = "Floki"
        self.sentinel.process_line("now 0 player(s)")
        self.assertEqual(len(self.sentinel.active_players), 0)
        self.assertEqual(mock_notifier.broadcast.call_count, 2)

    @patch('monitor.sentinel.notifier')
    def test_raid_event_triggers_horn_of_war(self, mock_notifier):
        """Raid event fires Horn of War notification with debounce."""
        self.sentinel.active_players["Ragnar"] = "Ragnar"
        self.sentinel.process_line("Random event set:army_theelder")
        mock_notifier.broadcast.assert_called_once()
        msg = mock_notifier.broadcast.call_args[0][0]
        self.assertIn("HORN OF WAR", msg)
        self.assertIn("Ragnar", msg)

    @patch('monitor.sentinel.notifier')
    def test_raid_debounce(self, mock_notifier):
        """Second raid within 5 minutes is debounced."""
        import time
        self.sentinel.last_raid_time = time.time()  # Just fired
        self.sentinel.process_line("Random event set:army_theelder")
        mock_notifier.broadcast.assert_not_called()

    @patch('monitor.sentinel.notifier')
    def test_boss_defeat_announcement(self, mock_notifier):
        """Boss defeat global key triggers celebration."""
        self.sentinel.process_line("Setting global key defeated_eikthyr")
        mock_notifier.broadcast.assert_called_once()
        msg = mock_notifier.broadcast.call_args[0][0]
        self.assertIn("FORSAKEN VANQUISHED", msg)

    @patch('monitor.sentinel.notifier')
    def test_duplicate_join_debounced(self, mock_notifier):
        """Same player joining twice doesn't double-announce."""
        self.sentinel.process_line("Got character ZDOID from Ragnar : 1234:5678")
        self.sentinel.process_line("Got character ZDOID from Ragnar : 1234:9999")
        self.assertEqual(mock_notifier.broadcast.call_count, 1)

    @patch('monitor.sentinel.notifier')
    def test_leave_without_join_is_noop(self, mock_notifier):
        """Leave for unknown player doesn't crash or announce."""
        self.sentinel.process_line("Destroying abandoned non persistent zdo 1234 for player Ghost")
        mock_notifier.broadcast.assert_not_called()


if __name__ == "__main__":
    unittest.main()
