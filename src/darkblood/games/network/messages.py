"""Server -> client game messages (JEvent bodies), one dataclass per opcode.

All serializers follow schemas recovered from DarkBlood.exe (SHA-256 a82ae3d7...)."""
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


@dataclass
class CloseBagReq:
    """Opcode 2028: eEGS_CLOSE_BAG_REQ (0x00550000.c:1773).

    Wire format: i32 prefix (0x7FFFFFFF) + i64 bag_id.
    """
    prefix: int = 0x7FFFFFFF
    bag_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'CloseBagReq':
        if len(data) >= 12:
            prefix, bag_id = struct.unpack_from('<iq', data, 0)
            return cls(prefix=prefix, bag_id=bag_id)
        return cls()


@dataclass
class DragItemReq:
    """Opcode 2036: eEGS_DRAG_ITEM_REQ (JUserClient::DragItemREQ 0x00790000.c:4212).

    Wire format: i64 item_uid + i64 to_container + i32 to_slot (20 bytes).
    """
    item_uid: int = 0
    to_container: int = 0
    to_slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DragItemReq':
        if len(data) >= 20:
            item_uid, to_container, to_slot = struct.unpack_from('<qqi', data, 0)
            return cls(item_uid=item_uid, to_container=to_container, to_slot=to_slot)
        return cls()


@dataclass
class DragItemAck:
    """Opcode 2037: eEGS_DRAG_ITEM_ACK (On_eEGS_DRAG_ITEM_ACK 0x0077F570).

    Wire format: i32 result (0 = success) + tag 0x10 vector of Item structs.
    """
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(item.encode() for item in self.items))


@dataclass
class CharVerifyStatReq:
    """Opcode 2406: eEGS_CHAR_VERIFY_STAT_REQ. Heartbeat / stat verification from client."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'CharVerifyStatReq':
        return cls(raw_payload=data)


@dataclass
class CharVerifyStatAck:
    """Opcode 2407: eEGS_CHAR_VERIFY_STAT_ACK (On_eEGS_CHAR_VERIFY_STAT_ACK 0x0074B830)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class GameplayDieCharReq:
    """Opcode 5093: eERC_GAMEPLAY_DIE_CHAR_REQ (0x00780000.c:10409).

    Wire format: i64 from_char_uid + bool bDie + i32 damage + i32 cur_hp + i32 max_hp (21 bytes).
    """
    from_char_uid: int = 0
    bDie: bool = True
    damage: int = 0
    cur_hp: int = 0
    max_hp: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GameplayDieCharReq':
        if len(data) >= 21:
            from_uid, bDie, damage, cur_hp, max_hp = struct.unpack_from('<q?iii', data, 0)
            return cls(from_char_uid=from_uid, bDie=bDie, damage=damage, cur_hp=cur_hp, max_hp=max_hp)
        return cls()


@dataclass
class GameplayDieCharAck:
    """Opcode 5094: eERC_GAMEPLAY_DIE_CHAR_ACK (On_eERC_GAMEPLAY_DIE_CHAR_ACK 0x0078F090).

    Wire format:
      i32 result (0)
      i64 from_char_uid
      i64 to_char_uid
      bool bDie
      i32 damage
      i32 cur_hp
      i32 max_hp
      u16 die_count
      (if bDie and to_char_uid == player_uid):
      u16 sRebirthCoin
    """
    result: int = 0
    from_char_uid: int = 0
    to_char_uid: int = 0
    bDie: bool = True
    damage: int = 0
    cur_hp: int = 0
    max_hp: int = 500
    die_count: int = 1
    rebirth_coin: int = 5

    def encode(self) -> bytes:
        data = struct.pack('<iqq?iiiH', self.result, self.from_char_uid, self.to_char_uid,
                           self.bDie, self.damage, self.cur_hp, self.max_hp, self.die_count)
        if self.bDie:
            data += struct.pack('<H', self.rebirth_coin)
        return data


@dataclass
class DailyRebirthCoinUseReq:
    """Opcode 2448: eEGS_DAILY_REBIRTH_COIN_USE_REQ. Client requests to revive with coin."""
    prefix: int = 0x7FFFFFFF
    coin_type: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DailyRebirthCoinUseReq':
        prefix = struct.unpack_from('<i', data, 0)[0] if len(data) >= 4 else 0x7FFFFFFF
        coin_type = data[4] if len(data) > 4 else 0
        return cls(prefix=prefix, coin_type=coin_type)


@dataclass
class DailyRebirthCoinUseAck:
    """Opcode 2449: eEGS_DAILY_REBIRTH_COIN_USE_ACK (On_eEGS_DAILY_REBIRTH_COIN_USE_ACK 0x0079DC70).

    Wire format: i32 result (0 = success) + u16 sDailyRecvCnt + i32 nPCBangCoinRemain.
    """
    result: int = 0
    daily_recv_cnt: int = 1
    pcbang_coin_remain: int = 5

    def encode(self) -> bytes:
        return struct.pack('<iHI', self.result, self.daily_recv_cnt, self.pcbang_coin_remain)


@dataclass
class ChoiceRewardPartyRankReq:
    """Opcode 5090: eERC_CHOICE_REWARD_PARTYRANK_REQ (0x00780000.c:9280).

    Wire format: i32 prefix (0x7FFFFFFF) + i32 card_index.
    """
    prefix: int = 0x7FFFFFFF
    card_index: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ChoiceRewardPartyRankReq':
        if len(data) >= 8:
            prefix, card_index = struct.unpack_from('<ii', data, 0)
            return cls(prefix=prefix, card_index=card_index)
        return cls()


@dataclass
class ChoiceRewardPartyRankAck:
    """Opcode 5091: eERC_CHOICE_REWARD_PARTYRANK_ACK (On_opcode_5091 0x0078D660).

    Wire format:
      i32 result (0 = success)
      i64 nChoiceCharUID
      tag 0x1E + 12-byte struct (u32 uid, u32 item_id, u16 count, u16 drop_type)
      i32 nBoxType
      i32 nBoxCost
    """
    result: int = 0
    char_uid: int = 0
    reward_uid: int = 1
    item_id: int = 0
    count: int = 1
    drop_type: int = 0
    box_type: int = 0
    box_cost: int = 0

    def encode(self) -> bytes:
        data = struct.pack('<iq', self.result, self.char_uid)
        data += b'\x1e' + struct.pack('<IIHH', self.reward_uid, self.item_id, self.count, self.drop_type)
        data += struct.pack('<ii', self.box_type, self.box_cost)
        return data


@dataclass
class UseItemReq:
    """Opcode 2038: eEGS_USE_ITEM_REQ (0x00780000.c:8159).

    Wire format: i64 item_uid + i32 use_count (12 bytes).
    """
    item_uid: int = 0
    use_count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'UseItemReq':
        if len(data) >= 12:
            item_uid, use_count = struct.unpack_from('<qi', data, 0)
            return cls(item_uid=item_uid, use_count=use_count)
        return cls()


@dataclass
class UseItemAck:
    """Opcode 2039: eEGS_USE_ITEM_ACK (On_opcode_2039 0x0077D4C0).

    Wire format:
      i32 result (0 = success)
      tag 0x10 vector of Item structs (vecItem)
      i32 nItemID
      i32 nUseCount
    """
    result: int = 0
    items: list = field(default_factory=list)
    item_id: int = 0
    use_count: int = 1

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<Ii', self.item_id, self.use_count))



@dataclass
class AssignQuickslotReq:
    """Opcode 2044: eEGS_ASSIGN_QUICKSLOT_REQ (0x00780000.c:8513).

    Wire format: u8 ucType + u8 ucSlotNum + i32 nRefID + i64 nRefUID (14 bytes).
    """
    slot_type: int = 0
    slot_num: int = 0
    ref_id: int = 0
    ref_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AssignQuickslotReq':
        if len(data) >= 14:
            stype, snum, rid, ruid = struct.unpack_from('<BBiq', data, 0)
            return cls(slot_type=stype, slot_num=snum, ref_id=rid, ref_uid=ruid)
        return cls()


@dataclass
class AssignQuickslotAck:
    """Opcode 2045: eEGS_ASSIGN_QUICKSLOT_ACK (On_eEGS_ASSIGN_QUICKSLOT_ACK 0x0078C4A0).

    Wire format:
      i32 result (0 = success)
      u8 ucType
      u8 ucSlotNum
      i32 nRefID
      i64 nRefUID
    """
    result: int = 0
    slot_type: int = 0
    slot_num: int = 0
    ref_id: int = 0
    ref_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iBBiq', self.result, self.slot_type, self.slot_num, self.ref_id, self.ref_uid)


@dataclass
class EquipItemReq:
    """Opcode 2042: eEGS_EQUIP_ITEM_REQ (0x00800000.c:500).

    Wire format: i64 item_uid + i32 equip_slot (12 bytes).
    """
    item_uid: int = 0
    equip_slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'EquipItemReq':
        if len(data) >= 12:
            item_uid, equip_slot = struct.unpack_from('<qi', data, 0)
            return cls(item_uid=item_uid, equip_slot=equip_slot)
        return cls()


@dataclass
class EquipItemAck:
    """Opcode 2043: eEGS_EQUIP_ITEM_ACK (On_eEGS_EQUIP_ITEM_ACK 0x007AE940).

    Wire format: i32 result (0 = success) + tag 0x10 vector of Item structs.
    """
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(item.encode() for item in self.items))


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
class DeleteItemReq:
    """Opcode 2040: eEGS_DELETE_ITEM_REQ (0x00550000.c:769).

    Wire format: i64 nItemUID + i32 nAmount (12 bytes).
    """
    item_uid: int = 0
    amount: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DeleteItemReq':
        if len(data) >= 12:
            uid, amt = struct.unpack_from('<qi', data, 0)
            return cls(item_uid=uid, amount=amt)
        return cls()


@dataclass
class DeleteItemAck:
    """Opcode 2041: eEGS_DELETE_ITEM_ACK (0x00557420).

    Wire format: i32 result + i64 nDeletedItemUID + i32 nDelAmount.
    """
    result: int = 0
    item_uid: int = 0
    del_amount: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqi', self.result, self.item_uid, self.del_amount)


@dataclass
class SwitchBagReq:
    """Opcode 2030: eEGS_SWITCH_BAG_REQ (0x00550000.c:626).

    Wire format: u16 sIndexFrom + u16 sIndexTo (4 bytes).
    """
    from_index: int = 0
    to_index: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'SwitchBagReq':
        if len(data) >= 4:
            f, t = struct.unpack_from('<HH', data, 0)
            return cls(from_index=f, to_index=t)
        return cls()


@dataclass
class SwitchBagAck:
    """Opcode 2031: eEGS_SWITCH_BAG_ACK (0x00557680).

    Wire format: i32 result + u16 sIndexFrom + u16 sIndexTo.
    """
    result: int = 0
    from_index: int = 0
    to_index: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iHH', self.result, self.from_index, self.to_index)


@dataclass
class SwitchQuickslotReq:
    """Opcode 2046: eEGS_SWITCH_QUCIKSLOT_REQ (0x00780000.c:8591).

    Wire format: u8 ucType + u8 ucSlotNumFrom + u8 ucSlotNumTo (3 bytes).
    """
    slot_type: int = 0
    from_slot: int = 0
    to_slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'SwitchQuickslotReq':
        if len(data) >= 3:
            t, f, to = struct.unpack_from('<BBB', data, 0)
            return cls(slot_type=t, from_slot=f, to_slot=to)
        return cls()


@dataclass
class SwitchQuickslotAck:
    """Opcode 2047: eEGS_SWITCH_QUCIKSLOT_ACK (On_eEGS_SWITCH_QUCIKSLOT_ACK 0x0078C790).

    Wire format: i32 result + u8 ucType + u8 ucSlotNumFrom + u8 ucSlotNumTo.
    """
    result: int = 0
    slot_type: int = 0
    from_slot: int = 0
    to_slot: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iBBB', self.result, self.slot_type, self.from_slot, self.to_slot)


@dataclass
class HttpNoticeCheckReq:
    """Opcode 2594: eEGS_HTTPNOTICE_CHECK_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'HttpNoticeCheckReq':
        return cls()


@dataclass
class HttpNoticeCheckAck:
    """Opcode 2595: eEGS_HTTPNOTICE_CHECK_ACK (0x005A5110).

    Wire format: i32 result + bool bWatch.
    """
    result: int = 0
    watch: bool = False

    def encode(self) -> bytes:
        return struct.pack('<i?', self.result, self.watch)


@dataclass
class PlayOptionUpdateReq:
    """Opcode 2216: eEGS_PLAY_OPTION_UPDATE_REQ (0x00790000.c:3729).

    Wire format: i64 char_uid + tag 0x1E struct (raw).
    """
    char_uid: int = 0
    raw: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'PlayOptionUpdateReq':
        if len(data) >= 8:
            uid = struct.unpack_from('<q', data, 0)[0]
            return cls(char_uid=uid, raw=data[8:])
        return cls()


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


@dataclass
class LevelUpNot:
    """Opcode 5087: eERC_LEVEL_UP_NOT (On_eERC_LEVEL_UP_NOT 0x0078CCF0).

    Wire format:
      tag 0x1E
        tag 0x0D + varuint(0) (empty stats array via 0x00A48D50)
        i64 char_uid
        u8 new_level
        i32 max_hp
        i32 max_mp
        bool flag
    """
    char_uid: int = 0
    new_level: int = 1
    max_hp: int = 1000
    max_mp: int = 500
    flag: bool = True

    def encode(self) -> bytes:
        inner = (b'\r' + varuint(0)
                 + struct.pack('<qBii?', self.char_uid, self.new_level, self.max_hp, self.max_mp, self.flag))
        return b'\x1e' + inner


@dataclass
class ChangeExpNot:
    """Opcode 5086: eERC_CHANGE_EXP_NOT (On_eERC_CHANGE_EXP_NOT 0x0078D170).

    Wire format:
      i32 nExpTotal
      tag 0x1E jGainExp: 8 x i32 + 1 x float (36 bytes).
    """
    exp_total: int = 0
    exp_details: tuple = (0, 0, 0, 0, 0, 0, 0, 0, 0.0)

    def encode(self) -> bytes:
        inner = struct.pack('<iiiiiiiif', *self.exp_details)
        return struct.pack('<i', self.exp_total) + b'\x1e' + inner


@dataclass
class LearnSkillReq:
    """Opcode 2050: eEGS_LEARN_SKILL_REQ (0x00780000.c:9504).

    Wire format: u16 sKindNameIndex + u8 ucLevel (3 bytes).
    """
    skill_index: int = 0
    level: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'LearnSkillReq':
        if len(data) >= 3:
            sidx, lvl = struct.unpack_from('<HB', data, 0)
            return cls(skill_index=sidx, level=lvl)
        return cls()


@dataclass
class LearnSkillAck:
    """Opcode 2051: eEGS_LEARN_SKILL_ACK (On_eEGS_LEARN_SKILL_ACK 0x0078DBE0).

    Wire format: i32 result + u16 sKindNameIndex + u8 ucLevel + i32 nRemainSP + i64 nRemainGold.
    """
    result: int = 0
    skill_index: int = 0
    level: int = 1
    remain_sp: int = 100
    remain_gold: int = 10000

    def encode(self) -> bytes:
        return struct.pack('<iHBiq', self.result, self.skill_index, self.level, self.remain_sp, self.remain_gold)


@dataclass
class ChangeBagPropertyReq:
    """Opcode 2048: eEGS_CHANGE_BAG_PROPERTY_REQ (0x00550000.c:676).

    Wire format: i64 nBagUID + u8 ucProperty (9 bytes).
    """
    bag_uid: int = 0
    property: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ChangeBagPropertyReq':
        if len(data) >= 9:
            uid, prop = struct.unpack_from('<qB', data, 0)
            return cls(bag_uid=uid, property=prop)
        return cls()


@dataclass
class ChangeBagPropertyAck:
    """Opcode 2049: eEGS_CHANGE_BAG_PROPERTY_ACK (On_eEGS_CHANGE_BAG_PROPERTY_ACK 0x00774040).

    Wire format: i32 result + i64 nBagUID + u8 ucProperty.
    """
    result: int = 0
    bag_uid: int = 0
    property: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqB', self.result, self.bag_uid, self.property)


@dataclass
class ModifySkillSpeechReq:
    """Opcode 2053: eEGS_MODIFY_SKILL_SPEECH_REQ (0x00780000.c:9674).

    Wire format: u16 sKindNameIndex + wide string strSpeech.
    """
    skill_index: int = 0
    speech: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'ModifySkillSpeechReq':
        if len(data) >= 2:
            sidx = struct.unpack_from('<H', data, 0)[0]
            speech = ''
            if len(data) > 2:
                rem = data[2:]
                speech = rem.decode('utf-16le', errors='replace')
            return cls(skill_index=sidx, speech=speech)
        return cls()


@dataclass
class ModifySkillSpeechAck:
    """Opcode 2054: eEGS_MODIFY_SKILL_SPEECH_ACK (On_eEGS_MODIFY_SKILL_SPEECH_ACK 0x0078E090).

    Wire format: i32 result + u16 sKindNameIndex + wide string strSpeech.
    """
    result: int = 0
    skill_index: int = 0
    speech: str = ''

    def encode(self) -> bytes:
        return struct.pack('<iH', self.result, self.skill_index) + wide_string(self.speech)


@dataclass
class DeleteSkillSpeechReq:
    """Opcode 2055: eEGS_DELETE_SKILL_SPEECH_REQ (0x00780000.c:9708).

    Wire format: u16 sKindNameIndex.
    """
    skill_index: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DeleteSkillSpeechReq':
        if len(data) >= 2:
            return cls(skill_index=struct.unpack_from('<H', data, 0)[0])
        return cls()


@dataclass
class DeleteSkillSpeechAck:
    """Opcode 2056: eEGS_DELETE_SKILL_SPEECH_ACK (On_eEGS_DELETE_SKILL_SPEECH_ACK 0x0078E270).

    Wire format: i32 result + u16 sKindNameIndex.
    """
    result: int = 0
    skill_index: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iH', self.result, self.skill_index)


@dataclass
class BuyItemReq:
    """Opcode 2067: eEGS_BUY_ITEM_REQ (0x00780000.c:10667).

    Wire format: i32 npc_id + i32 item_id + u16 count (10 bytes).
    """
    store_id: int = 0
    item_id: int = 0
    count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'BuyItemReq':
        if len(data) >= 10:
            sid, iid, cnt = struct.unpack_from('<iiH', data, 0)
            return cls(store_id=sid, item_id=iid, count=cnt)
        return cls()


@dataclass
class BuyItemAck:
    """Opcode 2068: eEGS_BUY_ITEM_ACK (On_eEGS_BUY_ITEM_ACK 0x0077E2F0).

    Wire format:
    If result != 0: i32 result (error popup, terminates frame).
    If result == 0 (success):
      - i32 result (0)
      - tag 0x1e (32-byte store item record 0x00A489D0)
      - i32 (prefix / u32)
      - i64 gold (player gold, written to +0x70)
      - tag 0x10 item vector (0x004B94C0)
      - i32, i16, i64, i32
    """
    result: int = 0
    store_record: bytes = b'\x00' * 32
    u32_1: int = 0
    gold: int = 0
    items: list = field(default_factory=list)
    u32_2: int = 0
    u16_1: int = 0
    i64_1: int = 0
    u32_3: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', 0)
                + b'\x1e' + (self.store_record[:32].ljust(32, b'\x00'))
                + struct.pack('<iq', self.u32_1, self.gold)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + struct.pack('<iHqi', self.u32_2, self.u16_1, self.i64_1, self.u32_3))


@dataclass
class SellItemReq:
    """Opcode 2069: eEGS_SELL_ITEM_REQ (0x00780000.c:10700).

    Wire format: i32 npc_id + i64 item_uid + u16 count (14 bytes).
    """
    npc_id: int = 0
    item_uid: int = 0
    count: int = 1

    @classmethod
    def decode(cls, data: bytes) -> 'SellItemReq':
        if len(data) >= 14:
            nid, uid, cnt = struct.unpack_from('<iqi', data, 0)
            return cls(npc_id=nid, item_uid=uid, count=cnt)
        return cls()


@dataclass
class SellItemAck:
    """Opcode 2070: eEGS_SELL_ITEM_ACK (On_eEGS_SELL_ITEM_ACK 0x0077E8E0).

    Wire format:
    If result != 0: i32 result (error popup, terminates frame).
    If result == 0 (success):
      - i32 result (0)
      - tag 0x10 item vector (0x004B9210)
      - i64 gold (player gold, written to +0x70)
      - tag 0x1e repurchase record (Item struct 0x00A53F50 + i32 + i64)
      - tag 0x13 map (0x006B9200)
    """
    result: int = 0
    gold: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        repurchase_record = b'\x1e' + Item(code='', uid=0).encode() + struct.pack('<iq', 0, 0)
        return (struct.pack('<i', 0)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold)
                + repurchase_record
                + b'\x13\x80')


@dataclass
class RepurchaseItemReq:
    """Opcode 2071: eEGS_REPURCHASE_ITEM_REQ (0x00780000.c:10735).

    Wire format: i64 item_uid (8 bytes).
    """
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RepurchaseItemReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class RepurchaseItemAck:
    """Opcode 2072: eEGS_REPURCHASE_ITEM_ACK (On_eEGS_REPURCHASE_ITEM_ACK 0x0077EC30).

    Wire format:
    If result != 0: i32 result (error popup).
    If result == 0 (success):
      - i32 result (0)
      - tag 0x10 item vector (0x004B9210)
      - i64 gold (player gold, written to +0x70)
    """
    result: int = 0
    gold: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', 0)
                + b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold))


@dataclass
class FriendListAddReq:
    """Opcode 2139: eEGS_FRIEND_LIST_ADD_REQ (0x00790000.c:1595).

    Wire format: wide string char_name.
    """
    char_name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'FriendListAddReq':
        return cls(char_name=data.decode('utf-16le', errors='replace'))


@dataclass
class FriendListAddAck:
    """Opcode 2140: eEGS_FRIEND_LIST_ADD_ACK (On_eEGS_FRIEND_LIST_ADD_ACK 0x007591A0).

    Wire format: i32 result (0xCE = player offline/not found).
    """
    result: int = 0xCE

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class FriendListDeleteReq:
    """Opcode 2135: eEGS_FRIEND_LIST_DELETE_REQ (0x00790000.c:1824).

    Wire format: i64 char_uid (8 bytes).
    """
    char_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'FriendListDeleteReq':
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
class ChangeBagNameReq:
    """Opcode 2032: eEGS_CHANGE_BAG_NAME_REQ.

    Wire format: i64 bag_uid + wide string bag_name.
    """
    bag_uid: int = 0
    name: str = ''

    @classmethod
    def decode(cls, data: bytes) -> 'ChangeBagNameReq':
        if len(data) < 8:
            return cls()
        bag_uid = struct.unpack_from('<q', data, 0)[0]
        name = data[8:].decode('utf-16le', errors='replace').rstrip('\x00')
        return cls(bag_uid=bag_uid, name=name)


@dataclass
class ChangeBagNameAck:
    """Opcode 2033: eEGS_CHANGE_BAG_NAME_ACK (On_eEGS_CHANGE_BAG_NAME_ACK 0x007528B0).

    Wire format: i32 result + i64 bag_uid + wide string bag_name.
    """
    result: int = 0
    bag_uid: int = 0
    name: str = ''

    def encode(self) -> bytes:
        raw_name = self.name.encode('utf-16le') + b'\x00\x00'
        return struct.pack('<iq', self.result, self.bag_uid) + raw_name


@dataclass
class UpdateSkillLockedReq:
    """Opcode 2117: eEGS_UPDATE_SKILL_LOCKED_REQ (0x00790000.c:1390).

    Wire format: i16 sKindNameIndex + bool bLocked.
    """
    skill_index: int = 0
    locked: bool = False

    @classmethod
    def decode(cls, data: bytes) -> 'UpdateSkillLockedReq':
        if len(data) >= 3:
            skill_index, locked = struct.unpack_from('<h?', data, 0)
            return cls(skill_index=skill_index, locked=locked)
        return cls()


@dataclass
class UpdateSkillLockedAck:
    """Opcode 2118: eEGS_UPDATE_SKILL_LOCKED_ACK (On_eEGS_UPDATE_SKILL_LOCKED_ACK 0x00752C70).

    Wire format: i32 result + i16 sKindNameIndex + bool bLocked.
    """
    result: int = 0
    skill_index: int = 0
    locked: bool = False

    def encode(self) -> bytes:
        return struct.pack('<ih?', self.result, self.skill_index, self.locked)


@dataclass
class DurabilityRepairReq:
    """Opcode 2145: eEGS_DURABILITY_REPAIR_REQ (0x00790000.c:2123).

    Wire format: tag 0x17 map of items to repair.
    """
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'DurabilityRepairReq':
        return cls(raw_payload=data)


@dataclass
class DurabilityRepairAck:
    """Opcode 2146: eEGS_DURABILITY_REPAIR_ACK (On_eEGS_DURABILITY_REPAIR_ACK 0x007930D0).

    Wire format: if result == 0: i32 result (0) + tag 0x17 map + i64 remain_gold.
                 if result != 0: i32 result error code.
    """
    result: int = 0
    remain_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # 0x17 = map tag, 0x80 = 0 elements
        return struct.pack('<i', 0) + b'\x17\x80' + struct.pack('<q', self.remain_gold)


@dataclass
class ItemUpgradeReq:
    """Opcode 2115: eEGS_ITEM_UPGRADE_REQ (0x00790000.c:296).

    Wire format: i64 nTargetItemUID + i64 nCatalystItemUID + i64 nProtectItemUID.
    """
    target_uid: int = 0
    catalyst_uid: int = 0
    protect_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ItemUpgradeReq':
        if len(data) >= 24:
            t, c, p = struct.unpack_from('<qqq', data, 0)
            return cls(target_uid=t, catalyst_uid=c, protect_uid=p)
        return cls()


@dataclass
class ItemUpgradeAck:
    """Opcode 2116: eEGS_ITEM_UPGRADE_ACK (On_eEGS_ITEM_UPGRADE_ACK 0x007909C0).

    Wire format: i32 result (non-zero safely terminates without requiring complex inventory structs).
    """
    result: int = 1

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class BuyLifeWaterReq:
    """Opcode 2086: eEGS_BUY_LIFE_WATER_REQ (0x00780000.c:11036).

    Wire format: bool bLifeWater.
    """
    flag: bool = True

    @classmethod
    def decode(cls, data: bytes) -> 'BuyLifeWaterReq':
        if len(data) >= 1:
            return cls(flag=bool(data[0]))
        return cls()


@dataclass
class BuyLifeWaterAck:
    """Opcode 2087: eEGS_BUY_LIFE_WATER_ACK (On_eEGS_BUY_LIFE_WATER_ACK 0x0078FF90).

    Wire format: i32 result + bool flag + i64 remain_currency.
    """
    result: int = 0
    flag: bool = True
    remain_currency: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i?q', self.result, self.flag, self.remain_currency)


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
class DurabilityChangeReq:
    """Opcode 2143: eEGS_DURABILITY_CHANGE_REQ (0x00790000.c:2049).

    Wire format: tag 0x17 map.
    """
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'DurabilityChangeReq':
        return cls(raw_payload=data)


@dataclass
class DurabilityChangeAck:
    """Opcode 2144: eEGS_DURABILITY_CHANGE_ACK (On_eEGS_DURABILITY_CHANGE_ACK 0x00774AE0).

    Wire format: i32 result + tag 0x10 vector of items.
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result) + b'\x10\x80'


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
class PostSendReq:
    """Opcode 2221: eEGS_POST_SEND_REQ (0x00795D70)."""
    recipient: str = ''
    title: str = ''
    gold: int = 0
    extra: int = 0
    items: list = field(default_factory=list)

    @classmethod
    def decode(cls, data: bytes) -> 'PostSendReq':
        return cls()


@dataclass
class PostSendAck:
    """Opcode 2222: eEGS_POST_SEND_ACK (0x00795F40)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class PostReadReq:
    """Opcode 2223: eEGS_POST_READ_REQ (0x007963C0)."""
    mail_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PostReadReq':
        if len(data) >= 8:
            return cls(mail_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class PostReadAck:
    """Opcode 2224: eEGS_POST_READ_ACK (0x0075A660)."""
    result: int = 0
    mail_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iq', self.result, self.mail_uid)


@dataclass
class PostGetAppendItemReq:
    """Opcode 2225: eEGS_POST_GET_APPEND_ITEM_REQ (0x0079664C)."""
    mail_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PostGetAppendItemReq':
        if len(data) >= 8:
            return cls(mail_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class PostGetAppendItemAck:
    """Opcode 2226: eEGS_POST_GET_APPEND_ITEM_ACK (0x0077F8E0)."""
    result: int = 0
    mail_uid: int = 0
    gold: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<iqq', self.result, self.mail_uid, self.gold)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class PostDeleteReq:
    """Opcode 2236: eEGS_POST_DELETE_REQ (0x007964EC)."""
    mail_uids: list = field(default_factory=list)

    @classmethod
    def decode(cls, data: bytes) -> 'PostDeleteReq':
        uids = []
        if len(data) >= 2 and data[0] == 0x10:
            count, offset = read_varuint(data, 1)
            for _ in range(count):
                if offset + 8 <= len(data):
                    uids.append(struct.unpack_from('<q', data, offset)[0])
                    offset += 8
        elif len(data) >= 8:
            uids.append(struct.unpack_from('<q', data, 0)[0])
        return cls(mail_uids=uids)


@dataclass
class PostDeleteAck:
    """Opcode 2237: eEGS_POST_DELETE_ACK (0x007715F0)."""
    result: int = 0
    mail_uids: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.mail_uids))
                + struct.pack(f'<{len(self.mail_uids)}q', *self.mail_uids))


# --- Trade Opcodes (5069 - 5085) ---
@dataclass
class RequestTradeReq:
    """Opcode 5069: eERC_REQUEST_TRADE_REQ."""
    target_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RequestTradeReq':
        if len(data) >= 8:
            return cls(target_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class RequestTradeAck:
    """Opcode 5070: eERC_REQUEST_TRADE_ACK (0x00770E50)."""
    result: int = 0
    target_uid: int = 0
    target_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<iq', self.result, self.target_uid)
                + wide_string(self.target_name)
                + b'\x00\x00')


@dataclass
class AcceptRequestTradeReq:
    """Opcode 5071: eERC_ACCEPT_REQUEST_TRADE_REQ."""
    source_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AcceptRequestTradeReq':
        if len(data) >= 8:
            return cls(source_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class AcceptRequestTradeAck:
    """Opcode 5072: eERC_ACCEPT_REQUEST_TRADE_ACK (0x007587B0)."""
    result: int = 0
    source_uid: int = 0
    target_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqq', self.result, self.source_uid, self.target_uid)


@dataclass
class CancelTradeReq:
    """Opcode 5073: eERC_CANCEL_TRADE_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'CancelTradeReq':
        return cls()


@dataclass
class CancelTradeAck:
    """Opcode 5074: eERC_CANCEL_TRADE_ACK (0x0077DE00)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class InsertTradeItemReq:
    """Opcode 5075: eERC_INSERT_TRADE_ITEM_REQ."""
    item_uid: int = 0
    slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'InsertTradeItemReq':
        if len(data) >= 12:
            uid, slot = struct.unpack_from('<qi', data, 0)
            return cls(item_uid=uid, slot=slot)
        return cls()


@dataclass
class InsertTradeItemAck:
    """Opcode 5076: eERC_INSERT_TRADE_ITEM_ACK (0x0077D980)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class DeleteTradeItemReq:
    """Opcode 5077: eERC_DELETE_TRADE_ITEM_REQ."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DeleteTradeItemReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class DeleteTradeItemAck:
    """Opcode 5078: eERC_DELETE_TRADE_ITEM_ACK (0x0077DBB0)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class UpdateTradeArReq:
    """Opcode 5079: eERC_UPDATE_TRADE_AR_REQ."""
    gold: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'UpdateTradeArReq':
        if len(data) >= 8:
            return cls(gold=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class UpdateTradeArAck:
    """Opcode 5080: eERC_UPDATE_TRADE_AR_ACK (0x00758940)."""
    result: int = 0
    char_uid: int = 0
    gold: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iqq', self.result, self.char_uid, self.gold)


@dataclass
class AcceptTradeReq:
    """Opcode 5081: eERC_ACCEPT_TRADE_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'AcceptTradeReq':
        return cls()


@dataclass
class AcceptTradeAck:
    """Opcode 5082: eERC_ACCEPT_TRADE_ACK (0x0078EB40)."""
    result: int = 0
    char_uid: int = 0
    accepted: bool = True

    def encode(self) -> bytes:
        return struct.pack('<iq?', self.result, self.char_uid, self.accepted)


@dataclass
class FinallyAcceptTradeReq:
    """Opcode 5083: eERC_FINALLY_ACCEPT_TRADE_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'FinallyAcceptTradeReq':
        return cls()


@dataclass
class FinallyAcceptTradeAck:
    """Opcode 5084: eERC_FINALLY_ACCEPT_TRADE_ACK."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


# --- Party & Team Opcodes (5049 - 5055, 5015 - 5016) ---
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
                + b'\x1e\x00'
                + struct.pack('<iqqqi', 0, 0, 0, 0, 0))
        return data


# --- Quest Giveup & Fail Opcodes (2078 - 2081) ---
@dataclass
class QuestGiveupReq:
    """Opcode 2078: eEGS_QUEST_GIVEUP_REQ."""
    quest_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'QuestGiveupReq':
        if len(data) >= 4:
            return cls(quest_id=struct.unpack_from('<I', data, 0)[0])
        return cls()


@dataclass
class QuestGiveupAck:
    """Opcode 2079: eEGS_QUEST_GIVEUP_ACK (0x006223B0)."""
    result: int = 0
    quest_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iI', self.result, self.quest_id) + b'\x1e\x10\x80'


@dataclass
class QuestFailReq:
    """Opcode 2080: eEGS_QUEST_FAIL_REQ."""
    quest_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'QuestFailReq':
        if len(data) >= 4:
            return cls(quest_id=struct.unpack_from('<I', data, 0)[0])
        return cls()


@dataclass
class QuestFailAck:
    """Opcode 2081: eEGS_QUEST_FAIL_ACK (0x006223B0)."""
    result: int = 0
    quest_id: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iI', self.result, self.quest_id) + b'\x1e\x10\x80'


# --- Enchanting & Upgrade Opcodes (2254-2259, 2284-2285, 2672-2673) ---
@dataclass
class MagicEnchantEnchantReq:
    """Opcode 2254: eEGS_MAGICENCHANT_ENCHANT_REQ."""
    item_uid: int = 0
    catalyst_uid: int = 0
    scroll_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'MagicEnchantEnchantReq':
        if len(data) >= 24:
            return cls(*struct.unpack_from('<qqq', data, 0))
        return cls()


@dataclass
class MagicEnchantEnchantAck:
    """Opcode 2255: eEGS_MAGICENCHANT_ENCHANT_ACK (0x00796DC0)."""
    result: int = 0
    items: list = field(default_factory=list)
    gold: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold))


@dataclass
class MagicEnchantEraseOptionReq:
    """Opcode 2256: eEGS_MAGICENCHANT_ERASE_OPTION_REQ."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'MagicEnchantEraseOptionReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class MagicEnchantEraseOptionAck:
    """Opcode 2257: eEGS_MAGICENCHANT_ERASE_OPTION_ACK (0x00797120)."""
    result: int = 0
    items: list = field(default_factory=list)
    gold: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<q', self.gold))


@dataclass
class MagicEnchantExpendSlotReq:
    """Opcode 2258: eEGS_MAGICENCHANT_EXPEND_SLOT_REQ."""
    item_uid: int = 0
    stone_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'MagicEnchantExpendSlotReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()


@dataclass
class MagicEnchantExpendSlotAck:
    """Opcode 2259: eEGS_MAGICENCHANT_EXPEND_SLOT_ACK (0x0077FC60)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class RandomItemUpgradeReq:
    """Opcode 2284: eEGS_RANDOM_ITEM_UPGRADE_REQ."""
    item_uid: int = 0
    stone_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'RandomItemUpgradeReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()


@dataclass
class RandomItemUpgradeAck:
    """Opcode 2285: eEGS_RANDOM_ITEM_UPGRADE_ACK (0x0077FED0)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class FixItemUpgradeReq:
    """Opcode 2672: eEGS_FIX_ITEM_UPGRADE_REQ."""
    item_uid: int = 0
    stone_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'FixItemUpgradeReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()


@dataclass
class FixItemUpgradeAck:
    """Opcode 2673: eEGS_FIX_ITEM_UPGRADE_ACK (0x00783C40)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


# --- Loot Pickup & Monster Drop Notifications (5065-5068, 5114) ---
@dataclass
class PickUpItemReq:
    """Opcode 5065: eERC_PICK_UP_ITEM_REQ."""
    drop_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PickUpItemReq':
        if len(data) >= 8:
            return cls(drop_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class PickUpItemAck:
    """Opcode 5066: eERC_PICK_UP_ITEM_ACK."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class PickUpItemResultAck:
    """Opcode 5068: eERC_PICK_UP_ITEM_RESULT_ACK (0x0078AD80)."""
    result: int = 0
    picker_uid: int = 0
    item: object = None

    def encode(self) -> bytes:
        item_bytes = b'\x1e\x00' if self.item is None else (b'\x1e' + self.item.encode())
        return struct.pack('<iq', self.result, self.picker_uid) + item_bytes


@dataclass
class GetDropArNot:
    """Opcode 5114: eERC_GET_DROP_AR_NOT (0x00792700)."""
    result: int = 0
    gold: int = 0
    drop_id: int = 0
    picker_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<iiiq', self.result, self.gold, self.drop_id, self.picker_uid)


# --- Friend Presence & Real-Time Char Info (5118, 5119, 5096) ---
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
class UpdateCharInfoNot:
    """Opcode 5096: eERC_UPDATE_CHAR_INFO_NOT (0x0078C990)."""
    char_details: bytes = b''
    layer_net_id: int = 0

    def encode(self) -> bytes:
        return b'\x1e' + self.char_details + struct.pack('<q', self.layer_net_id)


# --- Customization, Renaming & Keymapping (2310-2311, 2314-2315, 2319-2320, 2338-2339) ---
@dataclass
class CharNickChangeReq:
    """Opcode 2310: eEGS_CHAR_NICK_CHANGE_REQ."""
    new_name: str = ''
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'CharNickChangeReq':
        try:
            length, off = read_varuint(data, 0)
            name = data[off:off + length].decode('utf-16le', errors='ignore')
            off += length
            item_uid = struct.unpack_from('<q', data, off)[0] if off + 8 <= len(data) else 0
            return cls(new_name=name, item_uid=item_uid)
        except Exception:
            return cls()


@dataclass
class CharNickChangeAck:
    """Opcode 2311: eEGS_CHAR_NICK_CHANGE_ACK (0x00780200)."""
    result: int = 0
    items: list = field(default_factory=list)
    new_name: str = ''

    def encode(self) -> bytes:
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + wide_string(self.new_name))


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
class KeyboardSetCustomKeyReq:
    """Opcode 2319: eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ."""
    keys_blob: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'KeyboardSetCustomKeyReq':
        return cls(keys_blob=data)


@dataclass
class KeyboardSetCustomKeyAck:
    """Opcode 2320: eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK (0x00753960)."""
    result: int = 0
    keys_blob: bytes = b''

    def encode(self) -> bytes:
        return struct.pack('<i', self.result) + wide_string(self.keys_blob.decode('utf-16le', errors='ignore') if self.keys_blob else '')


@dataclass
class ItemSpiritChangeReq:
    """Opcode 2338: eEGS_ITEM_SPIRIT_CHANGE_REQ."""
    item_uid: int = 0
    spirit_item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'ItemSpiritChangeReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()


@dataclass
class ItemSpiritChangeAck:
    """Opcode 2339: eEGS_ITEM_SPIRIT_CHANGE_ACK (0x00780860)."""
    result: int = 0
    spirit_uid: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (struct.pack('<iq', self.result, self.spirit_uid)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


# --- Mentoring & Teaching (5351 - 5357) ---
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

@dataclass
class TitleChangeReq:
    """Opcode 2335: eEGS_TITLE_CHANGE_REQ (0x00799753)."""
    title_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'TitleChangeReq':
        if len(data) >= 4:
            return cls(title_id=struct.unpack_from('<i', data, 0)[0])
        return cls()


@dataclass
class TitleChangeAck:
    """Opcode 2336: eEGS_TITLE_CHANGE_ACK (0x007751C0)."""
    result: int = 0
    title_id: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ii', self.result, self.title_id)


@dataclass
class AchieveGetListReq:
    """Opcode 2327: eEGS_ACHIEVE_GET_LIST_REQ."""
    @classmethod
    def decode(cls, data: bytes) -> 'AchieveGetListReq':
        return cls()


@dataclass
class AchieveGetListAck:
    """Opcode 2328: eEGS_ACHIEVE_GET_LIST_ACK (0x0079D650)."""
    result: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # result (u32) + Tag 0x1E + Tag 0x17 (map) + Tag 0x17 (map) + Tag 0x0A (bool) + Tag 0x10 (vector)
        return (struct.pack('<i', self.result)
                + b'\x1e\x17\x80\x17\x80\x0a\x00\x10\x80')


@dataclass
class AchieveChangeNot:
    """Opcode 2329: eEGS_ACHIEVE_CHANGE_NOT (0x0076C720)."""
    def encode(self) -> bytes:
        # Tag 0x17 (map) + Tag 0x17 (map) + Tag 0x17 (map)
        return b'\x17\x80\x17\x80\x17\x80'


@dataclass
class AchieveCompleteNot:
    """Opcode 2330: eEGS_ACHIEVE_COMPLETE_NOT (0x0079D240)."""
    def encode(self) -> bytes:
        # Tag 0x10 (vector) + Tag 0x10 (vector)
        return b'\x10\x80\x10\x80'


# =========================================================================
# Avatar Gem / Zam Socketing (2362-2365)
# =========================================================================

@dataclass
class AvatarZamInsertReq:
    """Opcode 2362: eEGS_AVATAR_ZAM_INSERT_REQ (0x007A46CB)."""
    avatar_item_uid: int = 0
    zam_item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AvatarZamInsertReq':
        if len(data) >= 16:
            return cls(*struct.unpack_from('<qq', data, 0))
        return cls()


@dataclass
class AvatarZamInsertAck:
    """Opcode 2363: eEGS_AVATAR_ZAM_INSERT_ACK (0x00782D00)."""
    result: int = 0
    updated_items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.updated_items))
                + b''.join(i.encode() for i in self.updated_items))


@dataclass
class AvatarZamEraseReq:
    """Opcode 2364: eEGS_AVATAR_ZAM_ERASE_REQ (0x007A481B)."""
    avatar_item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'AvatarZamEraseReq':
        if len(data) >= 8:
            return cls(avatar_item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class AvatarZamEraseAck:
    """Opcode 2365: eEGS_AVATAR_ZAM_ERASE_ACK (0x00782F40)."""
    result: int = 0
    updated_items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.updated_items))
                + b''.join(i.encode() for i in self.updated_items))


# =========================================================================
# Monster Taming (2348-2351)
# =========================================================================

@dataclass
class TameingMonsterInsertReq:
    """Opcode 2348: eEGS_TAMEING_MONSTER_INSERT_REQ (0x00799BCC)."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'TameingMonsterInsertReq':
        return cls(raw_payload=data)


TameingMonsterInsertAck = TamingMonsterInsertAck


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


TameingMonsterDeleteAck = TamingMonsterDeleteAck


# =========================================================================
# Skill Reset, Promotion & Rebirth Coins (2280, 2283, 2286)
# =========================================================================

@dataclass
class InitSkillNot:
    """Opcode 2280: eEGS_INIT_SKILL_NOT (0x00797740)."""
    result: int = 0
    sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ii', self.result, self.sp) + b'\x17\x80'


@dataclass
class PromotionNot:
    """Opcode 2283: eEGS_PROMOTION_NOT (0x00797F00)."""
    result: int = 0
    new_class: int = 1
    sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iBi', self.result, self.new_class, self.sp) + b'\x17\x80'


@dataclass
class RebirthCoinChangeNot:
    """Opcode 2286: eEGS_REBIRTH_COIN_CHANGE_NOT (0x007983B0)."""
    result: int = 0
    coins: int = 10

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<ih', self.result, self.coins)


# =========================================================================
# Arena SP Item & Arena Square (2709-2710, 5165-5166)
# =========================================================================

@dataclass
class UseArenaSpItemReq:
    """Opcode 2709: eEGS_USE_ARENA_SP_ITEM_REQ."""
    item_uid: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'UseArenaSpItemReq':
        if len(data) >= 8:
            return cls(item_uid=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class UseArenaSpItemAck:
    """Opcode 2710: eEGS_USE_ARENA_SP_ITEM_ACK (0x007A7CA0)."""
    result: int = 0
    consumed_items: list = field(default_factory=list)
    arena_sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.consumed_items))
                + b''.join(i.encode() for i in self.consumed_items)
                + struct.pack('<i', self.arena_sp))


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

@dataclass
class SecondPassCreateReq:
    """Opcode 5256: eERC_SECOND_PASS_CREATE_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'SecondPassCreateReq':
        return cls(raw_payload=data)


@dataclass
class SecondPassCreateAck:
    """Opcode 5257: eERC_SECOND_PASS_CREATE_ACK (0x0075B020)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class SecondPassModifyReq:
    """Opcode 5258: eERC_SECOND_PASS_MODIFY_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'SecondPassModifyReq':
        return cls(raw_payload=data)


@dataclass
class SecondPassModifyAck:
    """Opcode 5259: eERC_SECOND_PASS_MODIFY_ACK (0x0075B050)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


@dataclass
class SecondPassAuthReq:
    """Opcode 5260: eERC_SECOND_PASS_AUTH_REQ."""
    raw_payload: bytes = b''

    @classmethod
    def decode(cls, data: bytes) -> 'SecondPassAuthReq':
        return cls(raw_payload=data)


@dataclass
class SecondPassAuthAck:
    """Opcode 5261: eERC_SECOND_PASS_AUTH_ACK (0x0075B080)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)


# =========================================================================
# Remote Inspection (6011-6012, 6028-6029)
# =========================================================================

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
                + b'\x0a\x00\x1e' + summary_dummy + b'\x10\x80\x10\x80')


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
        return struct.pack('<iq', self.result, self.item_uid) + b'\x1e' + item_dummy


# =========================================================================
# Item Operations & Stack Splitting (2092, 2111-2112, 2250-2251, 2321-2322)
# =========================================================================

@dataclass
class DivideItemReq:
    """Opcode 2250: eEGS_DIVIDE_ITEM_REQ (0x00795B83)."""
    source_item_uid: int = 0
    dest_item_uid: int = 0
    count: int = 1
    slot: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DivideItemReq':
        if len(data) >= 22:
            s_uid, d_uid, cnt, s = struct.unpack_from('<qqih', data, 0)
            return cls(source_item_uid=s_uid, dest_item_uid=d_uid, count=cnt, slot=s)
        return cls()


@dataclass
class DivideItemAck:
    """Opcode 2251: eEGS_DIVIDE_ITEM_ACK (0x0077F570)."""
    result: int = 0
    items: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<i', self.result)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items))


@dataclass
class UseLearnSkillItemReq:
    """Opcode 2111: eEGS_USE_LEARN_SKILL_ITEM_REQ."""
    item_uid: int = 0
    skill_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'UseLearnSkillItemReq':
        if len(data) >= 10:
            item_uid, skill_id = struct.unpack_from('<qh', data, 0)
            return cls(item_uid=item_uid, skill_id=skill_id)
        return cls()


@dataclass
class UseLearnSkillItemAck:
    """Opcode 2112: eEGS_USE_LEARN_SKILL_ITEM_ACK (0x0078BCD0)."""
    result: int = 0
    skill_id: int = 0
    skill_level: int = 1
    item_code: int = 0
    count: int = 1
    items: list = field(default_factory=list)
    sp: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return (struct.pack('<ihBii', self.result, self.skill_id, self.skill_level, self.item_code, self.count)
                + b'\x10' + varuint(len(self.items))
                + b''.join(i.encode() for i in self.items)
                + struct.pack('<i', self.sp))


@dataclass
class InventoryUpdatedNot:
    """Opcode 2092: eEGS_INVENTORY_UPDATED_NOT (0x0077F070)."""
    def encode(self) -> bytes:
        # Tag 0x10 deleted_items + Tag 0x10 added_items
        return b'\x10\x80\x10\x80'


@dataclass
class ItemRemainTimeNot:
    """Opcode 2321: eEGS_ITEM_REMAIN_TIME_NOT (0x0077AED0)."""
    item_uid: int = 0
    remain_seconds: int = 0

    def encode(self) -> bytes:
        return struct.pack('<qq', self.item_uid, self.remain_seconds)


@dataclass
class ItemDeleteNot:
    """Opcode 2322: eEGS_ITEM_DELETE_NOT (0x00774DD0)."""
    item_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.item_uid)


# =========================================================================
# Guild Banking, Level Up & Skills (2157-2158, 2164-2165, 2179-2186, 2205)
# =========================================================================

@dataclass
class GuildInfoNot:
    """Opcode 2157: eEGS_GUILD_INFO_NOT (0x00752FF0)."""
    def encode(self) -> bytes:
        # Tag 0x1E + dummy guild struct
        return b'\x1e' + b'\x00' * 64


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

@dataclass
class DepotSaveArReq:
    """Opcode 2228: eEGS_DEPOT_SAVE_AR_REQ."""
    gold: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DepotSaveArReq':
        if len(data) >= 8:
            return cls(gold=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class DepotSaveArAck:
    """Opcode 2229: eEGS_DEPOT_SAVE_AR_ACK (0x00795220)."""
    result: int = 0
    new_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # result (u32) + Tag 0x17 map + i64 new_storage_gold
        return struct.pack('<i', self.result) + b'\x17\x80' + struct.pack('<q', self.new_gold)


@dataclass
class DepotLoadArReq:
    """Opcode 2230: eEGS_DEPOT_LOAD_AR_REQ."""
    gold: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'DepotLoadArReq':
        if len(data) >= 8:
            return cls(gold=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class DepotLoadArAck:
    """Opcode 2231: eEGS_DEPOT_LOAD_AR_ACK (0x00795490)."""
    result: int = 0
    new_gold: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        # result (u32) + Tag 0x17 map + i64 new_storage_gold
        return struct.pack('<i', self.result) + b'\x17\x80' + struct.pack('<q', self.new_gold)


@dataclass
class PostNewArrivalNot:
    """Opcode 2227: eEGS_POST_NEW_ARRIVAL_NOT (0x007965B0)."""
    def encode(self) -> bytes:
        return b''


@dataclass
class PostReturnReq:
    """Opcode 2234: eEGS_POST_RETURN_REQ."""
    mail_id: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'PostReturnReq':
        if len(data) >= 8:
            return cls(mail_id=struct.unpack_from('<q', data, 0)[0])
        return cls()


@dataclass
class PostReturnAck:
    """Opcode 2235: eEGS_POST_RETURN_ACK (0x00771470)."""
    result: int = 0

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<i', self.result) + b'\x10\x80'


# =========================================================================
# Combat, AP, Penalties & Random Box (2085, 2109, 2196)
# =========================================================================

@dataclass
class InsertApNot:
    """Opcode 2109: eEGS_INSERT_AP_NOT (0x00790480)."""
    current_ap: int = 0
    total_ap: int = 0

    def encode(self) -> bytes:
        return struct.pack('<ii', self.current_ap, self.total_ap)


@dataclass
class ChangeDungeonPenaltyNot:
    """Opcode 2085: eEGS_CHANGE_DUNGEON_PENALTY_NOT (0x0078FA70)."""
    in_dungeon: bool = False
    is_penalty: bool = False
    penalty_level: int = 0
    penalty_id: int = 0
    duration: int = 0

    def encode(self) -> bytes:
        return struct.pack('<??hii', self.in_dungeon, self.is_penalty, self.penalty_level, self.penalty_id, self.duration)


@dataclass
class RandomboxResultItemNot:
    """Opcode 2196: eEGS_RANDOMBOX_RESULT_ITEM_NOT (0x0075A2E0)."""
    result: int = 0
    item_code: int = 0
    count: int = 1
    is_jackpot: bool = False

    def encode(self) -> bytes:
        if self.result != 0:
            return struct.pack('<i', self.result)
        return struct.pack('<iih?', self.result, self.item_code, self.count, self.is_jackpot)












