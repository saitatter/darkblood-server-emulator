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

from models import jhash

ROOT = Path(__file__).resolve().parent.parent
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
