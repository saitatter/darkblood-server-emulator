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
