"""Dark Blood protocol wire messages - Dungeon domain."""
from dataclasses import dataclass, field
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import read_varuint, varuint, wide_string
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
class ChangeDungeonPenaltyNot:
    """Opcode 2085: eEGS_CHANGE_DUNGEON_PENALTY_NOT (0x0078FA70)."""
    in_dungeon: bool = False
    is_penalty: bool = False
    penalty_level: int = 0
    penalty_id: int = 0
    duration: int = 0

    def encode(self) -> bytes:
        return struct.pack('<??hii', self.in_dungeon, self.is_penalty, self.penalty_level, self.penalty_id, self.duration)
