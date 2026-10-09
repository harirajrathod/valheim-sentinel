#!/usr/bin/env python3
"""
/root/test_valheim_farm.py - Unit Tests for Valheim Homestead Farming Engine
"""

import os
import sys
import unittest
import subprocess

sys.path.insert(0, "/root")
import valheim_farm

class TestValheimFarm(unittest.TestCase):
    def test_scan_farm_world_structure(self):
        farm = valheim_farm.scan_farm_world()
        self.assertIsInstance(farm, dict)
        self.assertIn('ready_seeds', farm)
        self.assertIn('ready_crops', farm)
        self.assertIn('growing', farm)
        self.assertIn('beehives', farm)
        self.assertIn('total_ready', farm)
        self.assertIn('total_growing', farm)
        self.assertGreaterEqual(farm['total_ready'], 0)
        self.assertGreaterEqual(farm['beehives'], 0)

    def test_format_farm_report(self):
        report = valheim_farm.format_farm_report()
        self.assertIsInstance(report, str)
        self.assertIn("VALHEIM HOMESTEAD & FARM REPORT", report)
        self.assertIn("Beehives", report)
        self.assertIn("Clan Pantry Stock", report)

    def test_format_cycle_complete_announcement(self):
        farm = valheim_farm.scan_farm_world()
        msg = valheim_farm.format_cycle_complete_announcement(farm)
        self.assertIsInstance(msg, str)
        self.assertIn("SEED CYCLE COMPLETE!", msg)
        self.assertIn("Harvest Bounty in the Fields", msg)
        self.assertIn("Cultivator", msg)

    def test_check_and_announce_dry_run(self):
        res = valheim_farm.check_and_announce_seed_cycle(force=True, dry_run=True)
        self.assertTrue(res)

    def test_valheim_info_cli_integration(self):
        res = subprocess.run(["python3", "/root/valheim_info.py", "--farm"], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("VALHEIM HOMESTEAD & FARM REPORT", res.stdout)

if __name__ == "__main__":
    unittest.main()
