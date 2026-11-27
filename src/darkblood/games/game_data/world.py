"""Monster stats, loot tables, money drops, dungeon maps and gate listings."""
import json
import re
from functools import lru_cache
from darkblood.core.hashing import jhash
from darkblood.games.game_data.loader import (
    bundled_asset,
    ASSETS_DIR, tsv_rows, _env_override, _section, _top_entries, data_root,
)


@lru_cache(maxsize=None)
def monsters():
    """{jhash(ID) & 0xFFFFFFFF: {'id', 'exp', 'lv', 'drop_cnt'}} from monster.lua."""
    override = _env_override('monster.lua')
    tsv = bundled_asset('monsters.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
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
    json_path = bundled_asset('looting.json', override)
    if json_path:
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
    tsv = bundled_asset('money_drops.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
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
    tsv = bundled_asset('dungeon_maps.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
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
    tsv = bundled_asset('dungeon_maps.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
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
    tsv = bundled_asset('map_gates.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
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
def dungeon_rewards():
    """End-of-dungeon card reward tables from dungeonreward.lua.

    Returns (prizes, dungeons):
      prizes   {PrizeCode: {'items': [[code, count], ...], 'kind': str, 'level': int, 'grade': int}}
      dungeons {DungeonID: [[prize_code, [n_prob, s_prob, r_prob, u_prob]], ...]}
    """
    override = _env_override('dungeonreward.lua')
    json_path = bundled_asset('dungeon_rewards.json', override)
    if json_path:
        data = json.loads(json_path.read_text(encoding='utf-8'))
        return data.get('prizes', {}), data.get('dungeons', {})

    path = override or (data_root() / 'dungeonreward.lua')
    if not path.exists():
        return {}, {}
    text = path.read_text(encoding='utf-8', errors='replace')
    prizes = {}
    for entry in _top_entries(_section(text, 'DictMap:LoadItemPrize')):
        pcode = re.search(r'PrizeCode = "([^"]+)"', entry)
        if not pcode:
            continue
        code = pcode.group(1)
        items = [[m[0], int(m[1])] for m in re.findall(r'\{"([^"]+)",\s*(\d+)\}', entry)]
        lvl = re.search(r'\bLevel = (\d+)', entry)
        grd = re.search(r'\bGrade = (\d+)', entry)
        kind = code.split('_Group_', 1)[0] if '_Group_' in code and not items else ''
        prizes[code] = {
            'items': items,
            'kind': kind,
            'level': int(lvl.group(1)) if lvl else 1,
            'grade': int(grd.group(1)) if grd else 0,
        }
    dungeons = {}
    for entry in _top_entries(_section(text, 'DictMap:LoadRewardItemGroup')):
        did = re.search(r'DungeonID = "([^"]+)"', entry)
        pcode = re.search(r'ItemPrizeCode = "([^"]+)"', entry)
        if not (did and pcode):
            continue
        probs = []
        for col in ('N_Prob', 'S_Prob', 'R_Prob', 'U_Prob'):
            m = re.search(rf'\b{col} = ([0-9.eE+-]+)', entry)
            probs.append(float(m.group(1)) if m else 0.0)
        dungeons.setdefault(did.group(1), []).append([pcode.group(1), probs])
    return prizes, dungeons


@lru_cache(maxsize=None)
def _waypoint_asset():
    """Load town waypoint coordinates, localization keys, and portal cost tables."""
    json_path = ASSETS_DIR / 'waypoints.json'
    if not json_path.is_file():
        return {}, {}, {}
    data = json.loads(json_path.read_text(encoding='utf-8'))
    by_layer = {}
    for entry in data.get('waypoints', []):
        key = ((jhash(entry['square']) & 0xFFFFFFFF) << 32) | (int(entry['layer']) & 0xFFFFFFFF)
        by_layer[key] = {
            'square': entry['square'],
            'layer': int(entry['layer']),
            'id': entry['id'],
            'id_hash': jhash(entry['id']) & 0xFFFFFFFF,
            'name': entry['name'],
            'x': int(entry['x']),
            'y': int(entry['y']),
        }
    costs = data.get('costs', {})
    ratios = {int(k): float(v) for k, v in data.get('level_ratios', {}).items()}
    return by_layer, costs, ratios


def waypoint_info(layer_net_id: int):
    """Return waypoint metadata dict for a packed layer_net_id, or None."""
    by_layer, _, _ = _waypoint_asset()
    return by_layer.get(int(layer_net_id))


def portal_cost(start_wp_id: str, dest_wp_id: str, level: int = 1) -> int:
    """Compute waypoint teleport AR cost matching DictSquarePortal::GetCost (0x00A688E0).

    0x00A68A72: int(int(base_cost) * float32(level_ratio) + 0.5).
    """
    if not start_wp_id or not dest_wp_id or start_wp_id == dest_wp_id:
        return 0
    _, costs, ratios = _waypoint_asset()
    base = costs.get(start_wp_id, {}).get(dest_wp_id)
    if base is None:
        return 0
    lv = max(1, min(int(level), max(ratios) if ratios else 1))
    ratio = ratios.get(lv, 1.0)
    return max(0, int(int(base) * ratio + 0.5))


@lru_cache(maxsize=None)
def dungeon_entry_rules() -> dict:
    """MapID -> {dungeon_id, enter_item_id, enter_item_amount, enter_limit, clear_limit, is_citadel}."""
    json_path = ASSETS_DIR / 'dungeon_entry_rules.json'
    if not json_path.is_file():
        return {}
    return json.loads(json_path.read_text(encoding='utf-8'))


def dungeon_entry_rule(map_id: str):
    """Return entry rule dict for a dungeon MapID, or None if unrestricted."""
    if not map_id:
        return None
    return dungeon_entry_rules().get(map_id)



