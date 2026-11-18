"""Dark Blood wire messages - Party and Spatial Movement domain."""
from dataclasses import dataclass, field
import struct
from typing import List

from darkblood.core.serialization.jser import JSerBufferReader, read_varuint, strip_prefix, varuint, wide_string


# =========================================================================
# Multiplayer Spatial Movement & Square Presence (5021, 5022, 5030, 5031)
# =========================================================================

@dataclass
class UserMoveNot:
    """Opcode 5030 / 5031: eERC_USER_MOVE_NOT.

    Spatial movement notification in town/square.
    Carries character UID, 3D coordinates (x, y, z), heading/angle, and move state.
    """
    char_id: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    angle: float = 0.0
    move_state: int = 0

    def encode(self) -> bytes:
        return struct.pack('<qffffi', self.char_id, self.x, self.y, self.z, self.angle, self.move_state)

    @classmethod
    def decode(cls, data: bytes) -> 'UserMoveNot':
        data = strip_prefix(data)
        if len(data) >= 28:
            char_id, x, y, z, angle, move_state = struct.unpack_from('<qffffi', data, 0)
            return cls(char_id=char_id, x=x, y=y, z=z, angle=angle, move_state=move_state)
        elif len(data) >= 20:
            x, y, z, angle, move_state = struct.unpack_from('<ffffi', data, 0)
            return cls(char_id=0, x=x, y=y, z=z, angle=angle, move_state=move_state)
        elif len(data) >= 16:
            x, y, z, angle = struct.unpack_from('<ffff', data, 0)
            return cls(char_id=0, x=x, y=y, z=z, angle=angle, move_state=0)
        elif len(data) >= 12:
            x, y, z = struct.unpack_from('<fff', data, 0)
            return cls(char_id=0, x=x, y=y, z=z, angle=0.0, move_state=0)
        return cls()


@dataclass
class UserJoinSquareNot:
    """Opcode 5021: eERC_USER_JOIN_SQUARE_NOT.

    Broadcast to existing occupants when a player enters the town square.
    """
    char_id: int = 0
    square_id: int = 1
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    angle: float = 0.0
    char_class: int = 0
    level: int = 1
    char_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<qiffffBB', self.char_id, self.square_id, self.x, self.y, self.z,
                            self.angle, self.char_class & 0xFF, self.level & 0xFF)
                + wide_string(self.char_name))

    @classmethod
    def decode(cls, data: bytes) -> 'UserJoinSquareNot':
        data = strip_prefix(data)
        if len(data) >= 8:
            char_id = struct.unpack_from('<q', data, 0)[0]
            square_id = struct.unpack_from('<i', data, 8)[0] if len(data) >= 12 else 1
            x = y = z = angle = 0.0
            if len(data) >= 28:
                x, y, z, angle = struct.unpack_from('<ffff', data, 12)
            char_class = 0
            level = 1
            if len(data) >= 30:
                char_class, level = struct.unpack_from('<BB', data, 28)
            char_name = ''
            if len(data) > 30:
                try:
                    length, offset = read_varuint(data, 30)
                    char_name = data[offset:offset + length].decode('utf-16le', errors='replace')
                except Exception:
                    pass
            return cls(char_id=char_id, square_id=square_id, x=x, y=y, z=z, angle=angle,
                       char_class=char_class, level=level, char_name=char_name)
        return cls()


@dataclass
class UserLeaveSquareNot:
    """Opcode 5022: eERC_USER_LEAVE_SQUARE_NOT.

    Broadcast to remaining occupants when a player leaves the square or disconnects.
    """
    char_id: int = 0
    reason: int = 0

    def encode(self) -> bytes:
        return struct.pack('<qi', self.char_id, self.reason)

    @classmethod
    def decode(cls, data: bytes) -> 'UserLeaveSquareNot':
        data = strip_prefix(data)
        if len(data) >= 8:
            char_id = struct.unpack_from('<q', data, 0)[0]
            reason = struct.unpack_from('<i', data, 8)[0] if len(data) >= 12 else 0
            return cls(char_id=char_id, reason=reason)
        return cls()


# =========================================================================
# Party Management Wire Messages (2100-2107, 5049-5051, 5054-5056)
# =========================================================================

@dataclass
class PartyInviteReq:
    """Opcode 2100 / 5049: eEGS_PARTY_INVITE_REQ / eERC_INVITE_REQ.

    Request party invitation to a target player.
    Supports either target UID (i64) or target character name (wstring).
    """
    target_uid: int = 0
    target_name: str = ''

    def encode(self) -> bytes:
        if self.target_uid:
            return struct.pack('<q', self.target_uid)
        return wide_string(self.target_name)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyInviteReq':
        data = strip_prefix(data)
        if len(data) >= 8:
            uid = struct.unpack_from('<q', data, 0)[0]
            if uid != 0:
                return cls(target_uid=uid)
        # Attempt decoding string if present
        if data:
            try:
                length, offset = read_varuint(data, 0)
                name = data[offset:offset + length].decode('utf-16le', errors='replace').rstrip('\x00')
                return cls(target_name=name)
            except Exception:
                pass
        return cls()


@dataclass
class PartyInviteAck:
    """Opcode 2101 / 5050: eEGS_PARTY_INVITE_ACK / eERC_INVITE_ACK (0x00758700).

    Wire format: i32 result (0 = success).
    Optionally appends target UID when available.
    """
    result: int = 0
    target_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyInviteAck':
        data = strip_prefix(data)
        if len(data) >= 4:
            res = struct.unpack_from('<i', data, 0)[0]
            uid = struct.unpack_from('<q', data, 4)[0] if len(data) >= 12 else 0
            return cls(result=res, target_uid=uid)
        return cls()


@dataclass
class PartyInviteNot:
    """Opcode 5051: eERC_INVITE_NOT (0x007706E0).

    The 0x00A4AD10 reader expects a bool, a host summary (0x00A49600),
    then room UID, room name, gate, map and difficulty. This sends a town
    party invitation using the client's constructor defaults for room fields.
    """
    inviter_uid: int = 0
    inviter_name: str = ''
    inviter_square_uid: int = 1

    def encode(self) -> bytes:
        # Unmapped host fields use 0x00473E60 defaults, including the opaque
        # 74-byte block consumed by 0x00A48B40. The summaries are untagged.
        host = (struct.pack('<qqI', self.inviter_square_uid, self.inviter_uid, 0)
                + wide_string(self.inviter_name)
                + struct.pack('<BHBqq', 0, 0xffff, 0, -1, -1) + bytes(74) + b'\x00')
        return (b'\x00' + host + struct.pack('<q', 0) + wide_string('')
                + struct.pack('<IIH', 0xffffffff, 0xffffffff, 0xffff))

    @classmethod
    def decode(cls, data: bytes) -> 'PartyInviteNot':
        reader = JSerBufferReader(data)
        reader.read_bool()
        square_uid = reader.read_i64()
        inviter_uid = reader.read_i64()
        reader.read_u32()
        name = reader.read_wstring()
        reader.read_bytes(4 + 16 + 74 + 1 + 8)
        reader.read_wstring()  # room name
        reader.read_bytes(10)  # gate, map, difficulty
        return cls(inviter_uid=inviter_uid, inviter_name=name, inviter_square_uid=square_uid)


@dataclass
class PartyJoinReq:
    """Opcode 2102: eEGS_PARTY_JOIN_REQ."""
    party_id: int = 0
    host_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<ii', self.party_id, self.host_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyJoinReq':
        data = strip_prefix(data)
        if len(data) >= 8:
            pid, hid = struct.unpack_from('<ii', data, 0)
            return cls(party_id=pid, host_uid=hid)
        elif len(data) >= 4:
            pid = struct.unpack_from('<i', data, 0)[0]
            return cls(party_id=pid)
        return cls()


@dataclass
class PartyJoinAck:
    """Opcode 2103: eEGS_PARTY_JOIN_ACK."""
    result: int = 0
    party_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<ii', self.result, self.party_id)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyJoinAck':
        data = strip_prefix(data)
        if len(data) >= 8:
            res, pid = struct.unpack_from('<ii', data, 0)
            return cls(result=res, party_id=pid)
        elif len(data) >= 4:
            res = struct.unpack_from('<i', data, 0)[0]
            return cls(result=res)
        return cls()


@dataclass
class PartyLeaveReq:
    """Opcode 2104: eEGS_PARTY_LEAVE_REQ."""
    party_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.party_id)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyLeaveReq':
        data = strip_prefix(data)
        if len(data) >= 4:
            return cls(party_id=struct.unpack_from('<i', data, 0)[0])
        return cls()


@dataclass
class PartyLeaveAck:
    """Opcode 2105: eEGS_PARTY_LEAVE_ACK."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyLeaveAck':
        data = strip_prefix(data)
        if len(data) >= 4:
            return cls(result=struct.unpack_from('<i', data, 0)[0])
        return cls()


@dataclass
class PartyKickReq:
    """Opcode 2106: eEGS_PARTY_KICK_REQ."""
    target_uid: int = 0
    party_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<qi', self.target_uid, self.party_id)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyKickReq':
        data = strip_prefix(data)
        if len(data) >= 12:
            tuid, pid = struct.unpack_from('<qi', data, 0)
            return cls(target_uid=tuid, party_id=pid)
        elif len(data) >= 8:
            tuid = struct.unpack_from('<q', data, 0)[0]
            return cls(target_uid=tuid)
        return cls()


@dataclass
class PartyKickAck:
    """Opcode 2107: eEGS_PARTY_KICK_ACK."""
    result: int = 0
    target_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iq', self.result, self.target_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyKickAck':
        data = strip_prefix(data)
        if len(data) >= 12:
            res, tuid = struct.unpack_from('<iq', data, 0)
            return cls(result=res, target_uid=tuid)
        elif len(data) >= 4:
            res = struct.unpack_from('<i', data, 0)[0]
            return cls(result=res)
        return cls()


@dataclass
class PartyAcceptInviteReq:
    """Opcode 5054: eERC_ACCEPT_INVITE_REQ."""
    host_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.host_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyAcceptInviteReq':
        data = strip_prefix(data)
        if len(data) >= 8:
            return cls(host_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class PartyAcceptInviteAck:
    """Opcode 5055: eERC_ACCEPT_INVITE_ACK."""
    result: int = 0
    party_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

    @classmethod
    def decode(cls, data: bytes) -> 'PartyAcceptInviteAck':
        data = strip_prefix(data)
        if len(data) >= 8:
            res, pid = struct.unpack_from('<ii', data, 0)
            return cls(result=res, party_id=pid)
        elif len(data) >= 4:
            return cls(result=struct.unpack_from('<i', data, 0)[0])
        return cls()


@dataclass
class PartyAcceptInviteNot:
    """Opcode 5056: eERC_ACCEPT_INVITE_NOT."""
    party_id: int = 0
    member_uid: int = 0
    member_name: str = ''
    is_leader: bool = False

    def encode(self) -> bytes:
        return (struct.pack('<iq?', self.party_id, self.member_uid, self.is_leader)
                + wide_string(self.member_name))

    @classmethod
    def decode(cls, data: bytes) -> 'PartyAcceptInviteNot':
        data = strip_prefix(data)
        if len(data) >= 13:
            pid, muid, is_lead = struct.unpack_from('<iq?', data, 0)
            name = ''
            if len(data) > 13:
                try:
                    length, offset = read_varuint(data, 13)
                    name = data[offset:offset + length].decode('utf-16le', errors='replace')
                except Exception:
                    pass
            return cls(party_id=pid, member_uid=muid, is_leader=is_lead, member_name=name)
        return cls()


@dataclass
class PartyMemberInfo:
    """Party member state structure."""
    char_id: int = 0
    char_name: str = ''
    char_class: int = 0
    level: int = 1
    hp: int = 1000
    max_hp: int = 1000
    is_leader: bool = False

    def encode(self) -> bytes:
        return (struct.pack('<qBBiII?', self.char_id, self.char_class & 0xFF, self.level & 0xFF,
                            0, self.hp, self.max_hp, self.is_leader)
                + wide_string(self.char_name))


@dataclass
class PartyInfoNot:
    """Full party roster notification sent to all members upon changes."""
    party_id: int = 0
    leader_uid: int = 0
    members: List[PartyMemberInfo] = field(default_factory=list)

    def encode(self) -> bytes:
        body = struct.pack('<iq', self.party_id, self.leader_uid) + b'\x10' + varuint(len(self.members))
        for m in self.members:
            body += m.encode()
        return body
