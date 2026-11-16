"""Server -> client game messages (JEvent bodies), one dataclass per opcode.

All serializers follow schemas recovered from DarkBlood.exe (SHA-256 a82ae3d7...)."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id


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
class RoomInfoListAck:
    """Opcode 2011: eEGS_GET_ROOMINFOLIST_ACK (JUserClient handler 0x0077A1F0).

    Field names from the read-failure messages: u32 nOK, bool
    m_bShowOnlyWaitRoom, i32 m_iViewRoomPage, tag 0x10 m_vecRoomList (0x46-byte
    elements, reader 0x00778F50), i32 m_iN* (probably the page count).
    Offline: no open rooms.
    """
    result: int = 0
    show_only_wait: bool = False
    page: int = 0
    pages: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<I?i', self.result, self.show_only_wait, self.page)
                + b'\x10' + varuint(0) + struct.pack('<i', self.pages))


@dataclass
class CreateRoomAck:
    """Opcode 5002: eERC_CREATE_ROOM_ACK (JAppPageGameRoom, table case 0x59D970 -> 0x5984D0).

    Read order (names from "jRoomInfo >> nTeamID >> jRelayAddress"): u32 nOK,
    implicit jRoomInfo (0x00A49380: i64, wstring, i16, i16, i32, i64, i64,
    i32, i32, i16), u32 nTeamID, implicit jRelayAddress (0x00A48910, 6 bytes:
    IPv4 network order + u16 LE port, as in 5134). The handler then connects
    JP2PClient (0x00956C80) to the relay address. jRoomInfo field meanings are
    not recovered: room id first, the requested name second, the rest echo the
    5001 request (i32, i32, i16, i16) or default to -1 / 0.
    """
    result: int = 0
    room_id: int = 1
    name: str = ''
    req_a: int = -1
    req_b: int = -1
    req_c: int = -1
    req_d: int = 1
    host_uid: int = 0
    team_id: int = 0
    relay_port: int = 9401

    def encode(self) -> bytes:
        info = (struct.pack('<q', self.room_id) + wide_string(self.name)
                + struct.pack('<hhiqqiih', self.req_c, self.req_d, self.req_a,
                              self.host_uid, 0, self.req_b, -1, self.req_d))
        relay = bytes([127, 0, 0, 1]) + struct.pack('<H', self.relay_port)
        return struct.pack('<I', self.result) + info + struct.pack('<I', self.team_id) + relay


@dataclass
class SelectDungeonAck:
    """Opcode 5044: eERC_SELECT_DUNGEON_ACK (JUserClient handler 0x007702E0).

    Read order: u32 result (0x94 is a special failure stored on app page 9),
    tag 0x17 map (0x0076AD10), tag 0x13 set (0x00765450), untagged J-wstring
    (0x00B35AB0), tag 0x13 set (0x005EAB90: varint, i32 elements). On success
    the wstring goes to JAppStateDungeonGate 0x006B2C00, which looks it up as
    the gate property id (failure logs "Invalidation in m_pjGateProp"), so it
    echoes the 5043 request ("Act1_G1"). The map and both sets feed
    0x006BCD20 (SetDunHist); their element meanings are not recovered and
    are sent empty. The handler then changes app state to the dungeon gate.
    """
    result: int = 0
    gate_id: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<I', self.result) + b'\x17' + varuint(0) + b'\x13' + varuint(0)
                + wide_string(self.gate_id) + b'\x13' + varuint(0))


@dataclass
class ChangeMapCodeAck:
    """Opcode 5010: eERC_CHANGE_MAPCODE_ACK (JAppStateDungeonGate vf20 -> 0x006D4A00).

    Read order: u32 result (0x00B35300), untagged J-wstring map code
    (0x00B35AB0), bool (0x00B35680). The map code is looked up as a map
    property (failure: "Invalidation in pjProp") and joined to
    "Data/Map/MyWork/". The bool's meaning is not recovered; it echoes the
    trailing byte of the 5009 request.
    """
    result: int = 0
    map_code: str = ''
    flag: bool = False

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + wide_string(self.map_code) + struct.pack('<?', self.flag)


@dataclass
class QuestHistoryNot:
    """Opcode 2410: eEGS_QUEST_HISTORY_REFRESH_NOT (handler 0x0076C1E0).

    Names from the read-failure message ("setQuestHistory >> bWeekly"): tag
    0x13 set of i32 quest ids (jhash of 'Q....S..'), bool bWeekly.
    """
    quest_ids: list = field(default_factory=list)
    weekly: bool = False

    def encode(self) -> bytes:
        body = b'\x13' + varuint(len(self.quest_ids))
        for q in sorted(self.quest_ids):
            body += struct.pack('<i', q - (1 << 32) if q >= 1 << 31 else q)
        return body + struct.pack('<?', self.weekly)


@dataclass
class QuestCompleteAck:
    """Opcode 2077: eEGS_QUEST_COMPLETE_ACK (JAppPageTalkBox, case 0x659F00 -> 0x656870).

    u32 result, then implicit struct jAck (reader 0x00A55B70), consumed by
    0x00656870 (local offsets confirmed against the reader):
      +0x00 i32 quest id (0x00A7B390 lookup)
      +0x04 i32 index passed to 0x00A88560 (-1 skips its table; 0 observed safe)
      +0x08 jInfo 18 raw bytes; first i32 1/2 selects extra actions (2 =
            class change, "GAME_241"); -1 = none
      +0x1A i32 (not read by the consumer)
      +0x1E i64 new gold total: diff with player +0x70 (= 2007 details +0x45,
            Character.u66) is announced ("GAME_783"), then stored
      +0x26 tag 0x10 item vector (0x004B94C0) -> inventory insert 0x007741D0
      +0x36 tag 0x17 map (0x004B0310), meaning unknown
      +0x42 i32 shown as floating number type 0xC when the quest's reward
            field (+0x19C of the quest prop) is positive: reward EXP
      +0x46 i32 floating number type 0xE when positive: reward GP
    The consumer never writes the player's EXP; the server persists it and
    the client sees it at the next selection.
    """
    result: int = 0
    quest_id: int = 0
    total: int = 0
    exp: int = 0
    gp: int = 0
    items: list = field(default_factory=list)  # [Item]

    def encode(self) -> bytes:
        qid = self.quest_id - (1 << 32) if self.quest_id >= 1 << 31 else self.quest_id
        info = struct.pack('<iHiii', -1, 0xFFFF, -1, -1, -1)
        return (struct.pack('<Iii', self.result, qid, 0) + info + struct.pack('<iq', 0, self.total)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + b'\x17' + varuint(0)
                + struct.pack('<ii', self.exp, self.gp))


@dataclass
class StoreInfoAck:
    """Opcode 2066: eEGS_GET_STORE_INFO_ACK (handler 0x007842C0).

    Draft schema (tools/extract_schemas.py): u32 result, i32 (stored at
    store window +0xCC; NPC id echoed, assumption), tag 0x10 vector of 32-byte
    records (0x00A489D0) and tag 0x10 vector of item structs (0x0077CEB0 ->
    0x00A53F50, sent empty). Store open 0x005953D0 passes the first u32 of
    each 32-byte record to 0x009E5870, an item-dict lookup returning the item
    tab, so a record starts with jhash(item id). The other 28 bytes are not
    recovered: i32 stock (-1 = unlimited, as in storelist.lua) + zeros.
    """
    result: int = 0
    npc_id: int = 0
    items: list = field(default_factory=list)  # [(item id string, count)]

    def encode(self) -> bytes:
        npc = self.npc_id - (1 << 32) if self.npc_id >= 1 << 31 else self.npc_id
        body = struct.pack('<Ii', self.result, npc) + b'\x10' + varuint(len(self.items))
        for item, count in self.items:
            body += struct.pack('<Ii', jhash(item), count) + b'\x00' * 24
        return body + b'\x10' + varuint(0)


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


@dataclass
class ChangeDungeonLayerNot:
    """Opcode 5095: eERC_CHANGE_DUNGEON_LAYER_NOT (JAppStateGamePlay::Initialize -> 0x007900B0).

    Sent by the client when entering a dungeon layer (e.g. Layer 4 of Lucid Forest).
    Wire format: i32 prefix (0x7FFFFFFF) + i64 layer_net_id.
    layer_net_id is (jhash(map_code) << 32) | layer_id.
    """
    prefix: int = 0x7FFFFFFF
    layer_net_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ChangeDungeonLayerNot':
        prefix, layer_net_id = struct.unpack_from('<iq', data, 0)
        return cls(prefix=prefix, layer_net_id=layer_net_id)

    @property
    def layer_id(self) -> int:
        return self.layer_net_id & 0xFFFFFFFF

    @property
    def map_hash(self) -> int:
        return (self.layer_net_id >> 32) & 0xFFFFFFFF


@dataclass
class ActiveWarFlagReq:
    """Opcode 2422: eEGS_ACTIVE_WARFLAG_REQ (0x0087D170 -> 0x0079C300).

    Sent by the client with the active war flag ID.
    Wire format: i32 prefix (0x7FFFFFFF) + u32 war_flag_id.
    """
    prefix: int = 0x7FFFFFFF
    war_flag_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ActiveWarFlagReq':
        prefix, war_flag_id = struct.unpack_from('<iI', data, 0)
        return cls(prefix=prefix, war_flag_id=war_flag_id)


@dataclass
class GuideBeginnerUpdateReq:
    """Opcode 2358: eEGS_GUIDE_BEGINNER_UPDATE_REQ (0x0079A3B0).

    Sent by the client to update completed/viewed beginner guide IDs.
    Wire format: i32 prefix (0x7FFFFFFF) + vector (tag 0x10) of u32 guide IDs.
    """
    prefix: int = 0x7FFFFFFF
    guide_ids: list = field(default_factory=list)

    @classmethod
    def decode(cls, data: bytes) -> 'GuideBeginnerUpdateReq':
        if len(data) < 4:
            return cls()
        prefix = struct.unpack_from('<i', data, 0)[0]
        offset = 4
        guide_ids = []
        if offset < len(data) and data[offset] == 0x10:
            offset += 1
            count, offset = read_varuint(data, offset)
            for _ in range(count):
                if offset + 4 <= len(data):
                    guide_ids.append(struct.unpack_from('<I', data, offset)[0])
                    offset += 4
        return cls(prefix=prefix, guide_ids=guide_ids)


@dataclass
class MonsterDeadReq:
    """Opcode 5063: eERC_MONSTER_DEAD_REQ (JUserClient::MonsterDeadREQ 0x0078A690).

    Sent by the client when a monster is killed in gameplay.
    Wire format: i32 prefix (0x7FFFFFFF) + u32 monster_id + u32 param.
    """
    prefix: int = 0x7FFFFFFF
    monster_id: int = 0
    param: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'MonsterDeadReq':
        prefix, monster_id, param = struct.unpack_from('<iII', data, 0)
        return cls(prefix=prefix, monster_id=monster_id, param=param)


@dataclass
class ItemDropEntry:
    """A dropped item entity on the dungeon floor (client struct 0x00A509E0, 26 bytes)."""
    drop_uid: int
    item_id: int
    count: int = 1
    drop_type: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    flags: int = 0

    def encode(self) -> bytes:
        return (b'\x1e' + struct.pack('<IIHH', self.drop_uid, self.item_id, self.count, self.drop_type)
                + b'\x13' + struct.pack('<fffH', self.x, self.y, self.z, self.flags))


@dataclass
class DropItemNot:
    """Opcode 5064: eERC_DROP_ITEM_NOT (JUserClient::On_eERC_DROP_ITEM_NOT 0x0078A870).

    Notifies the client of items dropped in the world (e.g. from monster defeat).
    Wire format: u32 source_id + vector (tag 0x10) of 26-byte ItemDropEntry structs.
    """
    source_id: int = 0
    drops: list = field(default_factory=list)

    def encode(self) -> bytes:
        header = struct.pack('<I', self.source_id) + b'\x10' + varuint(len(self.drops))
        return header + b''.join(d.encode() for d in self.drops)
