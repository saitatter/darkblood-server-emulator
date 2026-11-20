"""Read game tables from normalized assets or fallback client data.

Primary source: assets/ directory containing normalized TSV and JSON tables
exported by tools/export_assets.py. When present, the server runs completely
standalone without needing raw client Lua files.

Fallback/test override source: $DARKBLOOD_CLIENT_DATA or ../darkblood-client-data/lua_src/data/dict.
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path
from darkblood import REPO_ROOT
from darkblood.core.hashing import jhash


ROOT = REPO_ROOT
ASSETS_DIR = REPO_ROOT / 'assets'
ID_RE = re.compile(r'^ {4}ID = "([^"]+)",?$')
NAME_RE = re.compile(r'^ {6}"([^"]+)",?$')
ITEM_RE = re.compile(r'^ {6}\{"([^"]+)", (-?\d+)\},?$')


def data_root():
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    base = Path(env) if env else ROOT.parent / 'darkblood-client-data'
    return base / 'lua_src' / 'data' / 'dict'


def _env_override(filename: str):
    """Return Path to a test override file if explicitly placed in DARKBLOOD_CLIENT_DATA."""
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    if env:
        p = Path(env) / 'lua_src' / 'data' / 'dict' / filename
        if p.is_file():
            return p
    return None


def _quest_override_files():
    """Return quest files if explicitly placed in DARKBLOOD_CLIENT_DATA."""
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    if env:
        root = Path(env) / 'lua_src' / 'data' / 'dict'
        if root.is_dir():
            files = sorted(root.glob('quest_*.lua'))
            if files:
                return files
    return []


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
    override = _env_override('npc.lua')
    if override:
        return {jhash(npc): (npc, stores) for npc, stores in _entries(override, NAME_RE)}

    tsv = ASSETS_DIR / 'npcs.tsv'
    if tsv.is_file():
        out = {}
        for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if parts:
                nid = parts[0]
                stores = parts[1].split(',') if len(parts) > 1 and parts[1] else []
                out[jhash(nid)] = (nid, stores)
        return out
    return {jhash(npc): (npc, stores) for npc, stores in _entries(data_root() / 'npc.lua', NAME_RE)}


@lru_cache(maxsize=None)
def store_items():
    """store id -> [(item id, count)] (count -1 = unlimited)."""
    override = _env_override('storelist.lua')
    if override:
        return {store: [(item, int(n)) for item, n in items]
                for store, items in _entries(override, ITEM_RE)}

    tsv = ASSETS_DIR / 'stores.tsv'
    if tsv.is_file():
        out = {}
        for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 3:
                out.setdefault(parts[0], []).append((parts[1], int(parts[2])))
        return out
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
    q_override = _quest_override_files()
    if q_override:
        return q_override
    root = data_root()
    return sorted(root.glob('quest_act*.lua')) if root.exists() else []


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
def default_equipment():
    """Job -> [item ids] from DictItem:LoadDefaultEquipItem."""
    override = _env_override('defaultequipitem.lua')
    if not override:
        tsv = ASSETS_DIR / 'starter_equipment.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 2:
                    out.setdefault(int(parts[0]), []).append(parts[1])
            return out

    path = override or (data_root() / 'defaultequipitem.lua')
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
    0: 'LoadStatWarrior',
    1: 'LoadStatKnight',
    2: 'LoadStatHunter',
    3: 'LoadStatMage',
    4: 'LoadStatThief',
    5: 'LoadStatFighter',
    6: 'LoadStatWHunter',
}


@lru_cache(maxsize=None)
def char_level_stats():
    """Returns mapping (char_class, level) -> {'upexp', 'hp', 'mp'}."""
    override = _env_override('charstat.lua')
    if not override:
        tsv = ASSETS_DIR / 'char_stats.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 5:
                    cls_id, lv, hp, mp, upexp = parts[:5]
                    out[(int(cls_id), int(lv))] = {
                        'hp': int(float(hp)),
                        'mp': int(float(mp)),
                        'upexp': int(float(upexp)),
                    }
            return out

    path = override or (data_root() / 'charstat.lua')
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


@lru_cache(maxsize=1)
def level_up_ap():
    """AP awarded at each level in the client's DictChar:LoadLevelUp table."""
    override = _env_override('levelup.lua')
    if not override:
        tsv = ASSETS_DIR / 'levelup_ap.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 2:
                    out[int(parts[0])] = int(parts[1])
            return out

    path = override or (data_root() / 'levelup.lua')
    if not path.is_file():
        return {}
    return {int(level): int(ap) for ap, level in re.findall(
        r'\{\s*GainAP\s*=\s*(\d+)\s*,\s*Level\s*=\s*(\d+)\s*\}',
        path.read_text(encoding='utf-8', errors='replace'))}


ITEM_FIELD_RE = re.compile(r'^ {4}(\w+) = (-?\d+),?$')


@lru_cache(maxsize=None)
def item_int_fields():
    """{item id: {field: int}} for integer top-level fields (BuyPrice, SellPrice, BagSize)."""
    tsv = ASSETS_DIR / 'item_fields.tsv'
    if tsv.is_file():
        out = {}
        for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 4:
                out[parts[0]] = {
                    'BuyPrice': int(parts[1]),
                    'SellPrice': int(parts[2]),
                    'BagSize': int(parts[3]),
                }
        return out

    out = {}
    root = data_root()
    if not root.exists():
        return out
    for path in sorted(root.glob('item_*.lua')):
        fields = {}
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('  {'):
                fields = {}
                continue
            m = ITEM_ID_RE.match(line)
            if m:
                out.setdefault(m.group(1), {}).update(fields)
                continue
            m = ITEM_FIELD_RE.match(line)
            if m:
                fields[m.group(1)] = int(m.group(2))
    return out


def item_field(code: str, name: str, default=None):
    """One integer field of an item's dictionary entry (see item_int_fields)."""
    return item_int_fields().get(code, {}).get(name, default)


ITEM_EQUIP_FILES = ('item_equip1_15lv.lua', 'item_equip20_27lv.lua', 'item_equip30_37lv.lua',
                    'item_equip40_47lv.lua', 'item_equip50_57lv.lua')
DURABILITY_RE = re.compile(r'^ {4}Durability = ([\d.]+),?$')
ITEM_ID_RE = re.compile(r'^ {4}ItemID = "([^"]+)",?$')


@lru_cache(maxsize=None)
def item_durabilities():
    """Returns {item id: max Durability}."""
    tsv = ASSETS_DIR / 'item_durabilities.tsv'
    if tsv.is_file():
        out = {}
        for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 2:
                out[parts[0]] = float(parts[1])
        return out

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
    """{'complete': [(item, n)], 'skip': [(item, n)]}."""
    override = _env_override('tutorialreward.lua')
    if not override:
        tsv = ASSETS_DIR / 'tutorial_rewards.tsv'
        if tsv.is_file():
            out = {'complete': [], 'skip': []}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    out.setdefault(parts[0], []).append((parts[1], int(parts[2])))
            return out

    out = {'complete': [], 'skip': []}
    path = override or (data_root() / 'tutorialreward.lua')
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
    override = _env_override('item_cash.lua')
    if not override:
        tsv = ASSETS_DIR / 'cash_items.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    out[parts[0]] = {'type': int(parts[1]), 'adj': parts[2]}
            return out

    path = override or (data_root() / 'item_cash.lua')
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
    override = _env_override('item_cash.lua')
    if not override:
        tsv = ASSETS_DIR / 'cash_packages.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    out.setdefault(parts[0], []).append((parts[1], int(parts[2])))
            return out

    path = override or (data_root() / 'item_cash.lua')
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
    override = _env_override('item_cash.lua')
    if not override:
        json_path = ASSETS_DIR / 'random_boxes.json'
        if json_path.is_file():
            data = json.loads(json_path.read_text(encoding='utf-8'))
            states = {}
            for rid, grades in data.get('states', {}).items():
                states[rid] = [(float(g['prob']), g['groups']) for g in grades]
            groups = {}
            for gid, items in data.get('groups', {}).items():
                groups[gid] = [(item, int(cnt)) for item, cnt in items]
            return states, groups

    path = override or (data_root() / 'item_cash.lua')
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
    """{jhash(ID) & 0xFFFFFFFF: {'id', 'exp', 'lv', 'drop_cnt'}} from monster.lua."""
    override = _env_override('monster.lua')
    if not override:
        tsv = ASSETS_DIR / 'monsters.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 5:
                    mid, hp, lv, exp, drop = parts[:5]
                    out[jhash(mid) & 0xFFFFFFFF] = {
                        'id': mid,
                        'hp': float(hp),
                        'lv': int(lv),
                        'exp': float(exp),
                        'drop_cnt': int(drop),
                    }
            return out

    path = override or (data_root() / 'monster.lua')
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
    override = _env_override('itemlooting.lua')
    if not override:
        json_path = ASSETS_DIR / 'looting.json'
        if json_path.is_file():
            data = json.loads(json_path.read_text(encoding='utf-8'))
            items = {}
            for lid, val in data.get('looting_items', {}).items():
                if isinstance(val, (list, tuple)):
                    items[lid] = (val[0], val[1])
                else:
                    items[lid] = (val.get('one_item', ''), val.get('groups', []))
            return data.get('mon_looting', {}), items, data.get('groups', {})

    path = override or (data_root() / 'itemlooting.lua')
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
    """[(ItemID, Grade, DemandLv, Demand1Class)] for equipment entries."""
    tsv = ASSETS_DIR / 'equip_index.tsv'
    if tsv.is_file():
        out = []
        for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 4:
                out.append((parts[0], int(parts[1]), int(parts[2]), parts[3]))
        return out

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
def money_drops():
    """{item id: (GoldMin, GoldMax)} for AR drop items."""
    override = _env_override('item_moneysetting.lua')
    if not override:
        tsv = ASSETS_DIR / 'money_drops.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 3:
                    out[parts[0]] = (float(parts[1]), float(parts[2]))
            return out

    path = override or (data_root() / 'item_moneysetting.lua')
    if not path.exists():
        return {}
    out = {}
    for entry in _top_entries(path.read_text(encoding='utf-8', errors='replace')):
        iid = re.search(r'ItemID = "([^"]+)"', entry)
        lo = re.search(r'GoldMin = ([0-9.]+)', entry)
        hi = re.search(r'GoldMax = ([0-9.]+)', entry)
        if iid and lo and hi:
            out[iid.group(1)] = (float(lo.group(1)), float(hi.group(1)))
    return out


@lru_cache(maxsize=None)
def skill_costs():
    """{(skill index, level): (DemandPoint SP, DemandAr)} from skill table."""
    override = _env_override('skill.lua')
    if not override:
        tsv = ASSETS_DIR / 'skills.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 4:
                    out[(int(parts[0]), int(parts[1]))] = (int(parts[2]), int(parts[3]))
            return out

    path = override or (data_root() / 'skill.lua')
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8', errors='replace')
    end = text.find('assert(DictSkill:LoadSummonSkill')
    out = {}
    for entry in re.split(r'\n  \{\n', text[:end if end != -1 else len(text)])[1:]:
        idx = re.search(r'\n    NameIndex = "?(\d+)"?,', entry)
        lv = re.search(r'\n    Lv = (\d+)', entry)
        if not (idx and lv):
            continue
        sp = re.search(r'\n    DemandPoint = (\d+)', entry)
        ar = re.search(r'\n    DemandAr = (\d+)', entry)
        out[(int(idx.group(1)), int(lv.group(1)))] = (int(sp.group(1)) if sp else 0,
                                                       int(ar.group(1)) if ar else 0)
    return out


def skill_learn_cost(skill_index: int, current: int, target: int):
    """(SP, AR) to raise a skill from level current to target."""
    costs = skill_costs()
    sp = ar = 0
    for level in range(current + 1, target + 1):
        s, a = costs.get((skill_index, level), (0, 0))
        sp, ar = sp + s, ar + a
    return sp, ar


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
                    mids = re.findall(r'"(QM\d+)"', q_block)
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
                    mids = re.findall(r'"(QM\d+)"', q_block)
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
def achievements():
    """Counter achievements (Type 0) from DictAchieve:LoadAchieveInfo.

    Returns [(achieve_id, division, goal, accumulate)]. A Type 0 achievement
    completes when its AchieveDivision counter reaches GoalAmount: summed over
    runs when Accumulate is 1, within one report when it is 0. Group types
    (2/3, GroupCondition) are not included.
    """
    override = _env_override('achieve.lua')
    if not override:
        tsv = ASSETS_DIR / 'achievements.tsv'
        if tsv.is_file():
            out = []
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 4:
                    out.append((parts[0], int(parts[1]), int(parts[2]), int(parts[3])))
            return out
    path = override or (data_root() / 'achieve.lua')
    if not path.exists():
        return []
    section = _section(path.read_text(encoding='utf-8', errors='replace'), 'DictAchieve:LoadAchieveInfo')
    out = []
    for entry in _top_entries(section):
        fields = dict(re.findall(r'^    (\w+) = "?([^",{]*)"?,?$', entry, re.M))
        if fields.get('Type') != '0' or 'GoalAmount' not in fields:
            continue
        out.append((fields['AchieveID'], int(fields['AchieveDivision']),
                    int(float(fields['GoalAmount'])), int(fields.get('Accumulate') or 0)))
    return out


@lru_cache(maxsize=None)
def dungeon_maps():
    """MapID -> (DungeonID, Difficult, QuestLink) from DictMap:LoadMap.

    Each dungeon has up to 30 maps: PlayOrder 0..3 are the difficulties
    (Difficult 0..3), later ones quest variants with a QuestLink.
    """
    override = _env_override('maplist.lua')
    if not override:
        tsv = ASSETS_DIR / 'dungeon_maps.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 4:
                    out[parts[0]] = (parts[1], int(parts[2]), parts[3])
            return out
    path = override or (data_root() / 'maplist.lua')
    if not path.exists():
        return {}
    section = _section(path.read_text(encoding='utf-8', errors='replace'), 'DictMap:LoadMap')
    out = {}
    for entry in _top_entries(section):
        fields = dict(re.findall(r'^    (\w+) = "?([^",]*)"?,?$', entry, re.M))
        if 'MapID' in fields and 'DungeonID' in fields:
            out[fields['MapID']] = (fields['DungeonID'], int(fields.get('Difficult') or 0),
                                    fields.get('QuestLink', ''))
    return out


@lru_cache(maxsize=None)
def gate_dungeons():
    """Mapping: gate_id ("Act1_G1") -> list of dungeon_ids (["Act1_G1_A1", ...])."""
    override = _env_override('maplist.lua')
    if not override:
        tsv = ASSETS_DIR / 'map_gates.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('\t')
                if len(parts) >= 2:
                    gid = parts[0]
                    dlist = parts[1].split(',') if parts[1] else []
                    out[gid] = dlist
            return out

    path = override or (data_root() / 'maplist.lua')
    if not path.exists():
        return {}
    text = path.read_text(encoding='utf-8', errors='replace')
    section = _section(text, 'DictMap:LoadGate')
    out = {}
    for entry in _top_entries(section):
        gid = re.search(r'GateID = "([^"]+)"', entry)
        if not gid:
            continue
        dlist = re.findall(r'"([^"]+)"', entry.split('DungeonID = {', 1)[-1].split('}', 1)[0]) if 'DungeonID = {' in entry else []
        out[gid.group(1)] = dlist
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
