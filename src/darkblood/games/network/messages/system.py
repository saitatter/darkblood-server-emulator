"""Dark Blood protocol wire messages - System domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

@dataclass
class HttpNoticeCheckReq:
    """Opcode 2594: eEGS_HTTPNOTICE_CHECK_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'HttpNoticeCheckReq':
        return cls()

@dataclass
class HttpNoticeCheckAck:
    """Opcode 2595: eEGS_HTTPNOTICE_CHECK_ACK (0x005A5110).

    Wire format: i32 result + bool bWatch.
    """
    result: int = 0
    watch: bool = False

    def encode(self) -> bytes:
        return struct.pack('<i?', self.result, self.watch)

@dataclass
class PlayOptionUpdateReq:
    """Opcode 2216: eEGS_PLAY_OPTION_UPDATE_REQ (0x00790000.c:3729).

    Wire format: i64 char_uid + tag 0x1E struct (raw).
    """
    char_uid: int = 0
    raw: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'PlayOptionUpdateReq':
        if len(data) >= 8:
            uid = struct.unpack_from('<q', data, 0)[0]
            return cls(char_uid=uid, raw=data[8:])
        return cls()

@dataclass
class CharVerifyStatReq:
    """Opcode 2406: eEGS_CHAR_VERIFY_STAT_REQ. Heartbeat / stat verification from client."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'CharVerifyStatReq':
        return cls(raw_payload=data)

@dataclass
class CharVerifyStatAck:
    """Opcode 2407: eEGS_CHAR_VERIFY_STAT_ACK (On_eEGS_CHAR_VERIFY_STAT_ACK 0x0074B830)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class LevelUpNot:
    """Opcode 5087: eERC_LEVEL_UP_NOT (On_eERC_LEVEL_UP_NOT 0x0078CCF0).

    Reader 0x00A49160 reads the AP array first, then the fixed fields.
    The handler indexes that array to write the player's remaining AP.
    """
    char_uid: int = 0
    new_level: int = 1
    exp: int = 0
    total_ap: int = 0
    remaining_ap: int = 0
    flag: bool = True

    @classmethod
    def from_character(cls, char):
        return cls(char_uid=char['id'], new_level=char['level'], exp=char['exp'],
                   total_ap=char['total_ap'], remaining_ap=char['sp'])

    def encode(self) -> bytes:
        # 0x0078CCF0 checks tag 0x1E (and the array tag) through 0x00B35010,
        # which consumes no byte for tags outside 0x0F..0x1A: neither byte is
        # on the wire. Fill both AP array entries as in 2007.
        return varuint(2) + struct.pack('<IIqBII?', self.remaining_ap, self.remaining_ap,
                                        self.char_uid, self.new_level, self.exp, self.total_ap, self.flag)

@dataclass
class ChangeExpNot:
    """Opcode 5086: eERC_CHANGE_EXP_NOT (On_eERC_CHANGE_EXP_NOT 0x0078D170).

    Wire format:
      i32 nExpTotal
      tag 0x1E jGainExp: 8 x i32 + 1 x float (36 bytes).
    """
    exp_total: int = 0
    exp_details: tuple = (0, 0, 0, 0, 0, 0, 0, 0, 0.0)

    def encode(self) -> bytes:
        inner = struct.pack('<iiiiiiiif', *self.exp_details)
        # Tag 0x1E is checked by 0x00B35010 (0x0078D170) without reading a byte.
        return struct.pack('<i', self.exp_total) + inner

@dataclass
class CharNickChangeReq:
    """Opcode 2310: eEGS_CHAR_NICK_CHANGE_REQ."""
    new_name: str = ''
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'CharNickChangeReq':
        try:
            length, off = read_varuint(data, 0)
            name = data[off:off + length].decode('utf-16le', errors='ignore')
            off += length
            item_uid = struct.unpack_from('<q', data, off)[0] if off + 8 <= len(data) else 0
            return cls(new_name=name, item_uid=item_uid)
        except Exception:
            return cls()

@dataclass
class CharNickChangeAck:
    """Opcode 2311: eEGS_CHAR_NICK_CHANGE_ACK (0x00780200)."""
    result: int = 0
    items: list = field(default_factory=list)
    new_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + wide_string(self.new_name))

@dataclass
class KeyboardSetCustomKeyReq:
    """Opcode 2319: eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ."""
    keys_blob: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'KeyboardSetCustomKeyReq':
        return cls(keys_blob=data)

@dataclass
class KeyboardSetCustomKeyAck:
    """Opcode 2320: eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK (0x00753960)."""
    result: int = 0
    keys_blob: bytes = b''

    def encode(self) -> bytes:
        return struct.pack('<i', self.result) + wide_string(self.keys_blob.decode('utf-16le', errors='ignore') if self.keys_blob else '')

@dataclass
class TitleChangeReq:
    """Opcode 2335: eEGS_TITLE_CHANGE_REQ (0x00799753)."""
    title_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'TitleChangeReq':
        if len(data) >= 4:
            return cls(title_id=struct.unpack_from('<i', data, 0)[0])
        return cls()

@dataclass
class TitleChangeAck:
    """Opcode 2336: eEGS_TITLE_CHANGE_ACK (0x007751C0)."""
    result: int = 0
    title_id: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ii', self.result, self.title_id)

@dataclass
class AchieveGetListReq:
    """Opcode 2327: eEGS_ACHIEVE_GET_LIST_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'AchieveGetListReq':
        return cls()

@dataclass
class AchieveGetListAck:
    """Opcode 2328: eEGS_ACHIEVE_GET_LIST_ACK (0x0079D650)."""
    result: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # result (u32) + Tag 0x1E + Tag 0x17 (map) + Tag 0x17 (map) + Tag 0x0A (bool) + Tag 0x10 (vector)
        return (struct.pack('<i', self.result)
                + b'\x17\x80\x17\x80\x0a\x00\x10\x80')

@dataclass
class AchieveChangeNot:
    """Opcode 2329: eEGS_ACHIEVE_CHANGE_NOT (0x0076C720)."""
    def encode(self) -> bytes:
        # Tag 0x17 (map) + Tag 0x17 (map) + Tag 0x17 (map)
        return b'\x17\x80\x17\x80\x17\x80'

@dataclass
class AchieveCompleteNot:
    """Opcode 2330: eEGS_ACHIEVE_COMPLETE_NOT (0x0079D240)."""
    def encode(self) -> bytes:
        # Tag 0x10 (vector) + Tag 0x10 (vector)
        return b'\x10\x80\x10\x80'


# =========================================================================
# Avatar Gem / Zam Socketing (2362-2365)
# =========================================================================

@dataclass
class PromotionNot:
    """Opcode 2283: eEGS_PROMOTION_NOT (0x00797F00)."""
    result: int = 0
    new_class: int = 1
    sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iBi', self.result, self.new_class, self.sp) + b'\x17\x80'

@dataclass
class RebirthCoinChangeNot:
    """Opcode 2286: eEGS_REBIRTH_COIN_CHANGE_NOT (0x007983B0).

    u32 result + u16 owned rebirth coins, stored at player +0x7C; a positive
    difference shows UI_2653 ("received N coins").
    """
    result: int = 0
    coins: int = 10

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ih', self.result, self.coins)


# =========================================================================
# Arena SP Item & Arena Square (2709-2710, 5165-5166)
# =========================================================================

@dataclass
class UseArenaSpItemReq:
    """Opcode 2709: eEGS_USE_ARENA_SP_ITEM_REQ."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'UseArenaSpItemReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class UseArenaSpItemAck:
    """Opcode 2710: eEGS_USE_ARENA_SP_ITEM_ACK (0x007A7CA0)."""
    result: int = 0
    consumed_items: list = field(default_factory=list)
    arena_sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.consumed_items))
                + b''.join(i.encode() for i in self.consumed_items)
                + struct.pack('<i', self.arena_sp))

@dataclass
class SecondPassCreateReq:
    """Opcode 5256: eERC_SECOND_PASS_CREATE_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'SecondPassCreateReq':
        return cls(raw_payload=data)

@dataclass
class SecondPassCreateAck:
    """Opcode 5257: eERC_SECOND_PASS_CREATE_ACK (0x0075B020)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class SecondPassModifyReq:
    """Opcode 5258: eERC_SECOND_PASS_MODIFY_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'SecondPassModifyReq':
        return cls(raw_payload=data)

@dataclass
class SecondPassModifyAck:
    """Opcode 5259: eERC_SECOND_PASS_MODIFY_ACK (0x0075B050)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class SecondPassAuthReq:
    """Opcode 5260: eERC_SECOND_PASS_AUTH_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'SecondPassAuthReq':
        return cls(raw_payload=data)

@dataclass
class SecondPassAuthAck:
    """Opcode 5261: eERC_SECOND_PASS_AUTH_ACK (0x0075B080)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


# =========================================================================
# Remote Inspection (6011-6012, 6028-6029)
# =========================================================================

@dataclass
class GTargetListAck:
    """Opcode 5125: eERC_GTARGET_LIST_ACK (case in dispatcher 0x00874550 -> 0x00873490).

    Schema from tools/extract_schemas.py: u32 result, tag 0x10 vector of
    struct 0x00A49B50 {i32, bool, bool} (same element type as 5046
    vecTargetState). Field meanings not recovered; offline default is empty.
    """
    result: int = 0
    targets: list = field(default_factory=list)  # (i32, bool, bool)

    def encode(self) -> bytes:
        body = struct.pack('<I', self.result) + b'\x10' + varuint(len(self.targets))
        for value, a, b in self.targets:
            body += struct.pack('<i??', value, a, b)
        return body

@dataclass
class UpdateCharInfoNot:
    """Opcode 5096: eERC_UPDATE_CHAR_INFO_NOT (0x0078C990)."""
    char_details: bytes = b''
    layer_net_id: int = 0

    def encode(self) -> bytes:
        return self.char_details + struct.pack('<q', self.layer_net_id)


# --- Customization, Renaming & Keymapping (2310-2311, 2314-2315, 2319-2320, 2338-2339) ---
