"""Arena rooms and teams owned by one server (the league ladder is built from the stored characters)."""
from __future__ import annotations

from itertools import count
from typing import Dict

from darkblood.games.network.messages import ArenaRoomInfo, ArenaTeamInfo


class ArenaState:
    """Arena rooms and teams for one server instance.

    Held by BootstrapServer as `server.arena` (like `dungeon_rooms`); it used to
    live in ArenaHandlers class attributes shared by every server and test.
    """

    def __init__(self):
        self.rooms: Dict[int, ArenaRoomInfo] = {}
        self.room_members: Dict[int, list] = {}   # room id -> member dicts (server state, not on the wire)
        self.teams: Dict[int, ArenaTeamInfo] = {}
        self.room_ids = count(1)
        self.team_ids = count(1)
