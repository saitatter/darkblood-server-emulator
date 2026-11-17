"""Dark Blood protocol wire messages - Social domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item
from darkblood.games.network.messages.mail import (
    PostEntry, PostListReq, PostListAck, PostSendReq, PostSendAck,
    PostReadReq, PostReadAck, PostGetAppendItemReq, PostGetAppendItemAck,
    PostDeleteReq, PostDeleteAck, PostNewArrivalNot, PostReturnReq, PostReturnAck
)

@dataclass
class FriendEntry:
    """Friend struct, reader 0x00A49450 (2140 and the 2132 map).

    +0x00 i64 char uid, +0x08 wstring name, +0x24 u8, +0x25 u8 (sent as
    level, class like the lobby entry; not confirmed), +0x26 i64 location:
    the friend list (0x00926800) counts a friend online when it is not -1,
    +0x2E wstring (sent empty), +0x4A i64 (0), +0x52 bool (sent 1).
    """
    uid: int = 0
    name: str = ''
    level: int = 1
    char_class: int = 0
    online: bool = False

    def encode(self) -> bytes:
        return (struct.pack('<q', self.uid) + wide_string(self.name)
                + struct.pack('<BBq', self.level & 0xFF, self.char_class & 0xFF, 1 if self.online else -1)
                + wide_string('') + struct.pack('<q?', 0, True))


@dataclass
class FriendListAck:
    """Opcode 2132: eEGS_FRIEND_LIST_REQUEST_ACK response.

    Binary schema: Reader 0x007712E0.
    u32 result (0 = success) + tag 0x17 map (0x76AE20): entries tag 0x0F,
    i64 uid (key, 0x0074D520), FriendEntry.
    """
    result: int = 0
    friends: list = field(default_factory=list)  # [FriendEntry]

    def encode(self) -> bytes:
        body = struct.pack('<I', self.result) + b'\x17' + varuint(len(self.friends))
        for f in self.friends:
            body += b'\x0f' + struct.pack('<q', f.uid) + f.encode()
        return body

@dataclass
class FriendListAddReq:
    """Opcode 2139: eEGS_FRIEND_LIST_ADD_REQ (0x00790000.c:1595).

    Observed live: ffffff7f + J-wstring character name ("Mage1").
    """
    char_name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'FriendListAddReq':
        from darkblood.core.serialization.jser import WireError, strip_prefix
        data = strip_prefix(data)
        try:
            length, offset = read_varuint(data, 0)
            return cls(char_name=data[offset:offset + length].decode('utf-16le', errors='replace'))
        except WireError:
            return cls()

@dataclass
class FriendListAddAck:
    """Opcode 2140: eEGS_FRIEND_LIST_ADD_ACK (On_eEGS_FRIEND_LIST_ADD_ACK 0x007591A0).

    i32 result (0xCE: not found, shown via 0x00AB29C0; 0x1A5 another
    error), then on success the FriendEntry (tag 0x1E implicit), which the
    client adds to its list (0x00926800).
    """
    result: int = 0xCE
    friend: 'FriendEntry' = None

    def encode(self) -> bytes:
        if self.result != 0 or self.friend is None:
            return struct.pack('<i', self.result or 0xCE)
        return struct.pack('<i', 0) + self.friend.encode()

@dataclass
class FriendListDeleteReq:
    """Opcode 2135: eEGS_FRIEND_LIST_DELETE_REQ (0x00790000.c:1824).

    Wire format: i64 char_uid (8 bytes).
    """
    char_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'FriendListDeleteReq':
        from darkblood.core.serialization.jser import strip_prefix
        data = strip_prefix(data)  # requests usually carry the 0x7FFFFFFF prefix
        if len(data) >= 8:
            return cls(char_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class FriendListDeleteAck:
    """Opcode 2136: eEGS_FRIEND_LIST_DELETE_ACK (On_eEGS_FRIEND_LIST_DELETE_ACK 0x00759560).

    Wire format: i32 result + i64 char_uid.
    """
    result: int = 0
    char_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iq', self.result, self.char_uid)

@dataclass
class FriendListUpdateReq:
    """Opcode 2133: eEGS_FRIEND_LIST_UPDATE_REQ (0x00790000.c:1735).

    Wire format: i64 friend_char_uid + wide string comment.
    """
    char_uid: int = 0
    comment: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'FriendListUpdateReq':
        if len(data) < 8:
            return cls()
        uid = struct.unpack_from('<q', data, 0)[0]
        comment = data[8:].decode('utf-16le', errors='replace').rstrip('\x00')
        return cls(char_uid=uid, comment=comment)

@dataclass
class FriendListUpdateAck:
    """Opcode 2134: eEGS_FRIEND_LIST_UPDATE_ACK (On_eEGS_FRIEND_LIST_UPDATE_ACK 0x00752E80).

    Wire format: i32 result + i64 friend_char_uid + wide string comment.
    """
    result: int = 0
    char_uid: int = 0
    comment: str = ''

    def encode(self) -> bytes:
        raw_comment = self.comment.encode('utf-16le') + b'\x00\x00'
        return struct.pack('<iq', self.result, self.char_uid) + raw_comment

@dataclass
class FriendMyConnectionNot:
    """Opcode 5118: eERC_FRIEND_MY_CONNECTION_NOT (0x0077A8A0)."""
    char_uid: int = 0
    is_online: bool = True
    param1: int = 0
    param2: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q?qq', self.char_uid, self.is_online, self.param1, self.param2)

@dataclass
class FriendMyDisconnectionNot:
    """Opcode 5119: eERC_FRIEND_MY_DISCONNECTION_NOT (0x00758FA0)."""
    char_uid: int = 0
    notify: bool = True

    def encode(self) -> bytes:
        return struct.pack('<q?', self.char_uid, self.notify)

@dataclass
class PartyInviteReq:
    """Opcode 5049: eERC_INVITE_REQ."""
    target_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PartyInviteReq':
        if len(data) >= 8:
            return cls(target_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class PartyInviteAck:
    """Opcode 5050: eERC_INVITE_ACK (0x00758700)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class PartyAcceptInviteReq:
    """Opcode 5054: eERC_ACCEPT_INVITE_REQ."""
    host_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PartyAcceptInviteReq':
        if len(data) >= 8:
            return cls(host_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class PartyAcceptInviteAck:
    """Opcode 5055: eERC_ACCEPT_INVITE_ACK."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class ChangeTeamReq:
    """Opcode 5015: eERC_CHANGE_TEAM_REQ."""
    team_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ChangeTeamReq':
        if len(data) >= 4:
            return cls(team_id=struct.unpack_from('<i', data, 0)[0])
        return cls()

@dataclass
class ChangeTeamAck:
    """Opcode 5016: eERC_CHANGE_TEAM_ACK."""
    result: int = 0
    team_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<ii', self.result, self.team_id)


# --- Chat & In-Game Communication (5040 - 5041) ---

@dataclass
class ChatReq:
    """Opcode 5040: eERC_CHAT_REQ (0x007AC5E0)."""
    channel: int = 0
    sender: str = ''
    target: str = ''
    message: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'ChatReq':
        if not data:
            return cls()
        offset = 0
        if data[0] == 0x1E:
            offset = 1
        ch = data[offset] if offset < len(data) else 0
        offset += 1

        def get_wstr(buf, off):
            if off >= len(buf):
                return '', off
            try:
                length, noff = read_varuint(buf, off)
                val = buf[noff:noff + length].decode('utf-16le', errors='ignore')
                return val, noff + length
            except Exception:
                return '', off

        sender, offset = get_wstr(data, offset)
        target, offset = get_wstr(data, offset)
        message, offset = get_wstr(data, offset)

        if not message:
            raw = data[1:]
            if len(raw) % 2 != 0:
                raw = raw[:-1]
            try:
                text = raw.decode('utf-16le', errors='ignore').strip('\x00')
                if text:
                    message = text
            except Exception:
                pass
        return cls(channel=ch, sender=sender, target=target, message=message)

@dataclass
class ChatAck:
    """Opcode 5041: eERC_CHAT_ACK (0x007AC890)."""
    result: int = 0
    channel: int = 0
    sender: str = 'System'
    target: str = ''
    message: str = ''

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        data = (struct.pack('<iB', 0, self.channel)
                + wide_string(self.sender)
                + wide_string(self.target)
                + wide_string(self.message)
                + b'\x0a\x00\x10\x80\x10\x80'
                + struct.pack('<iqqqi', 0, 0, 0, 0, 0))
        return data


# --- Quest Giveup & Fail Opcodes (2078 - 2081) ---

# --- Trade Opcodes (5069 - 5085) ---


# =========================================================================
# Combat, AP, Penalties & Random Box (2085, 2109, 2196)
# =========================================================================

@dataclass
class UseSpeakerItemReq:
    """Opcode 2128: eEGS_USE_SPEAKER_ITEM_REQ (0x00790000.c:1992).

    Wire format: i64 speaker_uid + wide string message + i64 target_uid.
    """
    speaker_uid: int = 0
    message: str = ''
    target_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'UseSpeakerItemReq':
        if len(data) < 16:
            return cls()
        speaker_uid = struct.unpack_from('<q', data, 0)[0]
        # target_uid is the last 8 bytes
        target_uid = struct.unpack_from('<q', data, len(data) - 8)[0]
        raw_msg = data[8:len(data) - 8]
        message = raw_msg.decode('utf-16le', errors='replace').rstrip('\x00')
        return cls(speaker_uid=speaker_uid, message=message, target_uid=target_uid)

@dataclass
class UseSpeakerItemAck:
    """Opcode 2129: eEGS_USE_SPEAKER_ITEM_ACK (On_eEGS_USE_SPEAKER_ITEM_ACK 0x0077F320).

    Wire format: i32 result + i64 speaker_uid + tag 0x10 vector (updated item).
    """
    result: int = 0
    speaker_uid: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iq', self.result, self.speaker_uid) + b'\x10\x80'

@dataclass
class ContractUpdateReq:
    """Opcode 2121: eEGS_CONTRACT_UPDATE_REQ.

    Wire format: i32 nContractID.
    """
    contract_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ContractUpdateReq':
        if len(data) >= 4:
            return cls(contract_id=struct.unpack_from('<i', data, 0)[0])
        return cls()

@dataclass
class ContractUpdateAck:
    """Opcode 2122: eEGS_CONTRACT_UPDATE_ACK (On_eEGS_CONTRACT_UPDATE_ACK 0x00752D80).

    Wire format: i32 result + i32 nContractID.
    """
    result: int = 0
    contract_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<ii', self.result, self.contract_id)

@dataclass
class RequestCharInfoReq:
    """Opcode 6011: eERT_REQUEST_CHAR_INFO_REQ."""
    char_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RequestCharInfoReq':
        if len(data) >= 8:
            return cls(char_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class RequestCharInfoAck:
    """Opcode 6012: eERT_REQUEST_CHAR_INFO_ACK (0x00790FA0)."""
    result: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # result (u32) + bool(0) + Tag 0x1E summary struct + Tag 0x10 equipment + Tag 0x10 avatar
        summary_dummy = b'\x00' * 32
        return (struct.pack('<i', self.result)
                + b'\x0a\x00' + summary_dummy + b'\x10\x80\x10\x80')

@dataclass
class RequestItemInfoReq:
    """Opcode 6028: eERT_REQUEST_ITEM_INFO_REQ."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RequestItemInfoReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class RequestItemInfoAck:
    """Opcode 6029: eERT_REQUEST_ITEM_INFO_ACK (0x00766C20)."""
    result: int = 0
    item_uid: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result) + struct.pack('<q', self.item_uid)
        item_dummy = b'\x00' * 16
        return struct.pack('<iq', self.result, self.item_uid) + item_dummy


# =========================================================================
# Item Operations & Stack Splitting (2092, 2111-2112, 2250-2251, 2321-2322)
# =========================================================================

@dataclass
class GetInviteListReq:
    """Opcode 2024: eEGS_GET_INVITELIST_REQ (0x007A0000.c:7840)."""
    raw: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'GetInviteListReq':
        return cls(raw=data)

@dataclass
class GetInviteListAck:
    """Opcode 2025: eEGS_GET_INVITELIST_ACK (0x006A2E10).

    Wire format: i32 result + tag 0x10 vector of UserEntry (empty: b'\\x10\\x80').
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result) + b'\x10' + varuint(0)
