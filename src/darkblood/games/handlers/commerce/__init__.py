"""Commerce domain controller composed from stores, cash shop, trade and stalls mixins."""
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.commerce.cash_shop import CashShopHandlers
from darkblood.games.handlers.commerce.stalls import StallHandlers
from darkblood.games.handlers.commerce.stores import MONSTER_CARD_ACKS, StoreHandlers, store_record
from darkblood.games.handlers.commerce.trade import TradeHandlers
from darkblood.player_management.characters import free_bag_slots


class CommerceHandlers(
    StoreHandlers,
    CashShopHandlers,
    TradeHandlers,
    StallHandlers,
    BaseDomainService,
):
    """Store transactions, buybacks, cash packages, Steam integration, trade and stalls."""

    def __init__(self, session):
        super().__init__(session)
        # Items sold this session: repurchase uid -> (item record, price, sold_at).
        self._repurchase_items = {}

__all__ = [
    "CommerceHandlers",
    "MONSTER_CARD_ACKS",
    "free_bag_slots",
    "store_record",
]
