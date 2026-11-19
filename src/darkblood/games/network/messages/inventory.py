"""Dark Blood protocol wire messages - Inventory domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

PREFIX = bytes.fromhex('ffffff7f')


@dataclass
class ItemDropEntry:
    """A dropped item (struct 0x1A bytes, ctor 0x00A4FBA0, reader 0x00A509E0).

    The element reader 0x004C7F80 checks tag 0x1E through 0x00B35010 (no
    byte on the wire). Fields in read order: u32 +0 drop uid, u32 +4 item
    code (jhash), u16 +8 (ctor 0), u16 +10 (ctor 0xFFFF; passed with the
    item code to the drop message 0x004C8CA0, taken as the amount), tag 0x13
    set at +0xE (0x006B9F80, meaning not recovered, sent empty), u16 +0xC
    (ctor 0xFFFF). The client places the drop at the source monster
    (5064 header id, 0x00859C60), so no position is sent.
    """
    drop_uid: int
    item_id: int
    count: int = 1

    def encode(self) -> bytes:
        return (struct.pack('<IIHH', self.drop_uid, self.item_id & 0xFFFFFFFF, 0, self.count)
                + b'\x13' + varuint(0) + struct.pack('<H', 0xFFFF))

@dataclass
class DropItemNot:
    """Opcode 5064: eERC_DROP_ITEM_NOT (JUserClient::On_eERC_DROP_ITEM_NOT 0x0078A870).

    Notifies the client of items dropped in the world (e.g. from monster defeat).
    Wire format: u32 source_id + vector (tag 0x10) of 26-byte ItemDropEntry structs.
    """
    source_id: int = 0
    drops: list = field(default_factory=list)

    def encode(self) -> bytes:
        header = struct.pack('<I', self.source_id) + b'\x10' + varuint(len(self.drops))
        return header + b''.join(d.encode() for d in self.drops)

@dataclass
class OpenBagReq:
    """Opcode 2026: eEGS_OPEN_BAG_REQ (sent from 0x0082D34E).

    Observed body: i32 prefix (0x7FFFFFFF) + i64 uid of the bag item being
    equipped (12 bytes).
    """
    prefix: int = 0x7FFFFFFF
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'OpenBagReq':
        if len(data) >= 12:
            prefix, uid = struct.unpack_from('<iq', data, 0)
            return cls(prefix=prefix, item_uid=uid)
        return cls()


@dataclass
class OpenBagAck:
    """Opcode 2027: eEGS_OPEN_BAG_ACK (handler 0x00557860, dispatch 0x0055883F).

    u32 result (nonzero: error popup), then the implicit 0x1E bag struct read
    by 0x00A1EC30 (same Bag entry as the 2007 bag vector). The client inserts
    it with 0x00836010 and then 0x0082F060 looks up the inventory cell whose
    item uid equals the bag id, so the bag id is the bag item's uid.
    """
    result: int = 0
    bag: object = None  # entities.items.Bag

    def encode(self) -> bytes:
        if self.result != 0 or self.bag is None:
            return struct.pack('<I', self.result or 1)
        return struct.pack('<I', 0) + self.bag.encode()


@dataclass
class CloseBagReq:
    """Opcode 2028: eEGS_CLOSE_BAG_REQ (0x00550000.c:1773).

    Wire format: i32 prefix (0x7FFFFFFF) + i64 bag_id.
    """
    prefix: int = 0x7FFFFFFF
    bag_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'CloseBagReq':
        if len(data) >= 12:
            prefix, bag_id = struct.unpack_from('<iq', data, 0)
            return cls(prefix=prefix, bag_id=bag_id)
        return cls()

@dataclass
class DragItemReq:
    """Opcode 2036: eEGS_DRAG_ITEM_REQ (JUserClient::DragItemREQ 0x00790000.c:4212).

    Wire format: i64 item_uid + i64 to_container + i32 to_slot (20 bytes).
    """
    item_uid: int = 0
    to_container: int = 0
    to_slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DragItemReq':
        if len(data) >= 20:
            item_uid, to_container, to_slot = struct.unpack_from('<qqi', data, 0)
            return cls(item_uid=item_uid, to_container=to_container, to_slot=to_slot)
        return cls()

@dataclass
class DragItemAck:
    """Opcode 2037: eEGS_DRAG_ITEM_ACK (On_eEGS_DRAG_ITEM_ACK 0x0077F570).

    Wire format: i32 result (0 = success) + tag 0x10 vector of Item structs.
    """
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(item.encode() for item in self.items))

@dataclass
class UseItemReq:
    """Opcode 2038: eEGS_USE_ITEM_REQ (0x00780000.c:8159).

    Wire format: i64 item_uid + i32 use_count (12 bytes).
    """
    item_uid: int = 0
    use_count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'UseItemReq':
        # Live (2026-11-17): ffffff7f + i64 uid + i32 count, 16 bytes.
        offset = 4 if len(data) >= 16 and data[:4] == PREFIX else 0
        if len(data) >= offset + 12:
            item_uid, use_count = struct.unpack_from('<qi', data, offset)
            return cls(item_uid=item_uid, use_count=use_count)
        return cls()

@dataclass
class UseItemAck:
    """Opcode 2039: eEGS_USE_ITEM_ACK (On_opcode_2039 0x0077D4C0).

    Wire format:
      i32 result (0 = success)
      tag 0x10 vector of Item structs (vecItem)
      i32 nItemID
      i32 nUseCount
    """
    result: int = 0
    items: list = field(default_factory=list)
    item_id: int = 0
    use_count: int = 1

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<Ii', self.item_id, self.use_count))

@dataclass
class AssignQuickslotReq:
    """Opcode 2044: eEGS_ASSIGN_QUICKSLOT_REQ (writer 0x0078C2E0..: u8, u8, u32, u64).

    Wire format: i32 prefix (0x7FFFFFFF) + u8 ucType + u8 ucSlotNum + i32 nRefID
    + i64 nRefUID (18 bytes). Observed live: ffffff7f 01 01 9a010000 ffff..ff.
    Decoding from offset 0 (without the prefix) stored type/slot 255.
    """
    prefix: int = 0x7FFFFFFF
    slot_type: int = 0
    slot_num: int = 0
    ref_id: int = 0
    ref_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AssignQuickslotReq':
        if len(data) >= 18:
            prefix, stype, snum, rid, ruid = struct.unpack_from('<iBBiq', data, 0)
            return cls(prefix=prefix, slot_type=stype, slot_num=snum, ref_id=rid, ref_uid=ruid)
        return cls()

@dataclass
class AssignQuickslotAck:
    """Opcode 2045: eEGS_ASSIGN_QUICKSLOT_ACK (On_eEGS_ASSIGN_QUICKSLOT_ACK 0x0078C4A0).

    Wire format:
      i32 result (0 = success)
      u8 ucType
      u8 ucSlotNum
      i32 nRefID
      i64 nRefUID
    """
    result: int = 0
    slot_type: int = 0
    slot_num: int = 0
    ref_id: int = 0
    ref_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iBBiq', self.result, self.slot_type, self.slot_num, self.ref_id, self.ref_uid)

@dataclass
class EquipItemReq:
    """Opcode 2042: eEGS_EQUIP_ITEM_REQ (0x00800000.c:500).

    Wire format: i64 item_uid + i32 equip_slot (12 bytes). The live client
    (right-click equip, 2026-11-17) prepends the 0x7FFFFFFF prefix:
    ffffff7f + i64 uid + i32 slot (-1 = pick by item), 16 bytes.
    """
    item_uid: int = 0
    equip_slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'EquipItemReq':
        from darkblood.core.serialization.jser import strip_prefix
        data = strip_prefix(data)
        if len(data) >= 12:
            item_uid, equip_slot = struct.unpack_from('<qi', data, 0)
            return cls(item_uid=item_uid, equip_slot=equip_slot)
        return cls()

@dataclass
class EquipItemAck:
    """Opcode 2043: eEGS_EQUIP_ITEM_ACK (On_eEGS_EQUIP_ITEM_ACK 0x007AE940).

    Wire format: i32 result (0 = success) + tag 0x10 vector of Item structs.
    """
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(item.encode() for item in self.items))

@dataclass
class DeleteItemReq:
    """Opcode 2040: eEGS_DELETE_ITEM_REQ (0x00550000.c:769).

    Wire format: i64 nItemUID + i32 nAmount (12 bytes).
    """
    item_uid: int = 0
    amount: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DeleteItemReq':
        # Same optional 0x7FFFFFFF prefix as 2038/2042 (not yet seen live).
        offset = 4 if len(data) >= 16 and data[:4] == PREFIX else 0
        if len(data) >= offset + 12:
            uid, amt = struct.unpack_from('<qi', data, offset)
            return cls(item_uid=uid, amount=amt)
        return cls()

@dataclass
class DeleteItemAck:
    """Opcode 2041: eEGS_DELETE_ITEM_ACK (0x00557420).

    Wire format: i32 result + i64 nDeletedItemUID + i32 nDelAmount.
    """
    result: int = 0
    item_uid: int = 0
    del_amount: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqi', self.result, self.item_uid, self.del_amount)

@dataclass
class SwitchBagReq:
    """Opcode 2030: eEGS_SWITCH_BAG_REQ (0x00550000.c:626).

    Wire format: u16 sIndexFrom + u16 sIndexTo (4 bytes).
    """
    from_index: int = 0
    to_index: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'SwitchBagReq':
        if len(data) >= 4:
            f, t = struct.unpack_from('<HH', data, 0)
            return cls(from_index=f, to_index=t)
        return cls()

@dataclass
class SwitchBagAck:
    """Opcode 2031: eEGS_SWITCH_BAG_ACK (0x00557680).

    Wire format: i32 result + u16 sIndexFrom + u16 sIndexTo.
    """
    result: int = 0
    from_index: int = 0
    to_index: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iHH', self.result, self.from_index, self.to_index)

@dataclass
class SwitchQuickslotReq:
    """Opcode 2046: eEGS_SWITCH_QUCIKSLOT_REQ (sender 0x0078C2E0).

    Wire format: optional 0x7fffffff prefix + u8 ucType + u8 ucSlotNumFrom
    + u8 ucSlotNumTo.
    """
    slot_type: int = 0
    from_slot: int = 0
    to_slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'SwitchQuickslotReq':
        from darkblood.core.serialization.jser import strip_prefix
        data = strip_prefix(data)
        if len(data) >= 3:
            t, f, to = struct.unpack_from('<BBB', data, 0)
            return cls(slot_type=t, from_slot=f, to_slot=to)
        return cls()

@dataclass
class SwitchQuickslotAck:
    """Opcode 2047: eEGS_SWITCH_QUCIKSLOT_ACK (On_eEGS_SWITCH_QUCIKSLOT_ACK 0x0078C790).

    Wire format: i32 result + u8 ucType + u8 ucSlotNumFrom + u8 ucSlotNumTo.
    """
    result: int = 0
    slot_type: int = 0
    from_slot: int = 0
    to_slot: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iBBB', self.result, self.slot_type, self.from_slot, self.to_slot)

@dataclass
class ChangeBagPropertyReq:
    """Opcode 2048: eEGS_CHANGE_BAG_PROPERTY_REQ (0x00550000.c:676).

    Wire format: i64 nBagUID + u8 ucProperty (9 bytes).
    """
    bag_uid: int = 0
    property: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ChangeBagPropertyReq':
        if len(data) >= 9:
            uid, prop = struct.unpack_from('<qB', data, 0)
            return cls(bag_uid=uid, property=prop)
        return cls()

@dataclass
class ChangeBagPropertyAck:
    """Opcode 2049: eEGS_CHANGE_BAG_PROPERTY_ACK (On_eEGS_CHANGE_BAG_PROPERTY_ACK 0x00774040).

    Wire format: i32 result + i64 nBagUID + u8 ucProperty.
    """
    result: int = 0
    bag_uid: int = 0
    property: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqB', self.result, self.bag_uid, self.property)

@dataclass
class ChangeBagNameReq:
    """Opcode 2032: eEGS_CHANGE_BAG_NAME_REQ.

    Wire format: i64 bag_uid + wide string bag_name.
    """
    bag_uid: int = 0
    name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'ChangeBagNameReq':
        if len(data) < 8:
            return cls()
        bag_uid = struct.unpack_from('<q', data, 0)[0]
        name = data[8:].decode('utf-16le', errors='replace').rstrip('\x00')
        return cls(bag_uid=bag_uid, name=name)

@dataclass
class ChangeBagNameAck:
    """Opcode 2033: eEGS_CHANGE_BAG_NAME_ACK (On_eEGS_CHANGE_BAG_NAME_ACK 0x007528B0).

    Wire format: i32 result + i64 bag_uid + wide string bag_name.
    """
    result: int = 0
    bag_uid: int = 0
    name: str = ''

    def encode(self) -> bytes:
        raw_name = self.name.encode('utf-16le') + b'\x00\x00'
        return struct.pack('<iq', self.result, self.bag_uid) + raw_name

@dataclass
class DurabilityRepairReq:
    """Opcode 2145: eEGS_DURABILITY_REPAIR_REQ (0x00790000.c:2123).

    Wire format: tag 0x17 map of items to repair.
    """
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'DurabilityRepairReq':
        return cls(raw_payload=data)

@dataclass
class DurabilityRepairAck:
    """Opcode 2146: eEGS_DURABILITY_REPAIR_ACK (On_eEGS_DURABILITY_REPAIR_ACK 0x007930D0).

    Wire format: if result == 0: i32 result (0) + tag 0x17 map + i64 remain_gold.
                 if result != 0: i32 result error code.
    """
    result: int = 0
    remain_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # 0x17 = map tag, 0x80 = 0 elements
        return struct.pack('<i', 0) + b'\x17\x80' + struct.pack('<q', self.remain_gold)

@dataclass
class ItemUpgradeReq:
    """Opcode 2115: eEGS_ITEM_UPGRADE_REQ (0x00790000.c:296).

    Wire format: i64 nTargetItemUID + i64 nCatalystItemUID + i64 nProtectItemUID.
    """
    target_uid: int = 0
    catalyst_uid: int = 0
    protect_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ItemUpgradeReq':
        if len(data) >= 24:
            t, c, p = struct.unpack_from('<qqq', data, 0)
            return cls(target_uid=t, catalyst_uid=c, protect_uid=p)
        return cls()

@dataclass
class ItemUpgradeAck:
    """Opcode 2116: eEGS_ITEM_UPGRADE_ACK (On_eEGS_ITEM_UPGRADE_ACK 0x007909C0).

    Wire format: i32 result (non-zero safely terminates without requiring complex inventory structs).
    """
    result: int = 1

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class DurabilityChangeReq:
    """Opcode 2143: eEGS_DURABILITY_CHANGE_REQ (0x00790000.c:2049).

    Wire format: tag 0x17 map.
    """
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'DurabilityChangeReq':
        return cls(raw_payload=data)

@dataclass
class DurabilityChangeAck:
    """Opcode 2144: eEGS_DURABILITY_CHANGE_ACK (On_eEGS_DURABILITY_CHANGE_ACK 0x00774AE0).

    Wire format: i32 result + tag 0x10 vector of items.
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result) + b'\x10\x80'

@dataclass
class MagicEnchantEnchantReq:
    """Opcode 2254: eEGS_MAGICENCHANT_ENCHANT_REQ."""
    item_uid: int = 0
    catalyst_uid: int = 0
    scroll_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'MagicEnchantEnchantReq':
        if len(data) >= 24:
            return cls(*struct.unpack_from('<qqq', data, 0))
        return cls()

@dataclass
class MagicEnchantEnchantAck:
    """Opcode 2255: eEGS_MAGICENCHANT_ENCHANT_ACK (0x00796DC0)."""
    result: int = 0
    items: list = field(default_factory=list)
    gold: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold))

@dataclass
class MagicEnchantEraseOptionReq:
    """Opcode 2256: eEGS_MAGICENCHANT_ERASE_OPTION_REQ."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'MagicEnchantEraseOptionReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class MagicEnchantEraseOptionAck:
    """Opcode 2257: eEGS_MAGICENCHANT_ERASE_OPTION_ACK (0x00797120)."""
    result: int = 0
    items: list = field(default_factory=list)
    gold: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold))

@dataclass
class MagicEnchantExpendSlotReq:
    """Opcode 2258: eEGS_MAGICENCHANT_EXPEND_SLOT_REQ."""
    item_uid: int = 0
    stone_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'MagicEnchantExpendSlotReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()

@dataclass
class MagicEnchantExpendSlotAck:
    """Opcode 2259: eEGS_MAGICENCHANT_EXPEND_SLOT_ACK (0x0077FC60)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class RandomItemUpgradeReq:
    """Opcode 2284: eEGS_RANDOM_ITEM_UPGRADE_REQ."""
    item_uid: int = 0
    stone_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RandomItemUpgradeReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()

@dataclass
class RandomItemUpgradeAck:
    """Opcode 2285: eEGS_RANDOM_ITEM_UPGRADE_ACK (0x0077FED0)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class FixItemUpgradeReq:
    """Opcode 2672: eEGS_FIX_ITEM_UPGRADE_REQ."""
    item_uid: int = 0
    stone_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'FixItemUpgradeReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()

@dataclass
class FixItemUpgradeAck:
    """Opcode 2673: eEGS_FIX_ITEM_UPGRADE_ACK (0x00783C40)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


# --- Loot Pickup & Monster Drop Notifications (5065-5068, 5114) ---

@dataclass
class PickUpItemReq:
    """Opcode 5065: eERC_PICK_UP_ITEM_REQ (JUserClient::PickUpItemREQ, push at 0x0078AC3F).

    Event header 0x00408C60(0x13C9, -1, -1) (the ffffff7f prefix) + u32 drop
    uid (0x00B352B0).
    """
    drop_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PickUpItemReq':
        offset = 4 if len(data) >= 8 and data[:4] == PREFIX else 0
        if len(data) >= offset + 4:
            return cls(drop_uid=struct.unpack_from('<I', data, offset)[0])
        return cls()

@dataclass
class PickUpItemAck:
    """Opcode 5066: eERC_PICK_UP_ITEM_ACK."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class PickUpItemResultAck:
    """Opcode 5068: eERC_PICK_UP_ITEM_RESULT_ACK (global handler 0x0078AD80).

    u32 result, i64 picker character UID (0x00866CF0 lookup), then the drop
    struct (tag 0x1E checked without a byte, reader 0x00A509E0). The handler
    removes the drop from the floor (0x0086AFF0) and prints the pick-up
    message; inventory changes come separately (unsolicited 2037).
    """
    result: int = 0
    picker_uid: int = 0
    drop: 'ItemDropEntry' = None

    def encode(self) -> bytes:
        drop = self.drop or ItemDropEntry(drop_uid=0, item_id=0xFFFFFFFF, count=0)
        return struct.pack('<iq', self.result, self.picker_uid) + drop.encode()

@dataclass
class GetDropArNot:
    """Opcode 5114: eERC_GET_DROP_AR_NOT (0x00792700)."""
    result: int = 0
    gold: int = 0
    drop_id: int = 0
    picker_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iiiq', self.result, self.gold, self.drop_id, self.picker_uid)


# --- Friend Presence & Real-Time Char Info (5118, 5119, 5096) ---

@dataclass
class ItemSpiritChangeReq:
    """Opcode 2338: eEGS_ITEM_SPIRIT_CHANGE_REQ."""
    item_uid: int = 0
    spirit_item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ItemSpiritChangeReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()

@dataclass
class ItemSpiritChangeAck:
    """Opcode 2339: eEGS_ITEM_SPIRIT_CHANGE_ACK (0x00780860)."""
    result: int = 0
    spirit_uid: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<iq', self.result, self.spirit_uid)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


# --- Mentoring & Teaching (5351 - 5357) ---

@dataclass
class AvatarZamInsertReq:
    """Opcode 2362: eEGS_AVATAR_ZAM_INSERT_REQ (0x007A46CB)."""
    avatar_item_uid: int = 0
    zam_item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AvatarZamInsertReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()

@dataclass
class AvatarZamInsertAck:
    """Opcode 2363: eEGS_AVATAR_ZAM_INSERT_ACK (0x00782D00)."""
    result: int = 0
    updated_items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.updated_items))
                + b''.join(i.encode() for i in self.updated_items))

@dataclass
class AvatarZamEraseReq:
    """Opcode 2364: eEGS_AVATAR_ZAM_ERASE_REQ (0x007A481B)."""
    avatar_item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AvatarZamEraseReq':
        if len(data) >= 8:
            return cls(avatar_item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class AvatarZamEraseAck:
    """Opcode 2365: eEGS_AVATAR_ZAM_ERASE_ACK (0x00782F40)."""
    result: int = 0
    updated_items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.updated_items))
                + b''.join(i.encode() for i in self.updated_items))


# =========================================================================
# Monster Taming (2348-2351)
# =========================================================================

@dataclass
class DivideItemReq:
    """Opcode 2250: eEGS_DIVIDE_ITEM_REQ (0x00795B83)."""
    source_item_uid: int = 0
    dest_item_uid: int = 0
    count: int = 1
    slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DivideItemReq':
        if len(data) >= 22:
            s_uid, d_uid, cnt, s = struct.unpack_from('<qqih', data, 0)
            return cls(source_item_uid=s_uid, dest_item_uid=d_uid, count=cnt, slot=s)
        return cls()

@dataclass
class DivideItemAck:
    """Opcode 2251: eEGS_DIVIDE_ITEM_ACK (0x0077F570)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class InventoryUpdatedNot:
    """Opcode 2092: eEGS_INVENTORY_UPDATED_NOT (0x0077F070)."""
    def encode(self) -> bytes:
        # Tag 0x10 deleted_items + Tag 0x10 added_items
        return b'\x10\x80\x10\x80'

@dataclass
class ItemRemainTimeNot:
    """Opcode 2321: eEGS_ITEM_REMAIN_TIME_NOT (0x0077AED0)."""
    item_uid: int = 0
    remain_seconds: int = 0

    def encode(self) -> bytes:
        return struct.pack('<qq', self.item_uid, self.remain_seconds)

@dataclass
class ItemDeleteNot:
    """Opcode 2322: eEGS_ITEM_DELETE_NOT (0x00774DD0)."""
    item_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.item_uid)


# =========================================================================
# Guild Banking, Level Up & Skills (2157-2158, 2164-2165, 2179-2186, 2205)
# =========================================================================

@dataclass
class RandomboxResultItemNot:
    """Opcode 2196: eEGS_RANDOMBOX_RESULT_ITEM_NOT (0x0075A2E0)."""
    result: int = 0
    item_code: int = 0
    count: int = 1
    is_jackpot: bool = False

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iih?', self.result, self.item_code, self.count, self.is_jackpot)


# =========================================================================
# Depot / Storage Slot Extension (2461 - 2462)
# =========================================================================

@dataclass
class DepotSlotExtendReq:
    """Opcode 2461: eEGS_DEPOT_SLOT_EXTEND_REQ (0x00651718).

    Wire format: i64 nExtendItemUID + i16 sSlotIndex (10 bytes).
    """
    item_uid: int = 0
    slot_index: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DepotSlotExtendReq':
        from darkblood.core.serialization.jser import strip_prefix
        data = strip_prefix(data)
        if len(data) >= 10:
            uid, sidx = struct.unpack_from('<qh', data, 0)
            return cls(item_uid=uid, slot_index=sidx)
        return cls()


@dataclass
class DepotSlotExtendAck:
    """Opcode 2462: eEGS_DEPOT_SLOT_EXTEND_ACK (0x00651B20).

    Wire format:
      i32 result (0 = success)
      i16 sSlotIndex
      i64 tExtendExpireTime
      tag 0x10 vector of updated Item structs (0x004B9210)
    """
    result: int = 0
    slot_index: int = 0
    expire_time: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<ihq', self.result, self.slot_index, self.expire_time)
                + b'\x10' + varuint(len(self.items))
                + b''.join(item.encode() for item in self.items))
