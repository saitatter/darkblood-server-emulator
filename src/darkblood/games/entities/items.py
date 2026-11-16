"""Items and bag containers (client structs 0x00A53F50 / 0x00A1EC30)."""
from dataclasses import dataclass
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import to_i32 as _i32, varuint, wide_string


EQUIPPED = 1  # item container id treated as "worn" by 0x008354D0


@dataclass
class Item:
    """Item struct 0x00A53F50 (0xE4 bytes in memory), used by 2007, 2077, 2116...

    Wire order (all untagged except the 0x10 vectors), defaults from the
    client constructors 0x004AAA00/0x004AAB20:
      0x00A539A0 base: two arrays 0x00A4B250 (+0x0C, +0x6B: varint count
        <= 2 of 10-byte 0x00A49BB0 u16/u32/u32 entries), u16 +0, u16 +2, u16 +4 (0xFFFF), f32 +7 (0), bool +6,
        u16 +0x20 (0xFFFF), vector +0x22 (0x0084FC60), vector +0x32
        (0x004D9610), u32 +0x97 (0), i64 +0x9B (0), time64 +0xA3 (0),
        struct 0x00A53630 {bool, vector 0x00A52330}, vector +0x53,
        u32 +0x63, u32 +0x67, u32 +0x7F (-1), f32 +0x83 (-1.0), u32 +0x87
        (-1), f32 +0x8B (-1.0), u32 +0x8F, u32 +0x93 (-1), u8 +0x0B (0)
      outer: i64 +0xAB owner character UID (must match the player or -1;
        0x008354D0), i64 +0xB3 item UID, u32 +0xBB item code = jhash(item id)
        (8 GetItemProp 0x009E5440 call sites read it), i64 +0xBF container
        (1 = equipped, 2 = skipped, otherwise a bag id looked up by
        0x00828600), u8 +0xC7 slot index in the container, J-wstring +0xC8.
    Base field names come from the Lua item builder 0x006741F0: +0 Amount,
    +2 UpgStep, +4 Quality, +6 RCHold, +7 Durability (f32). Durability must be
    positive: 0x00A49920 reports gear with durability <= 0 as broken and
    0x009D89B0 skips broken gear when summing equipment stats, so sending 0
    left every weapon and armour piece without effect. The other base fields
    keep the constructor defaults.
    """
    code: str
    uid: int
    owner: int = -1
    container: int = -1
    slot: int = 0
    count: int = 1
    durability: float = None  # None -> the item's max Durability from the client tables

    def current_durability(self) -> float:
        if self.durability is not None:
            return float(self.durability)
        from darkblood.games.game_data.client_dict import item_max_durability
        maximum = item_max_durability(self.code)
        # Unknown items (tables absent, or non-equipment) get a positive value
        # so equipment is never reported as broken.
        return maximum if maximum is not None else 100.0

    def encode(self) -> bytes:
        # 0x00A4B250 x2 (+0x0C, +0x6B): varint count (max 2) of 10-byte
        # 0x00A49BB0 entries (u16, u32, u32); sent empty.
        b = varuint(0) + varuint(0)
        b += struct.pack('<HHHf?H', self.count, 0xFFFF, 0xFFFF, self.current_durability(), False, 0xFFFF)
        b += b'\x10' + varuint(0) + b'\x10' + varuint(0)
        b += struct.pack('<Iqq', 0, 0, 0)
        b += struct.pack('<?', False) + b'\x10' + varuint(0)
        b += b'\x10' + varuint(0)
        b += struct.pack('<iiififiiB', -1, -1, -1, -1.0, -1, -1.0, -1, -1, 0)
        b += struct.pack('<qqIqB', self.owner, self.uid, jhash(self.code), self.container, self.slot)
        return b + wide_string('')


@dataclass
class Bag:
    """Container entry of the 2007 bag vector (0x00558010 -> 0x005499F0 -> 0x00A1EC30, 0x2F bytes).

    i64 +0 id: matched against Item.container by 0x00828600; high dword must be
      < 0x80000000 for the bag to be active in 0x00827D80.
    u32 +8 code: bag item code / jhash (0x00827D80 requires != -1).
    J-wstring +0xC: bag name / label (sent empty).
    u8 +0x28 page: item category / tab (0x00551310: 0 matches any item type).
    u8 +0x29 capacity: number of cell slots in the bag (0x005509F0 loops 0..capacity-1).
    u16 +0x2A ui_slot: UI bag slot index (0..4, 0x00827D80 matches short at +0x2A).
    bool +0x2C, bool +0x2D, bool +0x2E (defaults 0, 0, 1 from 0x00A1E760).
    """
    bag_id: int = -1
    code: int = -1  # int hash, or item id string (hashed)
    b28: int = 0
    b29: int = 0
    w2a: int = 0xFFFF
    f2c: bool = False
    f2d: bool = False
    f2e: bool = True

    def encode(self) -> bytes:
        code = jhash(self.code) if isinstance(self.code, str) else self.code
        return (struct.pack('<qi', self.bag_id, _i32(code) if code != -1 else -1)
                + wide_string('') + struct.pack('<BBH???', self.b28, self.b29, self.w2a,
                                                self.f2c, self.f2d, self.f2e))
