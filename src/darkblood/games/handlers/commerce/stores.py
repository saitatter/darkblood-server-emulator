"""NPC store catalog, buying, selling, buyback, beauty shop, roulette and durability."""
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event, strip_prefix
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network.messages import (
    BuyItemAck,
    BuyItemReq,
    DurabilityChangeAck,
    DurabilityChangeReq,
    MonsterCardAlbumAck,
    MonsterCardDeckAck,
    MonsterCardListAck,
    RepurchaseItemAck,
    RepurchaseItemReq,
    RouletteManagerInfoAck,
    SellItemAck,
    SellItemReq,
    StoreInfoAck,
    StoreRecord,
)
from darkblood.player_management.characters import (
    add_reward_items,
    free_bag_slots,
    slots_needed,
)

MONSTER_CARD_ACKS = {2602: MonsterCardListAck, 2609: MonsterCardDeckAck, 2618: MonsterCardAlbumAck}

# Exact reward table from roulette.lua (DictRoulette:LoadReward).
# Tuple: (id, reward_type, value, rate, notify)
# reward_type 0 = AR share of jackpot (float), 1 = item code (str).
ROULETTE_REWARDS = (
    ('moneyreward1', 0, 0.99, 2.564102564e-8, True),
    ('moneyreward2', 0, 0.50, 1.282051282e-6, True),
    ('moneyreward3', 0, 0.25, 6.41025641e-6, True),
    ('moneyreward4', 0, 0.10, 1.282051282e-5, True),
    ('moneyreward5', 0, 0.05, 3.205128205e-4, True),
    ('moneyreward6', 0, 0.01, 0.005128205128, False),
    ('itemreward7',  1, 'IRanAEtc150R435', 0.12, False),
    ('itemreward8',  1, 'Igal1Cash6',      0.18, False),
    ('itemreward9',  1, 'Isal1Cash1',      0.21, False),
    ('itemreward10', 1, 'IRanAEtc150R436', 0.15, False),
    ('itemreward11', 1, 'IhppmppFS173',    0.153, False),
    ('itemreward12', 1, 'IhppmppFS172',    0.23153074, False),
)
_ROULETTE_JACKPOT_FLOOR = 100_000
_ROULETTE_JACKPOT_AR = 1_000_000
_ROULETTE_SPIN_COST = 100.0
# DictRoulette:LoadRoulettePoint (roulette.lua)
ROULETTE_POINT_VALUES = {
    0: 0.7,   # Monster kill
    1: 10.0,  # Dungeon clear
    2: 6.0,   # Quest completion
    3: 1.0,   # Misc / PvP / crafting
}
# DictRoulette:LoadSavingAr (SavingArType = 0)
ROULETTE_SAVING_AR_RATE = 0.2
ROULETTE_POINTS_CAP = 100.0


def add_roulette_points(char: dict, point_type: int) -> float:
    """Increment char['roulette_points'] by roulette.lua SavingPointType value (capped at 100.0)."""
    gain = ROULETTE_POINT_VALUES.get(point_type, 0.0)
    cur = float(char.get('roulette_points', 0.0))
    new_pts = min(ROULETTE_POINTS_CAP, round(cur + gain, 2))
    char['roulette_points'] = new_pts
    return new_pts


def contribute_roulette_jackpot(ar_amount: int) -> int:
    """Add 20% of AR (DictRoulette:LoadSavingAr) to the server jackpot pool."""
    global _ROULETTE_JACKPOT_AR
    if ar_amount > 0:
        _ROULETTE_JACKPOT_AR += max(1, int(ar_amount * ROULETTE_SAVING_AR_RATE))
    return _ROULETTE_JACKPOT_AR


def store_record(item: str, stock: int = -1, price: int = None) -> StoreRecord:
    """Store record for an item id; price defaults to the item's BuyPrice.

    The stock is clamped to i16 (storelist.lua -1 = unlimited)."""
    if price is None:
        from darkblood.games.game_data.client_dict import item_field
        price = item_field(item, 'BuyPrice', 0)
    return StoreRecord(item_hash=jhash(item), price=price & 0xFFFFFFFF,
                       stock=max(-0x8000, min(0x7FFF, stock)))


class StoreHandlers:
    def _shop_char(self):
        return self.current_char()


    async def _monster_card_empty(self, correlation, opcode):
        await self.transport.send_event(event(opcode, MONSTER_CARD_ACKS[opcode]().encode(), correlation),
                                        note=f'monster card ack {opcode} (empty)')


    def _repurchase_list(self):
        """Items sold this session, as RepurchaseItem entries (2066 vecRePur)."""
        from darkblood.games.network.messages.commerce import RepurchaseItem
        return [RepurchaseItem(item=Item(owner=0, **record), price=price, sell_time=sold_at)
                for record, price, sold_at in getattr(self, '_repurchase_items', {}).values()]

    @packet_handler(2065)
    async def handle_get_store_info(self, correlation, body):
        # eEGS_GET_STORE_INFO_REQ (i32, u32 npc id; observed when talking to a
        # shop NPC) -> eEGS_GET_STORE_INFO_ACK 2066: empty store.
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        from darkblood.games.game_data import client_dict
        npc, items = client_dict.items_for_npc(npc_id)
        ack = StoreInfoAck(npc_id=npc_id, records=[store_record(i, c) for i, c in items],
                           repurchase=self._repurchase_list())
        await self.reply(ack, correlation, note='store info ack (%s, %d items)' % (npc or '%08x' % npc_id, len(items)))


    @packet_handler(BuyItemReq)
    async def handle_buy_item(self, correlation, body):
        # eEGS_BUY_ITEM_REQ (0x0078F720) -> 2068 eEGS_BUY_ITEM_ACK (0x0077E2F0).
        from darkblood.games.network import results
        req = BuyItemReq.decode(body)
        self.transport.record('buy-item-req', body, store_id=req.store_id, item_id=req.item_id, count=req.count)
        char = self.current_char()
        if not char:
            ack = BuyItemAck(result=1)
            await self.reply(ack, correlation, note='buy item fail (no char)')
            return

        from darkblood.games.game_data import client_dict
        item_code = None
        item_stock = -1
        req_hash = req.item_id & 0xFFFFFFFF
        _, npc_items = client_dict.items_for_npc(req.store_id & 0xFFFFFFFF)
        for code, stock in npc_items:
            if jhash(code) == req_hash:
                item_code = code
                item_stock = stock
                break
        if not item_code:
            for s_items in client_dict.store_items().values():
                for code, stock in s_items:
                    if jhash(code) == req_hash:
                        item_code = code
                        item_stock = stock
                        break
                if item_code:
                    break
        if not item_code:
            item_code = 'Ihppa0001'

        count = max(1, req.count)
        free = free_bag_slots(char)
        if free is not None and slots_needed([(item_code, count)]) > free:
            ack = BuyItemAck(result=results.INVEN_FULL)
            await self.reply(ack, correlation, note='buy item fail (inventory full)')
            return

        unit_price = client_dict.item_field(item_code, 'BuyPrice', 0)
        cost = unit_price * count
        char_gold = char.get('gold', 100000)
        if char_gold >= cost:
            char_gold -= cost
            char['gold'] = char_gold
            char['u66'] = char_gold
            if cost > 0:
                contribute_roulette_jackpot(cost)
            new_items = add_reward_items(char, [(item_code, count)])
            self.save_char()
            wire_items = [Item(owner=UPDATE_OWNER, **i) for i in new_items]
            rec = store_record(item_code, stock=item_stock, price=unit_price)
            ack = BuyItemAck(
                result=0,
                store_record=rec.encode(),
                npc_id=req.store_id & 0xFFFFFFFF,
                gold=char_gold,
                items=wire_items,
                item_id=jhash(item_code),
                item_num=count,
                pvp_point=char.get('pvp_points', 0),
                league_point=char.get('league_points', 0),
            )
            await self.reply(ack, correlation, note=f'buy item ack (code={item_code} count={count} gold={char_gold})')
        else:
            ack = BuyItemAck(result=1)
            await self.reply(ack, correlation, note='buy item fail (insufficient gold)')


    @packet_handler(SellItemReq)
    async def handle_sell_item(self, correlation, body):
        # eEGS_SELL_ITEM_REQ (0x00780000.c:10700) -> 2070 eEGS_SELL_ITEM_ACK (0x0077E8E0).
        req = SellItemReq.decode(body)
        self.transport.record('sell-item-req', body, npc_id=req.npc_id, item_uid=req.item_uid, count=req.count)
        char = self.current_char()
        if not char:
            ack = SellItemAck(result=1)
            await self.reply(ack, correlation, note='sell item fail (no char)')
            return

        items = char.get('items', [])
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            ack = SellItemAck(result=1)
            await self.reply(ack, correlation, note='sell item fail (not found)')
            return

        cnt = max(1, req.count)
        curr = target.get('count', 1)
        del_cnt = min(cnt, curr)
        sold_record = dict(target, count=del_cnt)
        if curr <= del_cnt:
            items.remove(target)
            # 0x008354D0 overwrites bag->slots[slot]; an empty cell (code='', uid=-1)
            # clears the slot so the sold item disappears from the bag immediately.
            updated_item = Item(
                code='',
                uid=-1,
                owner=UPDATE_OWNER,
                container=target.get('container', 3),
                slot=target.get('slot', 0),
                count=0,
            )
        else:
            target['count'] = curr - del_cnt
            updated_item = Item(owner=UPDATE_OWNER, **target)

        from darkblood.games.game_data.client_dict import item_field
        earned = item_field(target.get('code', ''), 'SellPrice', 0) * del_cnt
        char_gold = char.get('gold', 0) + earned
        char['gold'] = char_gold
        char['u66'] = char_gold
        self.save_char()

        import time
        from darkblood.player_management.characters import next_item_uid
        repurchase_uid = sold_record['uid'] if curr <= del_cnt else next_item_uid(char)
        sold_record['uid'] = repurchase_uid
        repurchase_map = getattr(self, '_repurchase_items', None)
        if repurchase_map is None:
            repurchase_map = {}
            self._repurchase_items = repurchase_map
        sold_at = int(time.time())
        repurchase_map[repurchase_uid] = (sold_record, earned, sold_at)

        # On_eEGS_SELL_ITEM_ACK (0x0077E8E0 -> 0x0059F370) looks up repurchase_item's
        # item_id via 0x009E5440 and dereferences it unconditionally (0x0059F3B8).
        repurchase_wire = Item(owner=0, **sold_record)
        ack = SellItemAck(
            result=0,
            items=[updated_item],
            gold=char_gold,
            repurchase_item=repurchase_wire,
            repurchase_price=earned,
            sell_time=sold_at,
        )
        await self.reply(ack, correlation, note=f'sell item ack (uid={req.item_uid} code={target.get("code")} del={del_cnt} price={earned} gold={char_gold})')


    @packet_handler(RepurchaseItemReq)
    async def handle_repurchase_item(self, correlation, body):
        # eEGS_REPURCHASE_ITEM_REQ (0x0078F8A0) -> 2072 eEGS_REPURCHASE_ITEM_ACK (0x0077EC30 -> 0x0059F7F0).
        from darkblood.games.network import results
        req = RepurchaseItemReq.decode(body)
        self.transport.record('repurchase-item-req', body, item_uid=req.item_uid)
        char = self.current_char()
        if not char:
            await self.reply(RepurchaseItemAck(result=1), correlation, note='repurchase fail (no char)')
            return
        repurchase_map = getattr(self, '_repurchase_items', {})
        entry = repurchase_map.get(req.item_uid)
        if not entry:
            await self.reply(RepurchaseItemAck(result=1), correlation, note=f'repurchase fail (unknown {req.item_uid})')
            return
        sold_record, price, _sold_at = entry
        char_gold = char.get('gold', 0)
        if char_gold < price:
            await self.reply(RepurchaseItemAck(result=1), correlation,
                             note=f'repurchase fail (need {price} AR, have {char_gold})')
            return
        if free_bag_slots(char) < 1:
            await self.reply(RepurchaseItemAck(result=results.INVEN_FULL), correlation,
                             note='repurchase fail (inventory full)')
            return

        added = add_reward_items(char, [(sold_record['code'], sold_record.get('count', 1))])
        if not added:
            await self.reply(RepurchaseItemAck(result=results.INVEN_FULL), correlation,
                             note='repurchase fail (placement failed)')
            return
        if 'durability' in sold_record:
            added[0]['durability'] = sold_record['durability']
        repurchase_map.pop(req.item_uid, None)
        char_gold -= price
        char['gold'] = char_gold
        char['u66'] = char_gold
        self.save_char()

        wire_items = [Item(owner=UPDATE_OWNER, **r) for r in added]
        await self.reply(
            RepurchaseItemAck(result=0, item_uid=req.item_uid, items=wire_items, gold=char_gold),
            correlation,
            note=f'repurchase item ack (item={req.item_uid} price={price} gold={char_gold})',
        )


    @packet_handler(2601)
    async def handle_monster_card_list(self, correlation, body):
        # eEGS_MONSTERCARD_GET_LIST_REQ -> 2602.
        await self._monster_card_empty(correlation, 2602)


    @packet_handler(2608)
    async def handle_monster_card_deck(self, correlation, body):
        # eEGS_MONSTERCARD_GET_CHAR_DECK_REQ -> 2609.
        await self._monster_card_empty(correlation, 2609)


    @packet_handler(2617)
    async def handle_monster_card_album(self, correlation, body):
        # eEGS_MONSTERCARD_GET_ALBUM_REQ -> 2618.
        await self._monster_card_empty(correlation, 2618)


    @packet_handler(2592)
    async def handle_bag_change_sell_enable(self, correlation, body):
        # eEGS_BAG_CHANGE_SELL_ENABLE_REQ.
        body = strip_prefix(body)
        if len(body) >= 9:
            bag_id, enabled = struct.unpack_from('<Q?', body, 0)
            char = self._shop_char()
            if char is not None:
                char.setdefault('bag_sell_enabled', {})[str(bag_id)] = enabled
                self.save_char()
            self.transport.record('bag-sell-enable', body, bag=bag_id, enabled=enabled)


    @packet_handler(2390)
    async def handle_roulette_manager_info(self, correlation, body):
        # eEGS_ROULETTE_MANAGER_INFO_REQ -> eEGS_ROULETTE_MANAGER_INFO_ACK (2391), handler 0x0062CBC0.
        # Also sync current roulette_points via 2389 now that Page_RoulettePoint (0x0E) is loaded
        # (sending 2389 during 2006/2007 character select crashes at 0x00B01946 with NULL widget).
        from darkblood.games.network.messages.commerce import RoulettePointInsertNot
        ack = RouletteManagerInfoAck(manager_id=1, active=True, jackpot_ar=_ROULETTE_JACKPOT_AR)
        await self.reply(ack, correlation, note=f'roulette manager info ack (jackpot={_ROULETTE_JACKPOT_AR})')
        char = self.current_char()
        if char is not None:
            pts = float(char.get('roulette_points', _ROULETTE_SPIN_COST))
            await self.send_msg(RoulettePointInsertNot(roulette_points=pts),
                                note=f'roulette point not (pts={pts:.1f})')


    @packet_handler(DurabilityChangeReq)
    async def handle_durability_change(self, correlation, body):
        # eEGS_DURABILITY_CHANGE_REQ (0x00792AC0) -> 2144 eEGS_DURABILITY_CHANGE_ACK (0x00774AE0).
        from darkblood.games.game_data.client_dict import item_max_durability
        req = DurabilityChangeReq.decode(body)
        self.transport.record('durability-change-req', body, count=len(req.durabilities))
        char = self.current_char()
        broken_uids = []
        changed = False
        if char is not None and req.durabilities:
            items_by_uid = {int(it.get('uid', -1)): it for it in char.get('items', [])}
            for item_uid, new_dur in req.durabilities.items():
                item = items_by_uid.get(int(item_uid))
                if item is None:
                    continue
                max_dur = item_max_durability(item.get('code', ''))
                clamped = max(0.0, float(new_dur))
                if max_dur is not None:
                    clamped = min(clamped, float(max_dur))
                item['durability'] = clamped
                changed = True
                if clamped <= 0.0:
                    broken_uids.append(int(item_uid))
            if changed:
                self.save_char()
        ack = DurabilityChangeAck(result=0, changed_item_uids=broken_uids)
        await self.reply(ack, correlation, note=f'durability change ack (updated={len(req.durabilities)}, broken={len(broken_uids)})')


    @packet_handler(2416)
    async def handle_beauty_shop_care(self, correlation, body):
        # eEGS_BEAUTYSHOP_CARE_REQ (0x0079B730) -> 2417 eEGS_BEAUTYSHOP_CARE_ACK (0x0079B3A0).
        from darkblood.games.network.messages.commerce import BeautyShopCareAck, BeautyShopCareReq
        req = BeautyShopCareReq.decode(body)
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        if char is not None:
            char['beauty_style_slots'] = list(req.info.style_slots)
            self.save_char()
        await self.reply(BeautyShopCareAck(result=0, info=req.info, cur_ar=cur_ar, items=[]),
                         correlation, note='beauty shop care ack')


    @packet_handler(2590)
    async def handle_sell_item_all(self, correlation, body):
        # eEGS_SELL_ITEM_ALL_REQ (0x007A4BB0) -> 2591 eEGS_SELL_ITEM_ALL_ACK (0x007845B0).
        from darkblood.games.network.messages.commerce import SellItemAllAck
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        await self.reply(SellItemAllAck(result=0, items=[], cur_ar=cur_ar, deleted_item_uids=[]),
                         correlation, note=f'sell item all ack (ar={cur_ar})')


    @packet_handler(2386)
    async def handle_roulette_roll_dice(self, correlation, body):
        # eEGS_ROULETTE_ROLL_DICE_REQ -> 2387 eEGS_ROULETTE_ROLL_DICE_ACK (0x0062C850).
        global _ROULETTE_JACKPOT_AR
        import random
        from darkblood.games.network.messages.commerce import RoulettePointInsertNot, RouletteRollDiceAck
        from darkblood.games.network.messages.inventory import DragItemAck

        char = self.current_char()
        weights = [entry[3] for entry in ROULETTE_REWARDS]
        entry_id, reward_type, value, _, notify = random.choices(ROULETTE_REWARDS, weights=weights, k=1)[0]
        reward_hash = jhash(entry_id)

        reward_rate = 0.0
        reward_ar = 0
        reward_items = []
        reward_count = 0
        wire_items = []

        if reward_type == 0:
            reward_rate = float(value)
            reward_ar = max(1, int(_ROULETTE_JACKPOT_AR * reward_rate))
            _ROULETTE_JACKPOT_AR = max(_ROULETTE_JACKPOT_FLOOR, _ROULETTE_JACKPOT_AR - reward_ar)
            if char is not None:
                char['gold'] = int(char.get('gold', 0)) + reward_ar
                char['u66'] = char['gold']
        else:
            item_code = str(value)
            reward_items = [item_code]
            reward_count = 1
            if char is not None:
                new_items = add_reward_items(char, [(item_code, 1)])
                wire_items = [Item(owner=UPDATE_OWNER, **i) for i in new_items]

        cur_ar = int((char or {}).get('gold', 0))
        pts = float((char or {}).get('roulette_points', _ROULETTE_SPIN_COST))
        if pts >= _ROULETTE_SPIN_COST:
            pts = max(0.0, pts - _ROULETTE_SPIN_COST)
        if char is not None:
            char['roulette_points'] = pts
            self.save_char()

        await self.reply(
            RouletteRollDiceAck(
                result=0,
                reward_id=reward_hash,
                reward_type=reward_type,
                reward_rate=reward_rate,
                jackpot_ar=_ROULETTE_JACKPOT_AR,
                reward_count=reward_count,
                reward_ar=reward_ar,
                reward_items=reward_items,
                notify=notify,
                cur_ar=cur_ar,
            ),
            correlation,
            note=f'roulette roll dice ack ({entry_id}, ar={reward_ar}, items={reward_items})',
        )
        if wire_items:
            await self.send_msg(DragItemAck(result=0, items=wire_items), note=f'roulette item grant ({reward_items[0]})')
        await self.send_msg(RoulettePointInsertNot(roulette_points=pts), note=f'roulette point not (pts={pts:.1f})')


    @packet_handler(2388)
    async def handle_roulette_notice(self, correlation, body):
        # eEGS_ROULETTE_NOTICE_REQ -> 2389 eEGS_ROULETTE_POINT_INSERT_NOT (0x0063C390).
        from darkblood.games.network.messages.commerce import RoulettePointInsertNot
        char = self.current_char()
        pts = float((char or {}).get('roulette_points', _ROULETTE_SPIN_COST))
        await self.send_msg(RoulettePointInsertNot(roulette_points=pts), note=f'roulette point not (pts={pts:.1f})')


    @packet_handler(2530)
    async def handle_storage_share(self, correlation, body):
        # eEGS_STORAGE_SHARE_REQ -> 2531 eEGS_STORAGE_SHARE_ACK (0x0064EFB0).
        from darkblood.games.network.messages.commerce import StorageShareAck, StorageShareReq
        req = StorageShareReq.decode(body)
        await self.reply(StorageShareAck(result=0, items=[]), correlation,
                         note=f'storage share ack (item={req.item_uid})')

