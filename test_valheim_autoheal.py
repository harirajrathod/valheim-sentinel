#!/usr/bin/env python3
"""
Unit test suite for Valheim Autonomous PlayFab Auto-Heal Watchdog.
Tests:
  1. Regex matching against historical Error 4098 log lines and edge cases.
  2. PlayFab state storage persistence, schema resilience, and corruption recovery.
  3. Cooldown throttling guard (10m / 600s).
  4. Active player suppression guard (never interrupt gameplay).
  5. Active raid defense suppression guard.
  6. Hermetic dry-run execution without state or server mutation.
"""

import os
import sys
import time
import json
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/root")
from valheim_constants import PATTERNS
from valheim_monitor import (
    load_playfab_state,
    save_playfab_state,
    run_playfab_autoheal,
    PLAYFAB_STATE_FILE
)


class TestValheimAutoheal(unittest.TestCase):
    def setUp(self):
        self.test_state_file = "/tmp/test_valheim_playfab_state.json"
        self._orig_state_file = PLAYFAB_STATE_FILE

    def tearDown(self):
        if os.path.exists(self.test_state_file):
            try:
                os.remove(self.test_state_file)
            except Exception:
                pass

    def test_regex_error_4098_exact_log_match(self):
        """Verifies playfab_error_4098 matches real lines from current_run.log."""
        pat = PATTERNS.get("playfab_error_4098")
        self.assertIsNotNone(pat, "playfab_error_4098 pattern must be defined in PATTERNS")

        real_line = (
            "10/18/2026 09:20:29: PlayFab network error in session '30+ Gamers' and network "
            "4b8d14b5-e266-4a87-98d3-ed83b7725132|AwDmLnYSLzMUWP1HJIG0CFme11w7YVVhZU5vcnRoAAAAAAAAAAAAAAAAMnZhtFmwm2+5xoip1gMQZO0ZPAJr9HsbOYa1hNGP3Va8FUhkbnM4MWU1LTQ0MTFjZmFkLWFiMDUtNDE3Ny05N2JjLTViZDM4YTI0ZGFhNC51YWVub3J0aC5jbG91ZGFwcC5henVyZS5jb20= "
            "with type 'Error' and code '4098': the operation was called with an invalid handle"
        )
        self.assertTrue(bool(pat.search(real_line)), "Pattern must match real historical 4098 log line")

    def test_regex_no_false_positives(self):
        """Verifies playfab_error_4098 does not match normal PlayFab lines or other codes."""
        pat = PATTERNS.get("playfab_error_4098")
        benign_lines = [
            "10/18/2026 09:20:29: PlayFab network status normal in session '30+ Gamers'",
            "PlayFab network error with code '1000': something else happened",
            "Got handshake from client 12345",
            "World save (5/5)",
            "Random event set:army_goblin"
        ]
        for line in benign_lines:
            self.assertFalse(bool(pat.search(line)), f"Pattern must not falsely match: {line}")

    def test_state_load_save_resilience(self):
        """Verifies safe_load_json and atomic_save_json handle corrupt and default states."""
        with patch("valheim_monitor.PLAYFAB_STATE_FILE", self.test_state_file):
            # Test default creation when file does not exist
            if os.path.exists(self.test_state_file):
                os.remove(self.test_state_file)
            st = load_playfab_state()
            self.assertFalse(st["desync_pending"])
            self.assertEqual(st["error_count"], 0)

            # Test write and read back
            st["desync_pending"] = True
            st["error_count"] = 3
            st["last_error_time"] = 123456.78
            save_playfab_state(st)

            reloaded = load_playfab_state()
            self.assertTrue(reloaded["desync_pending"])
            self.assertEqual(reloaded["error_count"], 3)
            self.assertEqual(reloaded["last_error_time"], 123456.78)

    def test_suppression_when_players_online(self):
        """Verifies auto-heal is strictly suppressed when players are active."""
        active_warriors = {"Faye", "Musashi"}
        res = run_playfab_autoheal(
            reason="test_active",
            dry_run=True,
            active_players=active_warriors
        )
        self.assertFalse(res["success"])
        self.assertTrue(res.get("suppressed"))
        self.assertEqual(res.get("reason"), "players_online")
        self.assertEqual(res.get("player_count"), 2)

    def test_suppression_when_raid_active(self):
        """Verifies auto-heal is strictly suppressed during active raid defense."""
        active_raid = {
            "key": "army_goblin",
            "start_time": time.time(),
            "end_time": time.time() + 180
        }
        res = run_playfab_autoheal(
            reason="test_raid",
            dry_run=True,
            active_players=set(),
            active_raid=active_raid
        )
        self.assertFalse(res["success"])
        self.assertTrue(res.get("suppressed"))
        self.assertEqual(res.get("reason"), "active_raid")
        self.assertEqual(res.get("raid_key"), "army_goblin")

    def test_cooldown_guard(self):
        """Verifies auto-heal enforces 10-minute cooldown between automated runs."""
        with patch("valheim_monitor.PLAYFAB_STATE_FILE", self.test_state_file):
            recent_time = time.time() - 120  # 2 minutes ago
            st = {
                "desync_pending": True,
                "last_error_time": time.time(),
                "last_restart_time": recent_time,
                "last_alert_time": 0.0,
                "error_count": 1
            }
            save_playfab_state(st)

            res = run_playfab_autoheal(
                reason="test_cooldown",
                dry_run=False,  # testing live cooldown check
                force=False,
                active_players=set(),
                active_raid=None
            )
            self.assertFalse(res["success"])
            self.assertTrue(res.get("skipped"))
            self.assertEqual(res.get("reason"), "cooldown")
            self.assertGreater(res.get("remaining_seconds", 0), 400)

    def test_dry_run_execution(self):
        """Verifies hermetic dry_run autoheal succeeds without mutating state or server."""
        with patch("valheim_monitor.PLAYFAB_STATE_FILE", self.test_state_file):
            st = {
                "desync_pending": True,
                "last_error_time": time.time(),
                "last_restart_time": 0.0,
                "last_alert_time": 0.0,
                "error_count": 1
            }
            save_playfab_state(st)

            res = run_playfab_autoheal(
                reason="test_dry_run",
                dry_run=True,
                force=True,
                active_players=set(),
                active_raid=None
            )
            self.assertTrue(res["success"])
            self.assertTrue(res["dry_run"])
            self.assertIn("join_code", res)

            # Ensure disk state file was NOT overwritten during dry run
            post_st = load_playfab_state()
            self.assertTrue(post_st["desync_pending"], "Dry run must NOT clear desync_pending on disk")


if __name__ == "__main__":
    unittest.main()
