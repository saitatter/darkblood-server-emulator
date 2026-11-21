"""Monster stats, loot tables, money drops, dungeon maps and gate listings."""
import json
import re
from functools import lru_cache
from darkblood.core.hashing import jhash
from darkblood.games.game_data.loader import (
    ASSETS_DIR, _env_override, _section, _top_entries, data_root,
)


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


_QUEST_COPY_IGNORED = {'MapID', 'PlayOrder', 'QuestLink', 'Money'}


@lru_cache(maxsize=None)
def dungeon_map_copies():
    """Quest MapID -> regular MapID it duplicates (same DungeonID and Difficult,
    same file, monsters and stats; only MapID, PlayOrder, QuestLink and Money
    differ). Quest maps with their own content are not listed."""
    override = _env_override('maplist.lua')
    if not override:
        tsv = ASSETS_DIR / 'dungeon_maps.tsv'
        if tsv.is_file():
            out = {}
            for line in tsv.read_text(encoding='utf-8', errors='replace').splitlines()[1:]:
                parts = line.split('	')
                if len(parts) >= 5 and parts[4]:
                    out[parts[0]] = parts[4]
            return out
    path = override or (data_root() / 'maplist.lua')
    if not path.exists():
        return {}
    section = _section(path.read_text(encoding='utf-8', errors='replace'), 'DictMap:LoadMap')
    entries = {}
    for entry in _top_entries(section):
        fields = dict(re.findall(r'^    (\w+) = (.*?),?$', entry, re.M))
        map_id = fields.get('MapID', '').strip('"')
        if map_id:
            entries[map_id] = fields
    out = {}
    for map_id, fields in entries.items():
        if not fields.get('QuestLink', '').strip('"'):
            continue
        for other_id, other in entries.items():
            if other.get('QuestLink', '').strip('"') or other.get('DungeonID') != fields.get('DungeonID')                     or other.get('Difficult') != fields.get('Difficult'):
                continue
            keys = (set(fields) | set(other)) - _QUEST_COPY_IGNORED
            if all(fields.get(k) == other.get(k) for k in keys):
                out[map_id] = other_id
            break
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

