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
