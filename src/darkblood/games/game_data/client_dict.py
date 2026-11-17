"""Read game tables from the private decompiled client data (never committed).

Source: lua_src/ in the private workspace built by tools/build_client_data.py
(unluac output of Data/Dict/*.lua). Location: $DARKBLOOD_CLIENT_DATA, default
../darkblood-client-data next to this repository. When the files are absent
every lookup returns empty results, so the server still runs.

Only the fields the server needs are parsed, with line-based scanning of the
unluac output (keys are emitted sorted, one per line):
  npc.lua        DictNpc entries:     ID = "<npc>" ... StoreList = {"<store>", ...}
  storelist.lua  DictStoreList:Load:  ID = "<store>" ... StoreList = {{"<item>", n}, ...}
Client keys these strings with JHashString (models.jhash).
"""
import os
import re
from functools import lru_cache
from pathlib import Path
from darkblood import REPO_ROOT
from darkblood.core.hashing import jhash


ROOT = REPO_ROOT
ID_RE = re.compile(r'^ {4}ID = "([^"]+)",?$')
NAME_RE = re.compile(r'^ {6}"([^"]+)",?$')
ITEM_RE = re.compile(r'^ {6}\{"([^"]+)", (-?\d+)\},?$')


def data_root():
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    base = Path(env) if env else ROOT.parent / 'darkblood-client-data'
    return base / 'lua_src' / 'data' / 'dict'


def _entries(path, item_re):
    """Yield (ID, [StoreList values]) for top-level entries of a dict file."""
    if not path.exists():
        return
    current, values, inside = None, [], False
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = ID_RE.match(line)
        if m:
            current = m.group(1)
            continue
        if line.startswith('    StoreList = {') and current:
            if line.rstrip().endswith('{}') or line.rstrip().endswith('{},'):
                yield current, []
                continue
            inside, values = True, []
            continue
        if inside:
            if line.startswith('    }'):
                yield current, values
                inside = False
                continue
            m = item_re.match(line)
            if m:
                values.append(m.groups() if m.lastindex and m.lastindex > 1 else m.group(1))


@lru_cache(maxsize=None)
def npc_stores():
    """jhash(npc id) -> (npc id, [store ids])."""
    return {jhash(npc): (npc, stores) for npc, stores in _entries(data_root() / 'npc.lua', NAME_RE)}


@lru_cache(maxsize=None)
def store_items():
    """store id -> [(item id, count)] (count -1 = unlimited)."""
    return {store: [(item, int(n)) for item, n in items]
            for store, items in _entries(data_root() / 'storelist.lua', ITEM_RE)}


def items_for_npc(npc_hash):
    """Items of every store an NPC opens, in dict order, without duplicates."""
    npc = npc_stores().get(npc_hash)
    if not npc:
        return None, []
    seen, items = set(), []
    for store in npc[1]:
        for item, count in store_items().get(store, []):
            if item not in seen:
                seen.add(item)
                items.append((item, count))
    return npc[0], items

QUEST_KEY_RE = re.compile(r'^ {4}(\w+) = (?:"([^"]*)"|(-?[\d.]+)),?$')
UNIT_VALUE_RE = re.compile(r'^ {8}(?:"([^"]+)"|(-?\d+)),?$')


def _quest_files():
    root = data_root()
    return sorted(root.glob('quest_act*.lua')) if root.exists() else []


@lru_cache(maxsize=None)
def quests():
    """jhash(quest id) -> {'id', 'exp', 'gold', 'gp', 'items', 'select'} from DictQuest:LoadQuest.

    Rewards: RewardExp, RewardGold, RewardGP, RewardItemG (group given in
    full) and RewardSelectG (group the player picks one entry from).
    """
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
                        items=entry.get('RewardItemG'), select=entry.get('RewardSelectG'))
                continue
            m = QUEST_KEY_RE.match(line)
            if m:
                entry[m.group(1)] = m.group(2) if m.group(2) is not None else m.group(3)
    return out


@lru_cache(maxsize=None)
def item_groups():
    """GroupID -> [(item id, second field (meaning unknown, observed 0), count)]."""
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
def default_equipment():
    """Job -> [item ids] from DictItem:LoadDefaultEquipItem (defaultequipitem.lua)."""
    path = data_root() / 'defaultequipitem.lua'
    out, section, job, inside = {}, None, None, False
    if not path.exists():
        return out
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        if line.startswith('assert(DictItem:'):
            section = line[len('assert(DictItem:'):].split('(')[0]
            continue
        if section != 'LoadDefaultEquipItem':
            continue
        if line.startswith('    Job = '):
            job = int(line.split('=')[1].strip().rstrip(','))
            continue
        if line.startswith('    ItemList = {'):
            inside = True
            out[job] = []
            continue
        if inside:
            if line.startswith('    }'):
                inside = False
                continue
            m = NAME_RE.match(line)
            if m:
                out[job].append(m.group(1))
    return out


CLASS_SECTION_MAP = {
    1: 'LoadStatWarrior',
    2: 'LoadStatKnight',
    3: 'LoadStatHunter',
    4: 'LoadStatMage',
    5: 'LoadStatThief',
    6: 'LoadStatFighter',
    7: 'LoadStatWHunter',
}


@lru_cache(maxsize=None)
def char_level_stats():
    """Returns mapping (char_class, level) -> {'upexp', 'hp', 'mp'} parsed from charstat.lua."""
    path = data_root() / 'charstat.lua'
    out = {}
    if not path.exists():
        return out

    text = path.read_text(encoding='utf-8', errors='replace')
    for cls_id, sec_name in CLASS_SECTION_MAP.items():
        sec_start = text.find(sec_name)
        if sec_start == -1:
            continue
        sec_end = text.find('assert(DictChar:', sec_start + 1)
        sec_text = text[sec_start:sec_end] if sec_end != -1 else text[sec_start:]
        for block in re.split(r'\{\s*\n', sec_text):
            m_lvl = re.search(r'Level = (\d+)', block)
            m_exp = re.search(r'UPExp = ([\d.]+)', block)
            m_hp = re.search(r'HealthPoint = ([\d.]+)', block)
            m_mp = re.search(r'ManaPoint = ([\d.]+)', block)
            if m_lvl and m_exp:
                lvl = int(m_lvl.group(1))
                out[(cls_id, lvl)] = {
                    'upexp': int(float(m_exp.group(1))),
                    'hp': int(float(m_hp.group(1))) if m_hp else 100,
                    'mp': int(float(m_mp.group(1))) if m_mp else 100,
                }
    return out


def char_level_stat(char_class: int, level: int) -> dict:
    """Returns stat dictionary for (char_class, level) with fallback formula."""
    stats = char_level_stats()
    res = stats.get((char_class, level))
    if res:
        return res
    return {
        'upexp': int(144 * (1.5 ** (level - 1))),
        'hp': 200 + level * 150,
        'mp': 50 + level * 20,
    }



ITEM_EQUIP_FILES = ('item_equip1_15lv.lua', 'item_equip20_27lv.lua', 'item_equip30_37lv.lua',
                    'item_equip40_47lv.lua', 'item_equip50_57lv.lua')
DURABILITY_RE = re.compile(r'^ {4}Durability = ([\d.]+),?$')
ITEM_ID_RE = re.compile(r'^ {4}ItemID = "([^"]+)",?$')


@lru_cache(maxsize=None)
def item_durabilities():
    """Returns {item id: max Durability} from the item_equip*.lua dictionaries.

    Keys are emitted sorted, so Durability precedes ItemID inside an entry.
    The client stores the maximum as item prop +0xBE and treats an item whose
    current durability (Item +0x07, f32) is <= 0 as broken (0x00A49920): broken
    gear is skipped when equipment stats are summed (0x009D89B0).
    """
    out = {}
    for name in ITEM_EQUIP_FILES:
        path = data_root() / name
        if not path.exists():
            continue
        durability = None
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('  {'):
                durability = None
                continue
            m = DURABILITY_RE.match(line)
            if m:
                durability = float(m.group(1))
                continue
            m = ITEM_ID_RE.match(line)
            if m and durability is not None:
                out[m.group(1)] = durability
    return out


def item_max_durability(code: str):
    """Max durability of an equipment item, or None when the table lacks it."""
    return item_durabilities().get(code)


TUTORIAL_REWARD_RE = re.compile(r'\{RewardItemAmount = (\d+), RewardItemID = "([^"]+)"\}')


@lru_cache(maxsize=None)
def tutorial_rewards():
    """{'complete': [(item, n)], 'skip': [(item, n)]} from tutorialreward.lua
    (DictTutorialReward:CompleteLoad / :SkipLoad)."""
    out = {'complete': [], 'skip': []}
    path = data_root() / 'tutorialreward.lua'
    if not path.exists():
        return out
    text = path.read_text(encoding='utf-8', errors='replace')
    for key, loader in (('complete', 'CompleteLoad'), ('skip', 'SkipLoad')):
        start = text.find('DictTutorialReward:%s({' % loader)
        if start == -1:
            continue
        end = text.find('}),', start)
        out[key] = [(item, int(n)) for n, item in TUTORIAL_REWARD_RE.findall(text[start:end])]
    return out


PRODUCT_RE = re.compile(r'\{[^{}]*?ItemCount = (\d+),[^{}]*?ItemID = "([^"]+)",[^{}]*?Price = ([0-9.]+),[^{}]*?ProductID = (\d+),[^{}]*?\}')


@lru_cache(maxsize=None)
def cash_products():
    """{ProductID: (ItemID, ItemCount, Price USD)} from item_cash.lua (DictCash:LoadProductList)."""
    path = data_root() / 'item_cash.lua'
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8', errors='replace')
    start = text.find('DictCash:LoadProductList(')
    if start == -1:
        return {}
    return {int(pid): (item, int(count), float(price))
            for count, item, price, pid in PRODUCT_RE.findall(text[start:])}


def _section(text, loader):
    """Body of `assert(<loader>({ ... }), "<loader>")` (first occurrence)."""
    start = text.find(loader + '({')
    if start == -1:
        return ''
    end = text.find('}), "%s")' % loader, start)
    return text[start:end if end != -1 else len(text)]


def _top_entries(section):
    """Split a dict section into its top-level `  {` ... `  },` entries."""
    return re.split(r'\n  \{\n', section)[1:]


ENTRY_ITEM_RE = re.compile(r'"([^"]+)",\s*(-?\d+),\s*(-?\d+)')


@lru_cache(maxsize=None)
def cash_items():
    """{ItemID: {'type': int, 'adj': str}} for item_cash.lua DictItem:LoadItem entries."""
    path = data_root() / 'item_cash.lua'
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8', errors='replace')
    out = {}
    pos = 0
    while True:
        section = _section(text[pos:], 'DictItem:LoadItem')
        if not section:
            break
        for entry in _top_entries(section):
            iid = re.search(r'ItemID = "([^"]+)"', entry)
            if not iid:
                continue
            adj = re.search(r'AdjValue = "([^"]*)"', entry)
            typ = re.search(r'\bType = (\d+)', entry)
            out[iid.group(1)] = {'type': int(typ.group(1)) if typ else -1,
                                 'adj': adj.group(1) if adj else ''}
        pos = text.find(section, pos) + len(section)
    return out


@lru_cache(maxsize=None)
def cash_packages():
    """{GroupID: [(ItemID, count)]} from DictItem:LoadPackage (PACKAGEnnn)."""
    path = data_root() / 'item_cash.lua'
    if not path.exists():
        return {}
    section = _section(path.read_text(encoding='utf-8', errors='replace'), 'DictItem:LoadPackage')
    out = {}
    for entry in _top_entries(section):
        gid = re.search(r'GroupID = "([^"]+)"', entry)
        if gid:
            out[gid.group(1)] = [(i, int(n)) for i, n, _ in ENTRY_ITEM_RE.findall(entry)]
    return out


@lru_cache(maxsize=None)
def random_boxes():
    """(states, groups) from DictRandomBox: states = {RandomID: [(prob, [GroupID])]},
    groups = {GroupID: [(ItemID, count)]}."""
    path = data_root() / 'item_cash.lua'
    if not path.exists():
        return {}, {}
    text = path.read_text(encoding='utf-8', errors='replace')
    groups = {}
    for entry in _top_entries(_section(text, 'DictRandomBox:LoadRandomBoxGroup')):
        gid = re.search(r'GroupID = "([^"]+)"', entry)
        if gid:
            groups[gid.group(1)] = [(i, int(n)) for i, n, _ in ENTRY_ITEM_RE.findall(entry)]
    states = {}
    for entry in _top_entries(_section(text, 'DictRandomBox:LoadRandomBoxState')):
        rid = re.search(r'RandomID = "([^"]+)"', entry)
        if not rid:
            continue
        grades = []
        for grade in 'NSRUM':
            prob = re.search(r'\b%s_Item_Prob = ([0-9.eE+-]+)' % grade, entry)
            glist = re.findall(r'\b%s_ItemGroup = \{([^}]*)\}' % grade, entry)
            names = re.findall(r'"([^"]+)"', ' '.join(glist))
            if prob and float(prob.group(1)) > 0 and names:
                grades.append((float(prob.group(1)), names))
        states[rid.group(1)] = grades
    return states, groups


@lru_cache(maxsize=None)
def monsters():
    """{jhash(ID) & 0xFFFFFFFF: {'id', 'exp', 'lv', 'drop_cnt'}} from monster.lua.

    5063 (MONSTER_DEAD_REQ) carries the monster's template hash.
    """
    from darkblood.core.hashing import jhash
    path = data_root() / 'monster.lua'
    if not path.exists():
        return {}
    out = {}
    for entry in _top_entries(path.read_text(encoding='utf-8', errors='replace')):
        mid = re.search(r'\bID = "([^"]+)"', entry)
        if not mid:
            continue
        exp = re.search(r'\bExp = ([0-9.]+)', entry)
        lv = re.search(r'\bLv = (\d+)', entry)
        drop = re.search(r'\bDropCnt = (\d+)', entry)
        hp = re.search(r'\bHP = ([0-9.]+)', entry)
        out[jhash(mid.group(1)) & 0xFFFFFFFF] = {
            'id': mid.group(1), 'exp': float(exp.group(1)) if exp else 0.0,
            'lv': int(lv.group(1)) if lv else 1, 'drop_cnt': int(drop.group(1)) if drop else 0,
            'hp': float(hp.group(1)) if hp else 0.0}
    return out


@lru_cache(maxsize=None)
def looting():
    """Loot tables from itemlooting.lua (DictItemDrop).

    Returns (mon_looting, looting_items, groups):
      mon_looting   {DungeonID: [{'looting_id', 'prob', 'ave_hp', 'adjust_hp', 'rotate'}]}
      looting_items {LootingID: (OneItemID or '', [GroupID])}
      groups        {GroupID: [ItemID]}
    """
    path = data_root() / 'itemlooting.lua'
    if not path.exists():
        return {}, {}, {}
    text = path.read_text(encoding='utf-8', errors='replace')
    groups = {}
    for entry in _top_entries(_section(text, 'DictItemDrop:LoadLootingItemGroup')):
        gid = re.search(r'GroupID = "([^"]+)"', entry)
        if gid:
            groups[gid.group(1)] = re.findall(r'"([^"]+)",\s*\d+', entry.split('Item = {', 1)[-1])
    items = {}
    for entry in _top_entries(_section(text, 'DictItemDrop:LoadLootingItem')):
        lid = re.search(r'LootingID = "([^"]+)"', entry)
        if not lid:
            continue
        one = re.search(r'OneItemID = "([^"]*)"', entry)
        glist = re.search(r'ItemGroup = \{([^}]*)\}', entry)
        items[lid.group(1)] = (one.group(1) if one else '',
                               re.findall(r'"([^"]+)"', glist.group(1)) if glist else [])
    mon = {}
    pos = 0
    while True:
        section = _section(text[pos:], 'DictItemDrop:LoadMonLooting')
        if not section:
            break
        for entry in _top_entries(section):
            did = re.search(r'DungeonID = "([^"]+)"', entry)
            lid = re.search(r'LootingID = "([^"]+)"', entry)
            prob = re.search(r'UsuallyProb = ([0-9.eE+-]+)', entry)
            if not (did and lid and prob):
                continue
            ave = re.search(r'AveMonHP = ([0-9.]+)', entry)
            adj = re.search(r'AdjustProbByMonHP = (\d+)', entry)
            rot = re.search(r'\bRotateCount = (\d+)', entry)
            mon_id = re.search(r'MonID = "([^"]+)"', entry)
            mon.setdefault(did.group(1), []).append({
                'mon_id': mon_id.group(1) if mon_id else '',
                'looting_id': lid.group(1), 'prob': float(prob.group(1)),
                'ave_hp': float(ave.group(1)) if ave else 0.0,
                'adjust_hp': bool(adj and adj.group(1) == '1'),
                'rotate': int(rot.group(1)) if rot else 1})
        pos = text.find(section, pos) + len(section)
    return mon, items, groups


@lru_cache(maxsize=None)
def equip_index():
    """[(ItemID, Grade, DemandLv, Demand1Class)] for every item_equip*.lua entry."""
    out = []
    for name in ITEM_EQUIP_FILES:
        path = data_root() / name
        if not path.exists():
            continue
        for entry in _top_entries(path.read_text(encoding='utf-8', errors='replace')):
            iid = re.search(r'ItemID = "([^"]+)"', entry)
            if not iid:
                continue
            grade = re.search(r'\bGrade = (\d+)', entry)
            lv = re.search(r'\bDemandLv = (\d+)', entry)
            cls = re.search(r'Demand1Class = "([01]+)"', entry)
            out.append((iid.group(1), int(grade.group(1)) if grade else 0,
                        int(lv.group(1)) if lv else 1, cls.group(1) if cls else ''))
    return out


@lru_cache(maxsize=None)
def quest_monster_objectives():
    """Mapping: monster_id (str) -> [(quest_id_hash, objective_index, target_count)].

    Parsed from LoadMission and LoadQuest in quest_act*.lua.
    """
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
                    mids = re.findall(r'"(QM\d+)"', q_block)
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
