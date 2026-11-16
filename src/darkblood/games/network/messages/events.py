"""Dark Blood protocol wire messages - Events domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

@dataclass
class RouletteManagerInfoAck:
    """Opcode 2391: eEGS_ROULETTE_MANAGER_INFO_ACK response.

    Binary schema: Reader 0x006CC6B0.
    u32 result (0 = success) + untagged 21 bytes (0xA48B80).
    """
    result: int = 0
    payload: bytes = field(default_factory=lambda: b'\x00' * 21)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + self.payload

@dataclass
class NpcFirstMeetAck:
    """Opcode 2095: eEGS_NPC_FIRST_MEET_ACK response.

    Binary schema: Reader 0x00752B60.
    u32 result (0 = success) + u32 npc_id.
    """
    result: int = 0
    npc_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<II', self.result, self.npc_id)

@dataclass
class TamingMonsterInsertAck:
    """Opcode 2349: eEGS_TAMEING_MONSTER_INSERT_ACK response.

    Binary schema: Reader 0x00771A00.
    u32 result (0 = success) + tag 0x10 vector.
    """
    result: int = 0
    monsters: list = field(default_factory=list)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x10' + varuint(len(self.monsters))

@dataclass
class TamingMonsterDeleteAck:
    """Opcode 2351: eEGS_TAMEING_MONSTER_DELETE_ACK response.

    Binary schema: Reader 0x00771BB0.
    u32 result (0 = success) + tag 0x10 vector + i32 deleted_slot.
    """
    result: int = 0
    monsters: list = field(default_factory=list)
    deleted_slot: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<I', self.result)
                + b'\x10' + varuint(len(self.monsters))
                + struct.pack('<i', self.deleted_slot))

@dataclass
class TameingMonsterInsertReq:
    """Opcode 2348: eEGS_TAMEING_MONSTER_INSERT_REQ (0x00799BCC)."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'TameingMonsterInsertReq':
        return cls(raw_payload=data)

@dataclass
class TameingMonsterDeleteReq:
    """Opcode 2350: eEGS_TAMEING_MONSTER_DELETE_REQ (0x00799D5A)."""
    monster_id: int = 0
    slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'TameingMonsterDeleteReq':
        if len(data) >= 8:
            return cls(*struct.unpack_from('<ii', data, 0))
        return cls()

@dataclass
class RequestTeachingReq:
    """Opcode 5351: eERC_REQUEST_TEACHING_REQ."""
    target_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RequestTeachingReq':
        if len(data) >= 8:
            return cls(target_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class RequestTeachingAck:
    """Opcode 5352: eERC_REQUEST_TEACHING_ACK (0x0075C200)."""
    result: int = 0
    target_uid: int = 0
    target_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<iq', self.result, self.target_uid)
                + wide_string(self.target_name)
                + b'\x00\x00\x01')

@dataclass
class AcceptRequestTeachingReq:
    """Opcode 5353: eERC_ACCEPT_REQUEST_TEACHING_REQ."""
    mentor_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AcceptRequestTeachingReq':
        if len(data) >= 8:
            return cls(mentor_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()

@dataclass
class AcceptRequestTeachingAck:
    """Opcode 5354: eERC_ACCEPT_REQUEST_TEACHING_ACK (0x0075C430)."""
    result: int = 0
    accepted: bool = True
    mentor_uid: int = 0
    mentor_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<i?q', self.result, self.accepted, self.mentor_uid)
                + wide_string(self.mentor_name))

@dataclass
class TeachingGetInfoNot:
    """Opcode 5355: eERC_TEACHING_GET_INFO_NOT (0x007A5890)."""
    info_payload: bytes = b''

    def encode(self) -> bytes:
        return b'\x1e\x00' if not self.info_payload else (b'\x1e' + self.info_payload)


# --- Citadel, Treasure & Gold Goblin Events (5344-5346, 5362-5367) ---

@dataclass
class TreasureStartNot:
    """Opcode 5344: eERC_TREASURE_START_NOT (0x007722F0)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class TreasureEndNot:
    """Opcode 5345: eERC_TREASURE_END_NOT (0x0075BC00)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class CitadelRewardNot:
    """Opcode 5346: eERC_CITADEL_REWARD_NOT (0x007833F0)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x17\x80'
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class GoldGoblinAppearNot:
    """Opcode 5362: eERC_GOLDGOBLIEN_APPEAR_NOT (0x007A6D10)."""
    goblin_id: int = 1

    def encode(self) -> bytes:
        return struct.pack('<i', self.goblin_id) + b'\x10\x80'

@dataclass
class GoldGoblinAttackReq:
    """Opcode 5363: eERC_GOLDGOBLIEN_ATTACK_REQ."""
    goblin_id: int = 1
    damage: int = 100

    @classmethod
    def decode(cls, data: bytes) -> 'GoldGoblinAttackReq':
        if len(data) >= 8:
            return cls(*struct.unpack_from('<ii', data, 0))
        return cls()

@dataclass
class GoldGoblinAttackAck:
    """Opcode 5364: eERC_GOLDGOBLIEN_ATTACK_ACK (0x00784A10)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class GoldGoblinDeadReq:
    """Opcode 5365: eERC_GOLDGOBLIEN_DEAD_REQ."""
    goblin_id: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'GoldGoblinDeadReq':
        if len(data) >= 4:
            return cls(goblin_id=struct.unpack_from('<i', data, 0)[0])
        return cls()

@dataclass
class GoldGoblinDeadAck:
    """Opcode 5366: eERC_GOLDGOBLIEN_DEAD_ACK (0x00784CA0)."""
    result: int = 0
    goblin_id: int = 1
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<iiihh', self.result, self.goblin_id, 0, 0, 0)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))

@dataclass
class GoldGoblinDisappearNot:
    """Opcode 5367: eERC_GOLDGOBLIEN_DISAPPEAR_NOT."""
    goblin_id: int = 1

    def encode(self) -> bytes:
        return struct.pack('<i', self.goblin_id)


# =========================================================================
# Titles & Achievements (2327-2336)
# =========================================================================
