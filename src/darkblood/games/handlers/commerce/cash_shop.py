"""Offline Steam Cash Shop, Premium inventory, cash packages, HTTP notices and play options."""
import importlib

from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data import cash_shop
from darkblood.games.network.messages import (
    BillingGetItemListAck,
    BillingGetItemListReq,
    BillingUseItemAck,
    BillingUseItemReq,
    ContractUpdateAck,
    ContractUpdateReq,
    CurrentCashAck,
    HttpNoticeCheckAck,
    PlayOptionUpdateReq,
    SteamBuyPackageAck,
    SteamBuyPackageReq,
    SteamFinalizeBuyItemAck,
    SteamInitBuyItemNot,
)
from darkblood.games.network.results import INVEN_FULL, INVEN_ITEM_NOT_FOUND, NO_EXIST_CHAR, OK
from darkblood.player_management.characters import add_reward_items, slots_needed


def _commerce_package():
    # free_bag_slots is looked up on the package so tests can patch it there;
    # importing the package at module level would be circular.
    return importlib.import_module('darkblood.games.handlers.commerce')


class CashShopHandlers:
    @packet_handler(2369)
    async def handle_get_current_cash(self, correlation, body):
        # eEGS_BILLING_GET_CURRENT_CASH_REQ -> 2370: result, u64 cash, u32 mileage.
        # Cash is per account (store meta, set from the dashboard); mileage 0.
        cash = self.store().account_cash(self.account)
        await self.reply(CurrentCashAck(cash=cash), correlation, note='current cash ack (%d)' % cash)


    @packet_handler(SteamInitBuyItemNot)
    async def handle_steam_init_buy_item(self, correlation, body):
        # eEGS_BILLING_STEAM_INIT_BUY_ITEM_NOT. On Steam the overlay then
        # authorizes the order, the MicroTxnAuthorizationResponse callback
        # (0x004E6440) sends 2713 and waits for 2714. Offline there is no
        # overlay, so the purchase completes here: products are free (prices
        # are USD). Bought products go to the account's Premium inventory
        # (vecCashItemOut); 2714 carries the whole list and closes the shop's
        # purchase flow (page dispatcher 0x004DCCC0 -> 0x004DB680). The player
        # moves them to the bags with 2394.
        req = SteamInitBuyItemNot.decode(body)
        cash_items = None
        if self._shop_char() is None:
            result, reason = 1, 'no character'
        else:
            try:
                products = cash_shop.load_catalog()
            except (OSError, ValueError) as exc:
                result, reason = 24, f'cash catalog unavailable: {exc}'
            else:
                result, reason = self._store_cash_products(req.product_ids, products)
                cash_items = self._cash_items()
        ack = SteamFinalizeBuyItemAck(result=result, cash_items=list(cash_items or []), authorized=result == 0)
        await self.send_msg(ack, note=f'steam buy ack (products {req.product_ids}: {reason})')


    def _cash_items(self):
        """The account's Premium inventory: ProductIDs waiting to be moved to a bag.

        Shared by the account's characters (inferred: UI_2420 contrasts it
        with "your character inventory"; the client keeps one list per login).
        """
        return self.store().account_data(self.account).setdefault('cash_items', [])


    def _store_cash_products(self, product_ids, products):
        if not product_ids or any(product not in products for product in product_ids):
            return 442, 'unknown product'
        self._cash_items().extend(int(product) for product in product_ids)
        self.store().save_account_data(self.account)
        return 0, f'{len(product_ids)} products to the Premium inventory'


    @packet_handler(BillingGetItemListReq)
    async def handle_billing_get_item_list(self, correlation, body):
        # eEGS_BILLING_GET_ITEMLIST_REQ -> 2393 (0x00557AE0). No sender was
        # found in this build; answer with the stored list.
        await self.reply(BillingGetItemListAck(result=0, cash_items=list(self._cash_items())), correlation,
                         note='premium inventory list')


    @packet_handler(BillingUseItemReq)
    async def handle_billing_use_item(self, correlation, body):
        # eEGS_BILLING_USE_ITEM_REQ (0x0054EA30: m_nUnlockCashID = ProductID)
        # -> 2395 (0x00558450): remaining list + the items inserted into the
        # bags (0x00835990, the 2037 path, so topped-up stacks keep their UID).
        req = BillingUseItemReq.decode(body)
        char = self._shop_char()
        cash_items = self._cash_items()
        products = {}
        if char is None:
            result, reason = NO_EXIST_CHAR, 'no character'
        elif req.product_id not in cash_items:
            result, reason = INVEN_ITEM_NOT_FOUND, 'not in the Premium inventory'
        else:
            try:
                products = cash_shop.load_catalog()
            except (OSError, ValueError) as exc:
                result, reason = 24, f'cash catalog unavailable: {exc}'
            else:
                result, reason = (442, 'unknown product') if req.product_id not in products else (OK, '')
        if result != OK:
            await self.reply(BillingUseItemAck(result=result), correlation,
                             note=f'premium item {req.product_id} refused ({reason})')
            return
        reward = products[req.product_id]
        free = _commerce_package().free_bag_slots(char)
        if free is not None and slots_needed([reward], char) > free:
            await self.reply(BillingUseItemAck(result=INVEN_FULL), correlation,
                             note=f'premium item {req.product_id} refused (inventory full)')
            return
        cash_items.remove(req.product_id)
        stored = add_reward_items(char, [reward])
        self.save_char()
        self.store().save_account_data(self.account)
        items = [Item(owner=UPDATE_OWNER, **i) for i in stored]
        await self.reply(BillingUseItemAck(result=OK, cash_items=list(cash_items), items=items), correlation,
                         note='premium item %d -> %s' % (req.product_id, ', '.join(i['code'] for i in stored)))


    @packet_handler(2713)
    async def handle_steam_finalize_buy_item(self, correlation, body):
        # eEGS_BILLING_STEAM_FINALIZE_BUY_ITEM_REQ (0x004E6440: u64 order id,
        # bool authorized). Not reached offline; acknowledge without items.
        await self.reply(SteamFinalizeBuyItemAck(cash_items=list(self._cash_items()), authorized=False), correlation, note='steam finalize ack (no order)')


    @packet_handler(2594)
    async def handle_http_notice_check(self, correlation, body):
        # eEGS_HTTPNOTICE_CHECK_REQ -> 2595 eEGS_HTTPNOTICE_CHECK_ACK (0x005A5110).
        ack = HttpNoticeCheckAck(result=0, watch=False)
        await self.reply(ack, correlation, note='http notice check ack')


    @packet_handler(PlayOptionUpdateReq)
    async def handle_play_option_update(self, correlation, body):
        # eEGS_PLAY_OPTION_UPDATE_REQ (0x00794ED0) - fire and forget; persist 24-byte PlayOption block (+0x84 in 2007).
        req = PlayOptionUpdateReq.decode(body)
        self.transport.record('play-option-update', body, char_uid=req.char_uid)
        char = self.current_char()
        if char is not None and len(req.raw) == 24:
            char['play_option'] = req.raw.hex()
            self.save_char()


    @packet_handler(ContractUpdateReq)
    async def handle_contract_update(self, correlation, body):
        # eEGS_CONTRACT_UPDATE_REQ -> 2122 eEGS_CONTRACT_UPDATE_ACK (0x00752D80).
        req = ContractUpdateReq.decode(body)
        self.transport.record('contract-update-req', body, contract_id=req.contract_id)
        ack = ContractUpdateAck(result=0, contract_id=req.contract_id)
        await self.reply(ack, correlation, note=f'contract update ack (contract={req.contract_id})')


    @packet_handler(2721)
    async def handle_steam_buy_package(self, correlation, body):
        # eEGS_STEAM_BUY_PACKAGE_REQ (0x007A8420) -> 2722 eEGS_STEAM_BUY_PACKAGE_ACK.
        req = SteamBuyPackageReq.decode(body)
        self.transport.record('steam-buy-package-req', body, package_id=req.package_id)
        await self.reply(SteamBuyPackageAck(result=0), correlation,
                         note=f'steam buy package ack (pkg={req.package_id})')

