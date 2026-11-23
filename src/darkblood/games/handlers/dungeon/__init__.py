"""Dungeon domain controller composed from rooms, combat and events mixins."""
from darkblood.core.network.proudnet import relay_address
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.dungeon.combat import DungeonCombatHandlers
from darkblood.games.handlers.dungeon.events import DungeonEventsHandlers
from darkblood.games.handlers.dungeon.rooms import DAILY_REBIRTH_COINS, DungeonRoom, DungeonRoomHandlers


class DungeonHandlers(
    DungeonRoomHandlers,
    DungeonCombatHandlers,
    DungeonEventsHandlers,
    BaseDomainService,
):
    """Rooms, dungeon gate, map code, combat, loot and dungeon events."""

    def __init__(self, session):
        super().__init__(session)
        self.room = None
        self._finish_game_reply = None
        self.reward_card = None
        self.reward_card_claimed = False

__all__ = [
    "DAILY_REBIRTH_COINS",
    "DungeonHandlers",
    "DungeonRoom",
    "relay_address",
]
