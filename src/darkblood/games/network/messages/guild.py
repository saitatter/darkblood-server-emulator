"""Dark Blood protocol wire messages - Guild domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

@dataclass
class GuildOrAttendanceAck:
    """Opcode 2570: ACK response to opcode 2569.

    Binary schema: Reader 0x00772160.
    u32 result (0 = success) + tag 0x17 map (0x76AE20).
    """
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x17' + varuint(len(self.items))

@dataclass
class GuildCreateReq:
    """Opcode 2150 (eEGS_GUILD_CREATE_REQ) & 5121 (eERC_GUILD_CREATE_PROPOSAL_REQ).

    Wire format: wide string strGuildName.
    """
    guild_name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'GuildCreateReq':
        return cls(guild_name=data.decode('utf-16le', errors='replace').rstrip('\x00'))

@dataclass
class GuildCreateAck:
    """Opcode 2151: eEGS_GUILD_CREATE_ACK (On_eEGS_GUILD_CREATE_ACK 0x00793720).

    Wire format: i32 result + i64 nGuildUID + wide string strGuildName + i64 nRemainGold.
    """
    result: int = 0
    guild_uid: int = 1
    guild_name: str = ''
    remain_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        raw_name = self.guild_name.encode('utf-16le') + b'\x00\x00'
        return struct.pack('<iq', self.result, self.guild_uid) + raw_name + struct.pack('<q', self.remain_gold)

@dataclass
class GuildCreateProposalAck:
    """Opcode 5122: eERC_GUILD_CREATE_PROPOSAL_ACK (On_eERC_GUILD_CREATE_PROPOSAL_ACK 0x00759750).

    Wire format: i32 result (0 = success).
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class GuildPersonJoinReq:
    """Opcode 2155: eEGS_GUILD_PERSON_JOIN_REQ (0x00790000.c:2837).

    Wire format: i64 guild_uid.
    """
    guild_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GuildPersonJoinReq':
        if len(data) >= 8:
            return cls(guild_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class GuildPersonJoinAck:
    """Opcode 2156: eEGS_GUILD_PERSON_JOIN_ACK (On_eEGS_GUILD_PERSON_JOIN_ACK 0x0075A220).

    Wire format: i32 result.
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class GuildInviteReq:
    """Opcode 2160: eEGS_GUILD_INVITE_REQ.

    Wire format: wide string char_name.
    """
    char_name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'GuildInviteReq':
        return cls(char_name=data.decode('utf-16le', errors='replace').rstrip('\x00'))

@dataclass
class GuildInviteAck:
    """Opcode 2161: eEGS_GUILD_INVITE_ACK (On_eEGS_GUILD_INVITE_ACK 0x00759870).

    Wire format: i32 result.
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class GuildPersonLeaveReq:
    """Opcode 2162: eEGS_GUILD_PERSON_LEAVE_REQ (0x00790000.c:2761).

    Wire format: empty.
    """
    @classmethod
    def decode(cls, data: bytes) -> 'GuildPersonLeaveReq':
        return cls()

@dataclass
class GuildPersonLeaveAck:
    """Opcode 2163: eEGS_GUILD_PERSON_LEAVE_ACK (On_eEGS_GUILD_PERSON_LEAVE_ACK 0x00759CA0).

    Wire format: i32 result.
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class GuildMoneyInReq:
    """Opcode 2179: eEGS_GUILD_MONEY_IN_REQ (0x00790000.c:3031).

    Wire format: i64 amount (8 bytes).
    """
    amount: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GuildMoneyInReq':
        if len(data) >= 8:
            return cls(amount=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class GuildMoneyInAck:
    """Opcode 2180: eEGS_GUILD_MONEY_IN_ACK (On_eEGS_GUILD_MONEY_IN_ACK 0x00794250).

    Wire format: i32 result (0 = success) + i64 remain_gold (written to +0x70).
    """
    result: int = 0
    remain_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iq', self.result, self.remain_gold)

@dataclass
class GuildMoneyOutReq:
    """Opcode 2181: eEGS_GUILD_MONEY_OUT_REQ (0x00790000.c:3141).

    Wire format: i64 amount (8 bytes).
    """
    amount: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GuildMoneyOutReq':
        if len(data) >= 8:
            return cls(amount=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class GuildMoneyOutAck:
    """Opcode 2182: eEGS_GUILD_MONEY_OUT_ACK (On_eEGS_GUILD_MONEY_OUT_ACK 0x00794470).

    Wire format: i32 result (0 = success) + i64 remain_gold (written to +0x70).
    """
    result: int = 0
    remain_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iq', self.result, self.remain_gold)

@dataclass
class GuildLevelUpReq:
    """Opcode 2183: eEGS_GUILD_LEVEL_UP_REQ (0x00790000.c:3250).

    Wire format: empty or i32 prefix.
    """
    prefix: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GuildLevelUpReq':
        if len(data) >= 4:
            return cls(prefix=struct.unpack_from('<i', data, 0)[0])
        return cls()

@dataclass
class GuildLevelUpAck:
    """Opcode 2184: eEGS_GUILD_LEVEL_UP_ACK (On_eEGS_GUILD_LEVEL_UP_ACK 0x00753380).

    Wire format: i32 result (0 = success) + i16 new_level.
    """
    result: int = 0
    new_level: int = 1

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ih', self.result, self.new_level)

@dataclass
class GuildNoticeModifyReq:
    """Opcode 2185: eEGS_GUILD_NOTICE_MODIFY_REQ (0x00790000.c:3278).

    Wire format: wide string notice.
    """
    notice: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'GuildNoticeModifyReq':
        return cls(notice=data.decode('utf-16le', errors='replace').rstrip('\x00'))

@dataclass
class GuildNoticeModifyAck:
    """Opcode 2186: eEGS_GUILD_NOTICE_MODIFY_ACK (On_eEGS_GUILD_NOTICE_MODIFY_ACK 0x0075A120).

    Wire format: i32 result (0 = success).
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class GuildNoticeDeleteReq:
    """Opcode 2188: eEGS_GUILD_NOTICE_DELETE_REQ (0x00790000.c:3388).

    Wire format: empty or i32 prefix.
    """
    prefix: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GuildNoticeDeleteReq':
        if len(data) >= 4:
            return cls(prefix=struct.unpack_from('<i', data, 0)[0])
        return cls()

@dataclass
class GuildNoticeDeleteAck:
    """Opcode 2189: eEGS_GUILD_NOTICE_DELETE_ACK (On_eEGS_GUILD_NOTICE_DELETE_ACK 0x0074B830).

    Wire format: i32 result (0 = success).
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class GuildAllSkillInitReq:
    """Opcode 2214: eEGS_GUILD_ALL_SKILL_INIT_REQ.

    Wire format: empty or i32 prefix.
    """
    prefix: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GuildAllSkillInitReq':
        if len(data) >= 4:
            return cls(prefix=struct.unpack_from('<i', data, 0)[0])
        return cls()

@dataclass
class GuildAllSkillInitAck:
    """Opcode 2215: eEGS_GUILD_ALL_SKILL_INIT_ACK (0x00752D80).

    Wire format: i32 result (0 = success) + i32 param.
    """
    result: int = 0
    param: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ii', self.result, self.param)


# --- Mailbox Opcodes (2221 - 2237) ---

@dataclass
class GuildNameChangeReq:
    """Opcode 2314: eEGS_GUILD_NAME_CHANGE_REQ."""
    new_name: str = ''
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GuildNameChangeReq':
        try:
            length, off = read_varuint(data, 0)
            name = data[off:off + length].decode('utf-16le', errors='ignore')
            off += length
            item_uid = struct.unpack_from('<q', data, off)[0] if off + 8 <= len(data) else 0
            return cls(new_name=name, item_uid=item_uid)
        except Exception:
            return cls()

@dataclass
class GuildNameChangeAck:
    """Opcode 2315: eEGS_GUILD_NAME_CHANGE_ACK (0x00780590)."""
    result: int = 0
    items: list = field(default_factory=list)
    new_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + wide_string(self.new_name))

@dataclass
class GuildInfoNot:
    """Opcode 2157: eEGS_GUILD_INFO_NOT (0x00752FF0)."""
    def encode(self) -> bytes:
        # Tag 0x1E + dummy guild struct
        return b'\x00' * 64

@dataclass
class GuildPersonListNot:
    """Opcode 2158: eEGS_GUILD_PERSON_LIST_NOT (0x0077ABA0)."""
    def encode(self) -> bytes:
        # Tag 0x10 vector of guild members
        return b'\x10\x80'

@dataclass
class GuildPersonGradeModifyReq:
    """Opcode 2164: eEGS_GUILD_PERSON_GRADE_MODIFY_REQ."""
    member_uid: int = 0
    new_grade: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'GuildPersonGradeModifyReq':
        if len(data) >= 10:
            member_uid, new_grade = struct.unpack_from('<qh', data, 0)
            return cls(member_uid=member_uid, new_grade=new_grade)
        return cls()

@dataclass
class GuildPersonGradeModifyAck:
    """Opcode 2165: eEGS_GUILD_PERSON_GRADE_MODIFY_ACK (0x00753170)."""
    result: int = 0
    member_uid: int = 0
    new_grade: int = 1

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iqh', self.result, self.member_uid, self.new_grade)

@dataclass
class GuildSkillNot:
    """Opcode 2205: eEGS_GUILD_SKILL_NOT (0x00779390)."""
    flag: bool = False

    def encode(self) -> bytes:
        # bool flag + Tag 0x10 vector
        return (b'\x01' if self.flag else b'\x00') + b'\x10\x80'


# =========================================================================
# Storage / Depot & Mailbox Notifications (2227-2231, 2234-2235)
# =========================================================================
