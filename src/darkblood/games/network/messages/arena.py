"""Dark Blood protocol wire messages - Arena, PvP Duels, and League domain.

Binary schemas recovered from DarkBlood.exe (SHA-256 a82ae3d7...)
and verified against client dispatchers:
- 1v1 PvP Town Duels (Opcodes 5097 - 5113, table case in 0x006D2610)
- Arena Channels / Square (Opcodes 2304 / 2305 & alias 2446 / 2447, 0x004B7E80 -> 0x004B67F0)
- Arena Room Management (Opcodes 2306 / 2307 & 2448 / 2449, 5145 / 5146, 5148 / 5149, 5153 / 5154)
- Arena Teams (Opcodes 5269 / 5270 & 2452 / 2453, 5271 / 5272 & 2454 / 2455, 5274 / 5275 & 2456 / 2457)
- League Season Arena Rankings (Opcodes 2550 / 2551 & 2475 / 2476, 2552 / 2553 & 2477 / 2478)
"""
from __future__ import annotations
from dataclasses import dataclass, field
import struct

from darkblood.core.serialization.jser import read_varuint, varuint, wide_string


# ==============================================================================
# 1v1 PvP Town Duels (Opcodes 5097 - 5113)
# ==============================================================================

@dataclass
class DuelRequestReq:
    """Opcode 5100 (eERC_DUEL_REQUEST_REQ): Challenger requests a duel."""
    target_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.target_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'DuelRequestReq':
        if len(data) < 8:
            return cls()
        return cls(target_uid=struct.unpack_from('<q', data)[0])


@dataclass
class DuelRequestAck:
    """Opcode 5101 (eERC_DUEL_REQUEST_ACK): Server confirms duel request to challenger.

    Binary schema: Table case in 0x006D2610 -> 0x006C0A10.
    Layout: u32 result, i64 target_uid, wstring target_name, u8 char_class, u8 level.
    """
    result: int = 0
    target_uid: int = 0
    target_name: str = "Opponent"
    char_class: int = 1
    level: int = 1

    def encode(self) -> bytes:
        return (
            struct.pack('<Iq', self.result, self.target_uid)
            + wide_string(self.target_name)
            + struct.pack('<BB', self.char_class, self.level)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'DuelRequestAck':
        if len(data) < 12:
            return cls()
        res, target_uid = struct.unpack_from('<Iq', data)
        target_name = ""
        char_class = 1
        level = 1
        try:
            length, offset = read_varuint(data, 12)
            target_name = data[offset:offset + length].decode('utf-16le').rstrip('\x00')
            rem = offset + length
            if len(data) >= rem + 2:
                char_class, level = struct.unpack_from('<BB', data, rem)
        except Exception:
            pass
        return cls(result=res, target_uid=target_uid, target_name=target_name,
                   char_class=char_class, level=level)


@dataclass
class DuelStartReq:
    """Opcode 5097 (eERC_DUEL_START_REQ): Both players accept and start the duel."""
    opponent_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.opponent_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'DuelStartReq':
        if len(data) < 8:
            return cls()
        return cls(opponent_uid=struct.unpack_from('<q', data)[0])


@dataclass
class DuelStartAck:
    """Opcode 5098 (eERC_DUEL_START_ACK): Server acknowledges duel combat initialization.

    Binary schema: Table case in 0x006D2610 -> 0x006CBE60.
    Layout: u32 result, tag 0x1E struct (36 bytes), tag 0x17 map.
    """
    result: int = 0
    session_blob: bytes = field(default_factory=lambda: bytes(36))

    def encode(self) -> bytes:
        blob = self.session_blob.ljust(36, b'\x00')[:36]
        return (
            struct.pack('<I', self.result)
            + blob
            + b'\x17' + varuint(0)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'DuelStartAck':
        if len(data) < 4:
            return cls()
        res = struct.unpack_from('<I', data)[0]
        blob = data[4:40] if len(data) >= 40 else bytes(36)
        return cls(result=res, session_blob=blob)


@dataclass
class DuelStartNot:
    """Opcode 5099 (eERC_DUEL_START_NOT): Notification to players that duel countdown begins.

    Binary schema: Table case in 0x006D2610 -> 0x006CCDF0.
    Layout: tag 0x1E struct (36 bytes).
    """
    session_blob: bytes = field(default_factory=lambda: bytes(36))

    def encode(self) -> bytes:
        return self.session_blob.ljust(36, b'\x00')[:36]

    @classmethod
    def decode(cls, data: bytes) -> 'DuelStartNot':
        return cls(session_blob=data[:36] if len(data) >= 36 else bytes(36))


@dataclass
class DuelResultReq:
    """Opcode 5105 (eERC_DUEL_RESULT_REQ): Duel match outcome reported."""
    winner_uid: int = 0
    loser_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<qq', self.winner_uid, self.loser_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'DuelResultReq':
        if len(data) < 16:
            return cls()
        w, l = struct.unpack_from('<qq', data)
        return cls(winner_uid=w, loser_uid=l)


@dataclass
class DuelResultAck:
    """Opcode 5106 (eERC_DUEL_RESULT_ACK): Duel outcome confirmed.

    Binary schema: Table case in 0x006D2610 -> 0x006CC6B0.
    Layout: u32 result, tag 0x1E struct (21 bytes).
    """
    result: int = 0
    result_blob: bytes = field(default_factory=lambda: bytes(21))

    def encode(self) -> bytes:
        blob = self.result_blob.ljust(21, b'\x00')[:21]
        return struct.pack('<I', self.result) + blob

    @classmethod
    def decode(cls, data: bytes) -> 'DuelResultAck':
        if len(data) < 4:
            return cls()
        res = struct.unpack_from('<I', data)[0]
        blob = data[4:25] if len(data) >= 25 else bytes(21)
        return cls(result=res, result_blob=blob)


@dataclass
class DuelGiveupNot:
    """Opcode 5108 (eERC_DUEL_GIVEUP_NOT): Player surrenders duel match."""
    surrender_char_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.surrender_char_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'DuelGiveupNot':
        if len(data) < 8:
            return cls()
        return cls(surrender_char_uid=struct.unpack_from('<q', data)[0])


@dataclass
class DuelRefuseReq:
    """Opcode 5112 (eERC_DUEL_REFUSE_REQ): Target player declines the duel challenge."""
    challenger_uid: int = 0

    def encode(self) -> bytes:
        return struct.pack('<q', self.challenger_uid)

    @classmethod
    def decode(cls, data: bytes) -> 'DuelRefuseReq':
        if len(data) < 8:
            return cls()
        return cls(challenger_uid=struct.unpack_from('<q', data)[0])


@dataclass
class DuelRefuseAck:
    """Opcode 5113 (eERC_DUEL_REFUSE_ACK): Server notifies challenger that duel was declined.

    Binary schema: Table case in 0x006D2610 -> 0x006B4120.
    Layout: u32 result, i64 target_uid, wstring target_name, u8 char_class, u8 level.
    """
    result: int = 0
    target_uid: int = 0
    target_name: str = "Opponent"
    char_class: int = 1
    level: int = 1

    def encode(self) -> bytes:
        return (
            struct.pack('<Iq', self.result, self.target_uid)
            + wide_string(self.target_name)
            + struct.pack('<BB', self.char_class, self.level)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'DuelRefuseAck':
        if len(data) < 12:
            return cls()
        res, target_uid = struct.unpack_from('<Iq', data)
        target_name = ""
        char_class = 1
        level = 1
        try:
            length, offset = read_varuint(data, 12)
            target_name = data[offset:offset + length].decode('utf-16le').rstrip('\x00')
            rem = offset + length
            if len(data) >= rem + 2:
                char_class, level = struct.unpack_from('<BB', data, rem)
        except Exception:
            pass
        return cls(result=res, target_uid=target_uid, target_name=target_name,
                   char_class=char_class, level=level)


# ==============================================================================
# Arena Square Channels (Opcodes 2304 / 2305 & aliases 2446 / 2447)
# ==============================================================================

@dataclass
class ArenaSquareListReq:
    """Opcode 2304 / 2446 (eEGS_ARENA_SQUARELIST_REQ): Request arena square/channel list."""
    server_key: int = 1

    def encode(self) -> bytes:
        return struct.pack('<iI', 0x7fffffff, self.server_key)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaSquareListReq':
        if len(data) >= 8:
            return cls(server_key=struct.unpack_from('<I', data, 4)[0])
        elif len(data) >= 4:
            return cls(server_key=struct.unpack_from('<i', data)[0])
        return cls()


@dataclass
class ArenaSquareListAck:
    """Opcode 2305 / 2447 (eEGS_ARENA_SQUARELIST_ACK): List of arena channels.

    Binary schema: Case in 0x004B7E80 -> 0x004B67F0, element 0x0049F160 -> 0x00A49700.
    Layout: u32 result, tag 0x10 vector of square entries (tag 0x1e, u64 id, wstring name, u32 0, u32 load, u32 0).
    """
    result: int = 0
    squares: list = field(default_factory=list)

    def encode(self) -> bytes:
        sq_bytes = bytearray()
        items = self.squares if self.squares else [{'id': 101, 'name': 'Arena Channel 1', 'load': 50}]
        for sq in items:
            sq_id = sq.get('id', 101)
            name = sq.get('name', 'Arena 1')
            load = sq.get('load', 50)
            sq_bytes.extend(
                b'\x1e'
                + struct.pack('<q', sq_id)
                + wide_string(name)
                + struct.pack('<III', 0, load, 0)
            )
        return (
            struct.pack('<I', self.result)
            + b'\x10' + varuint(len(items))
            + bytes(sq_bytes)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaSquareListAck':
        if len(data) < 4:
            return cls()
        res = struct.unpack_from('<I', data)[0]
        curr = 4
        squares = []
        if curr < len(data) and data[curr] == 0x10:
            curr += 1
            try:
                count, curr = read_varuint(data, curr)
                for _ in range(count):
                    if curr < len(data) and data[curr] == 0x1e:
                        curr += 1
                    sq_id = struct.unpack_from('<q', data, curr)[0]
                    curr += 8
                    l, curr = read_varuint(data, curr)
                    name = data[curr:curr + l].decode('utf-16le').rstrip('\x00')
                    curr += l
                    f1, load, max_u = struct.unpack_from('<III', data, curr)
                    curr += 12
                    squares.append({'id': sq_id, 'name': name, 'load': load})
            except Exception:
                pass
        return cls(result=res, squares=squares)


@dataclass
class ArenaJoinSquareAck:
    """Opcode 5138 (eERC_ARENA_JOIN_SQUARE_ACK): Connect to arena town channel."""
    result: int = 0
    square_id: int = 101

    def encode(self) -> bytes:
        return struct.pack('<Iq', self.result, self.square_id)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaJoinSquareAck':
        if len(data) >= 12:
            res, sq = struct.unpack_from('<Iq', data)
            return cls(result=res, square_id=sq)
        return cls()


# ==============================================================================
# Arena Room Structure & Match Management (Opcodes 2306-2309, 5145-5154)
# ==============================================================================

@dataclass
class ArenaRoomInfo:
    """Arena Match Room data structure (sARENA_ROOM_INFO).

    Binary schema:
    - Base structure (0x00A49380 / 0x00A492F0):
      u64 room_id, wstring name, u16 map_id, u16 game_mode, u32 max_players,
      u64 host_uid, u64 team_id, u32 state, u32 min_level, u16 field10.
    - Extended structure (0x00A50A70 / 0x00A4F330):
      u16 f11, u16 f12, u16 f13, u32 f14, u32 f15, u32 f16, u16 f17,
      wstring password, wstring notice, bool has_custom_map,
      map tag 0x17, u16 f22, u32 f23, u8 f24.
    """
    room_id: int = 1
    room_name: str = "Arena Room"
    map_id: int = 1
    game_mode: int = 1
    max_players: int = 8
    host_uid: int = 0
    team_id: int = 0
    state: int = 0
    min_level: int = 1
    field10: int = 0
    field11: int = 0
    field12: int = 0
    field13: int = 0
    field14: int = 0
    field15: int = 0
    field16: int = 0
    field17: int = 0
    password: str = ""
    notice: str = ""
    has_custom_map: bool = False
    custom_map_bytes: bytes = b''
    field22: int = 0
    field23: int = 0
    field24: int = 0
    members: list = field(default_factory=list)

    def encode(self) -> bytes:
        base = (
            struct.pack('<Q', self.room_id)
            + wide_string(self.room_name)
            + struct.pack('<HHIQQIIH',
                          self.map_id, self.game_mode, self.max_players,
                          self.host_uid, self.team_id, self.state,
                          self.min_level, self.field10)
        )
        extra = (
            struct.pack('<HHHIIIH',
                        self.field11, self.field12, self.field13,
                        self.field14, self.field15, self.field16,
                        self.field17)
            + wide_string(self.password)
            + wide_string(self.notice)
            + struct.pack('<?', self.has_custom_map)
            + (self.custom_map_bytes if self.has_custom_map else b'\x17\x00')
            + struct.pack('<HIB', self.field22, self.field23, self.field24)
        )
        return b'\x1e' + base + extra

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple['ArenaRoomInfo', int]:
        if not data or offset >= len(data):
            return cls(), offset
        curr = offset
        if curr < len(data) and data[curr] == 0x1e:
            curr += 1
        if curr + 8 > len(data):
            return cls(), curr
        room_id = struct.unpack_from('<Q', data, curr)[0]
        curr += 8
        name = ""
        try:
            length, str_off = read_varuint(data, curr)
            name = data[str_off:str_off + length].decode('utf-16le').rstrip('\x00')
            curr = str_off + length
        except Exception:
            pass
        map_id = cls.map_id
        mode = cls.game_mode
        max_p = cls.max_players
        host = cls.host_uid
        team = cls.team_id
        st = cls.state
        min_lvl = cls.min_level
        f10 = cls.field10
        if curr + 32 <= len(data):
            map_id, mode, max_p, host, team, st, min_lvl, f10 = struct.unpack_from('<HHIQQIIH', data, curr)
            curr += 32

        f11 = f12 = f13 = f14 = f15 = f16 = f17 = 0
        if curr + 22 <= len(data):
            f11, f12, f13, f14, f15, f16, f17 = struct.unpack_from('<HHHIIIH', data, curr)
            curr += 22

        pw = ""
        notice = ""
        try:
            if curr < len(data):
                l_pw, o_pw = read_varuint(data, curr)
                pw = data[o_pw:o_pw + l_pw].decode('utf-16le').rstrip('\x00')
                curr = o_pw + l_pw
            if curr < len(data):
                l_not, o_not = read_varuint(data, curr)
                notice = data[o_not:o_not + l_not].decode('utf-16le').rstrip('\x00')
                curr = o_not + l_not
        except Exception:
            pass

        has_map = False
        if curr < len(data):
            has_map = bool(data[curr])
            curr += 1
        if curr < len(data) and data[curr] == 0x17:
            curr += 1
            try:
                m_cnt, curr = read_varuint(data, curr)
            except Exception:
                pass
        f22 = f23 = f24 = 0
        if curr + 7 <= len(data):
            f22, f23, f24 = struct.unpack_from('<HIB', data, curr)
            curr += 7
        return cls(
            room_id=room_id, room_name=name, map_id=map_id, game_mode=mode,
            max_players=max_p, host_uid=host, team_id=team, state=st,
            min_level=min_lvl, field10=f10, field11=f11, field12=f12,
            field13=f13, field14=f14, field15=f15, field16=f16,
            field17=f17, password=pw, notice=notice, has_custom_map=has_map,
            field22=f22, field23=f23, field24=f24
        ), curr


@dataclass
class ArenaGetRoomListReq:
    """Opcode 2306 / 2448 (eEGS_ARENA_GET_ROOMLIST_REQ): Request arena rooms list."""
    page: int = 0

    def encode(self) -> bytes:
        return struct.pack('<i', self.page)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaGetRoomListReq':
        if len(data) >= 4:
            return cls(page=struct.unpack_from('<i', data)[0])
        return cls()


@dataclass
class ArenaGetRoomListAck:
    """Opcode 2307 / 2449 (eEGS_ARENA_GET_ROOMLIST_ACK): List of open arena match rooms.

    Binary schema: Case in 0x004C6080 -> 0x004B96D0, item 0x0049E9C0 -> 0x00A50A70.
    Layout: u32 result, bool flag, i32 count, tag 0x10 vector of ArenaRoomInfo.
    """
    result: int = 0
    flag: bool = True
    rooms: list = field(default_factory=list)

    def encode(self) -> bytes:
        room_bytes = bytearray()
        for r in self.rooms:
            if isinstance(r, ArenaRoomInfo):
                room_bytes.extend(r.encode())
            elif isinstance(r, dict):
                room_bytes.extend(ArenaRoomInfo(**r).encode())
        return (
            struct.pack('<I?i', self.result, self.flag, len(self.rooms))
            + b'\x10' + varuint(len(self.rooms))
            + bytes(room_bytes)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaGetRoomListAck':
        if len(data) < 9:
            return cls()
        res, flag, count = struct.unpack_from('<I?i', data)
        curr = 9
        rooms = []
        if curr < len(data) and data[curr] == 0x10:
            curr += 1
            try:
                vec_count, curr = read_varuint(data, curr)
                for _ in range(vec_count):
                    room, curr = ArenaRoomInfo.decode(data, curr)
                    rooms.append(room)
            except Exception:
                pass
        return cls(result=res, flag=flag, rooms=rooms)


@dataclass
class ArenaCreateRoomReq:
    """Opcode 5153 (eERC_ARENA_CREATE_ROOM_REQ): Client creates match room.

    Binary schema: Serializer at 0x004C21E0 -> 0x0049E980 -> 0x00A4F330.
    """
    room: ArenaRoomInfo = field(default_factory=ArenaRoomInfo)

    def encode(self) -> bytes:
        return self.room.encode()

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaCreateRoomReq':
        if not data:
            return cls()
        room, _ = ArenaRoomInfo.decode(data)
        return cls(room=room)


@dataclass
class ArenaCreateRoomAck:
    """Opcode 5154 (eERC_ARENA_CREATE_ROOM_ACK): Room creation response.

    Binary schema: Case in 0x004C6080 -> 0x004BCCE0.
    Layout: u32 result, tag 0x1E ArenaRoomInfo, tag 0x1E slot config (6 bytes).
    """
    result: int = 0
    room: ArenaRoomInfo = field(default_factory=ArenaRoomInfo)
    slot_config: bytes = field(default_factory=lambda: bytes(6))

    def encode(self) -> bytes:
        return (
            struct.pack('<I', self.result)
            + self.room.encode()
            + b'\x1e' + self.slot_config.ljust(6, b'\x00')[:6]
        )

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaCreateRoomAck':
        if len(data) < 4:
            return cls()
        res = struct.unpack_from('<I', data)[0]
        if len(data) > 4:
            room, offset = ArenaRoomInfo.decode(data, 4)
            slot_config = data[offset:] if len(data) > offset else bytes(6)
            return cls(result=res, room=room, slot_config=slot_config)
        return cls(result=res)


@dataclass
class ArenaJoinRoomReq:
    """Opcode 5145 (eERC_ARENA_JOIN_ROOM_REQ): Player requests joining match room.

    Binary schema: Encoded at 0x004C1C30: u64 room_id, wstring password.
    """
    room_id: int = 0
    password: str = ""

    def encode(self) -> bytes:
        return struct.pack('<Q', self.room_id) + wide_string(self.password)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaJoinRoomReq':
        if len(data) < 8:
            return cls()
        room_id = struct.unpack_from('<Q', data)[0]
        pw = ""
        if len(data) > 8:
            try:
                length, offset = read_varuint(data, 8)
                pw = data[offset:offset + length].decode('utf-16le').rstrip('\x00')
            except Exception:
                pass
        return cls(room_id=room_id, password=pw)


@dataclass
class ArenaJoinRoomAck:
    """Opcode 5146 (eERC_ARENA_JOIN_ROOM_ACK): Confirms joining match room.

    Binary schema: Handled at 0x004C6080 -> 0x004C5380.
    Layout: u32 result, tag 0x1E ArenaRoomInfo, u64 host_uid, tag 0x10 vector of members.
    """
    result: int = 0
    room: ArenaRoomInfo = field(default_factory=ArenaRoomInfo)
    host_uid: int = 0
    members: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (
            struct.pack('<I', self.result)
            + self.room.encode()
            + struct.pack('<Q', self.host_uid)
            + b'\x10' + varuint(len(self.members))
        )

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaJoinRoomAck':
        if len(data) < 4:
            return cls()
        res = struct.unpack_from('<I', data)[0]
        if len(data) > 4:
            room, offset = ArenaRoomInfo.decode(data, 4)
            host_uid = 0
            if offset + 8 <= len(data):
                host_uid = struct.unpack_from('<Q', data, offset)[0]
            return cls(result=res, room=room, host_uid=host_uid)
        return cls(result=res)


@dataclass
class ArenaLeaveRoomReq:
    """Opcode 5148 (eERC_ARENA_LEAVE_ROOM_REQ): Leave arena room."""
    def encode(self) -> bytes:
        return b''

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaLeaveRoomReq':
        return cls()


@dataclass
class ArenaLeaveRoomAck:
    """Opcode 5149 (eERC_ARENA_LEAVE_ROOM_ACK): Confirm room departure.

    Binary schema: Handled at 0x004BB5B0.
    Layout: u32 result, tag 0x10 vector, tag 0x1E struct, tag 0x1E struct.
    """
    result: int = 0

    def encode(self) -> bytes:
        return (
            struct.pack('<I', self.result)
            + b'\x10' + varuint(0)
            + b'\x1e' + bytes(14)
            + b'\x1e' + bytes(14)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaLeaveRoomAck':
        if len(data) >= 4:
            return cls(result=struct.unpack_from('<I', data)[0])
        return cls()


@dataclass
class ArenaGetInviteListReq:
    """Opcode 2308 (eEGS_ARENA_GET_INVITELIST_REQ): Request pending arena invites."""
    def encode(self) -> bytes:
        return b''

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaGetInviteListReq':
        return cls()


@dataclass
class ArenaGetInviteListAck:
    """Opcode 2309 (eEGS_ARENA_GET_INVITELIST_ACK): Pending arena team invites.

    Binary schema: Case in 0x004C5200 -> 0x004B4680.
    Layout: u32 result, tag 0x10 vector.
    """
    result: int = 0
    invites: list = field(default_factory=list)

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x10' + varuint(len(self.invites))

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaGetInviteListAck':
        if len(data) >= 4:
            return cls(result=struct.unpack_from('<I', data)[0])
        return cls()


# ==============================================================================
# Arena Teams (Opcodes 5269 - 5275 & aliases 2452 - 2457)
# ==============================================================================

@dataclass
class ArenaTeamInfo:
    """Arena Team full record."""
    team_id: int = 1
    team_type: int = 1
    score: int = 1000
    member_count: int = 1
    team_name: str = "Gladiators"
    leader_name: str = "Leader"
    notice: str = "Welcome to Arena Team"
    timestamp: int = 0
    leader_uid: int = 0
    field10: int = 0
    field11: int = 0
    field12: int = 0
    members: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (
            struct.pack('<qhii', self.team_id, self.team_type, self.score, self.member_count)
            + wide_string(self.team_name)
            + wide_string(self.leader_name)
            + wide_string(self.notice)
            + struct.pack('<QqIII', self.timestamp, self.leader_uid, self.field10, self.field11, self.field12)
            + b'\x17\x00'
        )


@dataclass
class ArenaTeamCreateReq:
    """Opcode 5269 / 2452 (eERC_ARENA_TEAM_CREATE_REQ): Create an arena PvP team."""
    team_name: str = "Gladiators"
    team_type: int = 1

    def encode(self) -> bytes:
        name_bytes = self.team_name.encode('utf-16le')
        return varuint(len(name_bytes)) + name_bytes + struct.pack('<h', self.team_type)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaTeamCreateReq':
        if not data:
            return cls()
        try:
            length, offset = read_varuint(data, 0)
            name = data[offset:offset + length].decode('utf-16le').rstrip('\x00')
            ttype = struct.unpack_from('<h', data, offset + length)[0] if len(data) >= offset + length + 2 else 1
            return cls(team_name=name, team_type=ttype)
        except Exception:
            return cls()


@dataclass
class ArenaTeamCreateAck:
    """Opcode 5270 / 2453 (eERC_ARENA_TEAM_CREATE_ACK): Arena team created.

    Binary schema: Table case in 0x0049D180 -> 0x0049BEF0.
    Layout: u32 result, i64 team_id, i16 type, i32 score, i32 member_cnt,
    wstring name, wstring leader, wstring notice.
    """
    result: int = 0
    team_id: int = 1
    team_type: int = 1
    score: int = 1000
    member_count: int = 1
    team_name: str = "Gladiators"
    leader_name: str = "Leader"
    notice: str = "Welcome to Arena Team"

    def encode(self) -> bytes:
        return (
            struct.pack('<I', self.result)
            + struct.pack('<qhii', self.team_id, self.team_type, self.score, self.member_count)
            + wide_string(self.team_name)
            + wide_string(self.leader_name)
            + wide_string(self.notice)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaTeamCreateAck':
        if len(data) < 4:
            return cls()
        res = struct.unpack_from('<I', data)[0]
        curr = 4
        if curr < len(data) and data[curr] == 0x1e:
            curr += 1
        if curr + 18 > len(data):
            return cls(result=res)
        tid, ttype, score, mc = struct.unpack_from('<qhii', data, curr)
        curr += 18
        tname = lhead = notice = ""
        try:
            l, curr = read_varuint(data, curr)
            tname = data[curr:curr + l].decode('utf-16le').rstrip('\x00')
            curr += l
            l, curr = read_varuint(data, curr)
            lhead = data[curr:curr + l].decode('utf-16le').rstrip('\x00')
            curr += l
            l, curr = read_varuint(data, curr)
            notice = data[curr:curr + l].decode('utf-16le').rstrip('\x00')
            curr += l
        except Exception:
            pass
        return cls(result=res, team_id=tid, team_type=ttype, score=score,
                   member_count=mc, team_name=tname, leader_name=lhead, notice=notice)


@dataclass
class ArenaTeamJoinReq:
    """Opcode 5271 / 2454 (eERC_ARENA_TEAM_JOIN_REQ): Join existing arena team."""
    team_id: int = 1

    def encode(self) -> bytes:
        return struct.pack('<q', self.team_id)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaTeamJoinReq':
        if len(data) >= 8:
            return cls(team_id=struct.unpack_from('<q', data)[0])
        return cls()


@dataclass
class ArenaTeamJoinAck:
    """Opcode 5272 / 2455 (eERC_ARENA_TEAM_JOIN_ACK): Joined arena team.

    Binary schema: Table case in 0x0049D180 -> 0x0049C4B0.
    Layout: u32 result, i64 team_id, i16 type, i32 score, i32 member_cnt,
    wstring name, wstring leader, wstring notice.
    """
    result: int = 0
    team_id: int = 1
    team_type: int = 1
    score: int = 1000
    member_count: int = 2
    team_name: str = "Gladiators"
    leader_name: str = "Leader"
    notice: str = "Welcome to Arena Team"

    def encode(self) -> bytes:
        return (
            struct.pack('<I', self.result)
            + struct.pack('<qhii', self.team_id, self.team_type, self.score, self.member_count)
            + wide_string(self.team_name)
            + wide_string(self.leader_name)
            + wide_string(self.notice)
        )

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaTeamJoinAck':
        if len(data) < 4:
            return cls()
        res = struct.unpack_from('<I', data)[0]
        curr = 4
        if curr < len(data) and data[curr] == 0x1e:
            curr += 1
        if curr + 18 > len(data):
            return cls(result=res)
        tid, ttype, score, mc = struct.unpack_from('<qhii', data, curr)
        curr += 18
        tname = lhead = notice = ""
        try:
            l, curr = read_varuint(data, curr)
            tname = data[curr:curr + l].decode('utf-16le').rstrip('\x00')
            curr += l
            l, curr = read_varuint(data, curr)
            lhead = data[curr:curr + l].decode('utf-16le').rstrip('\x00')
            curr += l
            l, curr = read_varuint(data, curr)
            notice = data[curr:curr + l].decode('utf-16le').rstrip('\x00')
            curr += l
        except Exception:
            pass
        return cls(result=res, team_id=tid, team_type=ttype, score=score,
                   member_count=mc, team_name=tname, leader_name=lhead, notice=notice)


@dataclass
class ArenaTeamLeaveReq:
    """Opcode 5274 / 2456 (eERC_ARENA_TEAM_LEAVE_REQ): Leave arena team."""
    def encode(self) -> bytes:
        return b''

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaTeamLeaveReq':
        return cls()


@dataclass
class ArenaTeamLeaveAck:
    """Opcode 5275 / 2457 (eERC_ARENA_TEAM_LEAVE_ACK): Confirms departure from arena team.

    Binary schema: Table case in 0x0049D180 -> 0x00490100.
    Layout: u32 result, 14 raw bytes.
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + bytes(14)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaTeamLeaveAck':
        if len(data) >= 4:
            return cls(result=struct.unpack_from('<I', data)[0])
        return cls()


# ==============================================================================
# League Season Arena Rankings (Opcodes 2550 - 2553 & aliases 2475 - 2478)
# ==============================================================================

@dataclass
class LeagueRankEntry:
    """Leaderboard entry for PvP League ranking ladder.

    Binary schema: 0x00475AA0 -> 0x00A4A120.
    Layout: tag 0x1E, u32 rank, u64 char_uid, wstring name, u32 score,
    u8 char_class, u8 char_level, u32 wins, u32 losses, u32 draws, u32 rating, u32 tier.
    """
    rank: int = 1
    char_uid: int = 10001
    char_name: str = "Gladiator"
    score: int = 1500
    char_class: int = 1
    char_level: int = 50
    wins: int = 10
    losses: int = 2
    draws: int = 0
    rating: int = 1500
    tier: int = 1

    def encode(self) -> bytes:
        return (
            b'\x1e'
            + struct.pack('<IQ', self.rank, self.char_uid)
            + wide_string(self.char_name)
            + struct.pack('<IBBIIIII',
                           self.score, self.char_class, self.char_level,
                           self.wins, self.losses, self.draws,
                           self.rating, self.tier)
        )

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> tuple['LeagueRankEntry', int]:
        if offset >= len(data):
            return cls(), offset
        curr = offset
        if curr < len(data) and data[curr] == 0x1e:
            curr += 1
        if curr + 12 > len(data):
            return cls(), curr
        rank, char_uid = struct.unpack_from('<IQ', data, curr)
        curr += 12
        name = ""
        try:
            length, str_off = read_varuint(data, curr)
            name = data[str_off:str_off + length].decode('utf-16le').rstrip('\x00')
            curr = str_off + length
        except Exception:
            pass
        score = cls.score
        c_class = cls.char_class
        level = cls.char_level
        wins = cls.wins
        losses = cls.losses
        draws = cls.draws
        rating = cls.rating
        tier = cls.tier
        if curr + 26 <= len(data):
            score, c_class, level, wins, losses, draws, rating, tier = struct.unpack_from('<IBBIIIII', data, curr)
            curr += 26
        return cls(
            rank=rank, char_uid=char_uid, char_name=name, score=score,
            char_class=c_class, char_level=level, wins=wins, losses=losses,
            draws=draws, rating=rating, tier=tier
        ), curr


@dataclass
class LeagueSeasonArenaGetRankReq:
    """Opcode 2550 / 2475 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_REQ): Request season rank ladder."""
    season_id: int = 1

    def encode(self) -> bytes:
        return struct.pack('<i', self.season_id)

    @classmethod
    def decode(cls, data: bytes) -> 'LeagueSeasonArenaGetRankReq':
        if len(data) >= 4:
            return cls(season_id=struct.unpack_from('<i', data)[0])
        return cls()


@dataclass
class LeagueSeasonArenaGetRankAck:
    """Opcode 2551 / 2476 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_ACK): Arena ladder rank list.

    Binary schema: Case in 0x0049B230 -> 0x00499DC0.
    Layout: u32 result, i32 season_id, tag 0x10 vector of LeagueRankEntry, tag 0x1E footer.
    """
    result: int = 0
    season_id: int = 1
    ranks: list = field(default_factory=list)

    def encode(self) -> bytes:
        rank_bytes = bytearray()
        for r in self.ranks:
            if isinstance(r, LeagueRankEntry):
                rank_bytes.extend(r.encode())
            elif isinstance(r, dict):
                entry = LeagueRankEntry(**r)
                rank_bytes.extend(entry.encode())
        footer = b'\x1e' + struct.pack('<6H', 0, 0, 0, 0, 0, 0)
        return (
            struct.pack('<Ii', self.result, self.season_id)
            + b'\x10' + varuint(len(self.ranks))
            + bytes(rank_bytes)
            + footer
        )

    @classmethod
    def decode(cls, data: bytes) -> 'LeagueSeasonArenaGetRankAck':
        if len(data) < 8:
            return cls()
        res, season = struct.unpack_from('<Ii', data)
        curr = 8
        ranks = []
        if curr < len(data) and data[curr] == 0x10:
            curr += 1
            try:
                count, curr = read_varuint(data, curr)
                for _ in range(count):
                    entry, curr = LeagueRankEntry.decode(data, curr)
                    ranks.append(entry)
            except Exception:
                pass
        return cls(result=res, season_id=season, ranks=ranks)


@dataclass
class LeagueSeasonArenaGetMyRankReq:
    """Opcode 2552 / 2477 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_REQ): Request player's personal rank."""
    season_id: int = 1

    def encode(self) -> bytes:
        return struct.pack('<i', self.season_id)

    @classmethod
    def decode(cls, data: bytes) -> 'LeagueSeasonArenaGetMyRankReq':
        if len(data) >= 4:
            return cls(season_id=struct.unpack_from('<i', data)[0])
        return cls()


@dataclass
class LeagueSeasonArenaGetMyRankAck:
    """Opcode 2553 / 2478 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_ACK): Personal rank reply.

    Binary schema: Table case in 0x0049D180 -> 0x00492A10.
    Layout: u32 result, i32 my_rank.
    """
    result: int = 0
    my_rank: int = 1

    def encode(self) -> bytes:
        return struct.pack('<Ii', self.result, self.my_rank)

    @classmethod
    def decode(cls, data: bytes) -> 'LeagueSeasonArenaGetMyRankAck':
        if len(data) >= 8:
            res, rank = struct.unpack_from('<Ii', data)
            return cls(result=res, my_rank=rank)
        return cls()
