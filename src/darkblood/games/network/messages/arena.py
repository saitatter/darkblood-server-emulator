"""Dark Blood protocol wire messages - Arena and PvP Duels domain.

Binary schemas recovered from DarkBlood.exe (SHA-256 a82ae3d7...)
and verified against client dispatchers.
"""
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
            + b'\x1e' + blob
            + b'\x17' + varuint(0)
        )


@dataclass
class DuelStartNot:
    """Opcode 5099 (eERC_DUEL_START_NOT): Notification to players that duel countdown begins.

    Binary schema: Table case in 0x006D2610 -> 0x006CCDF0.
    Layout: tag 0x1E struct (36 bytes).
    """
    session_blob: bytes = field(default_factory=lambda: bytes(36))

    def encode(self) -> bytes:
        blob = self.session_blob.ljust(36, b'\x00')[:36]
        return b'\x1e' + blob


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
        return struct.pack('<I', self.result) + b'\x1e' + blob


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


# ==============================================================================
# Arena Lobby, Rooms, Teams & Matchmaking (Opcodes 2304-2309, 5269-5275)
# ==============================================================================

@dataclass
class ArenaSquareListReq:
    """Opcode 2304 (eEGS_ARENA_SQUARELIST_REQ): Request arena square/channel list."""
    server_key: int = 1

    def encode(self) -> bytes:
        return struct.pack('<iI', 0x7fffffff, self.server_key)

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaSquareListReq':
        if len(data) >= 8:
            return cls(server_key=struct.unpack_from('<I', data, 4)[0])
        return cls()


@dataclass
class ArenaSquareListAck:
    """Opcode 2305 (eEGS_ARENA_SQUARELIST_ACK): List of arena channels.

    Binary schema: Case in 0x004B7E80 -> 0x004B67F0.
    Layout: u32 result, tag 0x10 vector of square entries (u64, wstring, u32, u32, u32).
    """
    result: int = 0
    squares: list = field(default_factory=list)

    def encode(self) -> bytes:
        # Default single channel if none provided
        sq_bytes = bytearray()
        items = self.squares if self.squares else [{'id': 101, 'name': 'Arena Channel 1', 'load': 50}]
        for sq in items:
            sq_id = sq.get('id', 101)
            name = sq.get('name', 'Arena 1')
            load = sq.get('load', 50)
            sq_bytes.extend(
                b'\x1e' + struct.pack('<q', sq_id)
                + wide_string(name)
                + struct.pack('<III', 0, load, 0)
            )
        return (
            struct.pack('<I', self.result)
            + b'\x10' + varuint(len(items))
            + bytes(sq_bytes)
        )


@dataclass
class ArenaGetRoomListReq:
    """Opcode 2306 (eEGS_ARENA_GET_ROOMLIST_REQ): Request arena rooms list."""
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
    """Opcode 2307 (eEGS_ARENA_GET_ROOMLIST_ACK): List of open arena match rooms.

    Binary schema: Case in 0x004C6080 -> 0x004B96D0.
    Layout: u32 result, bool flag, i32 count, tag 0x10 vector of rooms.
    """
    result: int = 0
    flag: bool = True
    rooms: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (
            struct.pack('<I?i', self.result, self.flag, len(self.rooms))
            + b'\x10' + varuint(len(self.rooms))
        )


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


@dataclass
class ArenaJoinSquareAck:
    """Opcode 5138 (eERC_ARENA_JOIN_SQUARE_ACK): Connect to arena town channel."""
    result: int = 0
    square_id: int = 101

    def encode(self) -> bytes:
        return struct.pack('<Iq', self.result, self.square_id)


@dataclass
class ArenaTeamCreateReq:
    """Opcode 5269 (eERC_ARENA_TEAM_CREATE_REQ): Create an arena PvP team."""
    team_name: str = "Gladiators"
    team_type: int = 1

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
    """Opcode 5270 (eERC_ARENA_TEAM_CREATE_ACK): Arena team created.

    Binary schema: Table case in 0x0049D180 -> 0x0049BEF0.
    Layout: u32 result, tag 0x1E struct (i64 team_id, i16 type, i32 score, i32 member_cnt,
    wstring name, wstring leader, wstring notice).
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
            + b'\x1e'
            + struct.pack('<qhii', self.team_id, self.team_type, self.score, self.member_count)
            + wide_string(self.team_name)
            + wide_string(self.leader_name)
            + wide_string(self.notice)
        )


@dataclass
class ArenaTeamJoinReq:
    """Opcode 5271 (eERC_ARENA_TEAM_JOIN_REQ): Join existing arena team."""
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
    """Opcode 5272 (eERC_ARENA_TEAM_JOIN_ACK): Joined arena team.

    Binary schema: Table case in 0x0049D180 -> 0x0049C4B0.
    Layout: u32 result, tag 0x1E struct (same as 5270).
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
            + b'\x1e'
            + struct.pack('<qhii', self.team_id, self.team_type, self.score, self.member_count)
            + wide_string(self.team_name)
            + wide_string(self.leader_name)
            + wide_string(self.notice)
        )


@dataclass
class ArenaTeamLeaveReq:
    """Opcode 5274 (eERC_ARENA_TEAM_LEAVE_REQ): Leave arena team."""
    def encode(self) -> bytes:
        return b''

    @classmethod
    def decode(cls, data: bytes) -> 'ArenaTeamLeaveReq':
        return cls()


@dataclass
class ArenaTeamLeaveAck:
    """Opcode 5275 (eERC_ARENA_TEAM_LEAVE_ACK): Confirms departure from arena team.

    Binary schema: Table case in 0x0049D180 -> 0x00490100.
    Layout: u32 result, tag 0x1E struct (14 raw bytes).
    """
    result: int = 0

    def encode(self) -> bytes:
        return struct.pack('<I', self.result) + b'\x1e' + bytes(14)


# ==============================================================================
# League Season Arena Rankings (Opcodes 2550 - 2553)
# ==============================================================================

@dataclass
class LeagueSeasonArenaGetRankReq:
    """Opcode 2550 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_REQ): Request season rank ladder."""
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
    """Opcode 2551 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_ACK): Arena ladder rank list.

    Binary schema: Case in 0x0049B230 -> 0x00499DC0.
    Layout: u32 result, i32 season_id, tag 0x10 vector of ranks.
    """
    result: int = 0
    season_id: int = 1
    ranks: list = field(default_factory=list)

    def encode(self) -> bytes:
        return (
            struct.pack('<Ii', self.result, self.season_id)
            + b'\x10' + varuint(len(self.ranks))
        )


@dataclass
class LeagueSeasonArenaGetMyRankReq:
    """Opcode 2552 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_REQ): Request player's personal rank."""
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
    """Opcode 2553 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_ACK): Personal rank reply.

    Binary schema: Table case in 0x0049D180 -> 0x00492A10.
    Layout: u32 result, i32 my_rank.
    """
    result: int = 0
    my_rank: int = 1

    def encode(self) -> bytes:
        return struct.pack('<Ii', self.result, self.my_rank)
