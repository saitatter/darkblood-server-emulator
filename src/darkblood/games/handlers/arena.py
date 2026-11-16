"""Arena matches, teams, ladder rankings, and 1v1 town duels handlers."""
import struct

from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import (
    ArenaGetInviteListAck,
    ArenaGetInviteListReq,
    ArenaGetRoomListAck,
    ArenaGetRoomListReq,
    ArenaSquareListAck,
    ArenaSquareListReq,
    ArenaTeamCreateAck,
    ArenaTeamCreateReq,
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
    LeagueSeasonArenaGetMyRankAck,
    LeagueSeasonArenaGetMyRankReq,
    LeagueSeasonArenaGetRankAck,
    LeagueSeasonArenaGetRankReq,
)
from darkblood.games.state import selected_character


class ArenaHandlers:
    """Arena matches, teams, ladder rankings, and 1v1 town duels handlers."""

    # ==========================================================================
    # 1v1 Town Duels (Opcodes 5097 - 5113)
    # ==========================================================================

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

    async def handle_duel_result(self, correlation: int, body: bytes):
        """Opcode 5105 (eERC_DUEL_RESULT_REQ) -> 5106 (eERC_DUEL_RESULT_ACK).

        Client table case: 0x006D2610 -> 0x006CC6B0.
        Records duel winner/loser and displays victory/defeat banner.
        """
        req = DuelResultReq.decode(body)
        self.transport.record('duel-result-req', body, winner=req.winner_uid, loser=req.loser_uid)
        ack = DuelResultAck(result=0).encode()
        await self.transport.send_event(event(5106, ack, correlation), note='duel result ack')

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
    # Arena Lobby, Rooms & Teams (Opcodes 2304-2309, 5269-5275)
    # ==========================================================================

    async def handle_arena_square_list(self, correlation: int, body: bytes):
        """Opcode 2304 (eEGS_ARENA_SQUARELIST_REQ) -> 2305 (eEGS_ARENA_SQUARELIST_ACK).

        Client handler: 0x004B7E80 -> 0x004B67F0.
        Returns the list of arena channels / square lobbies.
        """
        req = ArenaSquareListReq.decode(body)
        self.transport.record('arena-squarelist-req', body, server_key=req.server_key)
        ack = ArenaSquareListAck(result=0).encode()
        await self.transport.send_event(event(2305, ack, correlation), note='arena square list ack')

    async def handle_arena_get_room_list(self, correlation: int, body: bytes):
        """Opcode 2306 (eEGS_ARENA_GET_ROOMLIST_REQ) -> 2307 (eEGS_ARENA_GET_ROOMLIST_ACK).

        Client handler: 0x004C6080 -> 0x004B96D0.
        Returns open arena match rooms.
        """
        req = ArenaGetRoomListReq.decode(body)
        self.transport.record('arena-get-roomlist-req', body, page=req.page)
        ack = ArenaGetRoomListAck(result=0).encode()
        await self.transport.send_event(event(2307, ack, correlation), note='arena get room list ack')

    async def handle_arena_get_invite_list(self, correlation: int, body: bytes):
        """Opcode 2308 (eEGS_ARENA_GET_INVITELIST_REQ) -> 2309 (eEGS_ARENA_GET_INVITELIST_ACK).

        Client handler: 0x004C5200 -> 0x004B4680.
        Returns pending arena match invitations.
        """
        ack = ArenaGetInviteListAck(result=0).encode()
        await self.transport.send_event(event(2309, ack, correlation), note='arena get invite list ack')

    async def handle_arena_team_create(self, correlation: int, body: bytes):
        """Opcode 5269 (eERC_ARENA_TEAM_CREATE_REQ) -> 5270 (eERC_ARENA_TEAM_CREATE_ACK).

        Client handler: 0x0049D180 -> 0x0049BEF0.
        Creates an arena PvP team.
        """
        req = ArenaTeamCreateReq.decode(body)
        char_name = selected_character.get('name', 'Gladiator')
        self.transport.record('arena-team-create-req', body, team_name=req.team_name)
        ack = ArenaTeamCreateAck(
            result=0,
            team_id=1,
            team_type=req.team_type,
            score=1000,
            member_count=1,
            team_name=req.team_name,
            leader_name=char_name,
            notice="Ready for Arena combat"
        ).encode()
        await self.transport.send_event(event(5270, ack, correlation),
                                        note=f'arena team create ack (name={req.team_name})')

    async def handle_arena_team_join(self, correlation: int, body: bytes):
        """Opcode 5271 (eERC_ARENA_TEAM_JOIN_REQ) -> 5272 (eERC_ARENA_TEAM_JOIN_ACK).

        Client handler: 0x0049D180 -> 0x0049C4B0.
        Joins an existing arena PvP team.
        """
        req = ArenaTeamJoinReq.decode(body)
        self.transport.record('arena-team-join-req', body, team_id=req.team_id)
        ack = ArenaTeamJoinAck(result=0, team_id=req.team_id).encode()
        await self.transport.send_event(event(5272, ack, correlation),
                                        note=f'arena team join ack (team={req.team_id})')

    async def handle_arena_team_leave(self, correlation: int, body: bytes):
        """Opcode 5274 (eERC_ARENA_TEAM_LEAVE_REQ) -> 5275 (eERC_ARENA_TEAM_LEAVE_ACK).

        Client handler: 0x0049D180 -> 0x00490100.
        Departs from current arena team.
        """
        ack = ArenaTeamLeaveAck(result=0).encode()
        await self.transport.send_event(event(5275, ack, correlation), note='arena team leave ack')

    async def handle_league_season_arena_get_rank(self, correlation: int, body: bytes):
        """Opcode 2550 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_REQ) -> 2551 (eEGS_LEAGUE_SEASON_ARENA_GET_RANK_ACK).

        Client handler: 0x0049B230 -> 0x00499DC0.
        Returns league season rank leaderboard.
        """
        req = LeagueSeasonArenaGetRankReq.decode(body)
        ack = LeagueSeasonArenaGetRankAck(result=0, season_id=req.season_id).encode()
        await self.transport.send_event(event(2551, ack, correlation),
                                        note=f'league season arena get rank ack (season={req.season_id})')

    async def handle_league_season_arena_get_my_rank(self, correlation: int, body: bytes):
        """Opcode 2552 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_REQ) -> 2553 (eEGS_LEAGUE_SEASON_ARENA_GET_MY_RANK_ACK).

        Client handler: 0x0049D180 -> 0x00492A10.
        Returns player's rank on the arena ladder.
        """
        req = LeagueSeasonArenaGetMyRankReq.decode(body)
        ack = LeagueSeasonArenaGetMyRankAck(result=0, my_rank=1).encode()
        await self.transport.send_event(event(2553, ack, correlation),
                                        note=f'league season arena get my rank ack (season={req.season_id})')

    # Opcode backward-compatibility aliases
    on_5100 = handle_duel_request
    on_5097 = handle_duel_start
    on_5105 = handle_duel_result
    on_5112 = handle_duel_refuse
    on_2304 = handle_arena_square_list
    on_2306 = handle_arena_get_room_list
    on_2308 = handle_arena_get_invite_list
    on_5269 = handle_arena_team_create
    on_5271 = handle_arena_team_join
    on_5274 = handle_arena_team_leave
    on_2550 = handle_league_season_arena_get_rank
    on_2552 = handle_league_season_arena_get_my_rank
