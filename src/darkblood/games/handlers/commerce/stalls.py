"""Personal shops (town stalls) and Broker (Auction House) handlers."""
from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network.messages import (
    BrokerBuyItemAck,
    BrokerBuyItemReq,
    BrokerCancelAck,
    BrokerCancelReq,
    BrokerListAck,
    BrokerListReq,
    BrokerMyListAck,
    BrokerMyListReq,
    BrokerPriceAck,
    BrokerPriceReq,
    BrokerRegistItemAck,
    BrokerRegistItemReq,
    PersonalShopBuyAck,
    PersonalShopBuyReq,
    PersonalShopChangeNot,
    PersonalShopCloseAck,
    PersonalShopCloseNot,
    PersonalShopCloseReq,
    PersonalShopGetProductsAck,
    PersonalShopGetProductsReq,
    PersonalShopOpenAck,
    PersonalShopOpenReq,
    PersonalShopStartNot,
)
from darkblood.games.stalls import BrokerManager, PersonalShopManager


class StallHandlers:
    async def _broadcast_square(self, evt_data: bytes):
        """Broadcast an event to all players in the square."""
        try:
            from darkblood.games.world import GameWorldManager
            world = GameWorldManager.get()
            await world.broadcast_to_square(1, evt_data, exclude_char_id=self.char_id)
        except Exception:
            pass


    @packet_handler(PersonalShopOpenReq)
    async def handle_personal_shop_open(self, correlation, body):
        # eEGS_PERSONALSHOP_START_REQ -> 2341 eEGS_PERSONALSHOP_START_ACK (0x00601AA0)
        req = PersonalShopOpenReq.decode(body)
        char = self.current_char()
        if not char:
            ack = PersonalShopOpenAck(result=1)
            await self.reply(ack, correlation, note='personal shop open fail (no char)')
            return

        char_uid = char.get('id', self.char_id)
        char_name = char.get('name', 'Player')
        mgr = PersonalShopManager.get()
        success, msg, stall = mgr.open_stall(char_uid, char_name, req.title,
                                             [(o.item_uid, o.count, o.price) for o in req.items], char)
        if success and stall:
            ack = PersonalShopOpenAck(
                result=0,
                owner_uid=char_uid,
                title=stall.title,
                items=stall.wire_items(),
                expire_time=stall.expire_seconds
            )
            await self.reply(ack, correlation, note=f'personal shop open ack (uid={char_uid} items={len(stall.items)})')
            # Broadcast stall opening to town square
            notif = event(5254, PersonalShopStartNot(seller_uid=char_uid, title=stall.title).encode())
            await self._broadcast_square(notif)
        else:
            ack = PersonalShopOpenAck(result=1)
            await self.reply(ack, correlation, note=f'personal shop open fail ({msg})')


    @packet_handler(PersonalShopBuyReq)
    async def handle_personal_shop_buy(self, correlation, body):
        # eERC_PERSONALSHOP_BUYITEM_REQ -> 5243 eERC_PERSONALSHOP_BUYITEM_ACK (0x006022AC)
        req = PersonalShopBuyReq.decode(body)
        char = self.current_char()
        if not char:
            ack = PersonalShopBuyAck(result=1)
            await self.reply(ack, correlation, note='personal shop buy fail (no char)')
            return

        mgr = PersonalShopManager.get()
        success, msg, total_cost, new_items = mgr.buy_stall_item(
            char, req.seller_uid, req.item_uid, req.count, self.store()
        )
        if success:
            wire_items = [Item(owner=UPDATE_OWNER, **i) for i in new_items]
            stall = mgr.get_stall(req.seller_uid)
            remaining_stall = stall.wire_items() if stall else []
            ack = PersonalShopBuyAck(
                result=0,
                gold=char.get('gold', 0),
                items=wire_items,
                stall_items=remaining_stall,
                seller_uid=req.seller_uid
            )
            await self.reply(ack, correlation, note=f'personal shop buy ack (cost={total_cost} gold={char.get("gold", 0)})')
            if stall:
                notif = event(5250, PersonalShopChangeNot(
                    seller_uid=req.seller_uid,
                    title=stall.title,
                    item_count=len(stall.items)
                ).encode())
                await self._broadcast_square(notif)
        else:
            ack = PersonalShopBuyAck(result=1)
            await self.reply(ack, correlation, note=f'personal shop buy fail ({msg})')


    @packet_handler(PersonalShopCloseReq)
    async def handle_personal_shop_close(self, correlation, body):
        # eEGS_PERSONALSHOP_CLOSE_REQ -> 2343 eEGS_PERSONALSHOP_CLOSE_ACK (0x00601F09)
        char = self.current_char()
        char_uid = char.get('id', self.char_id) if char else self.char_id
        mgr = PersonalShopManager.get()
        success, returned = mgr.close_stall(char_uid, char, self.store())
        ack = PersonalShopCloseAck(result=0 if success else 1, owner_uid=char_uid)
        await self.reply(ack, correlation, note=f'personal shop close ack (uid={char_uid})')
        if success:
            notif = event(5255, PersonalShopCloseNot(seller_uid=char_uid).encode())
            await self._broadcast_square(notif)


    @packet_handler(PersonalShopGetProductsReq)
    async def handle_personal_shop_get_products(self, correlation, body):
        # eERT_PERSONALSHOP_GET_PRODUCTS_REQ -> 6022 eERT_PERSONALSHOP_GET_PRODUCTS_ACK (0x006029D6)
        req = PersonalShopGetProductsReq.decode(body)
        mgr = PersonalShopManager.get()
        stall = mgr.get_stall(req.seller_uid)
        if stall:
            ack = PersonalShopGetProductsAck(
                result=0,
                seller_uid=req.seller_uid,
                title=stall.title,
                items=stall.wire_items(),
                expire_time=stall.expire_seconds
            ).encode()
        else:
            ack = PersonalShopGetProductsAck(result=1, seller_uid=req.seller_uid).encode()
        await self.transport.send_event(event(6022, ack, correlation),
                                        note=f'personal shop get products ack (seller={req.seller_uid})')


    @packet_handler(BrokerListReq)
    async def handle_broker_list(self, correlation, body):
        # eEGS_BROKER_LIST_REQ -> 2263 eEGS_BROKER_LIST_ACK (0x005ADAC0)
        req = BrokerListReq.decode(body)
        mgr = BrokerManager.get()
        products, total = mgr.get_listings(page=req.page, category=req.category, filter_name=req.filter_name)
        ack = BrokerListAck(result=0, products=products, page=req.page, total_count=total)
        await self.reply(ack, correlation, note=f'broker list ack (page={req.page} count={len(products)} total={total})')


    @packet_handler(BrokerMyListReq)
    async def handle_broker_my_list(self, correlation, body):
        # eEGS_BROKER_MYLIST_REQ -> 2265 eEGS_BROKER_MYLIST_ACK (0x005ADFF0)
        char = self.current_char()
        char_uid = char.get('id', self.char_id) if char else self.char_id
        mgr = BrokerManager.get()
        my_products = mgr.get_my_listings(char_uid)
        ack = BrokerMyListAck(result=0, products=my_products)
        await self.reply(ack, correlation, note=f'broker mylist ack (uid={char_uid} count={len(my_products)})')


    @packet_handler(BrokerRegistItemReq)
    async def handle_broker_regist_item(self, correlation, body):
        # eEGS_BROKER_REGIST_ITEM_REQ -> 2267 eEGS_BROKER_REGIST_ITEM_ACK (0x005B06A0 -> 0x00A40460)
        req = BrokerRegistItemReq.decode(body)
        char = self.current_char()
        if not char:
            ack = BrokerRegistItemAck(result=1)
            await self.reply(ack, correlation, note='broker regist item fail (no char)')
            return

        mgr = BrokerManager.get()
        success, msg, listing = mgr.register_item(
            char, req.item_uid, None, req.price, 24, self.store()
        )
        wire_items = []
        if success and listing is not None:
            raw = listing.raw_dict
            wire_items.append(Item(
                owner=UPDATE_OWNER, uid=0, code='',
                container=raw.get('container', 3), slot=raw.get('slot', 0), count=0,
            ))
        char_uid = char.get('id', self.char_id)
        ack = BrokerRegistItemAck(
            result=0 if success else 1,
            cur_ar=int(char.get('gold', 0)),
            items=wire_items,
            my_products=mgr.get_my_listings(char_uid) if success else [],
        )
        await self.reply(ack, correlation, note=f'broker regist item ack (success={success} msg={msg})')


    @packet_handler(BrokerBuyItemReq)
    async def handle_broker_buy_item(self, correlation, body):
        # eEGS_BROKER_BUY_ITEM_REQ -> 2269 eEGS_BROKER_BUY_ITEM_ACK (0x005B0980 -> 0x00A1E7A0)
        from darkblood.games.network.messages.inventory import DragItemAck
        req = BrokerBuyItemReq.decode(body)
        char = self.current_char()
        if not char:
            ack = BrokerBuyItemAck(result=1)
            await self.reply(ack, correlation, note='broker buy item fail (no char)')
            return

        mgr = BrokerManager.get()
        success, msg, total_cost, new_items, bought_uid = mgr.buy_listing(
            char, req.listing_id, None, self.store()
        )
        gold = int(char.get('gold', 0))
        ack = BrokerBuyItemAck(result=0 if success else 1, gold=gold, item_uid=bought_uid)
        await self.reply(ack, correlation, note=f'broker buy item ack (success={success} cost={total_cost} gold={gold})')
        if success and new_items:
            wire_items = [Item(owner=UPDATE_OWNER, **i) for i in new_items]
            await self.send_msg(DragItemAck(result=0, items=wire_items), note='broker buy item grant')


    @packet_handler(BrokerCancelReq)
    async def handle_broker_cancel(self, correlation, body):
        # eEGS_BROKER_CANCEL_REQ -> 2271 eEGS_BROKER_CANCEL_ACK (0x005AC9D0)
        from darkblood.games.network.messages.inventory import DragItemAck
        req = BrokerCancelReq.decode(body)
        char = self.current_char()
        if not char:
            ack = BrokerCancelAck(result=1)
            await self.reply(ack, correlation, note='broker cancel fail (no char)')
            return

        mgr = BrokerManager.get()
        success, msg, returned = mgr.cancel_listing(char, req.listing_id, self.store())
        ack = BrokerCancelAck(result=0 if success else 1, item_uid=req.listing_id)
        await self.reply(ack, correlation, note=f'broker cancel ack (success={success} msg={msg})')
        if success and returned:
            wire_items = [Item(owner=UPDATE_OWNER, **i) for i in returned]
            await self.send_msg(DragItemAck(result=0, items=wire_items), note='broker cancel item return')


    @packet_handler(BrokerPriceReq)
    async def handle_broker_price(self, correlation, body):
        # eEGS_BROKER_PRICE_REQ -> 2273 eEGS_BROKER_PRICE_ACK
        req = BrokerPriceReq.decode(body)
        from darkblood.games.game_data import client_dict
        # Lookup code if any
        item_code = ''
        for s_items in client_dict.store_items().values():
            for code, _ in s_items:
                if jhash(code) == req.item_id:
                    item_code = code
                    break
            if item_code:
                break
        mgr = BrokerManager.get()
        avg_price, min_price = mgr.get_price_stats(item_code)
        ack = BrokerPriceAck(result=0, avg_price=avg_price, min_price=min_price)
        await self.reply(ack, correlation, note=f'broker price ack (avg={avg_price} min={min_price})')


    @packet_handler(2586)
    async def handle_sale_by_bulk_option(self, correlation, body):
        # eEGS_SALEBYBULK_OPTION_REQ (0x007A4930) -> 2587 eEGS_SALEBYBULK_OPTION_ACK (0x0076CBD0).
        from darkblood.games.network.messages.stalls import SaleByBulkOptionAck, SaleByBulkOptionReq
        req = SaleByBulkOptionReq.decode(body)
        char = self.current_char()
        opts = {}
        if char is not None:
            raw = char.setdefault('sale_by_bulk_options', {})
            raw[str(req.equip_idx)] = bool(req.enable)
            self.save_char()
            opts = {int(k): bool(v) for k, v in raw.items()}
        await self.reply(SaleByBulkOptionAck(result=0, sell_equip_info=opts), correlation,
                         note=f'sale by bulk option ack (idx={req.equip_idx} enable={req.enable})')


    @packet_handler(2588)
    async def handle_sale_by_bulk_regist(self, correlation, body):
        # eEGS_SALEBYBULK_REGIST_REQ (0x007A4A70) -> 2589 eEGS_SALEBYBULK_REGIST_ACK (0x007725D0).
        from darkblood.games.network.messages.stalls import SaleByBulkRegistAck, SaleByBulkRegistReq
        req = SaleByBulkRegistReq.decode(body)
        char = self.current_char()
        custom = []
        if char is not None:
            custom = list(char.setdefault('sale_by_bulk_custom', []))
            if req.is_add and req.reg_item_id not in custom:
                custom.append(req.reg_item_id)
            elif not req.is_add and req.reg_item_id in custom:
                custom.remove(req.reg_item_id)
            char['sale_by_bulk_custom'] = custom
            self.save_char()
        await self.reply(SaleByBulkRegistAck(result=0, custom_item_list=custom), correlation,
                         note=f'sale by bulk regist ack (item={req.reg_item_id} add={req.is_add})')

