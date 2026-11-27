"""NPC store catalog tables (npcs.tsv, stores.tsv)."""
from functools import lru_cache
from darkblood.core.hashing import jhash
from darkblood.games.game_data.loader import (
    ITEM_RE, NAME_RE, _entries, _env_override, bundled_asset, data_root, tsv_rows,
)


@lru_cache(maxsize=None)
def npc_stores():
    """jhash(npc id) -> (npc id, [store ids])."""
    override = _env_override('npc.lua')
    tsv = bundled_asset('npcs.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
            if parts:
                nid = parts[0]
                stores = parts[1].split(',') if len(parts) > 1 and parts[1] else []
                out[jhash(nid)] = (nid, stores)
        return out

    path = override or (data_root() / 'npc.lua')
    return {jhash(npc): (npc, stores) for npc, stores in _entries(path, NAME_RE)}


@lru_cache(maxsize=None)
def store_items():
    """store id -> [(item id, count)] (count -1 = unlimited)."""
    override = _env_override('storelist.lua')
    tsv = bundled_asset('stores.tsv', override)
    if tsv:
        out = {}
        for parts in tsv_rows(tsv):
            if len(parts) >= 3:
                out.setdefault(parts[0], []).append((parts[1], int(parts[2])))
        return out

    path = override or (data_root() / 'storelist.lua')
    return {store: [(item, int(n)) for item, n in items] for store, items in _entries(path, ITEM_RE)}


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

