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

from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.arena.duels import DuelHandlers
from darkblood.games.handlers.arena.rooms import ArenaRoomHandlers
from darkblood.games.handlers.arena.teams import ArenaTeamHandlers
from darkblood.games.handlers.arena.league import LeagueHandlers
from darkblood.games.handlers.arena.minigame import GbbHandlers
from darkblood.games.handlers.arena.extended import ArenaExtendedHandlers
from darkblood.games.handlers.arena.state import ArenaState


class ArenaHandlers(
    DuelHandlers,
    ArenaRoomHandlers,
    ArenaTeamHandlers,
    LeagueHandlers,
    GbbHandlers,
    ArenaExtendedHandlers,
    BaseDomainService,
):
    """Arena matches, teams, ladder rankings, and 1v1 town duels handlers."""

    def __init__(self, session):
        super().__init__(session)
        self._current_arena_room_id = None   # arena room this session joined (5145/5147)
        self._current_arena_team_id = None   # arena team this session created or joined

    @property
    def arena(self):
        """Server-wide arena state (rooms, teams, ladder) owned by the BootstrapServer."""
        return self.transport.server.arena

    def _get_active_char_info(self) -> tuple[int, str, int, int]:
        """Returns (uid, name, class, level) of the active session character."""
        char = self.current_char()
        if char is None:
            return 0, '', 0, 0
        return char['id'], char['name'], char['char_class'], char['level']


__all__ = ["ArenaHandlers", "ArenaState"]
