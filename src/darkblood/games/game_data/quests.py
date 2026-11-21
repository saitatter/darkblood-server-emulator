"""Quest rewards, item groups and monster/item/dungeon mission objective tables."""
import re
from functools import lru_cache
from darkblood.core.hashing import jhash
from darkblood.games.game_data.loader import (
    ASSETS_DIR, _quest_files, _quest_override_files, data_root,
)


QUEST_KEY_RE = re.compile(r'^ {4}(\w+) = (?:"([^"]*)"|(-?[\d.]+)),?$')


UNIT_VALUE_RE = re.compile(r'^ {8}(?:"([^"]+)"|(-?\d+)),?$')


@lru_cache(maxsize=None)
def quests():
    """jhash(quest id) -> {'id', 'exp', 'gold', 'gp', 'items', 'select', 'offer'} from DictQuest:LoadQuest."""
    q_override = _quest_override_files()
    if not q_override:
        tsv = ASSETS_DIR / 'quests.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 7:
                    qid, exp, gold, gp, offer, reward, select = parts[:7]
                    out[jhash(qid)] = dict(
                        id=qid,
                        exp=int(float(exp)),
                        gold=int(float(gold)),
                        gp=int(float(gp)),
                        items=reward or None,
                        select=select or None,
                        offer=offer or None,
                    )
            return out

    out = {}
    for path in _quest_files():
        section, entry = None, {}
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('assert(DictQuest:'):
                section = line[len('assert(DictQuest:'):].split('(')[0]
                continue
            if section != 'LoadQuest':
                continue
            if line == '  {':
                entry = {}
                continue
            if line.startswith('  }'):
                if 'ID' in entry:
                    out[jhash(entry['ID'])] = dict(
                        id=entry['ID'], exp=int(float(entry.get('RewardExp', 0))),
                        gold=int(float(entry.get('RewardGold', 0))),
                        gp=int(float(entry.get('RewardGP', 0))),
                        items=entry.get('RewardItemG'), select=entry.get('RewardSelectG'),
                        offer=entry.get('OfferItemG'))
                continue
            m = QUEST_KEY_RE.match(line)
            if m:
                entry[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return out


@lru_cache(maxsize=None)
def item_groups():
    """GroupID -> [(item id, second field, count)]."""
    q_override = _quest_override_files()
    if not q_override:
        tsv = ASSETS_DIR / 'quest_item_groups.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 4:
                    gid, item, f2, cnt = parts[:4]
                    out.setdefault(gid, []).append((item, int(f2), int(cnt)))
            return out

    out = {}
    for path in _quest_files():
        section, group, unit = None, None, []
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('assert(DictQuest:'):
                section = line[len('assert(DictQuest:'):].split('(')[0]
                continue
            if section != 'LoadItemGroup':
                continue
            if line.startswith('    GroupID = '):
                group = line.split('"')[1]
                out[group] = []
                continue
            if line == '      {':
                unit = []
                continue
            m = UNIT_VALUE_RE.match(line)
            if m and group is not None:
                unit.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
                continue
            if line.startswith('      }') and group is not None and len(unit) == 3:
                out[group].append(tuple(unit))
                unit = []
    return out


def quest_rewards(quest_hash, select_index=-1):
    """(exp, gold, gp, [(item id, count)]) for a completed quest; zeros if unknown."""
    quest = quests().get(quest_hash)
    if not quest:
        return 0, 0, 0, []
    items = [(item, count) for item, _, count in item_groups().get(quest['items'], [])]
    choices = item_groups().get(quest['select'], [])
    if 0 <= select_index < len(choices):
        items.append((choices[select_index][0], choices[select_index][2]))
    return quest['exp'], quest['gold'], quest['gp'], items


@lru_cache(maxsize=None)
def quest_mission_objectives():
    """Mapping: mission id ("QM807") -> [(quest_id_hash, objective_index, target_value)]."""
    q_override = _quest_override_files()
    if not q_override:
        tsv_m = ASSETS_DIR / 'quest_missions.tsv'
        tsv_c = ASSETS_DIR / 'quest_chains.tsv'
        if tsv_m.is_file() and tsv_c.is_file():
            targets = {}
            for line in tsv_m.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 4:
                    targets[parts[0]] = int(parts[3])
            out = {}
            for line in tsv_c.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    qid, idx, mid = parts[0], int(parts[1]), parts[2]
                    out.setdefault(mid, []).append((jhash(qid) & 0xFFFFFFFF, idx, targets.get(mid, 1)))
            return out

    root = data_root()
    if not root.exists():
        return {}
    targets, quest_missions = {}, {}
    for p in _quest_files():
        txt = p.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', txt):
            if block.startswith('LoadMission'):
                for m_block in re.split(r'\n  \{', block):
                    mid = re.search(r'MissionID\s*=\s*"([^"]+)"', m_block)
                    tval = re.search(r'TargetValue\s*=\s*(\d+)', m_block)
                    if mid:
                        targets[mid.group(1)] = int(tval.group(1)) if tval else 1
            elif block.startswith('LoadQuest'):
                for q_block in re.split(r'\n  \{', block):
                    qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                    mids = re.search(r'MissionID = \{([^}]*)\}', q_block)
                    if qid and mids:
                        quest_missions[jhash(qid.group(1)) & 0xFFFFFFFF] = re.findall(r'"([^"]+)"', mids.group(1))
    out = {}
    for q_hash, mids in quest_missions.items():
        for idx, mid in enumerate(mids):
            out.setdefault(mid, []).append((q_hash, idx, targets.get(mid, 1)))
    return out


@lru_cache(maxsize=None)
def quest_mission_counts():
    """Mapping: quest_id_hash (int) -> count of missions."""
    q_override = _quest_override_files()
    if not q_override:
        tsv_c = ASSETS_DIR / 'quest_chains.tsv'
        if tsv_c.is_file():
            counts = {}
            for line in tsv_c.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    qhash = jhash(parts[0]) & 0xFFFFFFFF
                    counts[qhash] = counts.get(qhash, 0) + 1
            return counts

    root = data_root()
    if not root.exists():
        return {}
    out = {}
    for p in _quest_files():
        txt = p.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', txt):
            if block.startswith('LoadQuest'):
                for q_block in re.split(r'\n  \{', block):
                    qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                    m_match = re.search(r'MissionID\s*=\s*\{([^}]*)\}', q_block, re.S)
                    mids = re.findall(r'"([^"]+)"', m_match.group(1)) if m_match else []
                    if qid and mids:
                        out[jhash(qid.group(1)) & 0xFFFFFFFF] = len(mids)
    return out


@lru_cache(maxsize=None)
def quest_item_objectives():
    """Mapping: item_code (str) -> [(quest_id_hash, objective_index, target_count)]."""
    q_override = _quest_override_files()
    if not q_override:
        tsv_m = ASSETS_DIR / 'quest_missions.tsv'
        tsv_c = ASSETS_DIR / 'quest_chains.tsv'
        if tsv_m.is_file() and tsv_c.is_file():
            mission_defs = {}
            for line in tsv_m.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 4 and parts[1] == '1':
                    mid, tid, tval = parts[0], parts[2], int(parts[3])
                    mission_defs[mid] = (tid, tval)
            out = {}
            for line in tsv_c.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    qid, idx, mid = parts[0], int(parts[1]), parts[2]
                    if mid in mission_defs:
                        tid, tval = mission_defs[mid]
                        out.setdefault(tid, []).append((jhash(qid) & 0xFFFFFFFF, idx, tval))
            return out

    root = data_root()
    if not root.exists():
        return {}
    mission_defs = {}
    quest_missions = {}

    for p in _quest_files():
        txt = p.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', txt):
            if block.startswith('LoadMission'):
                for m_block in re.split(r'\n  \{', block):
                    mid = re.search(r'MissionID\s*=\s*"([^"]+)"', m_block)
                    mtype = re.search(r'MissionType\s*=\s*"([^"]+)"', m_block)
                    tid = re.search(r'TargetID\s*=\s*"([^"]+)"', m_block)
                    tval = re.search(r'TargetValue\s*=\s*(\d+)', m_block)
                    if mid and mtype and tval and mtype.group(1) == '1' and tid:
                        mission_defs[mid.group(1)] = (tid.group(1), int(tval.group(1)))
            elif block.startswith('LoadQuest'):
                for q_block in re.split(r'\n  \{', block):
                    qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                    m_match = re.search(r'MissionID\s*=\s*\{([^}]*)\}', q_block, re.S)
                    mids = re.findall(r'"([^"]+)"', m_match.group(1)) if m_match else []
                    if qid and mids:
                        quest_missions[jhash(qid.group(1)) & 0xFFFFFFFF] = mids

    out = {}
    for qid_hash, mids in quest_missions.items():
        for obj_idx, mid in enumerate(mids):
            if mid in mission_defs:
                target_item, target_val = mission_defs[mid]
                out.setdefault(target_item, []).append((qid_hash, obj_idx, target_val))
    return out


@lru_cache(maxsize=None)
def quest_monster_objectives():
    """Mapping: monster_id (str) -> [(quest_id_hash, objective_index, target_count)]."""
    q_override = _quest_override_files()
    if not q_override:
        tsv_m = ASSETS_DIR / 'quest_missions.tsv'
        tsv_c = ASSETS_DIR / 'quest_chains.tsv'
        if tsv_m.is_file() and tsv_c.is_file():
            mission_defs = {}
            for line in tsv_m.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 4 and parts[1] == '0':
                    mid, tid, tval = parts[0], parts[2], int(parts[3])
                    mission_defs[mid] = (tid, tval)
            out = {}
            for line in tsv_c.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    qid, idx, mid = parts[0], int(parts[1]), parts[2]
                    if mid in mission_defs:
                        target_mon, tval = mission_defs[mid]
                        qhash = jhash(qid) & 0xFFFFFFFF
                        out.setdefault(target_mon, []).append((qhash, idx, tval))
                        out.setdefault(jhash(target_mon) & 0xFFFFFFFF, []).append((qhash, idx, tval))
            return out

    root = data_root()
    if not root.exists():
        return {}
    mission_defs = {}
    quest_missions = {}

    for p in _quest_files():
        txt = p.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', txt):
            if block.startswith('LoadMission'):
                for m_block in re.split(r'\n  \{', block):
                    mid = re.search(r'MissionID\s*=\s*"([^"]+)"', m_block)
                    mtype = re.search(r'MissionType\s*=\s*"([^"]+)"', m_block)
                    tid = re.search(r'TargetID\s*=\s*"([^"]+)"', m_block)
                    tval = re.search(r'TargetValue\s*=\s*(\d+)', m_block)
                    if mid and mtype and tval and mtype.group(1) == '0' and tid:
                        mission_defs[mid.group(1)] = (tid.group(1), int(tval.group(1)))
            elif block.startswith('LoadQuest'):
                for q_block in re.split(r'\n  \{', block):
                    qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                    m_match = re.search(r'MissionID\s*=\s*\{([^}]*)\}', q_block, re.S)
                    mids = re.findall(r'"([^"]+)"', m_match.group(1)) if m_match else []
                    if qid and mids:
                        quest_missions[jhash(qid.group(1)) & 0xFFFFFFFF] = mids

    out = {}
    for qid_hash, mids in quest_missions.items():
        for obj_idx, mid in enumerate(mids):
            if mid in mission_defs:
                target_mon, target_val = mission_defs[mid]
                target_hash = jhash(target_mon) & 0xFFFFFFFF
                out.setdefault(target_mon, []).append((qid_hash, obj_idx, target_val))
                out.setdefault(target_hash, []).append((qid_hash, obj_idx, target_val))
    return out


@lru_cache(maxsize=None)
def quest_dungeon_objectives():
    """Return (by_dungeon_id, by_map_id) for dungeon-clear quest objectives.

    - mission_type 2: target_id is a DungeonID (e.g. 'Act1_G1_A3')
    - mission_type 3: target_id is an exact MapID (e.g. 'Act1_G1_A34')
    Each maps id (str) -> [(quest_id_hash, objective_index, target_count)].
    """
    by_dungeon = {}
    by_map = {}
    tsv_m = ASSETS_DIR / 'quest_missions.tsv'
    tsv_c = ASSETS_DIR / 'quest_chains.tsv'
    if tsv_m.is_file() and tsv_c.is_file():
        mission_defs = {}
        for line in tsv_m.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 4 and parts[1] in ('2', '3') and parts[2]:
                mission_defs[parts[0]] = (parts[1], parts[2], int(parts[3]))
        for line in tsv_c.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 3:
                qid, idx, mid = parts[0], int(parts[1]), parts[2]
                if mid in mission_defs:
                    mtype, target_id, tval = mission_defs[mid]
                    qhash = jhash(qid) & 0xFFFFFFFF
                    bucket = by_dungeon if mtype == '2' else by_map
                    bucket.setdefault(target_id, []).append((qhash, idx, tval))
        return by_dungeon, by_map
    return by_dungeon, by_map

