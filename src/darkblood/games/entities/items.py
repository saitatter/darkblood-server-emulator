"""Items and bag containers (client structs 0x00A53F50 / 0x00A1EC30)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import to_i32 as _i32
from darkblood.core.serialization.wire import *  # noqa: F403
from darkblood.games.game_data.client_dict import item_max_durability


EQUIPPED = 1  # item container id treated as "worn" by 0x008354D0
DEPOT_CONTAINER = 2  # item container id handled by JDepotMgr (0x009411A0) and skipped by inventory (0x008354D0)

# Owner for item records in incremental updates (2037, 2039, 2043, rewards,
# shop). Per-item apply 0x008354D0 ignores a record whose i64 owner (+0xAB)
# differs from the inventory owner 0x007F9330 unless either is -1.
UPDATE_OWNER = -1


@dataclass
class Item(WireMessage):
    """Item struct 0x00A53F50 (0xE4 bytes in memory), used by 2007, 2077, 2116...

    Base field names come from the Lua item builder 0x006741F0: +0 Amount,
    +2 UpgStep, +4 Quality (sent 0 = base tier), +6 RCHold, +7 Durability (f32).
    Empty cells (vacated slot in a move/equip diff) encode uid -1 / code -1
    per the outer constructor 0x004AAB20.
    """
    code: str
    uid: i64
    owner: i64 = -1
    container: i64 = -1
    slot: u8 = 0
    count: u16 = 1
    durability: float = None  # None -> the item's max Durability from the client tables
    upgrade: int = None       # None -> 0xFFFF (un-upgraded); 0..20 -> UpgStep
    quality: u16 = 0          # 0 = base tier (+4 Quality)

    _WIRE_LAYOUT: ClassVar[tuple] = (
        Const(EmptyArray),                      # +0x0C dye array 1 (0x00A4B250)
        Const(EmptyArray),                      # +0x6B dye array 2 (0x00A4B250)
        'count',                                # +0 Amount
        Computed(u16, lambda s: (int(s.upgrade) & 0xFFFF) if s.upgrade is not None else 0xFFFF),  # +2 UpgStep
        Computed(u16, lambda s: int(s.quality) & 0xFFFF),  # +4 Quality (0 = base tier)
        Computed(f32, lambda s: s.current_durability()),  # +7 Durability
        Const(boolean, False),                  # +6 RCHold
        Const(u16, 0xFFFF),                     # +0x20
        Const(EmptyVector),                     # +0x22 (0x0084FC60)
        Const(EmptyVector),                     # +0x32 (0x004D9610)
        Const(u32, 0),                          # +0x97
        Const(i64, 0),                          # +0x9B
        Const(i64, 0),                          # +0xA3 time64
        Const(boolean, False),                  # 0x00A53630.bool
        Const(EmptyVector),                     # 0x00A53630.vector
        Const(EmptyVector),                     # +0x53
        Const(i32, -1),                         # +0x63
        Const(i32, -1),                         # +0x67
        Const(i32, -1),                         # +0x7F
        Const(f32, -1.0),                       # +0x83
        Const(i32, -1),                         # +0x87
        Const(f32, -1.0),                       # +0x8B
        Const(i32, -1),                         # +0x8F
        Const(i32, -1),                         # +0x93
        Const(u8, 0),                           # +0x0B
        'owner',                                # +0xAB owner character UID
        Computed(i64, lambda s: s.uid if s.code else -1),
        Computed(h32, lambda s: (jhash(s.code) & 0xFFFFFFFF) if s.code else 0xFFFFFFFF),
        'container',                            # +0xBF container
        'slot',                                 # +0xC7 slot index
        Const(wstr, ''),                        # +0xC8
    )

    def current_durability(self) -> float:
        maximum = item_max_durability(self.code)
        max_cap = float(int(maximum)) if maximum is not None else None
        if self.durability is not None:
            val = float(self.durability)
            return min(val, max_cap) if max_cap is not None else val
        return max_cap if max_cap is not None else 100.0


@dataclass
class Bag(WireMessage):
    """Container entry of the 2007 bag vector (0x00558010 -> 0x005499F0 -> 0x00A1EC30, 0x2F bytes)."""
    bag_id: i64 = -1
    code: int = -1  # int hash, or item id string (hashed)
    b28: u8 = 0
    b29: u8 = 0
    w2a: u16 = 0xFFFF
    f2c: bool = False
    f2d: bool = False
    f2e: bool = True
    name: wstr = ''

    _WIRE_LAYOUT: ClassVar[tuple] = (
        'bag_id',
        Computed(i32, lambda s: _i32(jhash(s.code)) if isinstance(s.code, str)
                 else (_i32(s.code) if s.code != -1 else -1)),
        'name',
        'b28',
        'b29',
        'w2a',
        'f2c',
        'f2d',
        'f2e',
    )
