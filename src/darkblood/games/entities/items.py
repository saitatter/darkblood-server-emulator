"""Items and bag containers (client structs 0x00A53F50 / 0x00A1EC30)."""
from dataclasses import dataclass

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import to_i32 as _i32
from darkblood.core.serialization.wire import JSerBufferWriter


EQUIPPED = 1  # item container id treated as "worn" by 0x008354D0


# Owner for item records in incremental updates (2037, 2039, 2043, rewards,
# shop). Per-item apply 0x008354D0 ignores a record whose i64 owner (+0xAB)
# differs from the inventory owner 0x007F9330 unless either is -1. Live: the
# records carried the character id 1, the client's own UID is 0 (2007 details
# +0x1C), so every equip/drag update was dropped (2026-11-17 tracer).
UPDATE_OWNER = -1


@dataclass
class Item:
    """Item struct 0x00A53F50 (0xE4 bytes in memory), used by 2007, 2077, 2116...

    Wire order (all untagged except the 0x10 vectors), defaults from the
    client constructors 0x004AAA00/0x004AAB20:
      0x00A539A0 base: two arrays 0x00A4B250 (+0x0C, +0x6B: varint count
        <= 2 of 10-byte 0x00A49BB0 u16/u32/u32 entries), u16 +0 Amount, u16 +2 UpgStep (0xFFFF), u16 +4 Quality (sent 0, see encode), f32 +7 Durability, bool +6,
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
        # The client keeps the max as an i16 (prop +0xBE, used by 0x00A49920),
        # so a fractional table value (helmet 18.525) showed as "19/18" live.
        return float(int(maximum)) if maximum is not None else 100.0

    def encode(self) -> bytes:
        w = JSerBufferWriter()
        # 0x00A4B250 x2 (+0x0C, +0x6B): varint count (max 2) of 10-byte
        # 0x00A49BB0 entries (u16, u32, u32); sent empty.
        w.write_varuint(0)
        w.write_varuint(0)
        # +4 Quality must be >= 0 (0 = base tier); +2 UpgStep stays 0xFFFF.
        w.write_u16(self.count)
        w.write_u16(0xFFFF)
        w.write_u16(0)
        w.write_f32(self.current_durability())
        w.write_bool(False)
        w.write_u16(0xFFFF)
        w.write_empty_container(0x10)
        w.write_empty_container(0x10)
        w.write_u32(0)
        w.write_i64(0)
        w.write_i64(0)
        w.write_bool(False)
        w.write_empty_container(0x10)
        w.write_empty_container(0x10)
        w.write_i32(-1)
        w.write_i32(-1)
        w.write_i32(-1)
        w.write_f32(-1.0)
        w.write_i32(-1)
        w.write_f32(-1.0)
        w.write_i32(-1)
        w.write_i32(-1)
        w.write_u8(0)
        if self.code:
            uid, code_hash = self.uid, jhash(self.code) & 0xFFFFFFFF
        else:
            # Empty cell (vacated slot): outer ctor 0x004AAB20 uses uid -1 / code -1.
            uid, code_hash = -1, 0xFFFFFFFF
        w.write_i64(self.owner)
        w.write_i64(uid)
        w.write_h32(code_hash)
        w.write_i64(self.container)
        w.write_u8(self.slot)
        w.write_wstring('')
        return w.to_bytes()


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
        w = JSerBufferWriter()
        w.write_i64(self.bag_id)
        w.write_i32(_i32(code) if code != -1 else -1)
        w.write_wstring('')
        w.write_u8(self.b28)
        w.write_u8(self.b29)
        w.write_u16(self.w2a)
        w.write_bool(self.f2c)
        w.write_bool(self.f2d)
        w.write_bool(self.f2e)
        return w.to_bytes()
