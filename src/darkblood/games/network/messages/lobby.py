"""Dark Blood protocol wire messages - Lobby domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

@dataclass
class GameServer:
    """A game server entry shown in the initial 'Server List' dialog (Opcode 2402/2403).

    Binary schema: Reader 0x00A496B0 (Constructor 0x0074DF70).
    """
    key: int = 1
    name: str = "Offline"
    u16: int = 0
    u64: int = 0
    flag_a: bool = False
    flag_b: bool = False
    flag_c: bool = True

    def encode(self) -> bytes:
        return wide_string(self.name) + struct.pack(
            '<HQ???', self.u16, self.u64, self.flag_a, self.flag_b, self.flag_c
        )

@dataclass
class ChannelSquare:
    """A channel / square entry shown in the 'Channel List' dialog (Opcode 2021/2022).

    Binary schema: Reader 0x00A49700 (u64 square_id, wstring name, u32 a, u32 load, u32 c).
    """
    square_id: int = 1
    name: str = "Channel 1"
    a: int = 0
    load: int = 100  # 100 = "Normal · [Good]" in UI
    c: int = 0

    def encode(self) -> bytes:
        return struct.pack('<Q', self.square_id) + wide_string(self.name) + struct.pack(
            '<III', self.a, self.load, self.c
        )

@dataclass
class SelectCharacterAck:
    """Opcode 2007: eEGS_SELECT_CHAR_ACK response.

    Handler 0x007AA4B0:
      Untagged struct 0x00A40760, starting with u32 result (0 = success)
        Contains nested Character Details (0x00A52630) and 59 container/scalar fields
      Tag 0x10 + Vector 0x004B9210
    """
    result: int = 0
    character: Character = field(default_factory=Character)
    active_quests: list = field(default_factory=list)  # [ActiveQuest]
    bags: list = field(default_factory=list)  # [Bag]
    items: list = field(default_factory=list)  # [Item]

    def encode(self) -> bytes:
        p = bytearray(struct.pack('<I', self.result))
        # Handler calls 0xA1EA20(1): peek result, then reset the body cursor.
        # Reader 0xA40760 rereads that same u32; do not emit a second copy.
        p += varuint(0)  # 0xa3ed30 max 3
        p += varuint(0)  # 0xa1e840 max 10

        # Nested character struct 0x00A52630
        p += self.character.encode_world_details()

        # Fields following character details in 0x00A40760:
        p += struct.pack('<QQQQBB', 0, 0, 0, 0, 0, 0)
        p += b'\x17' + varuint(0)  # 0xa40720
        # 0x558010: bag vector (+0x293), consumed by 0x00837D60 -> 0x00836010.
        p += b'\x10' + varuint(len(self.bags)) + b''.join(bag.encode() for bag in self.bags)
        # 0x4b9830: item vector (+0x2A3), inserted by 0x00835990 after the bags.
        p += b'\x10' + varuint(len(self.items)) + b''.join(item.encode() for item in self.items)
        p += b'\x10' + varuint(0)  # 0x4b2c30
        p += b'\x10' + varuint(0)  # 0xa3eec0
        p += b'\x17' + varuint(0)  # 0x4b1240
        p += b'\x17' + varuint(0)  # 0x76e560
        p += b'\x13' + varuint(0)  # 0x76a8c0
        p += b'\x17' + varuint(0)  # 0xa3e410
        p += struct.pack('<QII', 0, 0, 0)
        # 0xa3e450: active quests (0xA209B0); same map that 2074 fills via 0xA60960.
        p += b'\x17' + varuint(len(self.active_quests))
        for quest in sorted(self.active_quests, key=lambda q: q.uid):
            p += quest.encode_entry()
        p += b'\x13' + varuint(0)  # 0x5ee0f0
        p += (b'\x00' * 18)  # 0x641e00 (untagged 18 bytes)
        p += b'\x13' + varuint(0)  # 0x5ee0f0
        p += struct.pack('<QQQIQ', 0, 0, 0, 0, 0)
        p += struct.pack('<Q', 0)
        p += b'\x10' + varuint(0)  # 0x4b1a60
        p += struct.pack('<Q??', 0, False, False)
        p += struct.pack('<f', 0.0)
        p += struct.pack('<Q', 0)
        p += struct.pack('<Q', 0)
        p += b'\x17' + varuint(0)  # 0x485220
        p += b'\x17' + varuint(0)  # 0x485220
        p += wide_string('')  # 0xb35ab0
        # 0x74c1d0: untagged 2 maps + bool
        p += b'\x17' + varuint(0) + b'\x17' + varuint(0) + struct.pack('<?', False)
        p += b'\x17' + varuint(0)  # 0xa3ea00
        p += struct.pack('<QQI', 0, 0, 0)
        p += b'\x10' + varuint(0)  # 0x4da660
        p += b'\x10' + varuint(0)  # 0x4da660
        p += struct.pack('<HQQ', 0, 0, 0)
        p += b'\x17' + varuint(0)  # 0x5f9190
        p += b'\x17' + varuint(0)  # 0x76aba0
        # 0xa1e8c0: untagged map + u64 + bool + u64
        p += b'\x17' + varuint(0) + struct.pack('<Q?Q', 0, False, 0)
        p += b'\x10' + varuint(0)  # 0xa3edd0
        # 0xa1eea0: untagged u32 + u64 + u64 + u64
        p += struct.pack('<IQQQ', 0, 0, 0, 0)
        # 0xa1e900: untagged map + vector
        p += b'\x17' + varuint(0) + b'\x10' + varuint(0)
        p += struct.pack('<H', 0)
        p += b'\x10' + varuint(0)  # 0x4da660
        p += b'\x17' + varuint(0)  # 0x5f9150
        p += struct.pack('<H', 0)
        p += b'\x17' + varuint(0)  # 0x485220
        # Vector 0x004B9210
        p += b'\x10' + varuint(0)
        return bytes(p)

@dataclass
class JoinSquareAck:
    """Opcode 5029: eERC_JOIN_SQUARE_ACK response.

    Binary schema: Reader 0x00757AD0.
    u32 result (0 = success) + u64 square_id.
    """
    result: int = 0
    square_id: int = 1

    def encode(self) -> bytes:
        return struct.pack('<IQ', self.result, self.square_id)

@dataclass
class RelayAddressNot:
    """Opcode 5134: eERC_SQUARE_CHANGE_RELAY_ADDRESS_NOT notification.

    Binary schema: Reader 0x0075AAE0.
    Implicit 0x1E struct = 6 raw bytes (0xA48910): IPv4 network order + u16 LE port.
    """
    ip: str = "127.0.0.1"
    port: int = 9401

    def encode(self) -> bytes:
        octets = [int(x) for x in self.ip.split('.')]
        return bytes(octets) + struct.pack('<H', self.port)

@dataclass
class BackToSquareAck:
    """Opcode 5046: eERC_BACK_TO_SQUARE_ACK response.

    Handler 0x007897F0; field names from its read-failure message
    ("nJoinSquareUID >> nJoinLayerNetID >> vecTargetState >> bUseWaypoint >> iCurAr").
    u32 result, u64 nJoinSquareUID, u64 nJoinLayerNetID, tag 0x10 vector
    vecTargetState (0x00773870, element layout unknown -> empty), bool
    bUseWaypoint, u64 iCurAr*. Outside SquarePlay the handler validates the
    layer id like CanEnter, stores it at player+0xF0, runs
    ``g_jAppStateMgr:ChangeState(eAS_SquarePlay)`` and reconnects the relay.
    """
    result: int = 0
    square_uid: int = 1
    layer_net_id: int = field(default_factory=layer_net_id)
    use_waypoint: bool = False
    cur_area: int = 0  # meaning not recovered; local default

    def encode(self) -> bytes:
        return (struct.pack('<IQQ', self.result, self.square_uid, self.layer_net_id)
                + b'\x10' + varuint(0)
                + struct.pack('<?Q', self.use_waypoint, self.cur_area))

@dataclass
class RelayJoinGroupAck:
    """ProudNet Relay RMI 3001: JoinGroupACK.

    Binary schema: Relay PIDL RMI 3001.
    Magic 0x0003 + u16 rmi_id (3001) + u32 group_host_id.
    """
    group_host_id: int = 0x10000

    def encode(self) -> bytes:
        return b'\x00\x03' + struct.pack('<HI', 3001, self.group_host_id)

@dataclass
class DeleteCharacterReq:
    """Opcode 2014: eEGS_DELETE_CHARACTER_REQ (0x00780000.c:6618).

    Wire format: i64 nDelCharUID (8 bytes).
    """
    char_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DeleteCharacterReq':
        if len(data) >= 8:
            return cls(char_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class DeleteCharacterAck:
    """Opcode 2015: eEGS_DELETE_CHARACTER_ACK (On_eEGS_DELETE_CHARACTER_ACK 0x00758370).

    Wire format: i32 result + i64 nDelCharUID + i32 nUserDelCompleteTime (0 = instant).
    """
    result: int = 0
    char_uid: int = 0
    complete_time: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqi', self.result, self.char_uid, self.complete_time)

@dataclass
class ArenaBackToSquareReq:
    """Opcode 5165: eERC_ARENA_BACK_TO_SQUARE_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'ArenaBackToSquareReq':
        return cls()

@dataclass
class ArenaBackToSquareAck:
    """Opcode 5166: eERC_ARENA_BACK_TO_SQUARE_ACK (0x00758550)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


# =========================================================================
# Second Password / PIN (5256-5261)
# =========================================================================
