"""Arena: Arena teams (5269-5275)."""
from __future__ import annotations

from darkblood.games.network.messages import (
    ArenaTeamCreateAck,
    ArenaTeamCreateReq,
    ArenaTeamInfo,
    ArenaTeamJoinAck,
    ArenaTeamJoinReq,
    ArenaTeamLeaveAck,
    ArenaTeamLeaveReq,
)
from darkblood.games.dispatcher import packet_handler


class ArenaTeamHandlers:
    # Arena Teams (Opcodes 5269 - 5275)

    @staticmethod
    def _team_ack(ack_cls, team):
        """5270/5272 reply carrying the team summary."""
        return ack_cls(result=0, team_id=team.team_id, team_type=team.team_type, score=team.score,
                       member_count=team.member_count, team_name=team.team_name,
                       leader_name=team.leader_name, notice=team.notice)

    @packet_handler(ArenaTeamCreateReq)
    async def handle_arena_team_create(self, correlation: int, body: bytes):
        """Opcode 5269 / 2452 -> 5270 / 2453.

        Client handler: 0x0049D180 -> 0x0049BEF0.
        Creates an arena PvP team.
        """
        req = ArenaTeamCreateReq.decode(body)
        char_uid, char_name, _, _ = self._get_active_char_info()
        team_id = next(self.arena.team_ids)

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
        self.arena.teams[team_id] = team
        self._current_arena_team_id = team_id

        self.transport.record('arena-team-create-req', body, team_name=req.team_name)
        ack = self._team_ack(ArenaTeamCreateAck, team)
        await self.reply(ack, correlation, note=f'arena team create ack (name={req.team_name})')

    @packet_handler(ArenaTeamJoinReq)
    async def handle_arena_team_join(self, correlation: int, body: bytes):
        """Opcode 5271 / 2454 -> 5272 / 2455.

        Client handler: 0x0049D180 -> 0x0049C4B0.
        Joins an existing arena PvP team.
        """
        req = ArenaTeamJoinReq.decode(body)
        team = self.arena.teams.get(req.team_id)
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
            self.arena.teams[req.team_id] = team

        team.member_count += 1
        self._current_arena_team_id = team.team_id

        self.transport.record('arena-team-join-req', body, team_id=req.team_id)
        ack = self._team_ack(ArenaTeamJoinAck, team)
        await self.reply(ack, correlation, note=f'arena team join ack (team={req.team_id})')

    @packet_handler(ArenaTeamLeaveReq)
    async def handle_arena_team_leave(self, correlation: int, body: bytes):
        """Opcode 5274 / 2456 -> 5275 / 2457.

        Client handler: 0x0049D180 -> 0x00490100.
        Departs from current arena team.
        """
        curr_team = self._current_arena_team_id
        if curr_team and curr_team in self.arena.teams:
            team = self.arena.teams[curr_team]
            team.member_count = max(0, team.member_count - 1)
            self._current_arena_team_id = None

        ack = ArenaTeamLeaveAck(result=0)
        await self.reply(ack, correlation, note='arena team leave ack')
