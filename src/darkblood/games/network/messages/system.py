"""Dark Blood protocol wire messages - System domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import WireError, read_varuint, strip_prefix, varuint, wide_string
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
      i32 nExpTotal (written to player +0x78)
      jGainExp (0x00A49E20, tag 0x1E not on the wire): 8 x i32, J-wstring.
    The last field was sent as a 4-byte float: 0x00B35AB0 then read an
    unterminated varint, the whole message failed to parse and the EXP bar
    only moved on level-up (5087).
    """
    exp_total: int = 0
    exp_details: tuple = (0, 0, 0, 0, 0, 0, 0, 0)
    text: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<i8i', self.exp_total, *self.exp_details)
                + wide_string(self.text))

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
class AchieveEntry:
    """Achievement state, struct 0x00A1ED90: i32 id, bool, i32, time64.

    The id is JHashString(AchieveID), as loaded by 0x00A50DA0. The bool is
    sent as "completed" and the i32 as 0; neither is confirmed. The time is
    assumed to be Unix seconds.
    """
    achieve_hash: int
    completed_at: int = 0

    def encode(self) -> bytes:
        return struct.pack('<I?iq', self.achieve_hash & 0xFFFFFFFF, True, 0, self.completed_at)

    def completion_block(self) -> bytes:
        """13-byte block (0x00A1E7E0) whose first u32 0x0079D240 looks up and
        announces by name; the other 9 bytes are not recovered (zeros)."""
        return struct.pack('<I', self.achieve_hash & 0xFFFFFFFF) + b'\x00' * 9


@dataclass
class AchieveGetListAck:
    """Opcode 2328: eEGS_ACHIEVE_GET_LIST_ACK (0x0079D650).

    u32 result, struct 0x00A3E760 (tag 0x1E, not on the wire):
      tag 0x17 map 0x005EC140: 0x0F, u32 division, i64 counter
      tag 0x17 map 0x00A3DC50: 0x0F, u32 achieve hash, AchieveEntry
      bool (not recovered, sent 0)
    then tag 0x10 vector 0x0076B0C0 of 13-byte completion blocks.
    The old stub put a stray 0x0A byte before the bool.
    """
    result: int = 0
    divisions: dict = field(default_factory=dict)  # {division: counter}
    completed: list = field(default_factory=list)  # [AchieveEntry]

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        divs = b''.join(b'\x0f' + struct.pack('<Iq', d, v) for d, v in sorted(self.divisions.items()))
        done = b''.join(b'\x0f' + struct.pack('<I', e.achieve_hash & 0xFFFFFFFF) + e.encode()
                        for e in self.completed)
        return (struct.pack('<i', self.result)
                + b'\x17' + varuint(len(self.divisions)) + divs
                + b'\x17' + varuint(len(self.completed)) + done
                + b'\x00' + b'\x10' + varuint(len(self.completed))
                + b''.join(e.completion_block() for e in self.completed))


@dataclass
class AchieveUpdateReq:
    """Opcode 2444: eEGS_ACHIEVE_UPDATE_REQ (sender 0x007992D0).

    tag 0x10 vector of u32 achievement hashes the client completed itself
    (group/hidden achievements); answered by 2445 (u32 result, 0x0074B830).
    Not yet observed live.
    """
    hashes: list = field(default_factory=list)

    @classmethod
    def decode(cls, data: bytes) -> 'AchieveUpdateReq':
        data = strip_prefix(data)
        if not data or data[0] != 0x10:
            raise WireError('2444 without a vector tag')
        count, offset = read_varuint(data, 1)
        return cls(list(struct.unpack_from('<%dI' % count, data, offset)))


@dataclass
class AchieveDivUpdateReq:
    """Opcode 2446: eEGS_ACHIEVE_DIV_UPDATE_REQ, sent after a dungeon run.

    tag 0x17 map: 0x0F, u32 division, i64 amount. Live values go up and down
    between runs (division 24: 192, 194, 70, ...), so they are per-run deltas.
    """
    amounts: dict = field(default_factory=dict)

    @classmethod
    def decode(cls, data: bytes) -> 'AchieveDivUpdateReq':
        data = strip_prefix(data)
        if not data or data[0] != 0x17:
            raise WireError('2446 without a map tag')
        count, offset = read_varuint(data, 1)
        amounts = {}
        for _ in range(count):
            if data[offset] != 0x0F:
                raise WireError('2446 entry without a pair tag')
            division, amount = struct.unpack_from('<Iq', data, offset + 1)
            amounts[division] = amount
            offset += 13
        return cls(amounts)

@dataclass
class AchieveChangeNot:
    """Opcode 2329: eEGS_ACHIEVE_CHANGE_NOT (0x0076C720)."""
    def encode(self) -> bytes:
        # Tag 0x17 (map) + Tag 0x17 (map) + Tag 0x17 (map)
        return b'\x17\x80\x17\x80\x17\x80'

@dataclass
class AchieveCompleteNot:
    """Opcode 2330: eEGS_ACHIEVE_COMPLETE_NOT (0x0079D240).

    tag 0x10 vector of AchieveEntry (0x0076EA70 -> 0x00A1ED90), applied to the
    achievement page; tag 0x10 vector of 13-byte completion blocks
    (0x00A1E7E0): for each, the handler looks the first u32 up (0x00AABAB0)
    and prints the completion message.
    """
    entries: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (b'\x10' + varuint(len(self.entries)) + b''.join(e.encode() for e in self.entries)
                + b'\x10' + varuint(len(self.entries)) + b''.join(e.completion_block() for e in self.entries))


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
