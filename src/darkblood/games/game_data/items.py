"""Item prices, durabilities, starter gear, cash packages, random boxes and life water."""
import json
import re
from functools import lru_cache
from darkblood.games.game_data.loader import (
    ASSETS_DIR, _env_override, _section, _top_entries, data_root,
)


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


ITEM_FIELD_RE = re.compile(r'^ {4}(\w+) = (-?\d+),?$')


@lru_cache(maxsize=None)
def item_int_fields():
    """{item id: {field: int}} for integer top-level fields (BuyPrice, SellPrice, BagSize, RepairPrice)."""
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
                    'RepairPrice': int(parts[4]) if len(parts) >= 5 else 0,
                }
        return out

    out = {}
    root = data_root()
    if not root.exists():
        return out
    for path in sorted(root.glob('item_*.lua')):
        item_id = None
        fields = {}
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('  {'):
                if item_id is not None and fields:
                    out.setdefault(item_id, {}).update(fields)
                item_id = None
                fields = {}
                continue
            if line.startswith('  }'):
                if item_id is not None and fields:
                    out.setdefault(item_id, {}).update(fields)
                item_id = None
                fields = {}
                continue
            m = ITEM_ID_RE.match(line)
            if m:
                item_id = m.group(1)
                continue
            m = ITEM_FIELD_RE.match(line)
            if m:
                fields[m.group(1)] = int(m.group(2))
        if item_id is not None and fields:
            out.setdefault(item_id, {}).update(fields)
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
    """Returns {item id: max Durability} truncated to integer as the client loads it into short (+0xBE)."""
    tsv = ASSETS_DIR / 'item_durabilities.tsv'
    if tsv.is_file():
        out = {}
        for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 2:
                out[parts[0]] = float(int(float(parts[1])))
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
                # Client stores dict max durability in a 16-bit short (+0xBE), truncating decimals.
                durability = float(int(float(m.group(1))))
                continue
            m = ITEM_ID_RE.match(line)
            if m and durability is not None:
                out[m.group(1)] = durability
    return out


def item_max_durability(code: str):
    """Max durability of an equipment item, or None when the table lacks it."""
    return item_durabilities().get(code)


@lru_cache(maxsize=1)
def life_water_prices():
    """{level: [step0, step1, step2, step3, step4]} AR costs from DictDunPenalty:LoadLifeWater."""
    tsv = ASSETS_DIR / 'life_water.tsv'
    if tsv.is_file():
        out = {}
        for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
            parts = line.split('\t')
            if len(parts) >= 6:
                out[int(parts[0])] = [int(x) for x in parts[1:6]]
        return out
    path = data_root() / 'dungeonpenalty.lua'
    if not path.is_file():
        return {}
    text = path.read_text(encoding='utf-8', errors='replace')
    m = re.search(r'LoadLifeWater\(\{(.*)\}\)', text, re.S)
    if not m:
        return {}
    out = {}
    for lv_s, step_s in re.findall(r'LV = (\d+),\s*step = \{([^}]+)\}', m.group(1)):
        nums = [int(x) for x in re.findall(r'\d+', step_s)]
        if len(nums) >= 5:
            out[int(lv_s)] = nums[:5]
    return out


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

    paths = [override] if override else [
        data_root() / name for name in ('item_cash.lua', 'item_randombox.lua', 'item_disposable.lua')
    ]
    out = {}
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
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
                # Keep all items from item_cash.lua (e.g. dyes without AdjValue), and
                # any item with an AdjValue from item_randombox.lua / item_disposable.lua.
                if path.name != 'item_cash.lua' and not (adj and adj.group(1)):
                    continue
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

    paths = [override] if override else [
        data_root() / name for name in ('item_cash.lua', 'item_disposable.lua')
    ]
    out = {}
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        pos = 0
        while True:
            section = _section(text[pos:], 'DictItem:LoadPackage')
            if not section:
                break
            for entry in _top_entries(section):
                gid = re.search(r'GroupID = "([^"]+)"', entry)
                if gid:
                    out[gid.group(1)] = [(i, int(n)) for i, n, _ in ENTRY_ITEM_RE.findall(entry)]
            pos = text.find(section, pos) + len(section)
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
                states[rid] = [
                    (float(g['prob']), g['groups']) if isinstance(g, dict) else (float(g[0]), list(g[1]))
                    for g in grades
                ]
            groups = {}
            for gid, items in data.get('groups', {}).items():
                groups[gid] = [(item, int(cnt)) for item, cnt in items]
            return states, groups

    paths = [override] if override else [
        data_root() / name for name in ('item_cash.lua', 'item_randombox.lua')
    ]
    groups = {}
    states = {}
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        pos = 0
        while True:
            section = _section(text[pos:], 'DictRandomBox:LoadRandomBoxGroup')
            if not section:
                break
            for entry in _top_entries(section):
                gid = re.search(r'GroupID = "([^"]+)"', entry)
                if gid:
                    groups[gid.group(1)] = [(i, int(n)) for i, n, _ in ENTRY_ITEM_RE.findall(entry)]
            pos = text.find(section, pos) + len(section)
        pos = 0
        while True:
            section = _section(text[pos:], 'DictRandomBox:LoadRandomBoxState')
            if not section:
                break
            for entry in _top_entries(section):
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
            pos = text.find(section, pos) + len(section)
    return states, groups


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

