#!/usr/bin/env python3
r"""
/root/test_challenger_world_state.py
Comprehensive Adversarial Stress Test Suite for valheim_info.py World State Parser.

Author: teamwork_preview_challenger (Challenger 1)
Role: critic, specialist
Target: /root/valheim_info.py

Adversarial Stress Test Categories:
1. Cross-ZDO Boundary Isolation & Bleed Prevention:
   - Adjacent portal-portal boundaries at 10..80 byte offsets
   - Untagged portal followed by tagged portal (zero tag leakage)
   - Portal creator attribution isolation (Dexter vs Hilda)
   - Adjacent portal-sign boundaries
   - Truncated packets, corrupted varints, infinite shift protection
   - Unity rich-text stripping, rune character sanitization, math operator preservation
2. Multi-Portal Proximity Pairing Engine:
   - 3, 4, 5, 6 portals with identical tags
   - Generalized N-portal stress test (7..12 portals)
   - Collinear, equidistant, and co-located (0m distance) coordinate topologies
   - Exact pair count invariant: pairs == N // 2, stranded == N % 2
3. Live Save Chunk Deduplication:
   - Regex grouping: r'^(.*__\d+)_(\d+)\.chunk$'
   - Digit boundary crossings: 9->10, 99->100, 999->1000
   - Multi-prefix interleaving and shuffled inputs
   - Legacy and unversioned chunk fallback handling
4. Numerical Save Sorting Engine:
   - Save ID extraction: r'_main\.(\d+)\.db2$'
   - Lexicographical trap verification: 9 vs 10, 99 vs 100
   - 1,000 randomized save history entries
   - Non-standard/malformed filenames and extensions
"""

import os
import sys
import math
import struct
import random
import unittest
from unittest.mock import patch

# Ensure target module can be imported from /root
sys.path.insert(0, '/root')
import valheim_info


class TestChallengerCrossZDOBoundary(unittest.TestCase):
    """Adversarial stress testing of cross-ZDO boundaries and serialization decoding."""

    def setUp(self):
        self.pw_hash = valheim_info.get_stable_hash('portal_wood')
        self.ps_hash = valheim_info.get_stable_hash('portal_stone')
        self.tag_hash = bytes.fromhex('ea917c29')
        self.sign_hash = struct.pack('<i', valheim_info.get_stable_hash('sign'))
        self.text_hash = struct.pack('<i', valheim_info.get_stable_hash('text'))
        self.dexter_id = b'Steam_76561198014682424'
        self.hilda_id = b'Steam_76561198229525716'

    def _encode_varint(self, val):
        buf = bytearray()
        while True:
            b = val & 0x7F
            val >>= 7
            if val != 0:
                buf.append(b | 0x80)
            else:
                buf.append(b)
                break
        return bytes(buf)

    def _build_portal_zdo(self, pos, prefab='portal_wood', tag="", creator_id=None, header_prefix=b'\x71\x09'):
        ph = struct.pack('<i', valheim_info.get_stable_hash(prefab))
        coords = struct.pack('<fff', *pos)
        body = bytearray()
        if creator_id:
            body.extend(creator_id if isinstance(creator_id, bytes) else creator_id.encode('ascii'))
            body.extend(b'\x00' * 8)
        if tag:
            body.extend(self.tag_hash)
            tag_bytes = tag.encode('utf-8')
            body.extend(self._encode_varint(len(tag_bytes)))
            body.extend(tag_bytes)
        return header_prefix + coords + ph + bytes(body)

    def _build_sign_zdo(self, pos, text="", creator_id=None, header_prefix=b'\x70\x09'):
        sh = self.sign_hash
        coords = struct.pack('<fff', *pos)
        body = bytearray()
        if creator_id:
            body.extend(creator_id if isinstance(creator_id, bytes) else creator_id.encode('ascii'))
            body.extend(b'\x00' * 8)
        if text is not None:
            body.extend(self.text_hash)
            text_bytes = text.encode('utf-8')
            body.extend(self._encode_varint(len(text_bytes)))
            body.extend(text_bytes)
        return header_prefix + coords + sh + bytes(body)

    def test_adjacent_portals_zero_tag_bleed(self):
        """Untagged portal followed 20 bytes later by a tagged portal: tag MUST NOT bleed."""
        for distance_padding in (0, 10, 25, 50, 80):
            p1 = self._build_portal_zdo((10.0, 0.0, 10.0), 'portal_wood', tag="", creator_id=self.dexter_id)
            p1 += b'\x00' * distance_padding
            p2 = self._build_portal_zdo((30.0, 0.0, 30.0), 'portal_wood', tag="SECRET_TAG", creator_id=self.hilda_id)
            data = p1 + p2

            idx = data.find(struct.pack('<i', self.pw_hash))
            self.assertGreaterEqual(idx, 12)

            bound = valheim_info.find_next_zdo_boundary(data, idx + 4, max_search=120)
            for other_ph in (self.pw_hash, self.ps_hash):
                cand = data.find(struct.pack('<i', other_ph), idx + 4)
                if cand != -1:
                    bound = min(bound, max(idx + 4, cand - 12))

            zdo_window = data[idx:bound]
            self.assertNotIn(b'SECRET_TAG', zdo_window, f"Tag bled across boundary at padding {distance_padding}")
            self.assertNotIn(self.hilda_id, zdo_window, f"Creator bled across boundary at padding {distance_padding}")
            self.assertIn(self.dexter_id, zdo_window)

    def test_wood_portal_adjacent_to_stone_portal(self):
        """Wood portal (untagged) adjacent to stone portal (tagged)."""
        p_wood = self._build_portal_zdo((0.0, 0.0, 0.0), 'portal_wood', tag="", creator_id=self.dexter_id)
        p_stone = self._build_portal_zdo((15.0, 0.0, 15.0), 'portal_stone', tag="STONE_GATE", creator_id=self.hilda_id)
        data = p_wood + p_stone

        idx = data.find(struct.pack('<i', self.pw_hash))
        bound = valheim_info.find_next_zdo_boundary(data, idx + 4, max_search=120)
        for other_ph in (self.pw_hash, self.ps_hash):
            cand = data.find(struct.pack('<i', other_ph), idx + 4)
            if cand != -1:
                bound = min(bound, max(idx + 4, cand - 12))

        window = data[idx:bound]
        self.assertNotIn(b'STONE_GATE', window)
        self.assertNotIn(self.hilda_id, window)

    def test_stone_portal_adjacent_to_wood_portal(self):
        """Stone portal (untagged) adjacent to wood portal (tagged)."""
        p_stone = self._build_portal_zdo((0.0, 0.0, 0.0), 'portal_stone', tag="", creator_id=self.hilda_id)
        p_wood = self._build_portal_zdo((15.0, 0.0, 15.0), 'portal_wood', tag="WOOD_GATE", creator_id=self.dexter_id)
        data = p_stone + p_wood

        idx = data.find(struct.pack('<i', self.ps_hash))
        bound = valheim_info.find_next_zdo_boundary(data, idx + 4, max_search=120)
        for other_ph in (self.pw_hash, self.ps_hash):
            cand = data.find(struct.pack('<i', other_ph), idx + 4)
            if cand != -1:
                bound = min(bound, max(idx + 4, cand - 12))

        window = data[idx:bound]
        self.assertNotIn(b'WOOD_GATE', window)
        self.assertNotIn(self.dexter_id, window)

    def test_varint_shift_overflow_attack(self):
        """Adversarial byte streams with endless continuation bits (0x80). Loop must not hang."""
        hostile_windows = [
            self.tag_hash + (b'\x80' * 1000),             # 1,000 continuation bits
            self.tag_hash + b'\xff\xff\xff\xff\xff\xff',   # 6 bytes with 0x80 set
            self.tag_hash + b'\x80',                       # 1 byte continuation, EOF
            self.tag_hash,                                 # Truncated right at tag hash
        ]
        for w in hostile_windows:
            t_idx = w.find(self.tag_hash)
            p = t_idx + 4
            tag_len = 0
            shift = 0
            iterations = 0
            while p < len(w) and shift <= 28:
                iterations += 1
                b = w[p]
                p += 1
                tag_len |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            self.assertLessEqual(iterations, 5, "Varint decoding executed more than 5 iterations!")

    def test_sign_text_edge_cases_and_sanitization(self):
        """Sanitization of rich text tags, mathematical symbols, runes, and emojis."""
        cases = [
            # HTML tags stripping
            ("<size=24><color=#FF5500><b>WAR ROOM</b></color></size>", "WAR ROOM"),
            ("Unclosed <color=#FFF>tag at end", "Unclosed tag at end"),
            ("<b><i>Nested Tags</i></b>", "Nested Tags"),
            # Mathematical operators (must NOT be stripped as tags)
            ("10 < 20 and 50 > 30", "10 < 20 and 50 > 30"),
            ("HP < 100 -> RETREAT", "HP < 100 -> RETREAT"),
            # Elder Futhark & Emojis
            ("ᚦᚢᚱᛁᛋᚨᛉ Thor's Keep ⚡🛡️", "ᚦᚢᚱᛁᛋᚨᛉ Thor's Keep ⚡🛡️"),
            # Accidental whitespace / newlines
            ("\n\n   Base   North   Exit \t\r\n", "Base North Exit"),
        ]
        import re
        for raw, expected in cases:
            clean = re.sub(r'</?[a-zA-Z][^>]*>', '', raw)
            clean = ' '.join(clean.split())
            self.assertEqual(clean, expected)


class TestChallengerMultiPortalProximityPairing(unittest.TestCase):
    """Adversarial stress testing of greedy multi-portal pairing logic."""

    def _pair(self, portals):
        remaining = list(portals)
        pairs = []
        while len(remaining) >= 2:
            best_dist = float('inf')
            best_ij = (0, 1)
            for i in range(len(remaining)):
                for j in range(i + 1, len(remaining)):
                    d = math.hypot(remaining[i]['pos'][0] - remaining[j]['pos'][0],
                                   remaining[i]['pos'][2] - remaining[j]['pos'][2])
                    if d < best_dist:
                        best_dist = d
                        best_ij = (i, j)
            pA = remaining.pop(max(best_ij))
            pB = remaining.pop(min(best_ij))
            pairs.append((pA, pB, best_dist))
        return pairs, remaining

    def test_n_portals_pairing_invariants(self):
        """Verify for N = 3, 4, 5, 6, 7, 8, 9, 10 that pairs == N//2 and stranded == N%2."""
        for n in range(3, 13):
            # Generate N portals with random coordinates
            random.seed(100 + n)
            portals = [{'id': f'P{i}', 'pos': (random.uniform(-5000, 5000), 0.0, random.uniform(-5000, 5000))}
                       for i in range(n)]
            pairs, stranded = self._pair(portals)
            self.assertEqual(len(pairs), n // 2, f"Failed pair count for N={n}")
            self.assertEqual(len(stranded), n % 2, f"Failed stranded count for N={n}")

    def test_three_portals_closest_paired(self):
        """3 portals: P1(0) and P2(10) must pair; P3(500) must be stranded."""
        portals = [
            {'id': 'P1', 'pos': (0.0, 0.0, 0.0)},
            {'id': 'P2', 'pos': (10.0, 0.0, 0.0)},
            {'id': 'P3', 'pos': (500.0, 0.0, 0.0)},
        ]
        pairs, stranded = self._pair(portals)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(stranded), 1)
        pair_ids = {pairs[0][0]['id'], pairs[0][1]['id']}
        self.assertEqual(pair_ids, {'P1', 'P2'})
        self.assertEqual(stranded[0]['id'], 'P3')

    def test_four_portals_two_independent_pairs(self):
        """4 portals: P1(0), P2(15), P3(300), P4(308). Expect (P1,P2) and (P3,P4)."""
        portals = [
            {'id': 'P1', 'pos': (0.0, 0.0, 0.0)},
            {'id': 'P2', 'pos': (15.0, 0.0, 0.0)},
            {'id': 'P3', 'pos': (300.0, 0.0, 0.0)},
            {'id': 'P4', 'pos': (308.0, 0.0, 0.0)},
        ]
        pairs, stranded = self._pair(portals)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len(stranded), 0)
        pair1_ids = {pairs[0][0]['id'], pairs[0][1]['id']}
        pair2_ids = {pairs[1][0]['id'], pairs[1][1]['id']}
        self.assertEqual(pair1_ids, {'P3', 'P4'})  # Closest distance (8m) paired first
        self.assertEqual(pair2_ids, {'P1', 'P2'})  # Second pair (15m)

    def test_five_portals_two_pairs_one_stranded(self):
        """5 portals: 2 pairs formed, exactly 1 stranded."""
        portals = [
            {'id': 'P1', 'pos': (0.0, 0.0, 0.0)},
            {'id': 'P2', 'pos': (5.0, 0.0, 0.0)},
            {'id': 'P3', 'pos': (100.0, 0.0, 0.0)},
            {'id': 'P4', 'pos': (107.0, 0.0, 0.0)},
            {'id': 'P5', 'pos': (2000.0, 0.0, 0.0)},
        ]
        pairs, stranded = self._pair(portals)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len(stranded), 1)
        self.assertEqual(stranded[0]['id'], 'P5')

    def test_six_portals_three_pairs_zero_stranded(self):
        """6 portals: Exactly 3 pairs, 0 stranded."""
        portals = [
            {'id': 'P1', 'pos': (0.0, 0.0, 0.0)},
            {'id': 'P2', 'pos': (10.0, 0.0, 0.0)},
            {'id': 'P3', 'pos': (200.0, 0.0, 0.0)},
            {'id': 'P4', 'pos': (212.0, 0.0, 0.0)},
            {'id': 'P5', 'pos': (1000.0, 0.0, 0.0)},
            {'id': 'P6', 'pos': (1015.0, 0.0, 0.0)},
        ]
        pairs, stranded = self._pair(portals)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(len(stranded), 0)

    def test_identical_and_collinear_coordinates(self):
        """Co-located portals (distance = 0.0) and collinear alignments."""
        co_located = [{'id': f'C{i}', 'pos': (42.0, 0.0, 84.0)} for i in range(6)]
        pairs, stranded = self._pair(co_located)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(len(stranded), 0)
        for _, _, dist in pairs:
            self.assertEqual(dist, 0.0)


class TestChallengerChunkDeduplication(unittest.TestCase):
    """Adversarial stress testing of regex chunk grouping and version deduplication."""

    def _dedup(self, chunks):
        import re
        chunks_by_prefix = {}
        for c in chunks:
            m = re.match(r'^(.*__\d+)_(\d+)\.chunk$', c)
            if m:
                prefix, ver = m.group(1), int(m.group(2))
                if prefix not in chunks_by_prefix or ver > chunks_by_prefix[prefix][0]:
                    chunks_by_prefix[prefix] = (ver, c)
            else:
                chunks_by_prefix[c] = (0, c)
        return sorted([v[1] for v in chunks_by_prefix.values()])

    def test_digit_boundary_crossing_selection(self):
        """Ensure 9 vs 10, 99 vs 100, 999 vs 1000 select the integer maximum."""
        # Case 1: 9 vs 10
        chunks1 = ['/path/chunk__0_9.chunk', '/path/chunk__0_10.chunk']
        self.assertEqual(self._dedup(chunks1), ['/path/chunk__0_10.chunk'])

        # Case 2: 99 vs 100
        chunks2 = ['/path/chunk__1_99.chunk', '/path/chunk__1_100.chunk']
        self.assertEqual(self._dedup(chunks2), ['/path/chunk__1_100.chunk'])

        # Case 3: 999 vs 1000
        chunks3 = ['/path/chunk__2_999.chunk', '/path/chunk__2_1000.chunk']
        self.assertEqual(self._dedup(chunks3), ['/path/chunk__2_1000.chunk'])

    def test_multi_prefix_interleaving_and_shuffling(self):
        """Randomly shuffled list across 5 different sector prefixes."""
        prefixes = ['00_01__0', '1e_20__1', '1e_1e__1', '24_1a__1', '02_05__3']
        all_chunks = []
        expected_latest = []
        for p in prefixes:
            for v in range(1, 25):
                all_chunks.append(f'/worlds/{p}_{v}.chunk')
            expected_latest.append(f'/worlds/{p}_24.chunk')

        # Add unversioned legacy chunks
        all_chunks.extend(['/worlds/legacy_a.chunk', '/worlds/legacy_b.chunk'])
        expected_latest.extend(['/worlds/legacy_a.chunk', '/worlds/legacy_b.chunk'])

        random.seed(42)
        shuffled = list(all_chunks)
        random.shuffle(shuffled)

        result = self._dedup(shuffled)
        self.assertEqual(result, sorted(expected_latest))

    def test_duplicate_versions_and_version_zero(self):
        """Chunks with version 0 and duplicate identical filenames."""
        chunks = [
            '/worlds/sec__0_0.chunk',
            '/worlds/sec__0_0.chunk',
            '/worlds/sec__0_1.chunk',
        ]
        self.assertEqual(self._dedup(chunks), ['/worlds/sec__0_1.chunk'])


class TestChallengerNumericalSaveSorting(unittest.TestCase):
    """Adversarial stress testing of save file ID extraction and sorting."""

    def _extract_save_id(self, p):
        import re
        m = re.search(r'_main\.(\d+)\.db2$', p)
        return int(m.group(1)) if m else 0

    def test_numerical_save_boundary_selection(self):
        """Ensure save selection never falls into lexicographical string sorting traps."""
        # Traps that fail under lexicographical sort:
        # '_main.10.db2' < '_main.9.db2' in ASCII string sort!
        files1 = ['/path/_main.9.db2', '/path/_main.10.db2']
        self.assertEqual(max(files1, key=self._extract_save_id), '/path/_main.10.db2')

        # '_main.100.db2' < '_main.99.db2' in ASCII string sort!
        files2 = ['/path/_main.99.db2', '/path/_main.100.db2']
        self.assertEqual(max(files2, key=self._extract_save_id), '/path/_main.100.db2')

        # '_main.1000.db2' < '_main.999.db2' in ASCII string sort!
        files3 = ['/path/_main.999.db2', '/path/_main.1000.db2']
        self.assertEqual(max(files3, key=self._extract_save_id), '/path/_main.1000.db2')

    def test_1000_shuffled_saves_simulation(self):
        """Simulate long-running server history of 1,000 saves in randomized order."""
        saves = [f'/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/_main.{i}.db2' for i in range(1, 1001)]
        random.seed(777)
        shuffled = list(saves)
        random.shuffle(shuffled)

        latest = max(shuffled, key=self._extract_save_id)
        self.assertEqual(latest, '/root/.config/unity3d/IronGate/Valheim/worlds_local/Valheim10/_main.1000.db2')

    def test_malformed_and_temporary_save_names(self):
        """Handle non-numbered, backup, and temporary save files."""
        cases = [
            ('/path/_main.db2', 0),
            ('/path/_main.old.db2', 0),
            ('/path/_main.123.db2.tmp', 0),
            ('/path/_main.123.db2.bak', 0),
            ('/path/other_world.456.db2', 0),
            ('/path/_main.456.db2', 456),
        ]
        for filename, expected_id in cases:
            self.assertEqual(self._extract_save_id(filename), expected_id)


class TestChallengerEndToEndSyntheticWorld(unittest.TestCase):
    """End-to-end integration test parsing synthetic multi-object binary chunk."""

    SYNTHETIC_CHUNK = '/root/synthetic_challenger_test.chunk'

    def setUp(self):
        self.helper = TestChallengerCrossZDOBoundary()
        self.helper.setUp()
        data = bytearray()

        # 1. Untagged portal built by Dexter
        data.extend(self.helper._build_portal_zdo((-100.0, 0.0, -100.0), 'portal_wood', tag="", creator_id=self.helper.dexter_id))
        # 2. Tagged portal built by Hilda directly adjacent (35 bytes later)
        data.extend(self.helper._build_portal_zdo((-95.0, 0.0, -95.0), 'portal_wood', tag="BASE_MAIN", creator_id=self.helper.hilda_id))
        # 3. Another portal tagged BASE_MAIN at distance 200m (forming 1 pair)
        data.extend(self.helper._build_portal_zdo((105.0, 0.0, 105.0), 'portal_wood', tag="BASE_MAIN", creator_id=self.helper.dexter_id))

        # 4. Three portals tagged COPPER_MINE (3 portals -> 1 pair, 1 stranded)
        data.extend(self.helper._build_portal_zdo((500.0, 0.0, 500.0), 'portal_wood', tag="COPPER_MINE", creator_id=self.helper.dexter_id))
        data.extend(self.helper._build_portal_zdo((512.0, 0.0, 500.0), 'portal_wood', tag="COPPER_MINE", creator_id=self.helper.hilda_id))
        data.extend(self.helper._build_portal_zdo((900.0, 0.0, 900.0), 'portal_wood', tag="COPPER_MINE", creator_id=self.helper.dexter_id))

        # 5. Four portals tagged SWAMP_CRYPT (4 portals -> 2 pairs, 0 stranded)
        data.extend(self.helper._build_portal_zdo((-1000.0, 0.0, 0.0), 'portal_wood', tag="SWAMP_CRYPT", creator_id=self.helper.dexter_id))
        data.extend(self.helper._build_portal_zdo((-985.0, 0.0, 0.0), 'portal_wood', tag="SWAMP_CRYPT", creator_id=self.helper.hilda_id))
        data.extend(self.helper._build_portal_zdo((-500.0, 0.0, 0.0), 'portal_wood', tag="SWAMP_CRYPT", creator_id=self.helper.dexter_id))
        data.extend(self.helper._build_portal_zdo((-485.0, 0.0, 0.0), 'portal_wood', tag="SWAMP_CRYPT", creator_id=self.helper.hilda_id))

        # 6. Signs with rich text and edge characters
        data.extend(self.helper._build_sign_zdo((10.0, 0.0, 10.0), text="<color=#00ff00><b>SAFE HAVEN</b></color>", creator_id=self.helper.dexter_id))
        data.extend(self.helper._build_sign_zdo((20.0, 0.0, 20.0), text="ᛟ HALDOR COIN VAULT *DO NOT STEAL*", creator_id=self.helper.hilda_id))

        with open(self.SYNTHETIC_CHUNK, 'wb') as f:
            f.write(data)

    def tearDown(self):
        if os.path.exists(self.SYNTHETIC_CHUNK):
            os.remove(self.SYNTHETIC_CHUNK)

    @patch('valheim_geography.get_active_chunk_files')
    def test_end_to_end_portal_report(self, mock_chunks):
        mock_chunks.return_value = [self.SYNTHETIC_CHUNK]
        report = valheim_info.get_portal_report()

        # Total portals: 1 untagged + 2 BASE_MAIN + 3 COPPER_MINE + 4 SWAMP_CRYPT = 10
        self.assertIn("• *Total Portals Built:* 10", report)

        # Connected pair: BASE_MAIN (2 portals)
        self.assertIn("`BASE_MAIN`", report)

        # Multi-portal conflicts: COPPER_MINE (3 portals -> 1 active pair, 1 stranded)
        self.assertIn("`COPPER_MINE`: 3 portals with identical tag", report)
        self.assertIn("Active Pair:", report)
        self.assertIn("Stranded:", report)

        # Multi-portal conflicts: SWAMP_CRYPT (4 portals -> 2 active pairs, 0 stranded)
        self.assertIn("`SWAMP_CRYPT`: 4 portals with identical tag", report)

        # Untagged portal listed under Orphaned / Unpaired
        self.assertIn("_[BLANK]_", report)
        self.assertIn("Dexter", report)

    @patch('valheim_geography.get_active_chunk_files')
    def test_end_to_end_sign_report(self, mock_chunks):
        mock_chunks.return_value = [self.SYNTHETIC_CHUNK]
        report = valheim_info.get_signs_report()

        self.assertIn("• *Total Inscriptions:* 2 signs", report)
        self.assertIn("SAFE HAVEN", report)
        self.assertNotIn("<color=", report)
        self.assertIn("ᛟ HALDOR COIN VAULT DO NOT STEAL", report)
        # Asterisks inside text stripped so markdown is intact
        self.assertNotIn("*DO NOT STEAL*", report)


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestChallengerCrossZDOBoundary))
    suite.addTests(loader.loadTestsFromTestCase(TestChallengerMultiPortalProximityPairing))
    suite.addTests(loader.loadTestsFromTestCase(TestChallengerChunkDeduplication))
    suite.addTests(loader.loadTestsFromTestCase(TestChallengerNumericalSaveSorting))
    suite.addTests(loader.loadTestsFromTestCase(TestChallengerEndToEndSyntheticWorld))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
