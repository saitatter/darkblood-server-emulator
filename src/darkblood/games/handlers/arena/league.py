"""Arena: League season arena rankings (2550-2553), built from the stored characters."""
from __future__ import annotations

from typing import List

from darkblood.games.config import OFFLINE_SERVER_ID
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages import (
    LeagueArenaCharInfo,
    LeagueRankEntry,
    LeagueSeasonArenaGetMyRankAck,
    LeagueSeasonArenaGetMyRankReq,
    LeagueSeasonArenaGetRankAck,
    LeagueSeasonArenaGetRankReq,
)

# LeagueArenaCharInfo: win + lose + draw < 10 is the placement phase, and 2553
# (0x00492A10) shows a rank only above 9 games.
PLACEMENT_GAMES = 10
UNRANKED = -1  # 2553: a negative rank shows UI_2933 "Not ranked"


def league_arena_info(char) -> LeagueArenaCharInfo:
    """The character's stored league record (`char['league_arena']`) with the client's defaults."""
    la = char.get('league_arena', {}) or {}
    return LeagueArenaCharInfo(
        rating=int(la.get('rating', 1300)),
        rating_float=float(la.get('rating_float', 1300.0)),
        season_stat_exp=int(la.get('season_stat_exp', 0)),
        used_league_point=int(la.get('used_league_point', 0)),
        daily_league_point=int(la.get('daily_league_point', 0)),
        daily_league_point_bonus=int(la.get('daily_league_point_bonus', 0)),
        total_league_point=int(la.get('total_league_point', 0)),
        stat_reset_count=int(la.get('stat_reset_count', 0)),
        rank=int(la.get('rank', UNRANKED)),
        win_count=int(la.get('win_count', 0)),
        lose_count=int(la.get('lose_count', 0)),
        draw_count=int(la.get('draw_count', 0)),
        win_streak=int(la.get('win_streak', 0)),
        season_stats={int(k): int(v) for k, v in (la.get('season_stats') or {}).items()},
    )


def league_ladder(characters) -> List[LeagueRankEntry]:
    """Ranked ladder of the characters past placement, by rating, then wins, then id."""
    ranked = []
    for char in characters:
        info = league_arena_info(char)
        if info.win_count + info.lose_count + info.draw_count < PLACEMENT_GAMES:
            continue
        ranked.append((char, info))
    ranked.sort(key=lambda ci: (-ci[1].rating, -ci[1].win_count, int(ci[0].get('id', 0))))
    return [
        LeagueRankEntry(
            rank=place,
            char_uid=int(char.get('id', 0)),
            char_name=char.get('name', ''),
            server_id=OFFLINE_SERVER_ID,
            char_class=int(char.get('char_class', 0)) & 0xFF,
            char_level=int(char.get('level', 1)) & 0xFF,
            wins=info.win_count,
            losses=info.lose_count,
            draws=info.draw_count,
            rating=max(0, info.rating),
            win_streak=info.win_streak,
        )
        for place, (char, info) in enumerate(ranked, start=1)
    ]


class LeagueHandlers:
    # League Season Arena Rankings (Opcodes 2550 - 2553)

    def _league_ladder(self) -> List[LeagueRankEntry]:
        return league_ladder(char for _, char in self.store().all_characters())

    @packet_handler(LeagueSeasonArenaGetRankReq)
    async def handle_league_season_arena_get_rank(self, correlation: int, body: bytes):
        """Opcode 2550 / 2475 -> 2551 / 2476.

        Client handler: 0x0049B230 -> 0x00499DC0 (nPageIdx >> m_vecSeasonRank >>
        jSeasonBeginTime); the page index is echoed and the whole ladder is sent,
        since the page size is not recovered.
        """
        req = LeagueSeasonArenaGetRankReq.decode(body)
        ranks = self._league_ladder()
        ack = LeagueSeasonArenaGetRankAck(result=0, season_id=req.season_id, ranks=ranks)
        await self.reply(ack, correlation, note=f'league season arena get rank ack (page={req.season_id}, {len(ranks)} ranked)')

    @packet_handler(LeagueSeasonArenaGetMyRankReq)
    async def handle_league_season_arena_get_my_rank(self, correlation: int, body: bytes):
        """Opcode 2552 / 2477 -> 2553 / 2478.

        Client handler: 0x0049D180 -> 0x00492A10. The player's place on the
        ladder, or -1 ("Not ranked") during placement.
        """
        req = LeagueSeasonArenaGetMyRankReq.decode(body)
        char_uid = self._get_active_char_info()[0]
        my_rank = next((e.rank for e in self._league_ladder() if e.char_uid == char_uid), UNRANKED)
        ack = LeagueSeasonArenaGetMyRankAck(result=0, my_rank=my_rank)
        await self.reply(ack, correlation, note=f'league season arena get my rank ack (season={req.season_id}, rank={my_rank})')
