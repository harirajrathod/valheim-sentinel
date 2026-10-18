#!/usr/bin/env python3
"""
/root/test_valheim_backup_drive.py - Unit Test Suite for Valheim Google Drive Backup Engine
"""

import os
import sys
import tempfile
import unittest
import shutil
import time

sys.path.insert(0, "/root")
import valheim_backup_drive as vbd


class TestValheimBackupDrive(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="valheim_drive_test_")
        self.world_dir = os.path.join(self.test_dir, "Valheim10")
        os.makedirs(self.world_dir, exist_ok=True)

        # Create mock chunk and save files
        for i in range(5):
            chunk_file = os.path.join(self.world_dir, f"chunk_{i}.chunk")
            with open(chunk_file, "w") as f:
                f.write(f"chunk data {i}")

        self.ok_file = os.path.join(self.world_dir, "_main.9999.ok")
        with open(self.ok_file, "w") as f:
            f.write("*")

        self.db2_file = os.path.join(self.world_dir, "_main.9999.db2")
        with open(self.db2_file, "w") as f:
            f.write("db2 content")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_active_save_info_valid(self):
        info = vbd.get_active_save_info(self.world_dir)
        self.assertTrue(info["exists"])
        self.assertEqual(info["save_id"], 9999)
        self.assertEqual(info["chunk_count"], 5)
        self.assertGreater(info["mtime"], 0.0)

    def test_get_active_save_info_nonexistent(self):
        info = vbd.get_active_save_info("/path/does/not/exist/999")
        self.assertFalse(info["exists"])
        self.assertIsNone(info["save_id"])
        self.assertEqual(info["chunk_count"], 0)

    def test_get_active_save_info_fallback_to_db2(self):
        # Remove .ok file and verify fallback to .db2
        os.remove(self.ok_file)
        info = vbd.get_active_save_info(self.world_dir)
        self.assertTrue(info["exists"])
        self.assertEqual(info["save_id"], 9999)

    def test_state_load_and_atomic_save(self):
        original_state_file = vbd.STATE_FILE
        test_state_file = os.path.join(self.test_dir, "test_state.json")
        try:
            vbd.STATE_FILE = test_state_file
            st = vbd.load_drive_backup_state()
            self.assertEqual(st.get("last_status"), "NEVER_RUN")

            vbd.update_drive_backup_state(
                save_id=9999,
                status="SUCCESS",
                duration=1.23,
                trigger="unit_test",
                snapshot_created=True
            )

            st2 = vbd.load_drive_backup_state()
            self.assertEqual(st2["last_save_id"], 9999)
            self.assertEqual(st2["last_status"], "SUCCESS")
            self.assertEqual(st2["last_duration_sec"], 1.23)
            self.assertEqual(st2["total_backups_performed"], 1)
            self.assertEqual(st2["last_snapshot_save_id"], 9999)
            self.assertEqual(len(st2["history"]), 1)
        finally:
            vbd.STATE_FILE = original_state_file

    def test_dry_run_backup(self):
        original_world_dir = vbd.WORLD_DIR
        original_state_file = vbd.STATE_FILE
        test_state_file = os.path.join(self.test_dir, "test_state_dry.json")
        try:
            vbd.WORLD_DIR = self.world_dir
            vbd.STATE_FILE = test_state_file
            res = vbd.perform_drive_backup(trigger="unit_test", force=True, dry_run=True)
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(res["save_id"], 9999)
        finally:
            vbd.WORLD_DIR = original_world_dir
            vbd.STATE_FILE = original_state_file

    def test_concurrency_lock(self):
        original_lock = vbd.LOCK_FILE
        test_lock = os.path.join(self.test_dir, "test.lock")
        fd = None
        try:
            vbd.LOCK_FILE = test_lock
            # Hold lock externally
            fd = open(test_lock, "w")
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            res = vbd.perform_drive_backup(trigger="concurrency_test", force=True, dry_run=True)
            self.assertFalse(res["success"])
            self.assertEqual(res["status"], "LOCKED")
        finally:
            if fd:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    fd.close()
                except Exception:
                    pass
            vbd.LOCK_FILE = original_lock

    def test_status_text_formatting(self):
        text = vbd.get_formatted_status_text()
        self.assertIn("Valheim Cloud Backup Status", text)
        self.assertIn("Current World Save", text)
        self.assertIn("Google Drive Save", text)
        self.assertIn("Drive Folder", text)

    def test_async_trigger_non_blocking(self):
        t0 = time.time()
        vbd.trigger_drive_backup_async(trigger="async_test")
        elapsed = time.time() - t0
        # Trigger call must be virtually instantaneous (<0.1s)
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    unittest.main()
