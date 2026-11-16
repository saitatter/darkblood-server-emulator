"""Dark Blood protocol wire messages - Commerce domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

@dataclass
class StoreInfoAck:
    """Opcode 2066: eEGS_GET_STORE_INFO_ACK (handler 0x007842C0).

    Draft schema (tools/extract_schemas.py): u32 result, i32 (stored at
    store window +0xCC; NPC id echoed, assumption), tag 0x10 vector of 32-byte
    records (0x00A489D0) and tag 0x10 vector of item structs (0x0077CEB0 ->
    0x00A53F50, sent empty). Store open 0x005953D0 passes the first u32 of
    each 32-byte record to 0x009E5870, an item-dict lookup returning the item
    tab, so a record starts with jhash(item id). The other 28 bytes are not
    recovered: i32 stock (-1 = unlimited, as in storelist.lua) + zeros.
    """
    result: int = 0
    npc_id: int = 0
    items: list = field(default_factory=list)  # [(item id string, count)]

    def encode(self) -> bytes:
        npc = self.npc_id - (1 << 32) if self.npc_id >= 1 << 31 else self.npc_id
        body = struct.pack('<Ii', self.result, npc) + b'\x10' + varuint(len(self.items))
        for item, count in self.items:
            body += struct.pack('<Ii', jhash(item), count) + b'\x00' * 24
        return body + b'\x10' + varuint(0)

@dataclass
class CurrentCashAck:
    """Opcode 2370: eEGS_BILLING_GET_CURRENT_CASH_ACK (case in 0x004DCCC0 -> 0x004CFDF0).

    u32 result, then implicit struct 0x1E (reader 0x00AC82A0, stored at
    +0x124): u64 cash + u32 mileage. 0x004CFDF0 logs them as
    "캐시 : %I64d, 마일리지 : %d" (CP949 strings 0x00C9E64C / 0x00C9E63C).
    """
    result: int = 0
    cash: int = 0
    mileage: int = 0

    def encode(self) -> bytes:
        return struct.pack('<IqI', self.result, self.cash, self.mileage)

@dataclass
class BuyItemReq:
    """Opcode 2067: eEGS_BUY_ITEM_REQ (0x00780000.c:10667).

    Wire format: i32 npc_id + i32 item_id + u16 count (10 bytes).
    """
    store_id: int = 0
    item_id: int = 0
    count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'BuyItemReq':
        if len(data) >= 10:
            sid, iid, cnt = struct.unpack_from('<iiH', data, 0)
            return cls(store_id=sid, item_id=iid, count=cnt)
        return cls()

@dataclass
class BuyItemAck:
    """Opcode 2068: eEGS_BUY_ITEM_ACK (On_eEGS_BUY_ITEM_ACK 0x0077E2F0).

    Wire format:
    If result != 0: i32 result (error popup, terminates frame).
    If result == 0 (success):
      - i32 result (0)
      - tag 0x1e (32-byte store item record 0x00A489D0)
      - i32 (prefix / u32)
      - i64 gold (player gold, written to +0x70)
      - tag 0x10 item vector (0x004B94C0)
      - i32, i16, i64, i32
    """
    result: int = 0
    store_record: bytes = b'\x00' * 32
    u32_1: int = 0
    gold: int = 0
    items: list = field(default_factory=list)
    u32_2: int = 0
    u16_1: int = 0
    i64_1: int = 0
    u32_3: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', 0)
                + b'\x1e' + (self.store_record[:32].ljust(32, b'\x00'))
                + struct.pack('<iq', self.u32_1, self.gold)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + struct.pack('<iHqi', self.u32_2, self.u16_1, self.i64_1, self.u32_3))

@dataclass
class SellItemReq:
    """Opcode 2069: eEGS_SELL_ITEM_REQ (0x00780000.c:10700).

    Wire format: i32 npc_id + i64 item_uid + u16 count (14 bytes).
    """
    npc_id: int = 0
    item_uid: int = 0
    count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'SellItemReq':
        if len(data) >= 14:
            nid, uid, cnt = struct.unpack_from('<iqi', data, 0)
            return cls(npc_id=nid, item_uid=uid, count=cnt)
        return cls()

@dataclass
class SellItemAck:
    """Opcode 2070: eEGS_SELL_ITEM_ACK (On_eEGS_SELL_ITEM_ACK 0x0077E8E0).

    Wire format:
    If result != 0: i32 result (error popup, terminates frame).
    If result == 0 (success):
      - i32 result (0)
      - tag 0x10 item vector (0x004B9210)
      - i64 gold (player gold, written to +0x70)
      - tag 0x1e repurchase record (Item struct 0x00A53F50 + i32 + i64)
      - tag 0x13 map (0x006B9200)
    """
    result: int = 0
    gold: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        repurchase_record = b'\x1e' + Item(code='', uid=0).encode() + struct.pack('<iq', 0, 0)
        return (struct.pack('<i', 0)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold)
                + repurchase_record
                + b'\x13\x80')

@dataclass
class RepurchaseItemReq:
    """Opcode 2071: eEGS_REPURCHASE_ITEM_REQ (0x00780000.c:10735).

    Wire format: i64 item_uid (8 bytes).
    """
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RepurchaseItemReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class RepurchaseItemAck:
    """Opcode 2072: eEGS_REPURCHASE_ITEM_ACK (On_eEGS_REPURCHASE_ITEM_ACK 0x0077EC30).

    Wire format:
    If result != 0: i32 result (error popup).
    If result == 0 (success):
      - i32 result (0)
      - tag 0x10 item vector (0x004B9210)
      - i64 gold (player gold, written to +0x70)
    """
    result: int = 0
    gold: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', 0)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold))

@dataclass
class BuyLifeWaterReq:
    """Opcode 2086: eEGS_BUY_LIFE_WATER_REQ (0x00780000.c:11036).

    Wire format: bool bLifeWater.
    """
    flag: bool = True

    @classmethod
    def decode(cls, data: bytes) -> 'BuyLifeWaterReq':
        if len(data) >= 1:
            return cls(flag=bool(data[0]))
        return cls()

@dataclass
class BuyLifeWaterAck:
    """Opcode 2087: eEGS_BUY_LIFE_WATER_ACK (On_eEGS_BUY_LIFE_WATER_ACK 0x0078FF90).

    Wire format: i32 result + bool flag + i64 remain_currency.
    """
    result: int = 0
    flag: bool = True
    remain_currency: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i?q', self.result, self.flag, self.remain_currency)

@dataclass
class RequestTradeReq:
    """Opcode 5069: eERC_REQUEST_TRADE_REQ."""
    target_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RequestTradeReq':
        if len(data) >= 8:
            return cls(target_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class RequestTradeAck:
    """Opcode 5070: eERC_REQUEST_TRADE_ACK (0x00770E50)."""
    result: int = 0
    target_uid: int = 0
    target_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<iq', self.result, self.target_uid)
                + wide_string(self.target_name)
                + b'\x00\x00')

@dataclass
class AcceptRequestTradeReq:
    """Opcode 5071: eERC_ACCEPT_REQUEST_TRADE_REQ."""
    source_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AcceptRequestTradeReq':
        if len(data) >= 8:
            return cls(source_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class AcceptRequestTradeAck:
    """Opcode 5072: eERC_ACCEPT_REQUEST_TRADE_ACK (0x007587B0)."""
    result: int = 0
    source_uid: int = 0
    target_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqq', self.result, self.source_uid, self.target_uid)

@dataclass
class CancelTradeReq:
    """Opcode 5073: eERC_CANCEL_TRADE_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'CancelTradeReq':
        return cls()

@dataclass
class CancelTradeAck:
    """Opcode 5074: eERC_CANCEL_TRADE_ACK (0x0077DE00)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class InsertTradeItemReq:
    """Opcode 5075: eERC_INSERT_TRADE_ITEM_REQ."""
    item_uid: int = 0
    slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'InsertTradeItemReq':
        if len(data) >= 12:
            uid, slot = struct.unpack_from('<qi', data, 0)
            return cls(item_uid=uid, slot=slot)
        return cls()

@dataclass
class InsertTradeItemAck:
    """Opcode 5076: eERC_INSERT_TRADE_ITEM_ACK (0x0077D980)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class DeleteTradeItemReq:
    """Opcode 5077: eERC_DELETE_TRADE_ITEM_REQ."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DeleteTradeItemReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class DeleteTradeItemAck:
    """Opcode 5078: eERC_DELETE_TRADE_ITEM_ACK (0x0077DBB0)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class UpdateTradeArReq:
    """Opcode 5079: eERC_UPDATE_TRADE_AR_REQ."""
    gold: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'UpdateTradeArReq':
        if len(data) >= 8:
            return cls(gold=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class UpdateTradeArAck:
    """Opcode 5080: eERC_UPDATE_TRADE_AR_ACK (0x00758940)."""
    result: int = 0
    char_uid: int = 0
    gold: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqq', self.result, self.char_uid, self.gold)

@dataclass
class AcceptTradeReq:
    """Opcode 5081: eERC_ACCEPT_TRADE_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'AcceptTradeReq':
        return cls()

@dataclass
class AcceptTradeAck:
    """Opcode 5082: eERC_ACCEPT_TRADE_ACK (0x0078EB40)."""
    result: int = 0
    char_uid: int = 0
    accepted: bool = True

    def encode(self) -> bytes:
        return struct.pack('<iq?', self.result, self.char_uid, self.accepted)

@dataclass
class FinallyAcceptTradeReq:
    """Opcode 5083: eERC_FINALLY_ACCEPT_TRADE_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'FinallyAcceptTradeReq':
        return cls()

@dataclass
class FinallyAcceptTradeAck:
    """Opcode 5084: eERC_FINALLY_ACCEPT_TRADE_ACK."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


# --- Party & Team Opcodes (5049 - 5055, 5015 - 5016) ---

@dataclass
class DepotSaveArReq:
    """Opcode 2228: eEGS_DEPOT_SAVE_AR_REQ."""
    gold: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DepotSaveArReq':
        if len(data) >= 8:
            return cls(gold=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class DepotSaveArAck:
    """Opcode 2229: eEGS_DEPOT_SAVE_AR_ACK (0x00795220)."""
    result: int = 0
    new_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # result (u32) + Tag 0x17 map + i64 new_storage_gold
        return struct.pack('<i', self.result) + b'\x17\x80' + struct.pack('<q', self.new_gold)

@dataclass
class DepotLoadArReq:
    """Opcode 2230: eEGS_DEPOT_LOAD_AR_REQ."""
    gold: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DepotLoadArReq':
        if len(data) >= 8:
            return cls(gold=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class DepotLoadArAck:
    """Opcode 2231: eEGS_DEPOT_LOAD_AR_ACK (0x00795490)."""
    result: int = 0
    new_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # result (u32) + Tag 0x17 map + i64 new_storage_gold
        return struct.pack('<i', self.result) + b'\x17\x80' + struct.pack('<q', self.new_gold)
