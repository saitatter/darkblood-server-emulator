"""Arena matches, teams, ladder rankings, and 1v1 town duels handlers.

Binary schemas recovered from DarkBlood.exe (SHA-256 a82ae3d7...)
and verified against client dispatchers:
- 1v1 Town Duels (Opcodes 5097 - 5113, table case in 0x006D2610)
- Arena Channels (Opcodes 2304 / 2305, 0x004B7E80 -> 0x004B67F0)
- Arena Room Management (Opcodes 2306 / 2307 & 2448 / 2449, 5145 / 5146, 5148 / 5149, 5153 / 5154)
- Arena Teams (Opcodes 5269 / 5270 & 2452 / 2453, 5271 / 5272 & 2454 / 2455, 5274 / 5275 & 2456 / 2457)
- League Season Arena Rankings (Opcodes 2550 / 2551 & 2475 / 2476, 2552 / 2553 & 2477 / 2478)
"""
from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import (
    ArenaCreateRoomAck,
    ArenaCreateRoomReq,
    ArenaGetInviteListAck,
    ArenaGetInviteListReq,
    ArenaGetRoomListAck,
    ArenaSquare,
    ArenaGetRoomListReq,
    ArenaJoinRoomAck,
    ArenaJoinRoomReq,
    ArenaLeaveRoomAck,
    ArenaLeaveRoomReq,
    ArenaRoomInfo,
    ArenaSquareListAck,
    ArenaSquareListReq,
    ArenaTeamCreateAck,
    ArenaTeamCreateReq,
    ArenaTeamInfo,
    ArenaTeamJoinAck,
    ArenaTeamJoinReq,
    ArenaTeamLeaveAck,
    ArenaTeamLeaveReq,
    DuelGiveupNot,
    DuelRefuseAck,
    DuelRefuseReq,
    DuelRequestAck,
    DuelRequestReq,
    DuelResultAck,
    DuelResultReq,
    DuelStartAck,
    DuelStartNot,
    DuelStartReq,
    LeagueRankEntry,
    LeagueSeasonArenaGetMyRankAck,
    LeagueSeasonArenaGetMyRankReq,
    LeagueSeasonArenaGetRankAck,
    LeagueSeasonArenaGetRankReq,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService


class ArenaHandlers(BaseDomainService):
    """Arena matches, teams, ladder rankings, and 1v1 town duels handlers."""

    # Server-wide shared state for rooms, teams, and leaderboard rankings
    _arena_rooms: Dict[int, ArenaRoomInfo] = {}
    _arena_room_members: Dict[int, list] = {}  # room id -> member dicts (server state, not on the wire)
    _arena_teams: Dict[int, ArenaTeamInfo] = {}
    _leaderboard: List[LeagueRankEntry] = []
    _room_id_counter: int = 1
    _team_id_counter: int = 1

    @classmethod
    def get_leaderboard(cls, season_id: int = 1) -> List[LeagueRankEntry]:
        """Returns or initializes realistic ranked league leaderboard."""
        if not cls._leaderboard:
            cls._leaderboard = [
                LeagueRankEntry(rank=1, char_uid=90001, char_name="BloodLord", score=2450,
                                char_class=1, char_level=60, wins=88, losses=6, draws=1, rating=2450, tier=1),
                LeagueRankEntry(rank=2, char_uid=90002, char_name="ShadowBlade", score=2320,
                                char_class=3, char_level=59, wins=75, losses=12, draws=3, rating=2320, tier=1),
                LeagueRankEntry(rank=3, char_uid=90003, char_name="ArchMage", score=2190,
                                char_class=2, char_level=57, wins=68, losses=16, draws=2, rating=2190, tier=1),
                LeagueRankEntry(rank=4, char_uid=90004, char_name="IronPaladin", score=2050,
                                char_class=1, char_level=55, wins=54, losses=19, draws=5, rating=2050, tier=2),
                LeagueRankEntry(rank=5, char_uid=90005, char_name="NightStalker", score=1940,
                                char_class=4, char_level=53, wins=48, losses=22, draws=1, rating=1940, tier=2),
                LeagueRankEntry(rank=6, char_uid=90006, char_name="StormRuler", score=1820,
                                char_class=2, char_level=50, wins=40, losses=25, draws=4, rating=1820, tier=2),
                LeagueRankEntry(rank=7, char_uid=90007, char_name="DeathWhisper", score=1710,
                                char_class=3, char_level=48, wins=35, losses=28, draws=2, rating=1710, tier=3),
                LeagueRankEntry(rank=8, char_uid=90008, char_name="SilverShield", score=1600,
                                char_class=1, char_level=45, wins=29, losses=30, draws=3, rating=1600, tier=3),
                LeagueRankEntry(rank=9, char_uid=90009, char_name="FlameWeaver", score=1510,
                                char_class=2, char_level=42, wins=24, losses=32, draws=1, rating=1510, tier=3),
                LeagueRankEntry(rank=10, char_uid=90010, char_name="SwiftArrow", score=1420,
                                char_class=4, char_level=40, wins=19, losses=35, draws=2, rating=1420, tier=4),
            ]
        return cls._leaderboard

    def _get_active_char_info(self) -> tuple[int, str, int, int]:
        """Returns (uid, name, class, level) of the active session character."""
        char = self.current_char()
        if char is None:
            return 0, '', 0, 0
        return char['id'], char['name'], char['char_class'], char['level']

    # ==========================================================================
    # 1v1 Town Duels (Opcodes 5097 - 5113)
    # ==========================================================================

    @packet_handler(DuelRequestReq)
    async def handle_duel_request(self, correlation: int, body: bytes):
        """Opcode 5100 (eERC_DUEL_REQUEST_REQ) -> 5101 (eERC_DUEL_REQUEST_ACK).

        Client table case: 0x006D2610 -> 0x006C0A10.
        Decodes challenged target UID and delivers duel challenge confirmation.
        """
        req = DuelRequestReq.decode(body)
        self.transport.record('duel-request-req', body, target_uid=req.target_uid)
        ack = DuelRequestAck(
            result=0,
            target_uid=req.target_uid,
            target_name="Challenger",
            char_class=1,
            level=20
        ).encode()
        await self.transport.send_event(event(5101, ack, correlation),
                                        note=f'duel request ack (target={req.target_uid})')

    @packet_handler(DuelStartReq)
    async def handle_duel_start(self, correlation: int, body: bytes):
        """Opcode 5097 (eERC_DUEL_START_REQ) -> 5098 (eERC_DUEL_START_ACK) & 5099 (DuelStartNot).

        Client table case: 0x006D2610 -> 0x006CBE60.
        Initializes duel combat session between two players and starts countdown.
        """
        req = DuelStartReq.decode(body)
        self.transport.record('duel-start-req', body, opponent_uid=req.opponent_uid)
        ack = DuelStartAck(result=0).encode()
        await self.transport.send_event(event(5098, ack, correlation),
                                        note=f'duel start ack (opponent={req.opponent_uid})')
        not_start = DuelStartNot().encode()
        await self.transport.send_event(event(5099, not_start),
                                        note=f'duel start not (opponent={req.opponent_uid})')

    @packet_handler(DuelResultReq)
    async def handle_duel_result(self, correlation: int, body: bytes):
        """Opcode 5105 (eERC_DUEL_RESULT_REQ) -> 5106 (eERC_DUEL_RESULT_ACK).

        Client table case: 0x006D2610 -> 0x006CC6B0.
        Records duel winner/loser and displays victory/defeat banner.
        """
        req = DuelResultReq.decode(body)
        self.transport.record('duel-result-req', body, winner=req.winner_uid, loser=req.loser_uid)
        ack = DuelResultAck(result=0).encode()
        await self.transport.send_event(event(5106, ack, correlation), note='duel result ack')

    @packet_handler(DuelRefuseReq)
    async def handle_duel_refuse(self, correlation: int, body: bytes):
        """Opcode 5112 (eERC_DUEL_REFUSE_REQ) -> 5113 (eERC_DUEL_REFUSE_ACK).

        Client table case: 0x006D2610 -> 0x006B4120.
        Notifies challenger that the challenge was declined.
        """
        req = DuelRefuseReq.decode(body)
        self.transport.record('duel-refuse-req', body, challenger_uid=req.challenger_uid)
        ack = DuelRefuseAck(
            result=0,
            target_uid=req.challenger_uid,
            target_name="Challenger",
            char_class=1,
            level=20
        ).encode()
        await self.transport.send_event(event(5113, ack, correlation),
                                        note=f'duel refuse ack (challenger={req.challenger_uid})')

    # ==========================================================================
    # Arena Channels / Square (Opcodes 2304 / 2305)
    # ==========================================================================

    @packet_handler(ArenaSquareListReq)
    async def handle_arena_square_list(self, correlation: int, body: bytes):
        """Opcode 2304 -> 2305 / 2447.

        Client handler: 0x004B7E80 -> 0x004B67F0.
        Returns the list of arena channels / square lobbies.
        """
        req = ArenaSquareListReq.decode(body)
        self.transport.record('arena-squarelist-req', body, server_key=req.server_key)
        squares = [
            ArenaSquare(square_id=101, name='Colosseum Channel 1', load=45),
            ArenaSquare(square_id=102, name='Gladiator Channel 2', load=20),
        ]
        ack = ArenaSquareListAck(result=0, squares=squares).encode()
        await self.transport.send_event(event(2305, ack, correlation), note='arena square list ack')

    # ==========================================================================
    # Arena Room Management (Opcodes 2306 / 2307, 5145-5154)
    # ==========================================================================

    @packet_handler(ArenaGetRoomListReq)
    async def handle_arena_get_room_list(self, correlation: int, body: bytes):
        """Opcode 2306 -> 2307 / 2449.

        Client handler: 0x004C6080 -> 0x004B96D0.
        Returns list of open arena match rooms.
        """
        req = ArenaGetRoomListReq.decode(body)
        self.transport.record('arena-get-roomlist-req', body, page=req.page)
        rooms = list(self._arena_rooms.values())
        ack = ArenaGetRoomListAck(result=0, flag=True, room_count=len(rooms), rooms=rooms).encode()
        await self.transport.send_event(event(2307, ack, correlation), note='arena get room list ack')

    @packet_handler(ArenaCreateRoomReq)
    async def handle_arena_create_room(self, correlation: int, body: bytes):
        """Opcode 5153 (eERC_ARENA_CREATE_ROOM_REQ) -> 5154 (eERC_ARENA_CREATE_ROOM_ACK).

        Client handler: 0x004C6080 -> 0x004BCCE0.
        Creates an arena PvP match room.
        """
        req = ArenaCreateRoomReq.decode(body)
        char_uid, char_name, char_class, char_level = self._get_active_char_info()
        room = req.room
        if not room.room_id or room.room_id <= 0:
            room.room_id = ArenaHandlers._room_id_counter
            ArenaHandlers._room_id_counter += 1
        if not room.room_name:
            room.room_name = f"{char_name}'s Colosseum"
        room.host_uid = char_uid
        room.team_id = getattr(self, '_current_arena_team_id', 0) or 1
        ArenaHandlers._arena_room_members[room.room_id] = [{
            'uid': char_uid,
            'name': char_name,
            'class': char_class,
            'level': char_level,
        }]
        ArenaHandlers._arena_rooms[room.room_id] = room
        self._current_arena_room_id = room.room_id

        self.transport.record('arena-create-room-req', body, room_id=room.room_id, name=room.room_name)
        ack = ArenaCreateRoomAck(result=0, room=room).encode()
        await self.transport.send_event(event(5154, ack, correlation),
                                        note=f'arena create room ack (id={room.room_id}, name={room.room_name})')

    @packet_handler(ArenaJoinRoomReq)
    async def handle_arena_join_room(self, correlation: int, body: bytes):
        """Opcode 5145 (eERC_ARENA_JOIN_ROOM_REQ) -> 5146 (eERC_ARENA_JOIN_ROOM_ACK).

        Client handler: 0x004C6080 -> 0x004C5380.
        Joins an existing arena PvP match room.
        """
        req = ArenaJoinRoomReq.decode(body)
        char_uid, char_name, char_class, char_level = self._get_active_char_info()
        room = ArenaHandlers._arena_rooms.get(req.room_id)
        if not room:
            room = ArenaRoomInfo(
                room_id=req.room_id or 1,
                room_name="Colosseum Arena",
                host_uid=char_uid,
            )
            ArenaHandlers._arena_rooms[room.room_id] = room

        member_entry = {'uid': char_uid, 'name': char_name, 'class': char_class, 'level': char_level}
        members = ArenaHandlers._arena_room_members.setdefault(room.room_id, [])
        if not any(m.get('uid') == char_uid for m in members):
            members.append(member_entry)
        self._current_arena_room_id = room.room_id

        self.transport.record('arena-join-room-req', body, room_id=req.room_id)
        ack = ArenaJoinRoomAck(result=0, room=room, host_uid=room.host_uid).encode()
        await self.transport.send_event(event(5146, ack, correlation),
                                        note=f'arena join room ack (room={room.room_id})')

    @packet_handler(ArenaLeaveRoomReq)
    async def handle_arena_leave_room(self, correlation: int, body: bytes):
        """Opcode 5148 (eERC_ARENA_LEAVE_ROOM_REQ) -> 5149 (eERC_ARENA_LEAVE_ROOM_ACK).

        Client handler: 0x004BB5B0.
        Leaves current match room and updates player count.
        """
        char_uid, _, _, _ = self._get_active_char_info()
        curr_room_id = getattr(self, '_current_arena_room_id', None)
        if curr_room_id and curr_room_id in ArenaHandlers._arena_rooms:
            room = ArenaHandlers._arena_rooms[curr_room_id]
            members = [m for m in ArenaHandlers._arena_room_members.get(curr_room_id, [])
                       if m.get('uid') != char_uid]
            ArenaHandlers._arena_room_members[curr_room_id] = members
            if not members:
                ArenaHandlers._arena_rooms.pop(curr_room_id, None)
                ArenaHandlers._arena_room_members.pop(curr_room_id, None)
            self._current_arena_room_id = None

        self.transport.record('arena-leave-room-req', body)
        ack = ArenaLeaveRoomAck(result=0).encode()
        await self.transport.send_event(event(5149, ack, correlation), note='arena leave room ack')

    @packet_handler(ArenaGetInviteListReq)
    async def handle_arena_get_invite_list(self, correlation: int, body: bytes):
        """Opcode 2308 (eEGS_ARENA_GET_INVITELIST_REQ) -> 2309 (eEGS_ARENA_GET_INVITELIST_ACK).

        Client handler: 0x004C5200 -> 0x004B4680.
        Returns pending arena match invitations.
        """
        ack = ArenaGetInviteListAck(result=0).encode()
        await self.transport.send_event(event(2309, ack, correlation), note='arena get invite list ack')

    # ==========================================================================
    # Arena Teams (Opcodes 5269 - 5275)
    # ==========================================================================

    @packet_handler(ArenaTeamCreateReq)
    async def handle_arena_team_create(self, correlation: int, body: bytes):
        """Opcode 5269 / 2452 -> 5270 / 2453.

        Client handler: 0x0049D180 -> 0x0049BEF0.
        Creates an arena PvP team.
        """
        req = ArenaTeamCreateReq.decode(body)
        char_uid, char_name, _, _ = self._get_active_char_info()
        team_id = ArenaHandlers._team_id_counter
        ArenaHandlers._team_id_counter += 1

        team = ArenaTeamInfo(
            team_id=team_id,
            team_type=req.team_type,
            score=1000,
            member_count=1,
            team_name=req.team_name,
            leader_name=char_name,
            leader_uid=char_uid,
            notice="Ready for Arena combat",
        )
        ArenaHandlers._arena_teams[team_id] = team
        self._current_arena_team_id = team_id

        self.transport.record('arena-team-create-req', body, team_name=req.team_name)
        ack = ArenaTeamCreateAck(
            result=0,
            team_id=team.team_id,
            team_type=team.team_type,
            score=team.score,
            member_count=team.member_count,
            team_name=team.team_name,
            leader_name=team.leader_name,
            notice=team.notice,
        ).encode()
        await self.transport.send_event(event(5270, ack, correlation),
                                        note=f'arena team create ack (name={req.team_name})')

    @packet_handler(ArenaTeamJoinReq)
    async def handle_arena_team_join(self, correlation: int, body: bytes):
        """Opcode 5271 / 2454 -> 5272 / 2455.

        Client handler: 0x0049D180 -> 0x0049C4B0.
        Joins an existing arena PvP team.
        """
        req = ArenaTeamJoinReq.decode(body)
        team = ArenaHandlers._arena_teams.get(req.team_id)
        if not team:
            team = ArenaTeamInfo(
                team_id=req.team_id,
                team_type=1,
                score=1000,
                member_count=1,
                team_name="Gladiators",
                leader_name="Leader",
                notice="Welcome to Arena Team",
            )
            ArenaHandlers._arena_teams[req.team_id] = team

        team.member_count += 1
        self._current_arena_team_id = team.team_id

        self.transport.record('arena-team-join-req', body, team_id=req.team_id)
        ack = ArenaTeamJoinAck(
            result=0,
            team_id=team.team_id,
            team_type=team.team_type,
            score=team.score,
            member_count=team.member_count,
            team_name=team.team_name,
            leader_name=team.leader_name,
            notice=team.notice,
        ).encode()
        await self.transport.send_event(event(5272, ack, correlation),
                                        note=f'arena team join ack (team={req.team_id})')

    @packet_handler(ArenaTeamLeaveReq)
    async def handle_arena_team_leave(self, correlation: int, body: bytes):
        """Opcode 5274 / 2456 -> 5275 / 2457.

        Client handler: 0x0049D180 -> 0x00490100.
        Departs from current arena team.
        """
        curr_team = getattr(self, '_current_arena_team_id', None)
        if curr_team and curr_team in ArenaHandlers._arena_teams:
            team = ArenaHandlers._arena_teams[curr_team]
            team.member_count = max(0, team.member_count - 1)
            self._current_arena_team_id = None

        ack = ArenaTeamLeaveAck(result=0).encode()
        await self.transport.send_event(event(5275, ack, correlation), note='arena team leave ack')

    # ==========================================================================
    # League Season Arena Rankings (Opcodes 2550 - 2553)
    # ==========================================================================

    @packet_handler(LeagueSeasonArenaGetRankReq)
    async def handle_league_season_arena_get_rank(self, correlation: int, body: bytes):
        """Opcode 2550 / 2475 -> 2551 / 2476.

        Client handler: 0x0049B230 -> 0x00499DC0.
        Returns league season rank leaderboard.
        """
        req = LeagueSeasonArenaGetRankReq.decode(body)
        ranks = ArenaHandlers.get_leaderboard(req.season_id)
        ack = LeagueSeasonArenaGetRankAck(result=0, season_id=req.season_id, ranks=ranks).encode()
        await self.transport.send_event(event(2551, ack, correlation),
                                        note=f'league season arena get rank ack (season={req.season_id})')

    @packet_handler(LeagueSeasonArenaGetMyRankReq)
    async def handle_league_season_arena_get_my_rank(self, correlation: int, body: bytes):
        """Opcode 2552 / 2477 -> 2553 / 2478.

        Client handler: 0x0049D180 -> 0x00492A10.
        Returns player's rank on the arena ladder.
        """
        req = LeagueSeasonArenaGetMyRankReq.decode(body)
        char_uid, char_name, _, _ = self._get_active_char_info()
        ranks = ArenaHandlers.get_leaderboard(req.season_id)
        my_rank = 1
        for entry in ranks:
            if entry.char_uid == char_uid or entry.char_name == char_name:
                my_rank = entry.rank
                break
        ack = LeagueSeasonArenaGetMyRankAck(result=0, my_rank=my_rank).encode()
        await self.transport.send_event(event(2553, ack, correlation),
                                        note=f'league season arena get my rank ack (season={req.season_id})')

    # ==========================================================================
    # Rock-Paper-Scissors Minigame (GBB: Opcodes 2715 - 2720)
    # ==========================================================================

    @packet_handler(2715)
    async def handle_minigame_gbb_start(self, correlation: int, body: bytes):
        """Opcode 2715 (eEGS_MINIGAME_GBB_START_REQ, 0x007A8280) -> 2716."""
        from darkblood.games.network.messages.arena import MinigameGbbStartAck
        await self.reply(MinigameGbbStartAck(result=0), correlation, note='minigame gbb start ack')

    @packet_handler(2717)
    async def handle_gbb_challenge(self, correlation: int, body: bytes):
        """Opcode 2717 (eEGS_GBB_CHALLENGE_REQ, 0x007A8300) -> 2718."""
        import random
        from darkblood.games.network.messages.arena import GbbChallengeAck, GbbChallengeReq
        req = GbbChallengeReq.decode(body)
        server_choice = random.randint(0, 2)
        if req.choice == server_choice:
            outcome = 0  # draw
        elif (req.choice - server_choice) % 3 == 1:
            outcome = 1  # win
        else:
            outcome = 2  # lose
        await self.reply(GbbChallengeAck(result=0, server_choice=server_choice, outcome=outcome),
                         correlation, note=f'gbb challenge ack (user={req.choice} srv={server_choice} out={outcome})')

    @packet_handler(2719)
    async def handle_gbb_giveup(self, correlation: int, body: bytes):
        """Opcode 2719 (eEGS_GBB_GIVEUP_REQ, 0x007A83A0) -> 2720."""
        from darkblood.games.network.messages.arena import GbbGiveupAck
        await self.reply(GbbGiveupAck(result=0), correlation, note='gbb giveup ack')

    # ==========================================================================
    # Extended Arena Room, Square, Team, League CharStat & Random Matching
    # ==========================================================================

    @packet_handler(5142)
    async def handle_arena_join_layer(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaJoinLayerAck, ArenaJoinLayerReq
        req = ArenaJoinLayerReq.decode(body)
        await self.reply(
            ArenaJoinLayerAck(result=0, arena_square_uid=1, join_layer_net_id=req.layer_net_id, join_square_uid=1),
            correlation, note=f'arena join layer ack (layer={req.layer_net_id})',
        )

    @packet_handler(5163)
    async def handle_arena_banish_user(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaBanishUserAck, ArenaBanishUserReq
        req = ArenaBanishUserReq.decode(body)
        await self.reply(ArenaBanishUserAck(result=0), correlation,
                         note=f'arena banish user ack (target={req.target_uid})')

    @packet_handler(5168)
    async def handle_arena_change_room_host(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaChangeRoomHostAck, ArenaChangeRoomHostReq
        req = ArenaChangeRoomHostReq.decode(body)
        await self.reply(ArenaChangeRoomHostAck(result=0, new_host_uid=req.new_host_uid), correlation,
                         note=f'arena change room host ack (host={req.new_host_uid})')

    @packet_handler(5172)
    async def handle_arena_start_game(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaStartGameAck
        await self.reply(ArenaStartGameAck(result=0, rand_sync=1, played_map_id=1), correlation,
                         note='arena start game ack')

    @packet_handler(5182)
    async def handle_arena_ready_game(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaReadyGameAck, ArenaReadyGameReq
        req = ArenaReadyGameReq.decode(body)
        char_uid, _, _, _ = self._get_active_char_info()
        await self.reply(ArenaReadyGameAck(result=0, char_uid=char_uid, is_ready=req.is_ready), correlation,
                         note=f'arena ready game ack (ready={req.is_ready})')

    @packet_handler(5202)
    async def handle_arena_random_matching_request(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaRandomMatchingRequestAck
        await self.reply(ArenaRandomMatchingRequestAck(result=0), correlation,
                         note='arena random matching request ack')

    @packet_handler(5265)
    async def handle_arena_change_room_char_info(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaChangeRoomCharInfoAck, ArenaChangeRoomCharInfoReq
        req = ArenaChangeRoomCharInfoReq.decode(body)
        char_uid, _, _, _ = self._get_active_char_info()
        await self.reply(
            ArenaChangeRoomCharInfoAck(result=0, char_uid=char_uid, team_id=req.team_id, is_ready=req.is_ready),
            correlation, note=f'arena change room char info ack (team={req.team_id})',
        )

    @packet_handler(5267)
    async def handle_arena_change_slot_char_info(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaChangeSlotCharInfoAck
        await self.reply(ArenaChangeSlotCharInfoAck(result=0), correlation,
                         note='arena change slot char info ack')

    @packet_handler(5282)
    async def handle_arena_team_banish(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaTeamBanishAck, ArenaTeamBanishReq
        req = ArenaTeamBanishReq.decode(body)
        await self.reply(ArenaTeamBanishAck(result=0), correlation,
                         note=f'arena team banish ack (target={req.target_uid})')

    @packet_handler(5286)
    async def handle_arena_team_change_host(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaTeamChangeHostAck, ArenaTeamChangeHostReq
        req = ArenaTeamChangeHostReq.decode(body)
        await self.reply(ArenaTeamChangeHostAck(result=0, new_host_uid=req.new_host_uid), correlation,
                         note=f'arena team change host ack (host={req.new_host_uid})')

    @packet_handler(5301)
    async def handle_arena_change_team_info(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import ArenaChangeTeamInfoAck, ArenaChangeTeamInfoReq
        req = ArenaChangeTeamInfoReq.decode(body)
        await self.reply(ArenaChangeTeamInfoAck(result=0, team_type=req.team_type, team_name=req.team_name),
                         correlation, note=f'arena change team info ack ({req.team_name})')

    @packet_handler(2556)
    async def handle_league_season_arena_charstat_update(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import (
            LeagueSeasonArenaCharStatUpdateAck, LeagueSeasonArenaCharStatUpdateReq,
        )
        req = LeagueSeasonArenaCharStatUpdateReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['league_season_stat'] = dict(req.season_stat)
            self.save_char()
        await self.reply(LeagueSeasonArenaCharStatUpdateAck(result=0, season_stat=req.season_stat),
                         correlation, note='league season arena charstat update ack')

    @packet_handler(2561)
    async def handle_league_season_arena_charstat_init(self, correlation: int, body: bytes):
        from darkblood.games.network.messages.arena import LeagueSeasonArenaCharStatInitAck
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        if char is not None:
            char['league_season_stat'] = {}
            self.save_char()
        await self.reply(LeagueSeasonArenaCharStatInitAck(result=0, cur_ar=cur_ar, season_init_stat_cnt=1),
                         correlation, note='league season arena charstat init ack')
