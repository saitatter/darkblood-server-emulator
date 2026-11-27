"""Offline Steam Cash Shop, cash packages, HTTP notices and play options."""
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data import cash_shop
from darkblood.games.network.messages import (
    ContractUpdateAck,
    ContractUpdateReq,
    CurrentCashAck,
    DragItemAck,
    HttpNoticeCheckAck,
    PlayOptionUpdateReq,
    SteamBuyPackageAck,
    SteamBuyPackageReq,
    SteamFinalizeBuyItemAck,
    SteamInitBuyItemNot,
)
from darkblood.player_management.characters import add_reward_items, slots_needed


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
        # are USD), items go to the bag and reach the client through an
        # unsolicited 2037 (global handler 0x0077F570, owner -1), and 2714
        # closes the shop's purchase flow (page dispatcher 0x004DCCC0).
        req = SteamInitBuyItemNot.decode(body)
        char = self._shop_char()
        if char is None:
            result, reason = 1, 'no character'
        else:
            try:
                products = cash_shop.load_catalog()
            except (OSError, ValueError) as exc:
                result, reason = 24, f'cash catalog unavailable: {exc}'
            else:
                result, reason = await self._grant_cash_products(char, req.product_ids, products)
        ack = SteamFinalizeBuyItemAck(result=result, applied=result == 0)
        await self.send_msg(ack, note=f'steam buy ack (products {req.product_ids}: {reason})')


    async def _grant_cash_products(self, char, product_ids, products):
        if not product_ids or any(product not in products for product in product_ids):
            return 442, 'unknown product'
        rewards = [products[product] for product in product_ids]
        free = __import__("darkblood.games.handlers.commerce", fromlist=["free_bag_slots"]).free_bag_slots(char)
        if free is not None and slots_needed(rewards) > free:
            return 67, 'inventory full'
        stored = add_reward_items(char, rewards)
        self.save_char()
        items = [Item(owner=UPDATE_OWNER, **i) for i in stored]
        await self.send_msg(DragItemAck(result=0, items=items), note='cash shop items (%s)' % ', '.join(i['code'] for i in stored))
        return 0, f'{len(stored)} items'


    @packet_handler(2713)
    async def handle_steam_finalize_buy_item(self, correlation, body):
        # eEGS_BILLING_STEAM_FINALIZE_BUY_ITEM_REQ (0x004E6440: u64 order id,
        # bool authorized). Not reached offline; acknowledge without items.
        await self.reply(SteamFinalizeBuyItemAck(applied=False), correlation, note='steam finalize ack (no order)')


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

