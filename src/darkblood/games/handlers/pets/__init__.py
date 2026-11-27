"""Pet, Mount, Taming and Monster Card domain controller."""
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.pets.cards import MonsterCardHandlersMixin
from darkblood.games.handlers.pets.mounts import (
    MountHandlersMixin,
    build_ridings_map,
    mount_item_info,
)
from darkblood.games.handlers.pets.pets import PetCoreHandlersMixin


class PetHandlers(
    PetCoreHandlersMixin,
    MountHandlersMixin,
    MonsterCardHandlersMixin,
    BaseDomainService,
):
    """Pet summoning, evolution, feeding, mounts, monster taming and monster cards."""

    def __init__(self, session):
        super().__init__(session)
        self.pet_energy_last_tick = None


__all__ = [
    'PetHandlers',
    'build_ridings_map',
    'mount_item_info',
]
