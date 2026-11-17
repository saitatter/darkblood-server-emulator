"""Dark Blood protocol wire messages - Pet, Mount and Taming domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.serialization.jser import WireError, read_varuint, varuint, wide_string


def read_wide(data: bytes, offset: int = 0) -> tuple:
    """Read a length-prefixed UTF-16LE string from binary payload."""
    size, offset = read_varuint(data, offset)
    if size % 2 or offset + size > len(data):
        raise WireError('Bad wide string in pet payload')
    return data[offset:offset + size].decode('utf-16le'), offset + size


# --- Taming Monster Messages ---

@dataclass
class TameingMonsterInsertReq:
    """Opcode 2348: eEGS_TAMEING_MONSTER_INSERT_REQ (0x00799BA0)."""
    monster_id: int = 0
    slot: int = 0
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'TameingMonsterInsertReq':
        if len(data) >= 8 and not data.startswith(b'\x1e'):
            m_id, slot = struct.unpack_from('<ii', data, 0)
            return cls(monster_id=m_id, slot=slot, raw_payload=data)
        return cls(raw_payload=data)

    def encode(self) -> bytes:
        if self.raw_payload:
            return self.raw_payload
        return struct.pack('<ii', self.monster_id, self.slot)


@dataclass
class TamingMonsterInsertAck:
    """Opcode 2349: eEGS_TAMEING_MONSTER_INSERT_ACK response (0x00771A00).

    Binary schema: u32 result (0 = success) + tag 0x10 vector.
    """
    result: int = 0
    monsters: list = field(default_factory=list)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x10' + varuint(len(self.monsters))


@dataclass
class TameingMonsterDeleteReq:
    """Opcode 2350: eEGS_TAMEING_MONSTER_DELETE_REQ (0x00799D30)."""
    monster_id: int = 0
    slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'TameingMonsterDeleteReq':
        if len(data) >= 8:
            return cls(*struct.unpack_from('<ii', data, 0))
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<ii', self.monster_id, self.slot)


@dataclass
class TamingMonsterDeleteAck:
    """Opcode 2351: eEGS_TAMEING_MONSTER_DELETE_ACK response (0x00771BB0).

    Binary schema: u32 result (0 = success) + tag 0x10 vector + i32 deleted_slot.
    """
    result: int = 0
    monsters: list = field(default_factory=list)
    deleted_slot: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<I', self.result)
                + b'\x10' + varuint(len(self.monsters))
                + struct.pack('<i', self.deleted_slot))


# --- Mount / Riding Messages ---

@dataclass
class RidingGetListReq:
    """Opcode 2434: eEGS_RIDING_GET_LIST_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'RidingGetListReq':
        return cls(raw_payload=data)

    def encode(self) -> bytes:
        return self.raw_payload


@dataclass
class RidingGetListAck:
    """Opcode 2435: eEGS_RIDING_GET_LIST_ACK (0x0076C5A0).

    Binary schema: u32 result + tag 0x17 container map of rides.
    """
    result: int = 0
    rides: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return struct.pack('<I', self.result) + b'\x17' + varuint(len(self.rides))


@dataclass
class RidingRideObjectReq:
    """Opcode 2437: eEGS_RIDING_RIDE_OBJECT_REQ (0x0079CE00).

    Binary schema: u32 ride_object_id.
    """
    ride_object_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RidingRideObjectReq':
        if len(data) >= 4:
            return cls(struct.unpack_from('<I', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<I', self.ride_object_id)


@dataclass
class RidingRideObjectAck:
    """Opcode 2438: eEGS_RIDING_RIDE_OBJECT_ACK (0x00753A90).

    Binary schema: u32 result + u32 ride_object_id (if result == 0).
    """
    result: int = 0
    ride_object_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RidingRideObjectAck':
        if len(data) >= 8:
            return cls(*struct.unpack_from('<II', data, 0))
        if len(data) >= 4:
            return cls(struct.unpack_from('<I', data, 0)[0], 0)
        return cls()

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return struct.pack('<II', self.result, self.ride_object_id)


# --- Pet Lifecycle Messages ---

@dataclass
class PetCreateReq:
    """Opcode 2464: eEGS_PET_CREATE_REQ (0x0079E0B0)."""
    pet_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PetCreateReq':
        if len(data) >= 8:
            return cls(struct.unpack_from('<q', data, 0)[0])
        if len(data) >= 4:
            return cls(struct.unpack_from('<i', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.pet_uid)


@dataclass
class PetCreateAck:
    """Opcode 2465: eEGS_PET_CREATE_ACK (0x0079E620).

    Binary schema: u32 result. If 0: tag 0x10 vector + i32 slot + tag 0x1E item.
    """
    result: int = 0
    pets: list = field(default_factory=list)
    slot: int = 0
    pet_item: bytes = b''

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        item_bytes = self.pet_item if self.pet_item else (b'\x00' * 8 + struct.pack('<I', 0) + b'\x00' * 40)
        return (struct.pack('<I', self.result)
                + b'\x10' + varuint(len(self.pets))
                + struct.pack('<i', self.slot)
                + b'\x1e' + item_bytes)


@dataclass
class PetDeleteReq:
    """Opcode 2466: eEGS_PET_DELETE_REQ (0x0079E260)."""
    pet_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PetDeleteReq':
        if len(data) >= 8:
            return cls(struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.pet_uid)


@dataclass
class PetDeleteAck:
    """Opcode 2467: eEGS_PET_DELETE_ACK (0x0079EA50).

    Binary schema: u32 result + i64 pet_uid (if result == 0).
    """
    result: int = 0
    pet_uid: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return struct.pack('<Iq', self.result, self.pet_uid)


@dataclass
class PetSummonReq:
    """Opcode 2468: eEGS_PET_SUMMON_REQ (0x0079E3E0)."""
    pet_slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PetSummonReq':
        if len(data) >= 2:
            return cls(struct.unpack_from('<H', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<H', self.pet_slot) if self.pet_slot else b''


@dataclass
class PetSummonAck:
    """Opcode 2469: eEGS_PET_SUMMON_ACK (0x0079ECF0).

    Binary schema: u32 result + u16 pet_slot (if result == 0).
    """
    result: int = 0
    pet_slot: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return struct.pack('<IH', self.result, self.pet_slot)


@dataclass
class PetReleaseSummonReq:
    """Opcode 2470: eEGS_PET_RELEASE_SUMMON_REQ (0x0079E510)."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'PetReleaseSummonReq':
        return cls(raw_payload=data)

    def encode(self) -> bytes:
        return self.raw_payload


@dataclass
class PetReleaseSummonAck:
    """Opcode 2471: eEGS_PET_RELEASE_SUMMON_ACK (0x0079EEE0).

    Binary schema: u32 result.
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<I', self.result)


@dataclass
class PetSaveReq:
    """Opcode 2473: eEGS_PET_SAVE_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'PetSaveReq':
        return cls(raw_payload=data)

    def encode(self) -> bytes:
        return self.raw_payload


@dataclass
class PetSaveAck:
    """Opcode 2474: eEGS_PET_SAVE_ACK (0x007758B0)."""
    result: int = 0
    value: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return struct.pack('<IH', self.result, self.value)


@dataclass
class PetLoadReq:
    """Opcode 2475: eEGS_PET_LOAD_REQ (0x0079F320)."""
    pet_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PetLoadReq':
        if len(data) >= 8:
            return cls(struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.pet_uid)


@dataclass
class PetLoadAck:
    """Opcode 2476: eEGS_PET_LOAD_ACK (0x0079F560)."""
    result: int = 0
    pet_uid: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return struct.pack('<Iq', self.result, self.pet_uid)


@dataclass
class PetReplaceReq:
    """Opcode 2477: eEGS_PET_REPLACE_REQ."""
    pet_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PetReplaceReq':
        if len(data) >= 8:
            return cls(struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.pet_uid)


@dataclass
class PetReplaceAck:
    """Opcode 2478: eEGS_PET_REPLACE_ACK (0x0079F770)."""
    result: int = 0
    pet_uid: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return struct.pack('<Iq', self.result, self.pet_uid)


@dataclass
class PetEatNormalReq:
    """Opcode 2480: eEGS_PET_EAT_NORMAL_REQ (0x0079FBA0)."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PetEatNormalReq':
        if len(data) >= 8:
            return cls(struct.unpack_from('<q', data, 0)[0])
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.item_uid)


@dataclass
class PetEatNormalAck:
    """Opcode 2481: eEGS_PET_EAT_NORMAL_ACK (0x00781260)."""
    result: int = 0
    pets: list = field(default_factory=list)
    satiety: int = 100
    status: int = 1

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return (struct.pack('<I', self.result)
                + b'\x10' + varuint(len(self.pets))
                + struct.pack('<HB', self.satiety, self.status))


@dataclass
class PetEvolutionReq:
    """Opcode 2484: eEGS_PET_EVOLUTION_REQ (0x0079FE20)."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'PetEvolutionReq':
        return cls(raw_payload=data)

    def encode(self) -> bytes:
        return self.raw_payload


@dataclass
class PetEvolutionAck:
    """Opcode 2485: eEGS_PET_EVOLUTION_ACK (0x0079FEF0)."""
    result: int = 0
    old_pet_uid: int = 0
    new_pet_id: int = 0
    new_pet_uid: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return (struct.pack('<I', self.result)
                + struct.pack('<qI', self.old_pet_uid, self.new_pet_id)
                + b'\x10' + varuint(0)
                + struct.pack('<q', self.new_pet_uid))


@dataclass
class PetNickChangeReq:
    """Opcode 2510: eEGS_PET_NICK_CHANGE_REQ (0x007A16DA)."""
    pet_uid: int = 0
    new_name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'PetNickChangeReq':
        if len(data) >= 8:
            uid = struct.unpack_from('<q', data, 0)[0]
            try:
                name, _ = read_wide(data, 8)
            except Exception:
                name = ''
            return cls(uid, name)
        return cls()

    def encode(self) -> bytes:
        return struct.pack('<q', self.pet_uid) + wide_string(self.new_name)


@dataclass
class PetNickChangeAck:
    """Opcode 2511: eEGS_PET_NICK_CHANGE_AKC (0x00781CD0)."""
    result: int = 0
    pet_uid: int = 0
    new_name: str = ''

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<I', self.result)
        return (struct.pack('<I', self.result)
                + b'\x10' + varuint(0)
                + struct.pack('<q', self.pet_uid)
                + wide_string(self.new_name))


# Aliases for Pet Call & Ride Call
PetCallReq = PetSummonReq
PetCallAck = PetSummonAck
RideCallReq = RidingRideObjectReq
RideCallAck = RidingRideObjectAck
