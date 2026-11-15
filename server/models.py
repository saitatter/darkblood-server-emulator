"""High-level domain models and packet serializers for Dark Blood Online.

Provides clean, human-readable Python dataclasses for game entities:
  - GameServer / ServerList (Opcode 2402/2403)
  - Channel / SquareList (Opcode 2021/2022)
  - Character / CharacterList (Opcode 2008/2009, 2012/2013)
  - CharacterDetails / SelectCharacterAck (Opcode 2006/2007)

All binary serializers follow schemas recovered from DarkBlood.exe (SHA-256 a82ae3d7...).
"""
from dataclasses import dataclass, field
from enum import IntEnum
import struct
from typing import List, Optional, Tuple


class CharacterClass(IntEnum):
    """Player character classes in Dark Blood Online."""
    WARRIOR = 0
    KNIGHT = 1
    HUNTER = 2
    MAGE = 3


def varuint(n: int) -> bytes:
    """Encode a non-negative integer using JSerBuffer 7-bit varuint format.

    Bit 7 is set on the terminating byte.
    """
    out = bytearray()
    while True:
        b = n & 127
        n >>= 7
        if n == 0:
            out.append(b | 128)
            return bytes(out)
        out.append(b)


def wide_string(s: str) -> bytes:
    """Encode a string as UTF-16LE prefixed with varuint byte-count."""
    raw = s.encode('utf-16le')
    return varuint(len(raw)) + raw


# =====================================================================
# Server & Channel (Square) Models
# =====================================================================

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


# =====================================================================
# Character Models
# =====================================================================

@dataclass
class CharacterVisuals:
    """Cosmetic and appearance parameters for a character."""
    face: int = 0
    hair: int = 0
    body_sliders: List[int] = field(default_factory=lambda: [100, 100, 100, 100, 100])
    extra: int = 0


@dataclass
class Character:
    """High-level representation of a player character."""
    id: int = 1
    name: str = "Tester"
    char_class: CharacterClass = CharacterClass.WARRIOR
    visuals: CharacterVisuals = field(default_factory=CharacterVisuals)
    level: int = 1
    location: str = "default town"

    # Low-level fields mapped by offset in client object 0x00A4AB30
    u09: int = 0
    u2e: int = 7
    u37: int = 17
    s49: Tuple[int, int, int] = (23, 25, 27)
    s53: Tuple[int, int, int] = (29, 31, 33)
    b5d: bool = False
    u5e: int = 9
    u3f: int = 19
    u47: int = 11
    u62: int = 13
    u66: int = 21
    u6e: int = 15
    b72: bool = False
    b73: bool = False
    b74: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> 'Character':
        """Instantiate a Character from storage JSON dictionary."""
        visuals = CharacterVisuals(
            face=data.get('face', 0),
            hair=data.get('hair', 0),
            body_sliders=list(data.get('body', [100] * 5)[:5]),
            extra=data.get('extra', 0)
        )
        return cls(
            id=data.get('id', 1),
            name=data.get('name', 'Tester'),
            char_class=CharacterClass(data.get('char_class', 0)),
            visuals=visuals,
            level=data.get('level', 1),
            location=data.get('location', 'default town'),
            u09=data.get('u09', 0),
            u2e=data.get('u2e', 7),
            u37=data.get('u37', 17),
            s49=tuple(data.get('s49', (23, 25, 27))),
            s53=tuple(data.get('s53', (29, 31, 33))),
            b5d=data.get('b5d', False),
            u5e=data.get('u5e', 9),
            u3f=data.get('u3f', 19),
            u47=data.get('u47', 11),
            u62=data.get('u62', 13),
            u66=data.get('u66', 21),
            u6e=data.get('u6e', 15),
            b72=data.get('b72', False),
            b73=data.get('b73', False),
            b74=data.get('b74', False)
        )

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary for character storage."""
        return {
            'id': self.id,
            'name': self.name,
            'char_class': int(self.char_class),
            'face': self.visuals.face,
            'hair': self.visuals.hair,
            'body': self.visuals.body_sliders,
            'extra': self.visuals.extra,
            'level': self.level,
            'location': self.location,
            'u09': self.u09,
            'u2e': self.u2e,
            'u37': self.u37,
            's49': list(self.s49),
            's53': list(self.s53),
            'b5d': self.b5d,
            'u5e': self.u5e,
            'u3f': self.u3f,
            'u47': self.u47,
            'u62': self.u62,
            'u66': self.u66,
            'u6e': self.u6e,
            'b72': self.b72,
            'b73': self.b73,
            'b74': self.b74
        }

    def encode_lobby_entry(self) -> bytes:
        """Serialize for Reader 0x00A4AB30 (Character Select list & creation ack)."""
        body = self.visuals.body_sliders[:5]
        out = varuint(len(body)) + bytes(body)
        out += struct.pack('<QBB', self.id, int(self.char_class), self.u09)
        out += wide_string(self.name)
        out += struct.pack('<III', self.visuals.face, self.visuals.hair, self.u2e)
        out += struct.pack('<Q', self.u37)
        out += struct.pack('<HII', *self.s49)
        out += struct.pack('<HII', *self.s53)
        out += struct.pack('<?I', bool(self.b5d), self.u5e)
        out += struct.pack('<QH', self.u3f, self.u47)
        out += struct.pack('<IQI', self.u62, self.u66, self.u6e)
        out += struct.pack('<???', bool(self.b72), bool(self.b73), bool(self.b74))
        return out

    def encode_world_details(self) -> bytes:
        """Serialize for struct Reader 0x00A52630 inside Opcode 2007 (SELECT_CHAR_ACK)."""
        b = bytearray()
        sliders = self.visuals.body_sliders[:5]
        b += varuint(len(sliders)) + bytes(sliders)  # 0xa48dd0
        b += varuint(0)  # 0xa48d50 (u32 array max 2)
        b += wide_string(self.name)
        b += struct.pack('<QQQ', 0, 0, self.id)
        b += struct.pack('<B', int(self.char_class))
        b += struct.pack('<III', 0, 0, 0)
        b += struct.pack('<B', 0)
        b += struct.pack('<IQI', 0, 0, 0)
        b += struct.pack('<HHHH', 0, 0, 0, 0)
        # Sub-struct 0xa488f0: tag 0x1E + 24 bytes
        b += b'\x1e' + (b'\x00' * 24)
        b += struct.pack('<Q?HHHHII', 0, False, 0, 0, 0, 0, 0, 0)
        b += struct.pack('<f', 0.0)
        b += struct.pack('<QHHHHHHHH', 0, 0, 0, 0, 0, 0, 0, 0, 0)
        # 2 x 0xa49bb0 (tag 0x1E + u16, u32, u32)
        b += b'\x1e' + struct.pack('<HII', 0, 0, 0)
        b += b'\x1e' + struct.pack('<HII', 0, 0, 0)
        # bool + 0xa48b40 (tag 0x1E + 74 bytes)
        b += struct.pack('<?', False)
        b += b'\x1e' + (b'\x00' * 74)
        b += struct.pack('<I', 0)
        # 5 x tag 0x10 vectors
        for _ in range(5):
            b += b'\x10' + varuint(0)
        # 0xa48b60: tag 0x1E + 4 bytes
        b += b'\x1e' + (b'\x00' * 4)
        b += struct.pack('<H?HH', 0, False, 0, 0)
        # 2 x tag 0x17 maps
        b += b'\x17' + varuint(0)
        b += b'\x17' + varuint(0)
        b += struct.pack('<HQQQQI', 0, 0, 0, 0, 0, 0)
        # tag 0x10 vector
        b += b'\x10' + varuint(0)
        b += struct.pack('<?HH', False, 0, 0)
        b += struct.pack('<f', 0.0)
        b += struct.pack('<?H??', False, 0, False, False)
        b += wide_string('')
        return bytes(b)


# =====================================================================
# Opcode ACK Responses
# =====================================================================

@dataclass
class SelectCharacterAck:
    """Opcode 2007: eEGS_SELECT_CHAR_ACK response.

    Handler 0x007AA4B0:
      u32 result (0 = success)
      Tag 0x1E + Struct 0x00A40760 (Player World Record)
        Contains nested Character Details (0x00A52630) and 59 container/scalar fields
      Tag 0x10 + Vector 0x004B9210
    """
    result: int = 0
    character: Character = field(default_factory=Character)

    def encode(self) -> bytes:
        p = bytearray(struct.pack('<I', self.result))
        p += b'\x1e'  # struct 0x00A40760
        p += struct.pack('<I', 0)  # field 0
        p += varuint(0)  # 0xa3ed30 max 3
        p += varuint(0)  # 0xa1e840 max 10

        # Nested character struct 0x00A52630
        p += b'\x1e' + self.character.encode_world_details()

        # Fields following character details in 0x00A40760:
        p += struct.pack('<QQQQBB', 0, 0, 0, 0, 0, 0)
        p += b'\x17' + varuint(0)  # 0xa40720
        p += b'\x10' + varuint(0)  # 0x558010
        p += b'\x10' + varuint(0)  # 0x4b9830
        p += b'\x10' + varuint(0)  # 0x4b2c30
        p += b'\x10' + varuint(0)  # 0xa3eec0
        p += b'\x17' + varuint(0)  # 0x4b1240
        p += b'\x17' + varuint(0)  # 0x76e560
        p += b'\x13' + varuint(0)  # 0x76a8c0
        p += b'\x17' + varuint(0)  # 0xa3e410
        p += struct.pack('<QII', 0, 0, 0)
        p += b'\x17' + varuint(0)  # 0xa3e450
        p += b'\x13' + varuint(0)  # 0x5ee0f0
        p += b'\x1e' + (b'\x00' * 18)  # 0x641e00 (tag 0x1E + 18 bytes)
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
        # 0x74c1d0: tag 0x1E + 2 maps + bool
        p += b'\x1e' + b'\x17' + varuint(0) + b'\x17' + varuint(0) + struct.pack('<?', False)
        p += b'\x17' + varuint(0)  # 0xa3ea00
        p += struct.pack('<QQI', 0, 0, 0)
        p += b'\x10' + varuint(0)  # 0x4da660
        p += b'\x10' + varuint(0)  # 0x4da660
        p += struct.pack('<HQQ', 0, 0, 0)
        p += b'\x17' + varuint(0)  # 0x5f9190
        p += b'\x17' + varuint(0)  # 0x76aba0
        # 0xa1e8c0: tag 0x1E + map + u64 + bool + u64
        p += b'\x1e' + b'\x17' + varuint(0) + struct.pack('<Q?Q', 0, False, 0)
        p += b'\x10' + varuint(0)  # 0xa3edd0
        # 0xa1eea0: tag 0x1E + u32 + u64 + u64 + u64
        p += b'\x1e' + struct.pack('<IQQQ', 0, 0, 0, 0)
        # 0xa1e900: tag 0x1E + map + vector
        p += b'\x1e' + b'\x17' + varuint(0) + b'\x10' + varuint(0)
        p += struct.pack('<H', 0)
        p += b'\x10' + varuint(0)  # 0x4da660
        p += b'\x17' + varuint(0)  # 0x5f9150
        p += struct.pack('<H', 0)
        p += b'\x17' + varuint(0)  # 0x485220
        # Vector 0x004B9210
        p += b'\x10' + varuint(0)
        return bytes(p)
