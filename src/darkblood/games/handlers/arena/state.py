"""Arena rooms, teams and the league ladder owned by one server."""
from __future__ import annotations

from itertools import count
from typing import Dict, List

from darkblood.games.network.messages import ArenaRoomInfo, ArenaTeamInfo, LeagueRankEntry


class ArenaState:
    """Arena rooms, teams and the league ladder for one server instance.

    Held by BootstrapServer as `server.arena` (like `dungeon_rooms`); it used to
    live in ArenaHandlers class attributes shared by every server and test.
    """

    def __init__(self):
        self.rooms: Dict[int, ArenaRoomInfo] = {}
        self.room_members: Dict[int, list] = {}   # room id -> member dicts (server state, not on the wire)
        self.teams: Dict[int, ArenaTeamInfo] = {}
        self.room_ids = count(1)
        self.team_ids = count(1)
        self._leaderboard: List[LeagueRankEntry] = []

    def leaderboard(self, season_id: int = 1) -> List[LeagueRankEntry]:
        """Returns or initializes realistic ranked league leaderboard."""
        if not self._leaderboard:
            self._leaderboard = [
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
        return self._leaderboard
