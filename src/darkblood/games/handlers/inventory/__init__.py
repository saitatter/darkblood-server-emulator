"""Inventory domain controller composed from responsibility-focused mixins."""
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.inventory.bags import BagHandlersMixin
from darkblood.games.handlers.inventory.crafting import CraftingHandlersMixin
from darkblood.games.handlers.inventory.depot import DepotHandlersMixin
from darkblood.games.handlers.inventory.items import ItemHandlersMixin


class InventoryHandlers(
    BagHandlersMixin,
    ItemHandlersMixin,
    CraftingHandlersMixin,
    DepotHandlersMixin,
    BaseDomainService,
):
    """Item management: bags, quickslots, drag/equip/use, crafting and depot."""


__all__ = ['InventoryHandlers']
