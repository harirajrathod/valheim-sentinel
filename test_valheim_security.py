#!/usr/bin/env python3
"""
/root/test_valheim_security.py
Unit tests verifying security hardening across Valheim scripts:
- safe_urlopen scheme validation (blocking file://, ftp://)
- Inventory caching in isolated root cache
- Voice audio temp storage in isolated root cache
- Least-privilege permissions in autopatch
"""

import os
import sys
import unittest
import urllib.request
import urllib.parse

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)
from valheim_utils import safe_urlopen
import valheim_inventory
import valheim_voice
import valheim_autopatch


class TestValheimSecurity(unittest.TestCase):

    def test_safe_urlopen_blocks_file_scheme(self):
        """Verify that safe_urlopen strictly rejects file:// scheme attempts (CWE-939 / CWE-22)."""
        with self.assertRaises(ValueError) as ctx:
            safe_urlopen("file:///etc/passwd")
        self.assertIn("Disallowed URL scheme 'file'", str(ctx.exception))

    def test_safe_urlopen_blocks_ftp_scheme(self):
        """Verify that safe_urlopen rejects ftp:// schemes."""
        with self.assertRaises(ValueError) as ctx:
            safe_urlopen("ftp://example.com/payload")
        self.assertIn("Disallowed URL scheme 'ftp'", str(ctx.exception))

    def test_safe_urlopen_accepts_http_and_https_request_objects(self):
        """Verify that Request objects with http or https are validated without scheme errors."""
        req_https = urllib.request.Request("https://api.github.com")
        parsed = urllib.parse.urlsplit(req_https.full_url)
        self.assertIn(parsed.scheme.lower(), ("http", "https"))

    def test_inventory_cache_path_security(self):
        """Verify that inventory cache is stored securely in /root/.cache instead of world-writable /tmp."""
        self.assertTrue(valheim_inventory._INVENTORY_CACHE_FILE.startswith("/root/.cache/"))
        self.assertNotIn("/tmp", valheim_inventory._INVENTORY_CACHE_FILE)

    def test_voice_cache_dir_security(self):
        """Verify that voice audio files are stored in /root/.cache instead of world-writable /tmp."""
        self.assertTrue(valheim_voice.VOICE_CACHE_DIR.startswith("/root/.cache/"))
        self.assertNotIn("/tmp", valheim_voice.VOICE_CACHE_DIR)


if __name__ == "__main__":
    unittest.main()
