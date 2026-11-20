"""Dark Blood protocol wire messages - Dungeon domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import JSerBufferReader, WireError, read_varuint, varuint, wide_string
from darkblood.games.entities.character import Character, layer_net_id
from darkblood.games.entities.items import Item

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
class RoomInfo:
    """Untagged jRoomInfo, reader 0x00A49380, shared by 5002 and 5004."""
    room_id: int
    name: str = ''
    req_a: int = -1
    req_b: int = -1
    req_c: int = -1
    req_d: int = 1
    host_uid: int = 0

    def encode(self) -> bytes:
        return (struct.pack('<q', self.room_id) + wide_string(self.name)
                + struct.pack('<hhiqqiih', self.req_c, self.req_d, self.req_a,
                              self.host_uid, 0, self.req_b, -1, self.req_d))


@dataclass
class CreateRoomAck:
    """5002 (0x005984D0): result, room info, team ID, relay endpoint."""
    result: int = 0
    room: RoomInfo = None
    team_id: int = 0
    relay: bytes = b''

    def encode(self) -> bytes:
        result = struct.pack('<I', self.result)
        if self.result:
            return result
        return result + self.room.encode() + struct.pack('<I', self.team_id) + self.relay


@dataclass
class JoinRoomReq:
    """5003 (0x0058B430): i64 room UID, with optional request prefix."""
    room_id: int

    @classmethod
    def decode(cls, data: bytes) -> 'JoinRoomReq':
        if len(data) == 12 and data[:4] == b'\xff\xff\xff\x7f':
            data = data[4:]
        if len(data) != 8:
            raise WireError('Invalid room UID request')
        return cls(*struct.unpack('<q', data))


@dataclass
class RoomMember:
    """jNetChar (0x00A533A0). Unmapped fields use constructor 0x00486190 defaults."""
    character: Character

    def encode(self) -> bytes:
        return (self.character.encode_world_details()
                + struct.pack('<q20sqqI', -1, b'\xff' * 8, -1, -1, 0)
                + struct.pack('<12HI', 2010, 1, 1, 0, 0, 0, 2010, 1, 1, 0, 0, 0, 0))


@dataclass
class JoinRoomAck:
    """5004 (0x00597C30): result, room info, host UID, roster, relay, two bools."""
    result: int = 0
    room: RoomInfo = None
    members: list = field(default_factory=list)
    relay: bytes = b''

    def encode(self) -> bytes:
        result = struct.pack('<I', self.result)
        if self.result:
            return result
        roster = b'\x10' + varuint(len(self.members)) + b''.join(member.encode() for member in self.members)
        return result + self.room.encode() + struct.pack('<q', self.room.host_uid) + roster + self.relay + b'\0\0'


@dataclass
class RoomMemberJoinedNot:
    """5035 (0x00598D90): jNetChar and bIsAllCharSameRate."""
    member: RoomMember

    def encode(self) -> bytes:
        return self.member.encode() + b'\0'


@dataclass
class RoomMemberLeftNot:
    """5036 (0x005991B0): result and departing character UID."""
    char_uid: int

    def encode(self) -> bytes:
        return struct.pack('<Iq', 0, self.char_uid)

@dataclass
class SelectDungeonAck:
    """Opcode 5044: eERC_SELECT_DUNGEON_ACK (JUserClient handler 0x007702E0).

    Read order: u32 result (0x94 is a special failure stored on app page 9),
    tag 0x17 map (0x0076AD10), tag 0x13 set (0x00765450), untagged J-wstring
    (0x00B35AB0), tag 0x13 set (0x005EAB90: varint, i32 elements). On success
    the wstring goes to JAppStateDungeonGate 0x006B2C00, which looks it up as
    the gate property id (failure logs "Invalidation in m_pjGateProp"), so it
    echoes the 5043 request ("Act1_G1"). The first set (gate +0x268) is sent
    empty; its element meaning is not recovered.

    History map (0x0076AD10): 0x0F, J-wstring dungeon id, value 0x00A492C0 =
    J-wstring map id, u8 m_ucDiff, u8 cleared flag. 0x006BCD20 (SetDunHist)
    copies it to the dungeon's gate slot; dungeons without an entry keep
    0/0 (0x00A48970). 0x00A4BC00 allows difficulty d when d-1 < m_ucDiff,
    or d-1 == m_ucDiff with the flag set, and the gate's auto-selection
    (0x006D1120) picks the map with Difficult == m_ucDiff, one step higher
    when the flag is set. So the entry is the highest cleared difficulty:
    sending 3/1 for every dungeon made "Unique" the default everywhere.

    The trailing i32 set is copied to gate +0x218 and holds active quest
    ids (JHashString of the quest id, i.e. the u32 quest id). Each dungeon
    has 30 map slots (prop +0xA0..+0x118); slots from index 4 are quest
    variants (e.g. Act1_G1_A16, QuestLink Q0002S01). 0x006B5930,
    0x006C77E0 and 0x006D1120 hash the map's +0x44 field, its QuestLink
    (the same field 0x006D5DE0 looks up as a quest), and offer/select the
    variant only when that hash is in this set.
    """
    result: int = 0
    gate_id: str = ''
    dun_history: dict = field(default_factory=dict)  # {dungeon_id: (map_id, ucDiff, cleared)}
    quest_ids: list = field(default_factory=list)  # active quest ids (u32)

    def encode(self) -> bytes:
        hist_bytes = b''
        for dun_id, (map_code, max_diff, state) in self.dun_history.items():
            hist_bytes += b'\x0f' + wide_string(dun_id) + wide_string(map_code) + struct.pack('<BB', max_diff, state)
        hist_map = b'\x17' + varuint(len(self.dun_history)) + hist_bytes
        ids = sorted({q & 0xFFFFFFFF for q in self.quest_ids})
        quest_set = b'\x13' + varuint(len(ids)) + b''.join(struct.pack('<I', q) for q in ids)
        return (struct.pack('<I', self.result) + hist_map + b'\x13' + varuint(0)
                + wide_string(self.gate_id) + quest_set)

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
class StartGameReq:
    """Opcode 5013: i32 request prefix followed by the dungeon map code."""

    map_code: str

    @classmethod
    def decode(cls, data: bytes) -> 'StartGameReq':
        reader = JSerBufferReader(data, offset=4)
        length = reader.read_varuint()
        map_code = reader.read_bytes(length).decode('utf-16le')
        if not map_code or '\x00' in map_code:
            raise WireError('Missing or invalid dungeon map code')
        return cls(map_code)


@dataclass
class StartGameAck:
    """Opcode 5014, reader 0x007880A0. Errors contain only the result.

    Success reads a u16 and u32, a J-wstring, maps 0x004B8B80, 0x0064E7D0
    and 0x004B7550, then an inventory update vector via 0x004B94C0. The
    scalar defaults and empty maps preserve the verified single-player reply.
    """

    result: int = 0
    map_code: str = ''
    item_updates: list = field(default_factory=list)

    def encode(self) -> bytes:
        if self.result:
            return struct.pack('<I', self.result)
        return (struct.pack('<IHI', 0, 0, 0) + wide_string(self.map_code)
                + (b'\x17' + varuint(0)) * 3
                + b'\x10' + varuint(len(self.item_updates))
                + b''.join(item.encode() for item in self.item_updates))


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
class GameplayDieCharReq:
    """Opcode 5093: eERC_GAMEPLAY_DIE_CHAR_REQ (writer 0x0078EDF0).

    Wire format: optional i32 prefix (0x7FFFFFFF) + i64 char_uid + bool bDie +
    i32 damage + i32 cur_hp + i32 max_hp (21 or 25 bytes).
    """
    prefix: int = 0x7FFFFFFF
    char_uid: int = 0
    bDie: bool = True
    damage: int = 0
    cur_hp: int = 0
    max_hp: int = 0

    @classmethod
    def decode(cls, data: bytes) -> 'GameplayDieCharReq':
        from darkblood.core.serialization.jser import strip_prefix
        data = strip_prefix(data)
        prefix = 0x7FFFFFFF
        if len(data) >= 21:
            uid, bDie, damage, cur_hp, max_hp = struct.unpack_from('<q?iii', data, 0)
            return cls(prefix=prefix, char_uid=uid, bDie=bDie, damage=damage, cur_hp=cur_hp, max_hp=max_hp)
        return cls()

@dataclass
class GameplayDieCharAck:
    """Opcode 5094: eERC_GAMEPLAY_DIE_CHAR_ACK (handler 0x0078F090, assembly-checked).

    Wire format after the u32 result (0x00A1EA20):
      i64 char_uid   compared with the own UID (0x00946570)
      i64 other_uid  (meaning not recovered; 0)
      bool bDie
      u32, u32, u32  (meanings not recovered; echoed from the request)
      u16            (meaning not recovered)
      u16 rebirth coins -- read only when bDie == 0 and char_uid is the own
                     UID (the revive case).
    With bDie set and char_uid == own UID the handler opens page 0x6B through
    0x008FC100(1). The previous emulator layout put an attacker UID first,
    so the client never matched its own UID and showed no revive window.
    """
    result: int = 0
    char_uid: int = 0
    other_uid: int = 0
    bDie: bool = True
    damage: int = 0
    cur_hp: int = 0
    max_hp: int = 0
    die_count: int = 0
    rebirth_coin: int = 0

    def encode(self) -> bytes:
        data = struct.pack('<Iqq?IIIH', self.result, self.char_uid, self.other_uid, self.bDie,
                           self.damage & 0xFFFFFFFF, self.cur_hp & 0xFFFFFFFF,
                           self.max_hp & 0xFFFFFFFF, self.die_count & 0xFFFF)
        if not self.bDie:
            data += struct.pack('<H', self.rebirth_coin & 0xFFFF)
        return data

@dataclass
class DailyRebirthCoinUseReq:
    """Opcode 2448: eEGS_DAILY_REBIRTH_COIN_USE_REQ (sender 0x0079D9xx): i32 prefix + bool.

    A claim of free daily rebirth coins, not a revive. bool 0 is the daily
    claim: the sender refuses locally when player +0x7E (received) >= 3
    (UI_2659) or +0x7C (owned) >= 3 (UI_2646). bool 1 is a PC-bang variant.
    Observed live: ffffff7f 00.
    """
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

    Wire format: u32 result (0 = success) + u16 -> player +0x7E (daily coins
    received) + u32 (passed to page 0x12 0x0054A1E0; PC-bang value). The ack
    does not change the owned coin count; 2286 does.
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
      12-byte reward struct (u32 uid, u32 item_id, u16 count, u16 drop_type)
      i32 nBoxType
      i32 nBoxCost
      If char_uid == local_player_uid:
        tag 0x10 + vector of Item (0x004B94C0)
        i64 new_gold (player +0x70)
    """
    result: int = 0
    char_uid: int = 0
    reward_uid: int = 1
    item_id: int = 0
    count: int = 1
    drop_type: int = 0
    box_type: int = 0
    box_cost: int = 0
    items: list = field(default_factory=list)  # [Item]
    gold: int = 0

    def encode(self) -> bytes:
        data = struct.pack('<iq', self.result, self.char_uid)
        data += struct.pack('<IIHH', self.reward_uid, self.item_id, self.count, self.drop_type)
        data += struct.pack('<ii', self.box_type, self.box_cost)
        data += b'\x10' + varuint(len(self.items)) + b''.join(i.encode() for i in self.items)
        data += struct.pack('<q', self.gold)
        return data

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
class LeaveRoomReq:
    """Opcode 5005: eERC_LEAVE_ROOM_REQ (0x0058B240)."""
    @classmethod
    def decode(cls, data: bytes) -> 'LeaveRoomReq':
        return cls()

@dataclass
class LeaveRoomAck:
    """Opcode 5006: eERC_LEAVE_ROOM_ACK (0x00598A00)."""
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.result)

@dataclass
class FinishGameReq:
    """Opcode 5017: eERC_FINISH_GAME_REQ (sender 0x007AD380)."""
    is_clear: bool = True

    @classmethod
    def decode(cls, data: bytes) -> 'FinishGameReq':
        # sender: 0x408c60 header, then bool is_clear
        # live body starts with 0x01
        is_clear = bool(data[0]) if data else True
        return cls(is_clear=is_clear)

@dataclass
class SingleReward:
    """mapSingleReward value in 5018: a raw 40-byte block (0x00A1E7A0 reads
    0x28 bytes; tag 0x1E is not on the wire).

    0x0071F9F0 copies it to JResultDirect +0x74 (result page 0x1B, +0xD4).
    Field uses recovered from the result screen builders:
      +0x00  i32  unknown (sent as 0)
      +0x04  i32  "num_total" (0x00720164)
      +0x08  i32  explist row 1, shown as value / 100.0 after "X" (0x007212E9)
      +0x0C  i32  explist row 2, shown as value / 100.0 after "X" (0x00721350)
      +0x10  i32  explist row 0 text (0x007212D3)
      +0x14..+0x1C  3 x i32 unknown (sent as 0)
      +0x20  i32  extra box count: 0x0071FF0F loops this many times adding
                  "extra_box" list entries, so it must stay small
      +0x24  i32  extra box price ("num_price", 0x0071FE83)
    The stylish/demolition/damage gauges are read from party member data,
    not from this block.
    """
    total: int = 0
    rate_a: int = 100
    rate_b: int = 100
    exp: int = 0
    extra_box_count: int = 0
    extra_box_price: int = 0

    def encode(self) -> bytes:
        return struct.pack('<10i', 0, self.total, self.rate_a, self.rate_b, self.exp,
                           0, 0, 0, self.extra_box_count, self.extra_box_price)


@dataclass
class FinishGameAck:
    """Opcode 5018: eERC_FINISH_GAME_ACK (handler 0x007ADB60).

    Wire format:
      u32 result (0 = success)
      bool is_clear (1 = dungeon clear / victory)
      wstring map_code
      bool flag (bSamePerson: False)
      tag 0x17 map (mapGuildPersonCnt: empty -> 0x17 + varuint(0))
      If is_clear:
        tag 0x17 map mapSingleReward: 0x0F, i64 char_uid, SingleReward
        i32 nPartyRankFirst, i32 nPartyRankFinal, i32 nBoxGrade, i32 nExtraBoxCost
        tag 0x10 vector (vecBonusMonster: empty -> 0x10 + varuint(0))
    """
    result: int = 0
    is_clear: bool = True
    map_code: str = ''
    flag: bool = False
    char_uid: int = 0
    rank_first: int = 1
    rank_final: int = 1
    box_grade: int = 1
    extra_box_cost: int = 0
    reward: SingleReward = field(default_factory=SingleReward)

    def encode(self) -> bytes:
        buf = bytearray()
        buf.extend(struct.pack('<I?', self.result, self.is_clear))
        buf.extend(wide_string(self.map_code))
        buf.extend(struct.pack('<?', self.flag))
        # mapGuildPersonCnt
        buf.append(0x17)
        buf.extend(varuint(0))
        if self.is_clear:
            # mapSingleReward
            buf.append(0x17)
            if self.char_uid:
                buf.extend(varuint(1))
                buf.append(0x0f)
                buf.extend(struct.pack('<q', self.char_uid))
                buf.extend(self.reward.encode())
            else:
                buf.extend(varuint(0))
            # nPartyRankFirst, nPartyRankFinal, nBoxGrade, nExtraBoxCost
            buf.extend(struct.pack('<iiii', self.rank_first, self.rank_final, self.box_grade, self.extra_box_cost))
            # vecBonusMonster
            buf.append(0x10)
            buf.extend(varuint(0))
        return bytes(buf)


