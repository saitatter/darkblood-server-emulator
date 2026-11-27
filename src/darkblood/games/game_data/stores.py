"""NPC store catalog tables (npcs.tsv, stores.tsv)."""
from functools import lru_cache
from darkblood.core.hashing import jhash
from darkblood.games.game_data.loader import (
    ASSETS_DIR, tsv_rows, ITEM_RE, NAME_RE, _entries, _env_override, data_root,
)


@lru_cache(maxsize=None)
def npc_stores():
    """jhash(npc id) -> (npc id, [store ids])."""
    override = _env_override('npc.lua')
    if override:
        return {jhash(npc): (npc, stores) for npc, stores in _entries(override, NAME_RE)}

    tsv = ASSETS_DIR / 'npcs.tsv'
    if tsv.is_file():
        out = {}
        for parts in tsv_rows(tsv):
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
        for parts in tsv_rows(tsv):
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

