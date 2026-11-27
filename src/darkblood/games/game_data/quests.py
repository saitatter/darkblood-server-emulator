"""Quest rewards, item groups and monster/item/dungeon mission objective tables."""
import re
from functools import lru_cache
from darkblood.core.hashing import jhash
from darkblood.games.game_data.loader import (
    ASSETS_DIR, tsv_rows, _quest_files, _quest_override_files, data_root,
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
            for parts in tsv_rows(tsv):
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
            for parts in tsv_rows(tsv):
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
def _mission_table():
    """(missions, chains) shared by the objective tables.

    missions: mission id -> (mission_type str, target_id str, target_value int or None)
    chains:   [(quest_id_hash, objective_index, mission_id)] in quest order
    Read from assets/quest_missions.tsv + quest_chains.tsv, or from the DictQuest
    LoadMission/LoadQuest blocks when quest Lua files override them.
    """
    missions, chains = {}, []
    if not _quest_override_files() and (ASSETS_DIR / 'quest_missions.tsv').is_file() \
            and (ASSETS_DIR / 'quest_chains.tsv').is_file():
        for parts in tsv_rows(ASSETS_DIR / 'quest_missions.tsv'):
            if len(parts) >= 4:
                missions[parts[0]] = (parts[1], parts[2], int(parts[3]))
        for parts in tsv_rows(ASSETS_DIR / 'quest_chains.tsv'):
            if len(parts) >= 3:
                chains.append((jhash(parts[0]) & 0xFFFFFFFF, int(parts[1]), parts[2]))
        return missions, chains

    if not data_root().exists() and not _quest_override_files():
        return missions, chains
    for path in _quest_files():
        text = path.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', text):
            if block.startswith('LoadMission'):
                for m_block in re.split(r'\n  \{', block):
                    mid = re.search(r'MissionID\s*=\s*"([^"]+)"', m_block)
                    if not mid:
                        continue
                    mtype = re.search(r'MissionType\s*=\s*"([^"]+)"', m_block)
                    tid = re.search(r'TargetID\s*=\s*"([^"]+)"', m_block)
                    tval = re.search(r'TargetValue\s*=\s*(\d+)', m_block)
                    missions[mid.group(1)] = (mtype.group(1) if mtype else '', tid.group(1) if tid else '',
                                              int(tval.group(1)) if tval else None)
            elif block.startswith('LoadQuest'):
                for q_block in re.split(r'\n  \{', block):
                    qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                    m_match = re.search(r'MissionID\s*=\s*\{([^}]*)\}', q_block, re.S)
                    if qid and m_match:
                        q_hash = jhash(qid.group(1)) & 0xFFFFFFFF
                        chains.extend((q_hash, idx, mid)
                                      for idx, mid in enumerate(re.findall(r'"([^"]+)"', m_match.group(1))))
    return missions, chains


def _objectives_by_target(types, hash_keys=False):
    """target_id -> [(quest_id_hash, objective_index, target_value)] for missions of `types`."""
    missions, chains = _mission_table()
    out = {}
    for q_hash, idx, mid in chains:
        mission = missions.get(mid)
        if not mission or mission[0] not in types or not mission[1] or mission[2] is None:
            continue
        mtype, target, value = mission
        out.setdefault(target, []).append((q_hash, idx, value))
        if hash_keys:
            out.setdefault(jhash(target) & 0xFFFFFFFF, []).append((q_hash, idx, value))
    return out


@lru_cache(maxsize=None)
def quest_mission_objectives():
    """Mapping: mission id ("QM807") -> [(quest_id_hash, objective_index, target_value)]."""
    missions, chains = _mission_table()
    out = {}
    for q_hash, idx, mid in chains:
        value = (missions.get(mid) or ('', '', None))[2]
        out.setdefault(mid, []).append((q_hash, idx, value if value is not None else 1))
    return out


@lru_cache(maxsize=None)
def quest_mission_counts():
    """Mapping: quest_id_hash (int) -> count of missions."""
    counts = {}
    for q_hash, _, _ in _mission_table()[1]:
        counts[q_hash] = counts.get(q_hash, 0) + 1
    return counts


@lru_cache(maxsize=None)
def quest_item_objectives():
    """Mapping: item_code (str) -> [(quest_id_hash, objective_index, target_count)] (MissionType 1)."""
    return _objectives_by_target({'1'})


@lru_cache(maxsize=None)
def quest_monster_objectives():
    """Mapping: monster_id (str) and jhash(monster_id) -> [(quest_id_hash, objective_index, target_count)] (MissionType 0)."""
    return _objectives_by_target({'0'}, hash_keys=True)


@lru_cache(maxsize=None)
def quest_dungeon_objectives():
    """Return (by_dungeon_id, by_map_id) for dungeon-clear quest objectives.

    - mission_type 2: target_id is a DungeonID (e.g. 'Act1_G1_A3')
    - mission_type 3: target_id is an exact MapID (e.g. 'Act1_G1_A34')
    Each maps id (str) -> [(quest_id_hash, objective_index, target_count)].
    """
    return _objectives_by_target({'2'}), _objectives_by_target({'3'})


def _promotion_target_class(base_class: int, promo_type: int) -> int:
    """Map (base_class 0..6, PromotionType 0|1) -> promoted class ID (0x10..0x16 / 0x50..0x56).

    Verified against client class lookup 0x00AC7130 and skilltree.lua Demand1Class:
    - For Hunter (2) and WHunter (6), PromotionType 0 is Trickster (0x52/0x56) and 1 is Shooter (0x12/0x16).
    - For all other base classes (0, 1, 3, 4, 5), PromotionType 0 is 0x10|base and 1 is 0x50|base.
    """
    if base_class in (2, 6):
        high = 0x50 if promo_type == 0 else 0x10
    else:
        high = 0x10 if promo_type == 0 else 0x50
    return high | (base_class & 0x0F)


@lru_cache(maxsize=None)
def quest_promotion_classes():
    """Mapping: jhash(quest_id) -> promoted class ID (u8) for final class-promotion quests."""
    q_override = _quest_override_files()
    if not q_override:
        tsv = ASSETS_DIR / 'quest_promotions.tsv'
        if tsv.is_file():
            out = {}
            for parts in tsv_rows(tsv):
                if len(parts) >= 2 and parts[0]:
                    out[jhash(parts[0]) & 0xFFFFFFFF] = int(parts[1], 0)
            return out

    all_quests = {}
    for p in _quest_files():
        txt = p.read_text(encoding='utf-8', errors='replace')
        for block in re.split(r'assert\(DictQuest:', txt):
            if not block.startswith('LoadQuest'):
                continue
            for q_block in re.split(r'\n  \{', block)[1:]:
                qid = re.search(r'\bID\s*=\s*"([^"]+)"', q_block)
                if not qid:
                    continue
                plv = re.search(r'PromotionLv\s*=\s*(\d+)', q_block)
                ptype = re.search(r'PromotionType\s*=\s*(\d+)', q_block)
                bcls = re.search(r'DemandBClass\s*=\s*"([^"]+)"', q_block)
                lim = re.search(r'LimitQuest\s*=\s*\{([^}]*)\}', q_block)
                all_quests[qid.group(1)] = {
                    'plv': int(plv.group(1)) if plv else None,
                    'ptype': int(ptype.group(1)) if ptype else None,
                    'bcls': bcls.group(1) if bcls else '',
                    'limits': re.findall(r'"([^"]+)"', lim.group(1)) if lim else [],
                }

    out = {}
    for qid, q in all_quests.items():
        if q['plv'] != 0 or '1' not in q['bcls']:
            continue
        base_class = q['bcls'].index('1')
        cur = q
        visited = {qid}
        found_ptype = None
        while cur and cur['limits']:
            prev_id = cur['limits'][0]
            if prev_id in visited or prev_id not in all_quests:
                break
            visited.add(prev_id)
            prev = all_quests[prev_id]
            if prev['ptype'] is not None:
                found_ptype = prev['ptype']
                break
            cur = prev
        if found_ptype is not None:
            out[jhash(qid) & 0xFFFFFFFF] = _promotion_target_class(base_class, found_ptype)
    return out


def quest_promotion_class(quest_hash: int):
    """Return the promoted class ID (u8) granted by completing quest_hash, or None."""
    return quest_promotion_classes().get(quest_hash & 0xFFFFFFFF)


@lru_cache(maxsize=None)
def quest_temp_skill_indices():
    """Mapping: jhash(temp_skill_id) -> NameIndex (u16) for promotion trial skills."""
    tsv = ASSETS_DIR / 'quest_temp_skills.tsv'
    out = {}
    if tsv.is_file():
        for parts in tsv_rows(tsv):
            if len(parts) >= 3 and parts[1] and parts[2]:
                out[int(parts[1], 0) & 0xFFFFFFFF] = int(parts[2])
    return out


def quest_temp_skill_index(skill_hash: int):
    """Return the numeric skill NameIndex for a promotion trial tempSkill jhash, or None."""
    return quest_temp_skill_indices().get(skill_hash & 0xFFFFFFFF)

