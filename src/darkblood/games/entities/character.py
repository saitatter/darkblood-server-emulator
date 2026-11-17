"""Player character entity and its wire encodings (lobby entry, world details)."""
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Tuple
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import varuint, wide_string


# SquareIDs declared by DictMap:LoadSquare in Data/Dict/maplist.lua.
SQUARE_IDS = ('Act1', 'Act2', 'ArenaLobby', 'Act4')


DEFAULT_SQUARE = 'Act1'


DEFAULT_LAYER = 1  # low dword: not validated by CanEnter; local default


def layer_net_id(square: str = DEFAULT_SQUARE, layer: int = DEFAULT_LAYER) -> int:
    """u64 nJoinLayerNetID: high dword = jhash(SquareID), low dword = layer.

    0x006FA540 converts it with 0x00A45380 (returns the high dword) and looks
    it up in DictMap+0x3C through 0x00990030. The meaning of the low dword is
    not recovered; 1 is a local default.
    """
    return (jhash(square) << 32) | (layer & 0xffffffff)


class CharacterClass(IntEnum):
    """Player character classes in Dark Blood Online."""
    WARRIOR = 0
    KNIGHT = 1
    HUNTER = 2
    MAGE = 3
    THIEF = 4
    FIGHTER = 5
    WHUNTER = 6



def delete_seconds_left(delete_time: int) -> int:
    """Seconds until a pending deletion completes (never negative)."""
    import time
    return max(0, int(delete_time) - int(time.time()))

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

    # Low-level fields mapped by offset in client object 0x00A4AB30
    u09: int = 0
    u2e: int = 7
    # +0x37 nJoinLayerNetID: character select resolves its high dword through
    # 0x00990030 (DictMap+0x3C) for "Text_Town"; unknown ids show "default town"
    # (0x00704278).
    join_layer_net_id: int = field(default_factory=layer_net_id)
    sp: int = 0  # skill points: details u32 array +0x51 -> player +0x8C
    s49: Tuple[int, int, int] = (23, 25, 27)
    s53: Tuple[int, int, int] = (29, 31, 33)
    # Lobby +0x5D / +0x5E: pending deletion and seconds left, shown by
    # character select (0x00703EB0) as "Deleted in %s" (UI_1531, RemainTime).
    b5d: bool = False
    u5e: int = 9
    # Lobby +0x3F guild UID (-1 = none) and +0x47 guild grade: the delete
    # check 0x006F1DD0 refuses a guild master (grade 4) with
    # MB_DeleteCharacter_GuildMaster. The old placeholders put every
    # character in guild 19.
    guild_uid: int = -1
    guild_grade: int = 0
    # 2007 details +0x41 EXP and +0x45 gold (player +0x78 / +0x70). Not part
    # of the lobby entry, whose +0x62 / +0x66 are the bonus fields below.
    u62: int = 13
    u66: int = 21
    # Lobby +0x62 f32 rate and +0x66 i64: when +0x66 > 0, character select
    # shows a "bonus" of (rate - 1.0) (0x007045B4). Meaning of the amount
    # (rest EXP?) not recovered; sent as no bonus.
    lobby_bonus_rate: float = 1.0
    lobby_bonus: int = 0
    u6e: int = 15
    b72: bool = False
    b73: bool = False
    blocked: bool = False  # lobby +0x74: "Block Status" (UI_3087)
    tutorial_cleared: bool = False
    # Details +0x59 / +0x5B, copied by 0x0095A150 to player +0x7C / +0x7E:
    # rebirth coins owned and daily rebirth coins already received (the
    # daily-claim sender refuses when either is >= 3).
    rebirth_coins: int = 3
    daily_rebirth_recv: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> 'Character':
        """Instantiate a Character from storage JSON dictionary."""
        visuals = CharacterVisuals(
            face=data.get('face', 0),
            hair=data.get('hair', 0),
            body_sliders=list(data.get('body', [100] * 5)[:5]),
            extra=data.get('extra', 0)
        )
        raw_class = data.get('char_class', 0)
        try:
            char_class = CharacterClass(raw_class)
        except ValueError:
            char_class = raw_class

        return cls(
            id=data.get('id', 1),
            name=data.get('name', 'Tester'),
            char_class=char_class,
            visuals=visuals,
            level=data.get('level', 1),
            u09=data.get('u09', 0),
            u2e=data.get('u2e', 7),
            join_layer_net_id=data.get('join_layer_net_id', layer_net_id()),
            sp=data.get('sp', 0),
            s49=tuple(data.get('s49', (23, 25, 27))),
            s53=tuple(data.get('s53', (29, 31, 33))),
            # +0x5D / +0x5E: pending deletion flag and seconds left
            # (0x006F02E0 sets both from 2015 / clears them on 2247; the
            # list shows +0x5E through the duration formatter 0x0074F1D0
            # as "Deleted in %s"). Stored as an absolute Unix time.
            b5d=bool(data.get('delete_time')),
            u5e=(delete_seconds_left(data['delete_time']) if data.get('delete_time')
                 else data.get('u5e', 9)),
            guild_uid=data.get('guild_uid', -1),
            guild_grade=data.get('guild_grade', 0),
            u62=data.get('u62', 13),
            u66=data.get('u66', 21),
            u6e=data.get('u6e', 15),
            b72=data.get('b72', False),
            b73=data.get('b73', False),
            blocked=data.get('blocked', False),
            tutorial_cleared=data.get('tutorial_cleared', False),
            rebirth_coins=data.get('rebirth_coins', 3),
            daily_rebirth_recv=data.get('daily_rebirth_recv', 0)
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
            'u09': self.u09,
            'u2e': self.u2e,
            'join_layer_net_id': self.join_layer_net_id,
            'sp': self.sp,
            's49': list(self.s49),
            's53': list(self.s53),
            'b5d': self.b5d,
            'u5e': self.u5e,
            'guild_uid': self.guild_uid,
            'guild_grade': self.guild_grade,
            'u62': self.u62,
            'u66': self.u66,
            'u6e': self.u6e,
            'b72': self.b72,
            'b73': self.b73,
            'blocked': self.blocked,
            'tutorial_cleared': self.tutorial_cleared,
            'rebirth_coins': self.rebirth_coins,
            'daily_rebirth_recv': self.daily_rebirth_recv
        }

    def encode_lobby_entry(self) -> bytes:
        """Serialize for Reader 0x00A4AB30 (Character Select list & creation ack)."""
        body = self.visuals.body_sliders[:5]
        out = varuint(len(body)) + bytes(body)
        out += struct.pack('<QBB', self.id, self.level, int(self.char_class))
        out += wide_string(self.name)
        out += struct.pack('<III', self.visuals.face, self.visuals.hair, self.u2e)
        out += struct.pack('<Q', self.join_layer_net_id)
        out += struct.pack('<HII', *self.s49)
        out += struct.pack('<HII', *self.s53)
        out += struct.pack('<?I', bool(self.b5d), self.u5e)
        out += struct.pack('<qH', self.guild_uid, self.guild_grade)
        out += struct.pack('<fqI', self.lobby_bonus_rate, self.lobby_bonus, self.u6e)
        out += struct.pack('<???', bool(self.b72), bool(self.b73), bool(self.blocked))
        return out

    def encode_world_details(self) -> bytes:
        """Serialize for struct Reader 0x00A52630 inside Opcode 2007 (SELECT_CHAR_ACK)."""
        # 0x00B35010 consumes only tags 0x0F..0x1A; struct 0x1E is implicit.
        b = bytearray()
        sliders = self.visuals.body_sliders[:5]
        b += varuint(len(sliders)) + bytes(sliders)  # 0xa48dd0
        # 0xa48d50: u32 array (max 2) at +0x51. 0x0095A150 sets the player's
        # skill points (+0x8C, also written by 2698 via 0x0096B9F0) from
        # element [details +0x18A] (u16, sent 0). Both entries carry SP.
        b += varuint(2) + struct.pack('<II', self.sp, self.sp)
        b += wide_string(self.name)
        # Reader 0x00A52630: i64 +0x1C, i64 +0x24, +0x2C (0x00B356F0).
        # 0x0095A150 copies +0x1C into the player's UID (+0x10), which
        # 0x00946570 returns. It was sent as 0 while every other place used
        # the character id, so owner checks (0x008354D0), user lookups
        # (0x00966470, 0x00938C70: crashes at 0x0055BF71 / 0x00650DB4) and
        # the revive UID disagreed. +0x2C keeps the id it carried before.
        b += struct.pack('<QQQ', self.id, 0, self.id)
        b += struct.pack('<B', int(self.char_class))
        # Face, hair, and cosmetic parameter (Reader 0x00A52630 +0x35, +0x39, +0x3D)
        b += struct.pack('<III', self.visuals.face, self.visuals.hair, self.u2e)
        b += struct.pack('<B', self.level)
        b += struct.pack('<IQI', self.u62, self.u66, self.u6e)
        b += struct.pack('<HHHH', 0, 0, 0, 0)
        # Sub-struct 0xa488f0: untagged 24 bytes
        b += (b'\x00' * 24)
        # Details +0x5F (u64) and +0x9C (bool), copied by 0x0095A150 into the
        # player object at +0xF0 and +0x80 respectively:
        #  * player+0xF0 is nJoinLayerNetID. JAppStateSquarePlay's CanEnter
        #    (vtable slot 0x30, 0x006FA540) rejects -1 and requires the high
        #    dword to be a loaded SquareID hash, otherwise the state change
        #    times out after 5 s (0x006F8343) and the client falls back to the
        #    previous state -- the tutorial restarts after "skip".
        #  * player+0x80 selects the state after selection (0x006F88C0):
        #    0 -> ChangeState(eAS_Tutorial), nonzero -> eAS_SquarePlay.
        #  * +0x59 / +0x5B -> player +0x7C rebirth coins / +0x7E daily coins received.
        b += struct.pack('<Q?HHHHII', layer_net_id(), bool(self.tutorial_cleared),
                         self.rebirth_coins & 0xFFFF, self.daily_rebirth_recv & 0xFFFF,
                         0, 0, 0xffffffff, 0xffffffff)
        b += struct.pack('<f', 0.0)
        b += struct.pack('<QHHHHHHHH', 0, 0, 0, 0, 0, 0, 0, 0, 0)
        # 2 x 0xa49bb0 (untagged u16, u32, u32)
        b += struct.pack('<HII', 0, 0, 0)
        b += struct.pack('<HII', 0, 0, 0)
        # bool + 0xa48b40 (untagged 74 bytes)
        b += struct.pack('<?', False)
        b += (b'\x00' * 74)
        b += struct.pack('<I', 0)
        # 5 x tag 0x10 vectors
        for _ in range(5):
            b += b'\x10' + varuint(0)
        # 0xa48b60: untagged 4 bytes
        b += (b'\x00' * 4)
        b += struct.pack('<H?HH', 0, False, 0, 0)
        # 2 x tag 0x17 maps
        b += b'\x17' + varuint(0)
        b += b'\x17' + varuint(0)
        b += struct.pack('<HQQQQI', 0, 0, 0, 0, 0, 0)
        # tag 0x10 vector
        b += b'\x10' + varuint(0)
        b += struct.pack('<?HH', False, 0, 0)
        b += struct.pack('<f', 0.0)
        # Reader 0xA52630: bool +1C9, u8 +1CA, u16 +1CB, bool +1CD/+1CE.
        b += struct.pack('<?BH??', False, 0, 0, False, False)
        b += wide_string('')
        return bytes(b)
