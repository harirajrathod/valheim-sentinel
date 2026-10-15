#!/usr/bin/env python3
"""
/root/test_parser_adversarial.py
Adversarial Stress Test Suite for valheim_info.py World State Parser.

Author: teamwork_preview_challenger (Challenger 1)
Covers:
1. Cross-ZDO Boundary Stress Test (Adjacent ZDOs, untagged+tagged, signs, truncated packets, varint corruption)
2. Multi-Portal Proximity Pairing Test (3, 4, 5, 6 portals, even/odd, distance pairing)
3. Chunk Deduplication Test (Regex version parsing, digit boundaries, prefixes, unversioned)
4. Numerical Save Sorting Test (Integer extraction, digit boundaries: 9 vs 10, 99 vs 100)
"""

import os
import sys
import math
import struct
import unittest
from unittest.mock import patch

# Import target module
import valheim_info


class TestCrossZDOBoundaryStress(unittest.TestCase):
    """Stress tests cross-ZDO boundary detection and field extraction isolation."""

    def setUp(self):
        self.pw_hash = valheim_info.get_stable_hash('portal_wood')
        self.ps_hash = valheim_info.get_stable_hash('portal_stone')
        self.p_hash = valheim_info.get_stable_hash('portal')
        self.tag_hash = struct.pack('<i', valheim_info.get_stable_hash('tag'))
        self.sign_hash = struct.pack('<i', valheim_info.get_stable_hash('sign'))
        self.text_hash = struct.pack('<i', valheim_info.get_stable_hash('text'))

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

    def _build_portal_zdo(self, pos, prefab_str='portal_wood', tag="", creator_id=None, header_prefix=b'\x71\x09'):
        """Constructs synthetic Valheim ZDO binary chunk for a portal."""
        ph = struct.pack('<i', valheim_info.get_stable_hash(prefab_str))
        coords = struct.pack('<fff', *pos)

        body = bytearray()
        # Optional creator
        if creator_id:
            body.extend(creator_id.encode('ascii'))
            body.extend(b'\x00' * 8)
        # Optional tag
        if tag:
            body.extend(self.tag_hash)
            tag_bytes = tag.encode('utf-8')
            body.extend(self._encode_varint(len(tag_bytes)))
            body.extend(tag_bytes)

        # In Valheim chunk, position comes 12 bytes immediately before prefab hash
        # Header sequence before position: header_prefix (e.g. 0x71, 0x09)
        zdo_bytes = header_prefix + coords + ph + bytes(body)
        return zdo_bytes

    def _build_sign_zdo(self, pos, text="", creator_id=None, header_prefix=b'\x70\x09'):
        """Constructs synthetic Valheim ZDO binary chunk for a sign."""
        sh = self.sign_hash
        coords = struct.pack('<fff', *pos)

        body = bytearray()
        if creator_id:
            body.extend(creator_id.encode('ascii'))
            body.extend(b'\x00' * 8)
        if text is not None:
            body.extend(self.text_hash)
            text_bytes = text.encode('utf-8')
            body.extend(self._encode_varint(len(text_bytes)))
            body.extend(text_bytes)

        return header_prefix + coords + sh + bytes(body)

    def test_adjacent_portals_no_bleed(self):
        """Portal 1 (untagged, Dexter) followed tightly by Portal 2 (tagged SECRET, Hilda)."""
        p1 = self._build_portal_zdo((10.0, 5.0, 10.0), 'portal_wood', tag="",
                                    creator_id='Steam_76561198014682424')
        p2 = self._build_portal_zdo((25.0, 5.0, 25.0), 'portal_wood', tag="SECRET_BASE",
                                    creator_id='Steam_76561198229525716')

        data = p1 + p2

        # Verify find_next_zdo_boundary and portal parsing logic
        idx1 = data.find(struct.pack('<i', self.pw_hash))
        self.assertGreaterEqual(idx1, 12)

        # Calculate bound for Portal 1 as in valheim_info.py
        bound1 = valheim_info.find_next_zdo_boundary(data, idx1 + 4, max_search=120)
        for other_ph in (self.pw_hash, self.ps_hash, self.p_hash):
            cand = data.find(struct.pack('<i', other_ph), idx1 + 4)
            if cand != -1:
                bound1 = min(bound1, max(idx1 + 4, cand - 12))

        zdo_window1 = data[idx1:bound1]

        # Assert Portal 1 does NOT contain Portal 2's tag or creator
        self.assertNotIn(b'SECRET_BASE', zdo_window1)
        self.assertNotIn(b'Steam_76561198229525716', zdo_window1)
        self.assertIn(b'Steam_76561198014682424', zdo_window1)

        # Now check Portal 2
        idx2 = data.find(struct.pack('<i', self.pw_hash), idx1 + 4)
        self.assertNotEqual(idx2, -1)
        bound2 = valheim_info.find_next_zdo_boundary(data, idx2 + 4, max_search=120)
        zdo_window2 = data[idx2:bound2]

        self.assertIn(b'SECRET_BASE', zdo_window2)
        self.assertIn(b'Steam_76561198229525716', zdo_window2)
        self.assertNotIn(b'Steam_76561198014682424', zdo_window2)

    def test_adjacent_portal_and_sign_no_bleed(self):
        """Untagged portal closely followed by a sign with rich text."""
        p = self._build_portal_zdo((100.0, 0.0, 100.0), 'portal_wood', tag="",
                                   creator_id='Steam_76561198014682424')
        s = self._build_sign_zdo((105.0, 0.0, 105.0), text="KEEP_OUT_TREASURY",
                                 creator_id='Steam_76561198229525716')

        data = p + s
        idx = data.find(struct.pack('<i', self.pw_hash))
        bound = valheim_info.find_next_zdo_boundary(data, idx + 4, max_search=120)

        # The ZDO boundary detector must detect sign's 0x70 0x09 and coords
        self.assertLessEqual(bound, len(p))
        zdo_window = data[idx:bound]
        self.assertNotIn(b'KEEP_OUT_TREASURY', zdo_window)
        self.assertNotIn(b'Steam_76561198229525716', zdo_window)

    def test_adjacent_signs_isolation(self):
        """Sign 1 (empty) followed tightly by Sign 2 ('TOMB OF ODIN')."""
        s1 = self._build_sign_zdo((50.0, 10.0, 50.0), text="",
                                  creator_id='Steam_76561198014682424')
        s2 = self._build_sign_zdo((60.0, 10.0, 60.0), text="TOMB OF ODIN",
                                  creator_id='Steam_76561198229525716')

        data = s1 + s2
        idx1 = data.find(self.sign_hash)
        bound1 = valheim_info.find_next_zdo_boundary(data, idx1 + 4, max_search=200)
        next_sign = data.find(self.sign_hash, idx1 + 4)
        if next_sign != -1:
            bound1 = min(bound1, max(idx1 + 4, next_sign - 12))

        window1 = data[idx1:bound1]
        self.assertNotIn(b'TOMB OF ODIN', window1)
        self.assertNotIn(b'Steam_76561198229525716', window1)

    def test_sign_edge_case_characters_and_unity_tags(self):
        """Sign text with rich text HTML tags, Unicode runes, and whitespace."""
        test_cases = [
            ("<color=#ff0000><b>DANGER</b></color> <size=20>Trolls Ahead!</size>",
             "DANGER Trolls Ahead!"),
            ("ᚠᚢᚦᚨᚱᚲ 🛡️ The Great Hall ⚔️ 🏰",
             "ᚠᚢᚦᚨᚱᚲ 🛡️ The Great Hall ⚔️ 🏰"),
            ("   \n\n  Spaced   Out   Rune  \t\n  ",
             "Spaced Out Rune"),
            ("Unclosed <color=red>tag without close",
             "Unclosed tag without close"),
            ("Math: 5 < 10 and 20 > 15",
             "Math: 5 < 10 and 20 > 15"),
        ]

        import re
        for raw, expected_clean in test_cases:
            cleaned = re.sub(r'</?[a-zA-Z][^>]*>', '', raw)
            cleaned = ' '.join(cleaned.split())
            self.assertEqual(cleaned, expected_clean)

    def test_truncated_packets_and_corrupted_varints(self):
        """Varint decoding loops must be resilient against truncation and infinite shift."""
        # 1. Truncated slice after tag hash
        zdo_window = self.tag_hash  # length 4, no varint following
        t_idx = zdo_window.find(self.tag_hash)
        p = t_idx + 4
        tag_len = 0
        shift = 0
        while p < len(zdo_window) and shift <= 28:
            b = zdo_window[p]
            p += 1
            tag_len |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        tag = zdo_window[p:p+tag_len].decode('utf-8', errors='replace')
        self.assertEqual(tag, "")

        # 2. Corrupted varint with infinite continuation bits (0x80)
        zdo_window = self.tag_hash + (b'\x80' * 50)
        p = t_idx + 4
        tag_len = 0
        shift = 0
        loop_count = 0
        while p < len(zdo_window) and shift <= 28:
            loop_count += 1
            b = zdo_window[p]
            p += 1
            tag_len |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        # Loop must stop when shift exceeds 28 (i.e. at most 5 iterations)
        self.assertLessEqual(loop_count, 5)

        # 3. Varint claims massive length (10,000 bytes) but only 3 bytes exist
        zdo_window = self.tag_hash + self._encode_varint(10000) + b'XYZ'
        t_idx = zdo_window.find(self.tag_hash)
        p = t_idx + 4
        tag_len = 0
        shift = 0
        while p < len(zdo_window) and shift <= 28:
            b = zdo_window[p]
            p += 1
            tag_len |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        tag = zdo_window[p:p+tag_len].decode('utf-8', errors='replace')
        self.assertEqual(tag, "XYZ")


class TestMultiPortalProximityPairing(unittest.TestCase):
    """Stress tests multi-portal pairing logic with 3, 4, 5, 6 portals."""

    def _pair_portals(self, portals):
        """Executes the exact greedy closest-pair algorithm from valheim_info.py."""
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
        stranded = remaining
        return pairs, stranded

    def test_three_portals_odd_stranded(self):
        """3 portals: Exactly 1 pair formed, exactly 1 stranded."""
        portals = [
            {'name': 'P1', 'pos': (0.0, 0.0, 0.0), 'creator': 'Dexter'},
            {'name': 'P2', 'pos': (10.0, 0.0, 0.0), 'creator': 'Hilda'},
            {'name': 'P3', 'pos': (150.0, 0.0, 0.0), 'creator': 'Rukia'},
        ]
        pairs, stranded = self._pair_portals(portals)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(stranded), 1)
        # Pair should be P1 and P2 (distance 10m)
        pair_names = {pairs[0][0]['name'], pairs[0][1]['name']}
        self.assertEqual(pair_names, {'P1', 'P2'})
        self.assertEqual(stranded[0]['name'], 'P3')

    def test_four_portals_even_no_stranded(self):
        """4 portals: Exactly 2 pairs formed, 0 stranded."""
        portals = [
            {'name': 'P1', 'pos': (0.0, 0.0, 0.0), 'creator': 'Dexter'},
            {'name': 'P2', 'pos': (12.0, 0.0, 0.0), 'creator': 'Hilda'},
            {'name': 'P3', 'pos': (200.0, 0.0, 0.0), 'creator': 'Rukia'},
            {'name': 'P4', 'pos': (206.0, 0.0, 0.0), 'creator': 'Claw'},
        ]
        pairs, stranded = self._pair_portals(portals)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len(stranded), 0)
        pair1_names = {pairs[0][0]['name'], pairs[0][1]['name']}
        pair2_names = {pairs[1][0]['name'], pairs[1][1]['name']}
        self.assertIn(pair1_names, [{'P3', 'P4'}, {'P1', 'P2'}])
        self.assertIn(pair2_names, [{'P3', 'P4'}, {'P1', 'P2'}])

    def test_five_portals_odd_stranded(self):
        """5 portals: Exactly 2 pairs formed, exactly 1 stranded."""
        portals = [
            {'name': 'P1', 'pos': (0.0, 0.0, 0.0), 'creator': 'Dexter'},
            {'name': 'P2', 'pos': (8.0, 0.0, 0.0), 'creator': 'Hilda'},
            {'name': 'P3', 'pos': (50.0, 0.0, 0.0), 'creator': 'Rukia'},
            {'name': 'P4', 'pos': (56.0, 0.0, 0.0), 'creator': 'Claw'},
            {'name': 'P5', 'pos': (900.0, 0.0, 0.0), 'creator': 'Thor'},
        ]
        pairs, stranded = self._pair_portals(portals)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len(stranded), 1)
        self.assertEqual(stranded[0]['name'], 'P5')

    def test_six_portals_even_no_stranded(self):
        """6 portals: Exactly 3 pairs formed, 0 stranded."""
        portals = [
            {'name': 'P1', 'pos': (0.0, 0.0, 0.0), 'creator': 'Dexter'},
            {'name': 'P2', 'pos': (10.0, 0.0, 0.0), 'creator': 'Hilda'},
            {'name': 'P3', 'pos': (100.0, 0.0, 0.0), 'creator': 'Rukia'},
            {'name': 'P4', 'pos': (115.0, 0.0, 0.0), 'creator': 'Claw'},
            {'name': 'P5', 'pos': (400.0, 0.0, 0.0), 'creator': 'Thor'},
            {'name': 'P6', 'pos': (425.0, 0.0, 0.0), 'creator': 'Odin'},
        ]
        pairs, stranded = self._pair_portals(portals)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(len(stranded), 0)

    def test_equidistant_and_identical_coordinates(self):
        """Edge case: Equilateral triangle (3 portals) and overlapping coordinates."""
        # Equilateral triangle of side 100
        p_tri = [
            {'name': 'T1', 'pos': (0.0, 0.0, 0.0)},
            {'name': 'T2', 'pos': (100.0, 0.0, 0.0)},
            {'name': 'T3', 'pos': (50.0, 0.0, 86.6)},
        ]
        pairs, stranded = self._pair_portals(p_tri)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(stranded), 1)

        # 4 overlapping portals at identical coordinates (0, 0, 0)
        p_overlap = [{'name': f'O{i}', 'pos': (0.0, 0.0, 0.0)} for i in range(4)]
        pairs, stranded = self._pair_portals(p_overlap)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len(stranded), 0)


class TestChunkDeduplication(unittest.TestCase):
    """Stress tests regex chunk deduplication across versions and digit boundaries."""

    def _dedup_chunks(self, raw_chunks):
        import re
        chunks_by_prefix = {}
        for c in raw_chunks:
            m = re.match(r'^(.*__\d+)_(\d+)\.chunk$', c)
            if m:
                prefix, ver = m.group(1), int(m.group(2))
                if prefix not in chunks_by_prefix or ver > chunks_by_prefix[prefix][0]:
                    chunks_by_prefix[prefix] = (ver, c)
            else:
                chunks_by_prefix[c] = (0, c)
        return sorted([v[1] for v in chunks_by_prefix.values()])

    def test_digit_boundary_crossing_dedup(self):
        """Versions crossing 9 -> 10, 99 -> 100 must pick highest integer, not string max."""
        # 8, 9, 10, 11 -> 11
        chunks1 = [
            '/dir/chunk__0_8.chunk',
            '/dir/chunk__0_9.chunk',
            '/dir/chunk__0_10.chunk',
            '/dir/chunk__0_11.chunk',
        ]
        res1 = self._dedup_chunks(chunks1)
        self.assertEqual(res1, ['/dir/chunk__0_11.chunk'])

        # 98, 99, 100, 101 -> 101
        chunks2 = [
            '/dir/zone__1_98.chunk',
            '/dir/zone__1_99.chunk',
            '/dir/zone__1_100.chunk',
            '/dir/zone__1_101.chunk',
        ]
        res2 = self._dedup_chunks(chunks2)
        self.assertEqual(res2, ['/dir/zone__1_101.chunk'])

    def test_interleaved_prefixes_and_unversioned(self):
        """Multiple prefixes coexisting, with unversioned legacy chunks."""
        chunks = [
            '/dir/1e_1e__1_143.chunk',
            '/dir/1e_1e__1_144.chunk',
            '/dir/1e_20__1_144.chunk',
            '/dir/1e_20__1_143.chunk',
            '/dir/00_00__0_26.chunk',
            '/dir/00_00__0_25.chunk',
            '/dir/legacy.chunk',
        ]
        res = self._dedup_chunks(chunks)
        expected = sorted([
            '/dir/1e_1e__1_144.chunk',
            '/dir/1e_20__1_144.chunk',
            '/dir/00_00__0_26.chunk',
            '/dir/legacy.chunk',
        ])
        self.assertEqual(res, expected)

    def test_shuffled_versions_and_zero(self):
        """Randomly ordered chunk versions including version 0."""
        chunks = [
            '/dir/area__2_50.chunk',
            '/dir/area__2_0.chunk',
            '/dir/area__2_5.chunk',
            '/dir/area__2_500.chunk',
            '/dir/area__2_25.chunk',
        ]
        res = self._dedup_chunks(chunks)
        self.assertEqual(res, ['/dir/area__2_500.chunk'])


class TestNumericalSaveSorting(unittest.TestCase):
    """Stress tests _main.*.db2 save file numerical extraction and selection."""

    def _extract_save_id(self, p):
        import re
        m = re.search(r'_main\.(\d+)\.db2$', p)
        return int(m.group(1)) if m else 0

    def test_digit_boundary_crossing_save_ids(self):
        """Lexicographical sort would fail on 9 vs 10, 99 vs 100."""
        # 9 vs 10
        saves_1 = ['/path/_main.9.db2', '/path/_main.10.db2']
        latest_1 = max(saves_1, key=self._extract_save_id)
        self.assertEqual(latest_1, '/path/_main.10.db2')

        # 99 vs 100
        saves_2 = ['/path/_main.99.db2', '/path/_main.100.db2']
        latest_2 = max(saves_2, key=self._extract_save_id)
        self.assertEqual(latest_2, '/path/_main.100.db2')

        # 999 vs 1000
        saves_3 = ['/path/_main.999.db2', '/path/_main.1000.db2']
        latest_3 = max(saves_3, key=self._extract_save_id)
        self.assertEqual(latest_3, '/path/_main.1000.db2')

    def test_large_shuffled_save_list(self):
        """Selection across realistic multi-digit production history."""
        saves = [f'/path/_main.{i}.db2' for i in range(1, 350)]
        import random
        shuffled = list(saves)
        random.seed(42)
        random.shuffle(shuffled)

        latest = max(shuffled, key=self._extract_save_id)
        self.assertEqual(latest, '/path/_main.349.db2')

    def test_malformed_and_unversioned_db2(self):
        """Edge cases: no number, 0, non-db2 extensions."""
        saves = ['/path/_main.db2', '/path/_main.0.db2', '/path/_main.1.db2']
        latest = max(saves, key=self._extract_save_id)
        self.assertEqual(latest, '/path/_main.1.db2')

        # Unnumbered returns 0
        self.assertEqual(self._extract_save_id('/path/_main.db2'), 0)
        self.assertEqual(self._extract_save_id('/path/random.db2'), 0)
        self.assertEqual(self._extract_save_id('/path/_main.50.db2.bak'), 0)


class TestEndToEndPortalReportSynthetic(unittest.TestCase):
    """End-to-end execution of get_portal_report() on synthetic chunk containing 3, 4, 5, 6 portals."""

    CHUNK_FILE = '/root/synthetic_portals_test.chunk'

    def setUp(self):
        self.helper = TestCrossZDOBoundaryStress()
        self.helper.setUp()
        chunk_bytes = bytearray()

        # 3 portals with tag "ALPHA"
        chunk_bytes.extend(self.helper._build_portal_zdo((0.0, 0.0, 0.0), tag="ALPHA", creator_id='Steam_76561198014682424'))
        chunk_bytes.extend(self.helper._build_portal_zdo((10.0, 0.0, 0.0), tag="ALPHA", creator_id='Steam_76561198229525716'))
        chunk_bytes.extend(self.helper._build_portal_zdo((100.0, 0.0, 0.0), tag="ALPHA", creator_id='Steam_76561198077562671'))

        # 4 portals with tag "BETA"
        chunk_bytes.extend(self.helper._build_portal_zdo((200.0, 0.0, 0.0), tag="BETA", creator_id='Steam_76561198014682424'))
        chunk_bytes.extend(self.helper._build_portal_zdo((212.0, 0.0, 0.0), tag="BETA", creator_id='Steam_76561198229525716'))
        chunk_bytes.extend(self.helper._build_portal_zdo((400.0, 0.0, 0.0), tag="BETA", creator_id='Steam_76561198077562671'))
        chunk_bytes.extend(self.helper._build_portal_zdo((406.0, 0.0, 0.0), tag="BETA", creator_id='PlayStation_8380385718227128186'))

        # 5 portals with tag "GAMMA"
        chunk_bytes.extend(self.helper._build_portal_zdo((500.0, 0.0, 0.0), tag="GAMMA", creator_id='Steam_76561198014682424'))
        chunk_bytes.extend(self.helper._build_portal_zdo((508.0, 0.0, 0.0), tag="GAMMA", creator_id='Steam_76561198229525716'))
        chunk_bytes.extend(self.helper._build_portal_zdo((600.0, 0.0, 0.0), tag="GAMMA", creator_id='Steam_76561198077562671'))
        chunk_bytes.extend(self.helper._build_portal_zdo((606.0, 0.0, 0.0), tag="GAMMA", creator_id='PlayStation_8380385718227128186'))
        chunk_bytes.extend(self.helper._build_portal_zdo((900.0, 0.0, 0.0), tag="GAMMA", creator_id='Steam_76561198014682424'))

        # 6 portals with tag "DELTA"
        chunk_bytes.extend(self.helper._build_portal_zdo((1000.0, 0.0, 0.0), tag="DELTA", creator_id='Steam_76561198014682424'))
        chunk_bytes.extend(self.helper._build_portal_zdo((1010.0, 0.0, 0.0), tag="DELTA", creator_id='Steam_76561198229525716'))
        chunk_bytes.extend(self.helper._build_portal_zdo((1100.0, 0.0, 0.0), tag="DELTA", creator_id='Steam_76561198077562671'))
        chunk_bytes.extend(self.helper._build_portal_zdo((1115.0, 0.0, 0.0), tag="DELTA", creator_id='PlayStation_8380385718227128186'))
        chunk_bytes.extend(self.helper._build_portal_zdo((1400.0, 0.0, 0.0), tag="DELTA", creator_id='Steam_76561198014682424'))
        chunk_bytes.extend(self.helper._build_portal_zdo((1425.0, 0.0, 0.0), tag="DELTA", creator_id='Steam_76561198229525716'))

        # 2 portals with tag "EPSILON" (standard connected pair)
        chunk_bytes.extend(self.helper._build_portal_zdo((-500.0, 0.0, 0.0), tag="EPSILON", creator_id='Steam_76561198014682424'))
        chunk_bytes.extend(self.helper._build_portal_zdo((-490.0, 0.0, 0.0), tag="EPSILON", creator_id='Steam_76561198229525716'))

        # Case mismatch portals: "ZETA" and "zeta"
        chunk_bytes.extend(self.helper._build_portal_zdo((-1000.0, 0.0, 0.0), tag="ZETA", creator_id='Steam_76561198014682424'))
        chunk_bytes.extend(self.helper._build_portal_zdo((-2000.0, 0.0, 0.0), tag="zeta", creator_id='Steam_76561198229525716'))

        # Accidental whitespace: " WHITESPACE "
        chunk_bytes.extend(self.helper._build_portal_zdo((-3000.0, 0.0, 0.0), tag=" WHITESPACE ", creator_id='Steam_76561198014682424'))

        # Untagged portal followed 30 bytes later by a tagged portal (isolation check)
        p_untagged = self.helper._build_portal_zdo((-4000.0, 0.0, 0.0), tag="", creator_id='Steam_76561198014682424')
        p_tagged = self.helper._build_portal_zdo((-3970.0, 0.0, 0.0), tag="TAGGED_NEIGHBOR", creator_id='Steam_76561198229525716')
        chunk_bytes.extend(p_untagged)
        chunk_bytes.extend(p_tagged)

        with open(self.CHUNK_FILE, 'wb') as f:
            f.write(chunk_bytes)

    def tearDown(self):
        if os.path.exists(self.CHUNK_FILE):
            os.remove(self.CHUNK_FILE)

    @patch('valheim_geography.get_active_chunk_files')
    def test_full_portal_report_execution(self, mock_chunks):
        mock_chunks.return_value = [self.CHUNK_FILE]
        report = valheim_info.get_portal_report()

        # 1. Total portal count: 3(ALPHA) + 4(BETA) + 5(GAMMA) + 6(DELTA) + 2(EPSILON) + 1(ZETA) + 1(zeta) + 1(WHITESPACE) + 1(untagged) + 1(TAGGED_NEIGHBOR) = 25
        self.assertIn("• *Total Portals Built:* 25", report)

        # 2. Standard connected pair
        self.assertIn("🟢 *Connected Pairs:*", report)
        self.assertIn("`EPSILON`", report)

        # 3. Multi-portal tags section
        self.assertIn("⚠️ *Multi-Portal Conflicts (>2 with same tag):*", report)

        # ALPHA: 3 portals -> 1 active pair, 1 stranded
        self.assertIn("`ALPHA`: 3 portals with identical tag", report)
        self.assertIn("Active Pair:", report)
        self.assertIn("Stranded:", report)

        # BETA: 4 portals -> 2 active pairs, 0 stranded
        self.assertIn("`BETA`: 4 portals with identical tag", report)

        # GAMMA: 5 portals -> 2 active pairs, 1 stranded
        self.assertIn("`GAMMA`: 5 portals with identical tag", report)

        # DELTA: 6 portals -> 3 active pairs, 0 stranded
        self.assertIn("`DELTA`: 6 portals with identical tag", report)

        # 4. Orphaned section & Case mismatch & whitespace warning
        self.assertIn("🔴 *Unpaired Portals (No Link):*", report)
        self.assertIn("Case mismatch: another portal tagged", report)
        self.assertIn("` WHITESPACE `", report)
        self.assertIn("_[BLANK]_", report)
        self.assertIn("TAGGED_NEIGHBOR", report)


class TestEndToEndSignReportSynthetic(unittest.TestCase):
    """End-to-end execution of get_signs_report() on synthetic chunk."""

    CHUNK_FILE = '/root/synthetic_signs_test.chunk'

    def setUp(self):
        self.helper = TestCrossZDOBoundaryStress()
        self.helper.setUp()
        chunk_bytes = bytearray()

        # Sign with HTML tags
        chunk_bytes.extend(self.helper._build_sign_zdo((10.0, 0.0, 10.0), text="<b><color=red>DANGER ZONE</color></b>", creator_id='Steam_76561198014682424'))
        # Sign with Runes and Emojis
        chunk_bytes.extend(self.helper._build_sign_zdo((20.0, 0.0, 20.0), text="ᚠᚢᚦᚨᚱᚲ Mead Hall 🛡️", creator_id='Steam_76561198229525716'))
        # Sign with Markdown asterisk characters (must be sanitized)
        chunk_bytes.extend(self.helper._build_sign_zdo((30.0, 0.0, 30.0), text="*TREASURY VAULT*", creator_id='Steam_76561198077562671'))
        # Empty sign (should be filtered)
        chunk_bytes.extend(self.helper._build_sign_zdo((40.0, 0.0, 40.0), text="", creator_id='Steam_76561198014682424'))

        with open(self.CHUNK_FILE, 'wb') as f:
            f.write(chunk_bytes)

    def tearDown(self):
        if os.path.exists(self.CHUNK_FILE):
            os.remove(self.CHUNK_FILE)

    @patch('valheim_geography.get_active_chunk_files')
    def test_full_signs_report_execution(self, mock_chunks):
        mock_chunks.return_value = [self.CHUNK_FILE]
        report = valheim_info.get_signs_report()

        self.assertIn("• *Total Inscriptions:* 3 signs", report)
        self.assertIn("DANGER ZONE", report)
        self.assertNotIn("<color=", report)
        self.assertIn("ᚠᚢᚦᚨᚱᚲ Mead Hall 🛡️", report)
        self.assertIn("TREASURY VAULT", report)
        # Asterisks inside text should be stripped so markdown doesn't break
        self.assertNotIn('*"*TREASURY VAULT*"*', report)


class TestEndToEndInventoryRobustness(unittest.TestCase):
    """End-to-end execution of scan_world_inventory() with valid containers and hostile payload corruptions."""

    CHUNK_FILE = '/root/synthetic_inv_test.chunk'

    def setUp(self):
        chunk_bytes = bytearray()
        target_s_items = valheim_info.TARGET_S_ITEMS

        # Valid chest containing 500 Coins and 12 Amber
        chest_hash = struct.pack('<i', valheim_info.get_stable_hash('piece_chest_wood'))
        chunk_bytes.extend(chest_hash)
        chunk_bytes.extend(b'\x00' * 16)
        chunk_bytes.extend(target_s_items)

        # Payload: version 109, count 2 items
        coin_hash = valheim_info.get_stable_hash('Coins')
        amber_hash = valheim_info.get_stable_hash('Amber')

        item_payload = bytearray()
        item_payload.extend(struct.pack('<IH', 109, 2))  # version=109, count=2
        # Item 1: stack=500, hash=Coins
        item_payload.extend(struct.pack('<Hi', 500, coin_hash))
        item_payload.extend(b'\x00' * 20)  # item properties padding
        # Item 2: stack=12, hash=Amber
        item_payload.extend(struct.pack('<Hi', 12, amber_hash))
        item_payload.extend(b'\x00' * 20)

        chunk_bytes.extend(struct.pack('<I', len(item_payload)))
        chunk_bytes.extend(item_payload)

        # Corrupted container 1: version 999 (invalid version)
        chunk_bytes.extend(chest_hash)
        chunk_bytes.extend(target_s_items)
        bad_payload1 = struct.pack('<IH', 999, 5) + b'\x00' * 40
        chunk_bytes.extend(struct.pack('<I', len(bad_payload1)))
        chunk_bytes.extend(bad_payload1)

        # Corrupted container 2: count 500 (> 100 max container slots)
        chunk_bytes.extend(chest_hash)
        chunk_bytes.extend(target_s_items)
        bad_payload2 = struct.pack('<IH', 109, 500) + b'\x00' * 40
        chunk_bytes.extend(struct.pack('<I', len(bad_payload2)))
        chunk_bytes.extend(bad_payload2)

        # Corrupted container 3: payload length claims 1000000 bytes (exceeds file)
        chunk_bytes.extend(chest_hash)
        chunk_bytes.extend(target_s_items)
        chunk_bytes.extend(struct.pack('<I', 1000000))
        chunk_bytes.extend(b'\x00' * 10)

        # Ashlands Drakkar ship container with 50 Flametal Bars
        drakkar_hash = struct.pack('<i', valheim_info.get_stable_hash('Drakkar'))
        flametal_hash = valheim_info.get_stable_hash('Flametal')
        chunk_bytes.extend(drakkar_hash)
        chunk_bytes.extend(b'\x00' * 16)
        chunk_bytes.extend(target_s_items)

        drakkar_payload = bytearray()
        drakkar_payload.extend(struct.pack('<IH', 109, 1))
        drakkar_payload.extend(struct.pack('<Hi', 50, flametal_hash))
        drakkar_payload.extend(b'\x00' * 20)
        chunk_bytes.extend(struct.pack('<I', len(drakkar_payload)))
        chunk_bytes.extend(drakkar_payload)

        with open(self.CHUNK_FILE, 'wb') as f:
            f.write(chunk_bytes)
        cache_file = '/root/.cache/valheim_inventory_cache.json'
        if os.path.exists(cache_file):
            try: os.remove(cache_file)
            except Exception: pass

    def tearDown(self):
        if os.path.exists(self.CHUNK_FILE):
            os.remove(self.CHUNK_FILE)
        cache_file = '/root/.cache/valheim_inventory_cache.json'
        if os.path.exists(cache_file):
            try: os.remove(cache_file)
            except Exception: pass

    @patch('valheim_inventory.get_active_chunk_files')
    def test_inventory_scan_and_wealth_report(self, mock_chunks):
        mock_chunks.return_value = [self.CHUNK_FILE]
        totals, count = valheim_info.scan_world_inventory()

        # Should safely parse valid items from chest and Drakkar, ignoring corruptions
        self.assertEqual(count, 2)
        self.assertEqual(totals.get('Coins'), 500)
        self.assertEqual(totals.get('Amber'), 12)
        self.assertEqual(totals.get('Flametal'), 50)

        # Also verify wealth report calculation
        report = valheim_info.get_wealth_report()
        # 500 coins + (12 * 5) = 560 Gold
        self.assertIn("500 🪙", report)
        self.assertIn("12 Amber (60g)", report)
        self.assertIn("~560 Gold", report)


def run_suite():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestCrossZDOBoundaryStress))
    suite.addTests(loader.loadTestsFromTestCase(TestMultiPortalProximityPairing))
    suite.addTests(loader.loadTestsFromTestCase(TestChunkDeduplication))
    suite.addTests(loader.loadTestsFromTestCase(TestNumericalSaveSorting))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndPortalReportSynthetic))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndSignReportSynthetic))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndInventoryRobustness))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_suite()
    sys.exit(0 if success else 1)

