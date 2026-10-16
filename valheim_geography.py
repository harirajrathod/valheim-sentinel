import os
import sys
import time
import math
import re
import glob
import json
import zlib
import struct
import ctypes
import argparse
import subprocess
from datetime import datetime, timedelta, timezone
from itertools import combinations

sys.path.insert(0, '/root')
from valheim_utils import (
    LOG_FILE,
    WORLDS_DIR,
    WORLD_DIR,
    IST,
    format_player_name,
    safe_load_json,
    atomic_save_json,
    get_stable_hash,
    get_active_chunk_files,
)
from valheim_constants import PATTERNS


def find_next_zdo_boundary(data, start_idx, max_search=250):
    """
    Finds the boundary of the current ZDO starting after start_idx.
    Scans forward up to max_search bytes for the next ZDO header:
    (0x70..0x73, 0x09 or 0x19, 12 bytes valid world coords [-10500..10500]).
    Returns the start index of the next ZDO or min(len(data), start_idx + max_search).
    """
    limit = min(len(data) - 18, start_idx + max_search)
    for i in range(start_idx, limit):
        if data[i] in (0x70, 0x71, 0x72, 0x73) and data[i+1] in (0x09, 0x19):
            try:
                x, y, z = struct.unpack('<fff', data[i+2:i+14])
                if -10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500:
                    return i
            except Exception:
                pass
    return min(len(data), start_idx + max_search)

def get_traders_status():
    """
    Scans chunk files, portal network, and world state to determine
    discovery and interaction status for Haldor, Hildir, and The Bog Witch.
    """
    chunks = get_active_chunk_files()

    # Extract portal tags and coordinates
    pw_hashes = {
        get_stable_hash('portal_wood'): 'Wood Portal',
        get_stable_hash('portal_stone'): 'Stone Portal',
    }
    tag_hash = bytes.fromhex('ea917c29')
    portals = []
    for c in chunks:
        try:
            with open(c, 'rb') as fp:
                data = fp.read()
        except Exception:
            continue
        for ph in pw_hashes:
            packed_ph = struct.pack('<i', ph)
            idx = 0
            while True:
                idx = data.find(packed_ph, idx)
                if idx == -1: break
                if idx >= 12:
                    x, y, z = struct.unpack('<fff', data[idx-12:idx])
                    if -10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500:
                        window = data[idx:idx+120]
                        t_idx = window.find(tag_hash)
                        if t_idx != -1:
                            p = t_idx + 4
                            tag_len, shift = 0, 0
                            while p < len(window) and shift <= 28:
                                b = window[p]
                                p += 1
                                tag_len |= (b & 0x7F) << shift
                                if not (b & 0x80): break
                                shift += 7
                            tag = window[p:p+tag_len].decode('utf-8', errors='replace').strip()
                            if tag:
                                portals.append({'tag': tag, 'coords': (x, y, z)})
                idx += 4

    # Check Hildir quest completion from db2
    hildir_quests = []
    try:
        db_files = sorted(glob.glob(os.path.join(WORLD_DIR, "_main.*.db2")))
        if db_files:
            with open(db_files[-1], 'rb') as f:
                db_data = f.read()
            idx = db_data.find(b'\x1f\x8b\x08')
            if idx != -1:
                d = zlib.decompressobj(16 + zlib.MAX_WBITS)
                decomp = d.decompress(db_data[idx:])
                for qk in [b'hildir1', b'hildir2', b'hildir3']:
                    if qk in decomp.lower():
                        hildir_quests.append(qk.decode('latin1'))
    except Exception:
        pass

    TRADERS_CONFIG = {
        'Haldor': ('Haldor', 'Black Forest', '🪙'),
        'Hildir': ('Hildir', 'Meadows', '👗'),
        'BogWitch': ('The Bog Witch', 'Swamps', '🧙‍♀️')
    }

    results = {}
    for t_key, (t_name, t_biome, t_icon) in TRADERS_CONFIG.items():
        th = struct.pack('<i', get_stable_hash(t_key))
        found_pos = None
        for c in chunks:
            try:
                with open(c, 'rb') as fp:
                    data = fp.read()
            except Exception:
                continue
            idx = data.find(th)
            if idx != -1 and idx >= 12:
                x, y, z = struct.unpack('<fff', data[idx-12:idx])
                if -10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500:
                    found_pos = (x, y, z)
                    break

        if found_pos:
            linked_portal = None
            for p in portals:
                px, _, pz = p['coords']
                dist = ((px - found_pos[0])**2 + (pz - found_pos[2])**2)**0.5
                if dist < 400:
                    linked_portal = p['tag']
                    break

            results[t_key] = {
                'name': t_name,
                'biome': t_biome,
                'icon': t_icon,
                'discovered': True,
                'interacted': bool(linked_portal),
                'portal': linked_portal,
                'coords': (round(found_pos[0], 1), round(found_pos[2], 1)),
                'quests': hildir_quests if t_key == 'Hildir' else []
            }
        else:
            results[t_key] = {
                'name': t_name,
                'biome': t_biome,
                'icon': t_icon,
                'discovered': False,
                'interacted': False,
                'portal': None,
                'coords': None,
                'quests': []
            }

    return results


def get_portal_location_desc(x, y, z):
    mb_x, mb_z = 12.8, -360.1
    dist = math.hypot(x - mb_x, z - mb_z)
    if dist < 80:
        return "🏠 Main Base"

    d_str = f"~{dist/1000:.1f}km" if dist >= 1000 else f"~{round(dist)}m"

    LANDMARKS = [
        ("The Elder Altar", "🌲", -1660.0, 1414.0, 180),
        ("Bonemass Altar", "☣️", 462.3, -2547.0, 180),
        ("Moder Altar", "❄️", 2247.1, 1918.2, 180),
        ("Eikthyr Altar", "⚡", -764.0, -73.5, 180),
        ("Haldor the Merchant", "🪙", -1669.2, 262.1, 180),
        ("Hildir the Trader", "👗", -3832.1, -251.8, 180),
        ("The Bog Witch", "🧙‍♀️", 443.8, -3196.1, 300),
    ]
    for lm_name, lm_icon, lx, lz, radius in LANDMARKS:
        if math.hypot(x - lx, z - lz) <= radius:
            return f"{lm_icon} *{lm_name}* ({d_str})"

    dx = x - mb_x
    dz = z - mb_z
    angle = math.atan2(dx, dz)
    degrees = (math.degrees(angle) + 360) % 360
    directions = [
        "North", "NNE", "NE", "ENE", "East", "ESE", "SE", "SSE",
        "South", "SSW", "SW", "WSW", "West", "WNW", "NW", "NNW"
    ]
    cardinal = directions[int((degrees + 11.25) / 22.5) % 16]
    return f"🌲 {d_str} {cardinal}"

def get_portal_report():
    chunks = get_active_chunk_files()

    pw_hashes = {
        get_stable_hash('portal_wood'): 'Wood Portal',
        get_stable_hash('portal_stone'): 'Stone Portal',
    }
    tag_hash = bytes.fromhex('ea917c29')

    platform_map = {
        'Steam_76561198229525716': 'Hilda',
        'Steam_76561198077562671': 'Rukia',
        'Steam_76561198014682424': 'Dexter',
        'PlayStation_8380385718227128186': 'Claw',
        'PlayStation_6663223001167151777': 'Rukia',
    }
    owner_map = {}
    ok_files = glob.glob(os.path.join(WORLD_DIR, "_main.*.ok"))
    if ok_files:
        last_save_mtime = max((os.path.getmtime(f) for f in ok_files), default=0)
    elif chunks:
        last_save_mtime = max((os.path.getmtime(c) for c in chunks), default=0)
    else:
        last_save_mtime = 0

    unsynced_connections = []

    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', errors='ignore') as f:
                log_lines = f.readlines()
            last_platform = None
            for l in log_lines[-10000:]:
                m_plat = PATTERNS["platform_id"].search(l)
                if m_plat:
                    last_platform = m_plat.group(1)
                m_name = PATTERNS["zdo_name_only"].search(l)
                if m_name and last_platform:
                    platform_map[last_platform] = m_name.group(1)
                    last_platform = None
                m_owner = PATTERNS["zdo_join_owner"].search(l)
                if m_owner:
                    owner_map[m_owner.group(2).strip()] = m_owner.group(1).strip()

            # Check for live portal connections in memory newer than last disk save
            seen_portal_pairs = set()
            for l in reversed(log_lines[-200:]):
                m_conn = PATTERNS["portal_connect"].search(l)
                if m_conn:
                    ts_str, u1, id1, u2, id2 = m_conn.group(1), m_conn.group(2), m_conn.group(3), m_conn.group(4), m_conn.group(5)
                    pair_key = tuple(sorted([(u1, id1), (u2, id2)]))
                    if pair_key not in seen_portal_pairs:
                        seen_portal_pairs.add(pair_key)
                        try:
                            dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc)
                            if dt.timestamp() > last_save_mtime:
                                p1_name = owner_map.get(u1, platform_map.get(u1, "Viking"))
                                p2_name = owner_map.get(u2, platform_map.get(u2, "Viking"))
                                time_ist = dt.astimezone(IST).strftime("%H:%M:%S IST")
                                unsynced_connections.append((time_ist, p1_name, p2_name))
                        except Exception:
                            pass
    except Exception:
        pass

    portals = []
    seen_portal_coords = set()
    for c in chunks:
        try:
            with open(c, 'rb') as fp:
                data = fp.read()
        except Exception:
            continue

        for ph, portal_type in pw_hashes.items():
            packed_ph = struct.pack('<i', ph)
            idx = 0
            while True:
                idx = data.find(packed_ph, idx)
                if idx == -1: break
                if idx >= 12:
                    x, y, z = struct.unpack('<fff', data[idx-12:idx])
                    if -10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500:
                        bound = find_next_zdo_boundary(data, idx + 4, max_search=120)
                        for other_ph in pw_hashes:
                            cand = data.find(struct.pack('<i', other_ph), idx + 4)
                            if cand != -1:
                                bound = min(bound, max(idx + 4, cand - 12))

                        zdo_window = data[idx:bound]
                        tag = ""
                        t_idx = zdo_window.find(tag_hash)
                        if t_idx != -1:
                            p = t_idx + 4
                            tag_len = 0
                            shift = 0
                            while p < len(zdo_window) and shift <= 28:
                                b = zdo_window[p]
                                p += 1
                                tag_len |= (b & 0x7F) << shift
                                if not (b & 0x80): break
                                shift += 7
                            tag = zdo_window[p:p+tag_len].decode('utf-8', errors='replace')

                        creator = "Unknown"
                        for s_id, s_name in platform_map.items():
                            if s_id.encode('ascii') in zdo_window:
                                creator = s_name
                                break

                        coord_key = (round(x, 1), round(y, 1), round(z, 1), tag)
                        if coord_key not in seen_portal_coords:
                            seen_portal_coords.add(coord_key)
                            portals.append({
                                'type': portal_type,
                                'tag': tag,
                                'pos': (x, y, z),
                                'creator': creator,
                            })
                idx += 4

    if not portals:
        return "🌀 *[Valheim Portals]*\n\n_No portals found in the realm yet! Craft with 10 Greydwarf Eyes, 20 Fine Wood, and 2 Surtling Cores._"

    if last_save_mtime == 0:
        sync_str = "⚪ Unknown (No saves detected)"
    else:
        now = time.time()
        sync_age_sec = max(0, int(now - last_save_mtime))
        if sync_age_sec < 60:
            sync_str = f"🟢 Fresh ({sync_age_sec}s ago)"
        elif sync_age_sec < 3600:
            sync_str = f"🟡 {sync_age_sec // 60}m {sync_age_sec % 60}s ago"
        else:
            sync_str = f"🔴 {sync_age_sec // 3600}h {(sync_age_sec % 3600) // 60}m ago"

    from collections import defaultdict
    groups = defaultdict(list)
    for p in portals:
        groups[p['tag']].append(p)

    lines = [
        "🌀 *REALM PORTAL DIRECTORY & STATUS*",
        f"• *Total Portals Built:* {len(portals)}",
        f"• *World Save Sync:* {sync_str}",
        ""
    ]

    if unsynced_connections:
        lines.append("⚡ *Live In-Game Links (Awaiting World Save):*")
        for t_ist, p1_name, p2_name in unsynced_connections:
            if p1_name != "Viking" or p2_name != "Viking":
                lines.append(f"• Linked in-game at {t_ist} (*{p1_name}* & *{p2_name}*)")
            else:
                lines.append(f"• Linked in-game at {t_ist}")
        lines.append("  💡 _Type `/save` in Valheim game chat to flush new tags & coordinates to disk instantly!_")
        lines.append("")

    connected = []
    orphaned = []
    conflicted = []

    # Sort tags: blank tag first, then alphabetical
    sorted_tags = sorted(groups.keys(), key=lambda t: (0 if t == "" else 1, t.lower()))

    for tag in sorted_tags:
        p_list = groups[tag]
        if len(p_list) == 2:
            connected.append((tag, p_list))
        elif len(p_list) == 1:
            orphaned.append((tag, p_list[0]))
        else:
            conflicted.append((tag, p_list))

    if connected:
        lines.append("🟢 *Connected Pairs:*")
        for tag, (p1, p2) in connected:
            display_tag = f"`{tag}`" if tag else "_[BLANK]_"
            loc1 = get_portal_location_desc(*p1['pos'])
            loc2 = get_portal_location_desc(*p2['pos'])
            c1 = format_player_name(p1['creator'])
            c2 = format_player_name(p2['creator'])
            creators = f"({c1})" if c1 == c2 else f"({c1} & {c2})"
            if loc1 == "🏠 Main Base" and loc2 != "🏠 Main Base":
                link_str = f"🏠 Main Base ↔ {loc2}"
            elif loc2 == "🏠 Main Base" and loc1 != "🏠 Main Base":
                link_str = f"🏠 Main Base ↔ {loc1}"
            elif loc1 == loc2:
                link_str = f"{loc1} [Local]"
            else:
                link_str = f"{loc1} ↔ {loc2}"
            warn = " ⚠️_(whitespace)_" if tag and tag != tag.strip() else ""
            lines.append(f"• {display_tag}{warn} — {link_str} _{creators}_")

    if orphaned:
        lines.append("")
        lines.append("🔴 *Unpaired Portals (No Link):*")
        for tag, p in orphaned:
            display_tag = f"`{tag}`" if tag else "_[BLANK]_"
            loc = get_portal_location_desc(*p['pos'])
            c = format_player_name(p['creator'])
            lines.append(f"• {display_tag} — {loc} (_{c}_)")
            if tag:
                for other_tag, _ in orphaned:
                    if other_tag and tag != other_tag and tag.lower() == other_tag.lower():
                        lines.append(f"  ↳ ⚠️ _Case mismatch: another portal tagged `{other_tag}` (case-sensitive)_")
                        break

    if conflicted:
        lines.append("")
        lines.append("⚠️ *Multi-Portal Conflicts (>2 with same tag):*")
        for tag, p_list in conflicted:
            display_tag = f"`{tag}`" if tag else "_[BLANK]_"
            lines.append(f"• {display_tag}: {len(p_list)} portals with identical tag")
            remaining = list(p_list)
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
            for pA, pB, dist in pairs:
                locA = get_portal_location_desc(*pA['pos'])
                locB = get_portal_location_desc(*pB['pos'])
                lines.append(f"  ↳ 🟢 Active Pair: {locA} ↔ {locB}")
            for s in remaining:
                locS = get_portal_location_desc(*s['pos'])
                lines.append(f"  ↳ 🔴 Stranded: {locS} ({format_player_name(s['creator'])})")

    lines.append("")
    lines.append("💡 _Type `/save` in Valheim game chat to sync new portal tags instantly._")

    return "\n".join(lines)

def get_world_signs():
    """
    Scans the active Valheim world chunks for placed signs,
    extracting the cleaned text, creator name, coordinates, and raw text.
    """
    chunks = get_active_chunk_files()

    sign_hash = struct.pack('<i', get_stable_hash('sign'))
    text_hash = struct.pack('<i', get_stable_hash('text'))

    platform_map = {
        'Steam_76561198229525716': 'Hilda',
        'Steam_76561198077562671': 'Rukia',
        'Steam_76561198014682424': 'Dexter',
        'PlayStation_8380385718227128186': 'Claw',
        'PlayStation_6663223001167151777': 'Rukia',
    }
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', errors='ignore') as f:
                lines = f.read().splitlines()[-10000:]
            last_platform = None
            for l in lines:
                m_plat = re.search(r'Platform ID ((?:Steam|PlayStation|Xbox)_[a-zA-Z0-9_-]+)', l)
                if m_plat:
                    last_platform = m_plat.group(1)
                m_name = re.search(r'Got character ZDOID from ([^ :]+)', l)
                if m_name and last_platform:
                    platform_map[last_platform] = m_name.group(1)
                    last_platform = None
    except Exception:
        pass

    signs = []
    seen_signatures = set()
    for c in chunks:
        try:
            with open(c, 'rb') as fp:
                data = fp.read()
        except Exception:
            continue

        idx = 0
        while True:
            idx = data.find(sign_hash, idx)
            if idx == -1:
                break
            pos = (0, 0, 0)
            if idx >= 12:
                x, y, z = struct.unpack('<fff', data[idx-12:idx])
                if -10500 <= x <= 10500 and -500 <= y <= 1000 and -10500 <= z <= 10500:
                    pos = (round(x, 1), round(y, 1), round(z, 1))

            bound = find_next_zdo_boundary(data, idx + 4, max_search=200)
            next_sign = data.find(sign_hash, idx + 4)
            if next_sign != -1:
                bound = min(bound, max(idx + 4, next_sign - 12))

            zdo_window = data[idx:bound]
            t_idx = zdo_window.find(text_hash)
            if t_idx != -1:
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
                raw_text = zdo_window[p:p+tag_len].decode('utf-8', errors='replace')
                clean_text = re.sub(r'</?[a-zA-Z][^>]*>', '', raw_text)
                clean_text = clean_text.replace('*', '')
                clean_text = ' '.join(clean_text.split())

                creator = "Homestead"
                for s_id, s_name in platform_map.items():
                    if s_id.encode('ascii') in zdo_window:
                        creator = s_name
                        break

                sig = (clean_text, pos)
                if clean_text and sig not in seen_signatures:
                    seen_signatures.add(sig)
                    signs.append({
                        'raw_text': raw_text,
                        'clean_text': clean_text,
                        'creator': creator,
                        'pos': pos
                    })
            idx += 4
    return signs

def get_signs_report():
    signs = get_world_signs()
    if not signs:
        return "📜 *[Valheim Signs]*\n\n_No carved signposts found in the realm yet!_"

    from collections import Counter
    scribes = Counter([format_player_name(s['creator']) for s in signs if s.get('creator')])

    LANDMARK_KEYWORDS = [
        'hall of heroes', 'the bacon factory', 'spawn base', 'sacrificial stones',
        'portal hub', 'witch stairs', 'walking deck', 'kitchen', 'brewery',
        'fallen & farms', 'fob', 'base / coal', 'bases', 'merchants', 'farm',
        'haven', 'vault', 'shrine', 'temple', 'tower', 'outpost', 'fort',
        'danger', 'zone'
    ]

    landmarks = []
    chest_count_by_loc = Counter()

    for s in signs:
        text = s['clean_text'].strip()
        if not text or text == "..." or len(text) < 2:
            continue

        loc_desc = get_portal_location_desc(*s['pos'])
        if "Main Base" in loc_desc:
            loc_key = "🏠 Main Base"
        elif "Bog Witch" in loc_desc:
            loc_key = "🧙‍♀️ Bog Witch Compound"
        elif "NE" in loc_desc:
            loc_key = "🌲 Northeast Outpost"
        else:
            loc_key = f"🌲 Outpost ({loc_desc})"

        clean_lower = text.lower().replace('&', 'and')
        is_landmark = any(k in clean_lower for k in LANDMARK_KEYWORDS)

        if is_landmark or ("floor" in clean_lower) or ("deck" in clean_lower) or ("hall" in clean_lower) or ("factory" in clean_lower):
            landmarks.append((text, format_player_name(s['creator']), loc_key))
        else:
            chest_count_by_loc[loc_key] += 1

    lines = [
        "📜 *REALM CARVED SIGNS & RUNES*",
        f"• *Total Inscriptions:* {len(signs)} signs across {len(chest_count_by_loc)} settlements",
        ""
    ]

    if landmarks:
        lines.append("🏛️ *Key Halls & Landmark Signposts:*")
        seen_lm = set()
        for text, creator, loc in landmarks:
            key = (text.upper(), loc)
            if key not in seen_lm:
                seen_lm.add(key)
                lines.append(f"• *\"{text}\"* — {loc} (_{creator}_)")
        lines.append("")

    if chest_count_by_loc:
        lines.append("📦 *Storage & Sorting Runes:*")
        for loc, count in chest_count_by_loc.most_common():
            label_plural = "chest label" if count == 1 else "chest labels"
            lines.append(f"• {loc}: *{count} {label_plural}* (Metals, Provisions, Armory)")
        lines.append("")

    lines.append("✍️ *Scribes of the Realm:*")
    scribe_line = " | ".join(f"*{p}:* {c}" for p, c in scribes.most_common() if p)
    lines.append(f"• {scribe_line}")

    return "\n".join(lines)
