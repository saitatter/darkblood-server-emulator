"""Dungeon domain controller composed from rooms, entry, combat, rewards and events mixins."""
from darkblood.core.network.proudnet import relay_address
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.dungeon.combat import DAILY_REBIRTH_COINS, DungeonCombatHandlers
from darkblood.games.handlers.dungeon.entry import DungeonEntryHandlers
from darkblood.games.handlers.dungeon.events import DungeonEventsHandlers
from darkblood.games.handlers.dungeon.gate import DungeonGateHandlers
from darkblood.games.handlers.dungeon.rewards import DungeonRewardsHandlers
from darkblood.games.handlers.dungeon.rooms import DungeonRoom, DungeonRoomHandlers


class DungeonHandlers(
    DungeonRoomHandlers,
    DungeonGateHandlers,
    DungeonEntryHandlers,
    DungeonCombatHandlers,
    DungeonRewardsHandlers,
    DungeonEventsHandlers,
    BaseDomainService,
):
    """Rooms, dungeon gate, map code, entry limits, combat, loot, rewards and events."""

    def __init__(self, session):
        super().__init__(session)
        self.room = None
        self.gate_id = ''             # last gate opened with 5043 (5052 reopens it)
        self.map_code = ''            # map of the current or last run (5009/5013)
        self.in_dungeon = False
        self.dungeon_cleared = False
        self.die_count = 0
        self._reset_dungeon_stats()   # per-run score, kills, EXP, layers, reward cards


__all__ = [
    "DAILY_REBIRTH_COINS",
    "DungeonHandlers",
    "DungeonRoom",
    "relay_address",
]
