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


def jhash(text: str) -> int:
    """JHashString key (0x00B3B5A0 -> 0x00B3AD70).

    DJB2 (seed 5381, h = h * 33 + c) over the UTF-16LE bytes of the string,
    each byte sign-extended. DictMap:LoadSquare (0x0098FD00) keys squares this
    way by their ``SquareID`` string from Data/Dict/maplist.lua.
    """
    h = 5381
    for byte in text.encode('utf-16le'):
        h = (h * 33 + (byte - 256 if byte > 127 else byte)) & 0xffffffff
    return h


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
    tutorial_cleared: bool = False

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
            b74=data.get('b74', False),
            tutorial_cleared=data.get('tutorial_cleared', False)
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
            'b74': self.b74,
            'tutorial_cleared': self.tutorial_cleared
        }

    def encode_lobby_entry(self) -> bytes:
        """Serialize for Reader 0x00A4AB30 (Character Select list & creation ack)."""
        body = self.visuals.body_sliders[:5]
        out = varuint(len(body)) + bytes(body)
        out += struct.pack('<QBB', self.id, self.level, int(self.char_class))
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
        # 0x00B35010 consumes only tags 0x0F..0x1A; struct 0x1E is implicit.
        b = bytearray()
        sliders = self.visuals.body_sliders[:5]
        b += varuint(len(sliders)) + bytes(sliders)  # 0xa48dd0
        b += varuint(0)  # 0xa48d50 (u32 array max 2)
        b += wide_string(self.name)
        b += struct.pack('<QQQ', 0, 0, self.id)
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
        b += struct.pack('<Q?HHHHII', layer_net_id(), bool(self.tutorial_cleared),
                         0, 0, 0, 0, 0xffffffff, 0xffffffff)
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


# =====================================================================
# Opcode ACK Responses
# =====================================================================

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
class PostListAck:
    """Opcode 2220: eEGS_POST_REQUEST_LIST_ACK response.

    Binary schema: Reader 0x007AEF70.
    u32 result (0), 2x tag 0x17 map (0x7680E0), u32 unread_count, bool notify.
    """
    result: int = 0
    unread_count: int = 0
    notify: bool = False

    def encode(self) -> bytes:
        return (struct.pack('<I', self.result)
                + b'\x17' + varuint(0)
                + b'\x17' + varuint(0)
                + struct.pack('<I?', self.unread_count, self.notify))


@dataclass
class FriendListAck:
    """Opcode 2132: eEGS_FRIEND_LIST_REQUEST_ACK response.

    Binary schema: Reader 0x007712E0.
    u32 result (0 = success) + tag 0x17 map (0x76AE20).
    """
    result: int = 0
    friends: list = field(default_factory=list)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x17' + varuint(len(self.friends))


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
class ClearTutorialAck:
    """Opcode 2083: eEGS_CLEAR_TUTORIAL_ACK response.

    Binary schema: Reader 0x0077EEB0.
    u32 result (0 = success) + tag 0x10 vector (0x4B9210).
    Transitions the client into Town Scene (Scene 9) via 0x006DBFA0(9).
    """
    result: int = 0
    elements: list = field(default_factory=list)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x10' + varuint(len(self.elements))


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
class QuestStartAck:
    """Opcode 2074: eEGS_QUEST_START_ACK (JAppPageTalkBox, case 0x659F00 -> 0x659790).

    Field names from the handler's read-failure message
    ("iQuestID >> iQuestUID >> jInfo >> vecItem"): u32 result, i32 iQuestID
    (jhash of the quest key, e.g. 'Q0001S01'), i64 iQuestUID, jInfo = 18 raw
    bytes (0x00A48A90; the client initialises it as i32 -1, u16 0xFFFF,
    3 x i32 -1, sent unchanged here), tag 0x10 vecItem (item vector 0x4B9210,
    empty). The quest UID is a local counter.
    """
    result: int = 0
    quest_id: int = 0
    quest_uid: int = 1

    def encode(self) -> bytes:
        qid = self.quest_id - (1 << 32) if self.quest_id >= 1 << 31 else self.quest_id
        info = struct.pack('<iHiii', -1, 0xFFFF, -1, -1, -1)
        return struct.pack('<Iiq', self.result, qid, self.quest_uid) + info + b'\x10' + varuint(0)


@dataclass
class StoreInfoAck:
    """Opcode 2066: eEGS_GET_STORE_INFO_ACK (handler 0x007842C0).

    Draft schema (tools/extract_schemas.py): u32 result, i32, tag 0x10 vector
    of 32-byte structs (0x00A489D0), tag 0x10 vector of item structs
    (0x0077CEB0 -> 0x00A53F50). The i32 is echoed from the request's NPC id
    (assumption); both vectors are empty offline until store contents from
    Data/Dict/storelist.lua are mapped.
    """
    result: int = 0
    npc_id: int = 0

    def encode(self) -> bytes:
        npc = self.npc_id - (1 << 32) if self.npc_id >= 1 << 31 else self.npc_id
        return struct.pack('<Ii', self.result, npc) + b'\x10' + varuint(0) + b'\x10' + varuint(0)


@dataclass
class CurrentCashAck:
    """Opcode 2370: eEGS_BILLING_GET_CURRENT_CASH_ACK (case in 0x004DCCC0 -> 0x004CFDF0).

    u32 result, then an implicit struct 0x00AC82A0 read as 12 raw bytes.
    The split of those bytes (cash amounts?) is not recovered; zeros offline.
    """
    result: int = 0
    raw: bytes = b'\x00' * 12

    def encode(self) -> bytes:
        assert len(self.raw) == 12
        return struct.pack('<I', self.result) + self.raw


@dataclass
class TutorialQuestStartAck:
    """Opcode 2347: eEGS_TUTORIAL_QUEST_START_ACK response.

    Binary schema: Reader 0x006481E0.
    u32 result (0 = success).
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<I', self.result)


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
    u32 result (0 = success) + tag 0x10 vector.
    """
    result: int = 0
    monsters: list = field(default_factory=list)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x10' + varuint(len(self.monsters))


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
class RelayJoinGroupAck:
    """ProudNet Relay RMI 3001: JoinGroupACK.

    Binary schema: Relay PIDL RMI 3001.
    Magic 0x0003 + u16 rmi_id (3001) + u32 group_host_id.
    """
    group_host_id: int = 0x10000

    def encode(self) -> bytes:
        return b'\x00\x03' + struct.pack('<HI', 3001, self.group_host_id)

