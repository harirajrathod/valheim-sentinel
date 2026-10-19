#!/usr/bin/env python3
"""
/root/test_valheim_crossplay_switch.py
Hermetic unit tests for the Valheim crossplay switching system.
"""

import os
import sys
import tempfile
import unittest
import json
import subprocess
from unittest import mock

sys.path.insert(0, "/root")
import valheim_whatsapp_action as vwa


class TestValheimCrossplaySwitch(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="valheim_cp_test_")
        self.script_path = os.path.join(self.test_dir, "start_valheim.sh")
        self.sample_base_script = (
            "#!/bin/bash\n"
            "cd /root/valheim_server || exit 1\n"
            "./valheim_server.x86_64 -name \"30+ Gamers\" -port 2458 -world \"Valheim10\" -password \"30+Me\" -public 1 -saveinterval 300\n"
        )
        with open(self.script_path, "w", encoding="utf-8") as f:
            f.write(self.sample_base_script)

    def tearDown(self):
        if os.path.exists(self.script_path):
            os.remove(self.script_path)
        if os.path.exists(self.test_dir):
            os.rmdir(self.test_dir)

    def test_set_crossplay_configuration_enable_and_disable(self):
        # 1. Enable crossplay
        res = vwa.set_crossplay_configuration(True, start_script_path=self.script_path)
        self.assertTrue(res)
        with open(self.script_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("-crossplay", content)
        self.assertIn("-name \"30+ Gamers\" -port 2458 -world \"Valheim10\" -password \"30+Me\" -public 1 -saveinterval 300 -crossplay", content)

        # 2. Idempotent enable (should not duplicate -crossplay)
        res_repeat = vwa.set_crossplay_configuration(True, start_script_path=self.script_path)
        self.assertTrue(res_repeat)
        with open(self.script_path, "r", encoding="utf-8") as f:
            content_repeat = f.read()
        self.assertEqual(content_repeat.count("-crossplay"), 1)

        # 3. Disable crossplay
        res_dis = vwa.set_crossplay_configuration(False, start_script_path=self.script_path)
        self.assertTrue(res_dis)
        with open(self.script_path, "r", encoding="utf-8") as f:
            content_dis = f.read()
        self.assertNotIn("-crossplay", content_dis)
        self.assertEqual(content_dis.strip(), self.sample_base_script.strip())

        # 4. Idempotent disable
        res_dis_repeat = vwa.set_crossplay_configuration(False, start_script_path=self.script_path)
        self.assertTrue(res_dis_repeat)
        with open(self.script_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), self.sample_base_script.strip())

    def test_switch_crossplay_dry_run_modes(self):
        # Verify dry-run with on
        res_on = vwa.switch_crossplay("on", dry_run=True)
        self.assertTrue(res_on.get("success"))
        self.assertTrue(res_on.get("dry_run"))
        self.assertTrue(res_on.get("crossplay"))
        self.assertEqual(res_on.get("action"), "enabled")

        # Verify dry-run with off (either already disabled or dry-run simulated)
        res_off = vwa.switch_crossplay("off", dry_run=True)
        self.assertTrue(res_off.get("success"))
        self.assertFalse(res_off.get("crossplay"))

        # Verify status query
        res_status = vwa.switch_crossplay("status", dry_run=True)
        self.assertTrue(res_status.get("success"))
        self.assertTrue(res_status.get("status_only"))
        self.assertIn("mode", res_status)

        # Verify invalid mode rejection
        res_invalid = vwa.switch_crossplay("maybe", dry_run=True)
        self.assertFalse(res_invalid.get("success"))
        self.assertIn("Invalid crossplay mode", res_invalid.get("error", ""))

    def test_switch_crossplay_cli_execution(self):
        # Execute --switch-crossplay status via CLI
        proc = subprocess.run(
            ["/usr/bin/python3", "/root/valheim_whatsapp_action.py", "--switch-crossplay", "status"],
            capture_output=True,
            text=True
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertTrue(data.get("success"))
        self.assertTrue(data.get("status_only"))


if __name__ == "__main__":
    unittest.main()
