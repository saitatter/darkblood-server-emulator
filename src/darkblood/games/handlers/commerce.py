"""Store / NPC commerce, cash shop, Steam purchases, player trade and notices."""
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event, strip_prefix
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data import cash_shop
from darkblood.games.network.messages import (
    AcceptRequestTradeAck,
    AcceptRequestTradeReq,
    AcceptTradeAck,
    BuyItemAck,
    BuyItemReq,
    CancelTradeAck,
    ContractUpdateAck,
    ContractUpdateReq,
    CurrentCashAck,
    DeleteTradeItemAck,
    DeleteTradeItemReq,
    DragItemAck,
    DurabilityChangeAck,
    DurabilityChangeReq,
    FinallyAcceptTradeAck,
    HttpNoticeCheckAck,
    InsertTradeItemAck,
    InsertTradeItemReq,
    MonsterCardEmptyAck,
    PlayOptionUpdateReq,
    RepurchaseItemAck,
    RepurchaseItemReq,
    RequestTradeAck,
    RequestTradeReq,
    RouletteManagerInfoAck,
    SellItemAck,
    SellItemReq,
    SteamFinalizeBuyItemAck,
    SteamInitBuyItemNot,
    StoreInfoAck,
    TamingMonsterDeleteAck,
    TamingMonsterInsertAck,
    UpdateTradeArAck,
    UpdateTradeArReq,
    PersonalShopOpenReq,
    PersonalShopOpenAck,
    PersonalShopCloseReq,
    PersonalShopCloseAck,
    PersonalShopBuyReq,
    PersonalShopBuyAck,
    PersonalShopGetProductsReq,
    PersonalShopGetProductsAck,
    PersonalShopChangeNot,
    PersonalShopStartNot,
    PersonalShopCloseNot,
    BrokerListReq,
    BrokerListAck,
    BrokerMyListReq,
    BrokerMyListAck,
    BrokerRegistItemReq,
    BrokerRegistItemAck,
    BrokerBuyItemReq,
    BrokerBuyItemAck,
    BrokerCancelReq,
    BrokerCancelAck,
    BrokerPriceReq,
    BrokerPriceAck,
    StallItem,
    BrokerProduct,
)
from darkblood.games.stalls import PersonalShopManager, BrokerManager
from darkblood.player_management.characters import (
    add_reward_items,
    free_bag_slots,
    slots_needed,
)
from darkblood.games.handlers.base import BaseDomainService


class CommerceHandlers(BaseDomainService):
    """Store transactions, buybacks, cash packages, Steam integration and P2P trade."""

    def _shop_char(self):
        return self.current_char()

    async def _monster_card_empty(self, correlation, opcode):
        await self.transport.send_event(event(opcode, MonsterCardEmptyAck(opcode=opcode).encode(), correlation),
                                        note=f'monster card ack {opcode} (empty)')

    async def on_2065(self, correlation, body):
        # eEGS_GET_STORE_INFO_REQ (i32, u32 npc id; observed when talking to a
        # shop NPC) -> eEGS_GET_STORE_INFO_ACK 2066: empty store.
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        from darkblood.games.game_data import client_dict
        npc, items = client_dict.items_for_npc(npc_id)
        ack = StoreInfoAck(npc_id=npc_id, items=items).encode()
        await self.transport.send_event(event(2066, ack, correlation),
                                        note='store info ack (%s, %d items)' % (npc or '%08x' % npc_id, len(items)))

    async def on_2067(self, correlation, body):
        # eEGS_BUY_ITEM_REQ (0x00780000.c:10667) -> 2068 eEGS_BUY_ITEM_ACK (0x0077E2F0).
        req = BuyItemReq.decode(body)
        self.transport.record('buy-item-req', body, store_id=req.store_id, item_id=req.item_id, count=req.count)
        char = self.current_char()
        if not char:
            ack = BuyItemAck(result=1).encode()
            await self.transport.send_event(event(2068, ack, correlation), note='buy item fail (no char)')
            return

        from darkblood.games.game_data import client_dict
        item_code = None
        for s_items in client_dict.store_items().values():
            for code, _ in s_items:
                if jhash(code) == req.item_id:
                    item_code = code
                    break
            if item_code:
                break
        if not item_code:
            item_code = 'Ihppa0001'

        count = max(1, req.count)
        cost = client_dict.item_field(item_code, 'BuyPrice', 0) * count
        char_gold = char.get('gold', 100000)
        if char_gold >= cost:
            char_gold -= cost
            char['gold'] = char_gold
            char['u66'] = char_gold
            new_items = add_reward_items(char, [(item_code, count)])
            self.store().save()
            wire_items = [Item(owner=UPDATE_OWNER, **i) for i in new_items]
            ack = BuyItemAck(result=0, gold=char_gold, items=wire_items).encode()
            await self.transport.send_event(event(2068, ack, correlation),
                                            note=f'buy item ack (code={item_code} count={count} gold={char_gold})')
        else:
            ack = BuyItemAck(result=1).encode()
            await self.transport.send_event(event(2068, ack, correlation), note='buy item fail (insufficient gold)')

    async def on_2069(self, correlation, body):
        # eEGS_SELL_ITEM_REQ (0x00780000.c:10700) -> 2070 eEGS_SELL_ITEM_ACK (0x0077E8E0).
        req = SellItemReq.decode(body)
        self.transport.record('sell-item-req', body, npc_id=req.npc_id, item_uid=req.item_uid, count=req.count)
        char = self.current_char()
        if not char:
            ack = SellItemAck(result=1).encode()
            await self.transport.send_event(event(2070, ack, correlation), note='sell item fail (no char)')
            return

        items = char.get('items', [])
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            ack = SellItemAck(result=1).encode()
            await self.transport.send_event(event(2070, ack, correlation), note='sell item fail (not found)')
            return

        cnt = max(1, req.count)
        curr = target.get('count', 1)
        del_cnt = min(cnt, curr)
        if curr <= del_cnt:
            items.remove(target)
        else:
            target['count'] = curr - del_cnt

        from darkblood.games.game_data.client_dict import item_field
        earned = item_field(target.get('code', ''), 'SellPrice', 0) * del_cnt
        char_gold = char.get('gold', 0) + earned
        char['gold'] = char_gold
        char['u66'] = char_gold
        self.store().save()

        wire_items = [Item(owner=UPDATE_OWNER, **i) for i in items]
        ack = SellItemAck(result=0, gold=char_gold, items=wire_items).encode()
        await self.transport.send_event(event(2070, ack, correlation),
                                        note=f'sell item ack (uid={req.item_uid} del={del_cnt} gold={char_gold})')

    async def on_2071(self, correlation, body):
        # eEGS_REPURCHASE_ITEM_REQ (0x00780000.c:10735) -> 2072 eEGS_REPURCHASE_ITEM_ACK (0x0077EC30).
        req = RepurchaseItemReq.decode(body)
        self.transport.record('repurchase-item-req', body, item_uid=req.item_uid)
        char = self.current_char()
        char_gold = char.get('gold', 0) if char else 0
        ack = RepurchaseItemAck(result=0, gold=char_gold, items=[]).encode()
        await self.transport.send_event(event(2072, ack, correlation),
                                        note=f'repurchase item ack (item={req.item_uid})')

    async def on_2369(self, correlation, body):
        # eEGS_BILLING_GET_CURRENT_CASH_REQ -> 2370: result, u64 cash, u32 mileage.
        # Cash is per account (store meta, set from the dashboard); mileage 0.
        cash = self.store().account_cash(self.account)
        await self.transport.send_event(event(2370, CurrentCashAck(cash=cash).encode(), correlation),
                                        note='current cash ack (%d)' % cash)

    async def on_2712(self, correlation, body):
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
                result, reason = 24, f'cash catalog unavailable ({cash_shop.CATALOG_PATH}): {exc}'
            else:
                result, reason = await self._grant_cash_products(char, req.product_ids, products)
        ack = SteamFinalizeBuyItemAck(result=result, applied=result == 0).encode()
        await self.transport.send_event(event(2714, ack),
                                        note=f'steam buy ack (products {req.product_ids}: {reason})')

    async def _grant_cash_products(self, char, product_ids, products):
        if not product_ids or any(product not in products for product in product_ids):
            return 442, 'unknown product'
        rewards = [products[product] for product in product_ids]
        free = free_bag_slots(char)
        if free is not None and slots_needed(rewards) > free:
            return 67, 'inventory full'
        stored = add_reward_items(char, rewards)
        self.store().save()
        items = [Item(owner=UPDATE_OWNER, **i) for i in stored]
        await self.transport.send_event(event(2037, DragItemAck(result=0, items=items).encode()),
                                        note='cash shop items (%s)' % ', '.join(i['code'] for i in stored))
        return 0, f'{len(stored)} items'

    async def on_2713(self, correlation, body):
        # eEGS_BILLING_STEAM_FINALIZE_BUY_ITEM_REQ (0x004E6440: u64 order id,
        # bool authorized). Not reached offline; acknowledge without items.
        await self.transport.send_event(event(2714, SteamFinalizeBuyItemAck(applied=False).encode(), correlation),
                                        note='steam finalize ack (no order)')

    async def on_2601(self, correlation, body):
        # eEGS_MONSTERCARD_GET_LIST_REQ -> 2602.
        await self._monster_card_empty(correlation, 2602)

    async def on_2608(self, correlation, body):
        # eEGS_MONSTERCARD_GET_CHAR_DECK_REQ -> 2609.
        await self._monster_card_empty(correlation, 2609)

    async def on_2617(self, correlation, body):
        # eEGS_MONSTERCARD_GET_ALBUM_REQ -> 2618.
        await self._monster_card_empty(correlation, 2618)

    async def on_2592(self, correlation, body):
        # eEGS_BAG_CHANGE_SELL_ENABLE_REQ.
        body = strip_prefix(body)
        if len(body) >= 9:
            bag_id, enabled = struct.unpack_from('<Q?', body, 0)
            char = self._shop_char()
            if char is not None:
                char.setdefault('bag_sell_enabled', {})[str(bag_id)] = enabled
                self.store().save()
            self.transport.record('bag-sell-enable', body, bag=bag_id, enabled=enabled)

    async def on_2390(self, correlation, body):
        # eEGS_ROULETTE_MANAGER_INFO_REQ -> eEGS_ROULETTE_MANAGER_INFO_ACK (2391), handler 0x6CC6B0.
        ack = RouletteManagerInfoAck().encode()
        await self.transport.send_event(event(2391, ack, correlation), note='roulette manager info ack')

    async def on_2594(self, correlation, body):
        # eEGS_HTTPNOTICE_CHECK_REQ -> 2595 eEGS_HTTPNOTICE_CHECK_ACK (0x005A5110).
        ack = HttpNoticeCheckAck(result=0, watch=False).encode()
        await self.transport.send_event(event(2595, ack, correlation), note='http notice check ack')

    async def on_2216(self, correlation, body):
        # eEGS_PLAY_OPTION_UPDATE_REQ (0x00790000.c:3729) - fire and forget.
        req = PlayOptionUpdateReq.decode(body)
        self.transport.record('play-option-update', body, char_uid=req.char_uid)

    async def on_2121(self, correlation, body):
        # eEGS_CONTRACT_UPDATE_REQ -> 2122 eEGS_CONTRACT_UPDATE_ACK (0x00752D80).
        req = ContractUpdateReq.decode(body)
        self.transport.record('contract-update-req', body, contract_id=req.contract_id)
        ack = ContractUpdateAck(result=0, contract_id=req.contract_id).encode()
        await self.transport.send_event(event(2122, ack, correlation),
                                        note=f'contract update ack (contract={req.contract_id})')

    async def on_2143(self, correlation, body):
        # eEGS_DURABILITY_CHANGE_REQ (0x00790000.c:2049) -> 2144 eEGS_DURABILITY_CHANGE_ACK (0x00774AE0).
        req = DurabilityChangeReq.decode(body)
        self.transport.record('durability-change-req', body)
        ack = DurabilityChangeAck(result=0).encode()
        await self.transport.send_event(event(2144, ack, correlation), note='durability change ack')

    # Trade handlers (5069 - 5083)
    async def on_5069(self, correlation, body):
        # eERC_REQUEST_TRADE_REQ -> 5070 eERC_REQUEST_TRADE_ACK (0x00770E50).
        req = RequestTradeReq.decode(body)
        self.transport.record('trade-request-req', body, target=req.target_uid)
        ack = RequestTradeAck(result=0, target_uid=req.target_uid, target_name='Partner').encode()
        await self.transport.send_event(event(5070, ack, correlation), note=f'trade request ack (target={req.target_uid})')

    async def on_5071(self, correlation, body):
        # eERC_ACCEPT_REQUEST_TRADE_REQ -> 5072 eERC_ACCEPT_REQUEST_TRADE_ACK (0x007587B0).
        req = AcceptRequestTradeReq.decode(body)
        self.transport.record('trade-accept-request-req', body, source=req.source_uid)
        my_uid = self.char_id
        ack = AcceptRequestTradeAck(result=0, source_uid=req.source_uid, target_uid=my_uid).encode()
        await self.transport.send_event(event(5072, ack, correlation), note='trade accept request ack')

    async def on_5073(self, correlation, body):
        # eERC_CANCEL_TRADE_REQ -> 5074 eERC_CANCEL_TRADE_ACK (0x0077DE00).
        self.transport.record('trade-cancel-req', body)
        ack = CancelTradeAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5074, ack, correlation), note='trade cancel ack')

    async def on_5075(self, correlation, body):
        # eERC_INSERT_TRADE_ITEM_REQ -> 5076 eERC_INSERT_TRADE_ITEM_ACK (0x0077D980).
        req = InsertTradeItemReq.decode(body)
        self.transport.record('trade-insert-item-req', body, item_uid=req.item_uid, slot=req.slot)
        ack = InsertTradeItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5076, ack, correlation), note=f'trade insert item ack (item={req.item_uid})')

    async def on_5077(self, correlation, body):
        # eERC_DELETE_TRADE_ITEM_REQ -> 5078 eERC_DELETE_TRADE_ITEM_ACK (0x0077DBB0).
        req = DeleteTradeItemReq.decode(body)
        self.transport.record('trade-delete-item-req', body, item_uid=req.item_uid)
        ack = DeleteTradeItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5078, ack, correlation), note=f'trade delete item ack (item={req.item_uid})')

    async def on_5079(self, correlation, body):
        # eERC_UPDATE_TRADE_AR_REQ -> 5080 eERC_UPDATE_TRADE_AR_ACK (0x00758940).
        req = UpdateTradeArReq.decode(body)
        self.transport.record('trade-update-ar-req', body, gold=req.gold)
        my_uid = self.char_id
        ack = UpdateTradeArAck(result=0, char_uid=my_uid, gold=req.gold).encode()
        await self.transport.send_event(event(5080, ack, correlation), note=f'trade update ar ack (gold={req.gold})')

    async def on_5081(self, correlation, body):
        # eERC_ACCEPT_TRADE_REQ -> 5082 eERC_ACCEPT_TRADE_ACK (0x0078EB40).
        self.transport.record('trade-accept-req', body)
        my_uid = self.char_id
        ack = AcceptTradeAck(result=0, char_uid=my_uid, accepted=True).encode()
        await self.transport.send_event(event(5082, ack, correlation), note='trade accept ack')

    async def on_5083(self, correlation, body):
        # eERC_FINALLY_ACCEPT_TRADE_REQ -> 5084 eERC_FINALLY_ACCEPT_TRADE_ACK.
        self.transport.record('trade-finally-accept-req', body)
        ack = FinallyAcceptTradeAck(result=0).encode()
        await self.transport.send_event(event(5084, ack, correlation), note='trade finally accept ack')

    # --- Personal Shop (Player Stalls) Handlers ---

    async def _broadcast_square(self, evt_data: bytes):
        """Broadcast an event to all players in the square."""
        try:
            from darkblood.games.world import GameWorldManager
            world = GameWorldManager.get()
            await world.broadcast_to_square(1, evt_data, exclude_char_id=self.char_id)
        except Exception:
            pass

    async def on_2340(self, correlation, body):
        # eEGS_PERSONALSHOP_START_REQ -> 2341 eEGS_PERSONALSHOP_START_ACK (0x00601AA0)
        req = PersonalShopOpenReq.decode(body)
        char = self.current_char()
        if not char:
            ack = PersonalShopOpenAck(result=1).encode()
            await self.transport.send_event(event(2341, ack, correlation), note='personal shop open fail (no char)')
            return

        char_uid = char.get('id', self.char_id)
        char_name = char.get('name', 'Player')
        mgr = PersonalShopManager.get()
        success, msg, stall = mgr.open_stall(char_uid, char_name, req.title, req.items, char)
        if success and stall:
            ack = PersonalShopOpenAck(
                result=0,
                owner_uid=char_uid,
                title=stall.title,
                items=stall.wire_items(),
                expire_time=stall.expire_seconds
            ).encode()
            await self.transport.send_event(event(2341, ack, correlation),
                                            note=f'personal shop open ack (uid={char_uid} items={len(stall.items)})')
            # Broadcast stall opening to town square
            notif = event(5254, PersonalShopStartNot(seller_uid=char_uid, title=stall.title).encode())
            await self._broadcast_square(notif)
        else:
            ack = PersonalShopOpenAck(result=1).encode()
            await self.transport.send_event(event(2341, ack, correlation),
                                            note=f'personal shop open fail ({msg})')

    async def on_5242(self, correlation, body):
        # eERC_PERSONALSHOP_BUYITEM_REQ -> 5243 eERC_PERSONALSHOP_BUYITEM_ACK (0x006022AC)
        req = PersonalShopBuyReq.decode(body)
        char = self.current_char()
        if not char:
            ack = PersonalShopBuyAck(result=1).encode()
            await self.transport.send_event(event(5243, ack, correlation), note='personal shop buy fail (no char)')
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
            ).encode()
            await self.transport.send_event(event(5243, ack, correlation),
                                            note=f'personal shop buy ack (cost={total_cost} gold={char.get("gold", 0)})')
            if stall:
                notif = event(5250, PersonalShopChangeNot(
                    seller_uid=req.seller_uid,
                    title=stall.title,
                    item_count=len(stall.items)
                ).encode())
                await self._broadcast_square(notif)
        else:
            ack = PersonalShopBuyAck(result=1).encode()
            await self.transport.send_event(event(5243, ack, correlation),
                                            note=f'personal shop buy fail ({msg})')

    async def on_2342(self, correlation, body):
        # eEGS_PERSONALSHOP_CLOSE_REQ -> 2343 eEGS_PERSONALSHOP_CLOSE_ACK (0x00601F09)
        char = self.current_char()
        char_uid = char.get('id', self.char_id) if char else self.char_id
        mgr = PersonalShopManager.get()
        success, returned = mgr.close_stall(char_uid, char, self.store())
        ack = PersonalShopCloseAck(result=0 if success else 1, owner_uid=char_uid).encode()
        await self.transport.send_event(event(2343, ack, correlation),
                                        note=f'personal shop close ack (uid={char_uid})')
        if success:
            notif = event(5255, PersonalShopCloseNot(seller_uid=char_uid).encode())
            await self._broadcast_square(notif)

    async def on_6021(self, correlation, body):
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

    # --- Broker (Marketplace / Auction House) Handlers ---

    async def on_2262(self, correlation, body):
        # eEGS_BROKER_LIST_REQ -> 2263 eEGS_BROKER_LIST_ACK (0x005ADAC0)
        req = BrokerListReq.decode(body)
        mgr = BrokerManager.get()
        products, total = mgr.get_listings(page=req.page, category=req.category, filter_name=req.filter_name)
        ack = BrokerListAck(result=0, products=products, page=req.page, total_count=total).encode()
        await self.transport.send_event(event(2263, ack, correlation),
                                        note=f'broker list ack (page={req.page} count={len(products)} total={total})')

    async def on_2264(self, correlation, body):
        # eEGS_BROKER_MYLIST_REQ -> 2265 eEGS_BROKER_MYLIST_ACK (0x005ADFF0)
        char = self.current_char()
        char_uid = char.get('id', self.char_id) if char else self.char_id
        mgr = BrokerManager.get()
        my_products = mgr.get_my_listings(char_uid)
        ack = BrokerMyListAck(result=0, products=my_products).encode()
        await self.transport.send_event(event(2265, ack, correlation),
                                        note=f'broker mylist ack (uid={char_uid} count={len(my_products)})')

    async def on_2266(self, correlation, body):
        # eEGS_BROKER_REGIST_ITEM_REQ -> 2267 eEGS_BROKER_REGIST_ITEM_ACK (0x005AFBAC)
        req = BrokerRegistItemReq.decode(body)
        char = self.current_char()
        if not char:
            ack = BrokerRegistItemAck(result=1).encode()
            await self.transport.send_event(event(2267, ack, correlation), note='broker regist item fail (no char)')
            return

        mgr = BrokerManager.get()
        success, msg, listing = mgr.register_item(
            char, req.item_uid, req.count, req.price, req.period_hours, self.store()
        )
        ack = BrokerRegistItemAck(result=0 if success else 1).encode()
        await self.transport.send_event(event(2267, ack, correlation),
                                        note=f'broker regist item ack (success={success} msg={msg})')

    async def on_2268(self, correlation, body):
        # eEGS_BROKER_BUY_ITEM_REQ -> 2269 eEGS_BROKER_BUY_ITEM_ACK (0x005B005C)
        req = BrokerBuyItemReq.decode(body)
        char = self.current_char()
        if not char:
            ack = BrokerBuyItemAck(result=1, gold=0).encode()
            await self.transport.send_event(event(2269, ack, correlation), note='broker buy item fail (no char)')
            return

        mgr = BrokerManager.get()
        success, msg, total_cost, new_items = mgr.buy_listing(
            char, req.listing_id, req.count, self.store()
        )
        gold = char.get('gold', 0)
        ack = BrokerBuyItemAck(result=0 if success else 1, gold=gold).encode()
        await self.transport.send_event(event(2269, ack, correlation),
                                        note=f'broker buy item ack (success={success} cost={total_cost} gold={gold})')

    async def on_2270(self, correlation, body):
        # eEGS_BROKER_CANCEL_REQ -> 2271 eEGS_BROKER_CANCEL_ACK (0x00789882)
        req = BrokerCancelReq.decode(body)
        char = self.current_char()
        if not char:
            ack = BrokerCancelAck(result=1).encode()
            await self.transport.send_event(event(2271, ack, correlation), note='broker cancel fail (no char)')
            return

        mgr = BrokerManager.get()
        success, msg = mgr.cancel_listing(char, req.listing_id, self.store())
        ack = BrokerCancelAck(result=0 if success else 1).encode()
        await self.transport.send_event(event(2271, ack, correlation),
                                        note=f'broker cancel ack (success={success} msg={msg})')

    async def on_2272(self, correlation, body):
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
        ack = BrokerPriceAck(result=0, avg_price=avg_price, min_price=min_price).encode()
        await self.transport.send_event(event(2273, ack, correlation),
                                        note=f'broker price ack (avg={avg_price} min={min_price})')
