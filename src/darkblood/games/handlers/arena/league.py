"""Arena: League season arena rankings (2550-2553)."""
from __future__ import annotations

from darkblood.games.network.messages import (
    LeagueSeasonArenaGetMyRankAck,
    LeagueSeasonArenaGetMyRankReq,
    LeagueSeasonArenaGetRankAck,
    LeagueSeasonArenaGetRankReq,
)
from darkblood.games.dispatcher import packet_handler


class LeagueHandlers:
    # League Season Arena Rankings (Opcodes 2550 - 2553)

    @packet_handler(LeagueSeasonArenaGetRankReq)
    async def handle_league_season_arena_get_rank(self, correlation: int, body: bytes):
        """Opcode 2550 / 2475 -> 2551 / 2476.

        Client handler: 0x0049B230 -> 0x00499DC0.
        Returns league season rank leaderboard.
        """
        req = LeagueSeasonArenaGetRankReq.decode(body)
        ranks = self.arena.leaderboard(req.season_id)
        ack = LeagueSeasonArenaGetRankAck(result=0, season_id=req.season_id, ranks=ranks)
        await self.reply(ack, correlation, note=f'league season arena get rank ack (season={req.season_id})')

    @packet_handler(LeagueSeasonArenaGetMyRankReq)
    async def handle_league_season_arena_get_my_rank(self, correlation: int, body: bytes):
        """Opcode 2552 / 2477 -> 2553 / 2478.

        Client handler: 0x0049D180 -> 0x00492A10.
        Returns player's rank on the arena ladder.
        """
        req = LeagueSeasonArenaGetMyRankReq.decode(body)
        char_uid, char_name, _, _ = self._get_active_char_info()
        ranks = self.arena.leaderboard(req.season_id)
        my_rank = 1
        for entry in ranks:
            if entry.char_uid == char_uid or entry.char_name == char_name:
                my_rank = entry.rank
                break
        ack = LeagueSeasonArenaGetMyRankAck(result=0, my_rank=my_rank)
        await self.reply(ack, correlation, note=f'league season arena get my rank ack (season={req.season_id})')
