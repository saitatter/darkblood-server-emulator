"""Core item movement, equip, consumption, dyeing, splitting and sealing handlers."""
import random
import struct
import time

# Dual Skill Activation Order items (Type=54 in item_cash.lua / item_disposable.lua): ItemID -> AdjValue (days).
DUAL_SKILL_ITEM_DAYS = {
    'IDSk1Cash269': 30,
    'IDSk20S159': 10,
    'IDSk20R434': 30,
}

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import DEPOT_CONTAINER, EQUIPPED, Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages import (
    AssignQuickslotAck,
    BuyLifeWaterAck,
    BuyLifeWaterReq,
    CharVerifyStatAck,
    CharVerifyStatReq,
    DeleteItemAck,
    DeleteItemReq,
    DivideItemAck,
    DivideItemReq,
    DragItemAck,
    DragItemReq,
    EquipItemAck,
    EquipItemReq,
    ItemDecomposeAck,
    ItemDecomposeReq,
    RandomboxResultItemNot,
    SealItemAck,
    SealItemReq,
    UseArenaSpItemAck,
    UseArenaSpItemReq,
    UseDyeingItemAck,
    UseDyeingItemReq,
    UseItemAck,
    UseItemLeaguePointAddAck,
    UseItemLeaguePointAddReq,
    UseItemReq,
    UseSelectedSkillChangeItemAck,
    UseSelectedSkillChangeItemReq,
)
from darkblood.player_management.characters import (
    DEFAULT_BAG_CAPACITY,
    INVENTORY_BAG_CONTAINER,
    add_reward_items,
    fits_equip_slot,
    free_bag_slots,
    slots_needed,
)


class ItemHandlersMixin:
    """Item drag/equip/use/dye/delete/divide/decompose/seal and misc consumables."""

    @staticmethod
    def _locate_dragged_item(char: dict, account_chars: dict, item_uid: int):
        dragged = next((i for i in char.get('items', []) if i.get('uid') == item_uid), None)
        if dragged is not None:
            return char, dragged
        # Item may reside in another account character's depot.
        for other in account_chars.values():
            if other is char:
                continue
            found = next(
                (i for i in other.get('items', [])
                 if i.get('uid') == item_uid and i.get('container') == DEPOT_CONTAINER),
                None,
            )
            if found is not None:
                return other, found
        return char, None

    @staticmethod
    def _resolve_drag_destination(char: dict, account_chars: dict, to_container: int):
        # JAppPageStorage::OnDragItem (0x00650D00) sends to_container = pjDepot->m_nCharUID
        # (whereas JAppPageInven sends bag_id and equipment uses 2042 EquipItemReq).
        bag_ids = {
            b.get('bag_id') for b in char.get('bags', [])
            if b.get('bag_id') not in (EQUIPPED, DEPOT_CONTAINER)
        }
        if to_container == DEPOT_CONTAINER:
            return account_chars.get(DEPOT_CONTAINER, char), DEPOT_CONTAINER
        if to_container in account_chars and to_container not in bag_ids:
            return account_chars[to_container], DEPOT_CONTAINER
        return char, to_container

    def _save_drag_chars(self, src_char: dict, dest_char: dict):
        if dest_char is src_char:
            self.store().save_char(self.account, src_char['id'])
        else:
            self.store().save_chars([(self.account, src_char['id']), (self.account, dest_char['id'])])

    @packet_handler(DragItemReq)
    async def handle_drag_item(self, correlation, body):
        """Opcode 2036 (eEGS_DRAG_ITEM_REQ) -> 2037 (eEGS_DRAG_ITEM_ACK): move or swap an item between bags/depot."""
        req = DragItemReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(DragItemAck(result=1), correlation, note='drag item fail (no char)')
            return
        account_chars = {int(c['id']): c for c in self.store().characters(self.account) if 'id' in c}
        src_char, dragged = self._locate_dragged_item(char, account_chars, req.item_uid)
        if not dragged:
            await self.reply(DragItemAck(result=1), correlation, note='drag item fail (not found)')
            return

        old_container, old_slot = dragged.get('container'), dragged.get('slot')
        dest_char, dest_container = self._resolve_drag_destination(char, account_chars, req.to_container)
        if dest_container == EQUIPPED and not fits_equip_slot(dragged.get('code', ''), req.to_slot):
            await self.reply(DragItemAck(result=1), correlation,
                             note='drag item fail (item does not fit equip slot %d)' % req.to_slot)
            return

        def _wire_owner(container, owner_char):
            return int(owner_char['id']) if container == DEPOT_CONTAINER else UPDATE_OWNER

        dest_items = dest_char.setdefault('items', [])
        src_items = src_char.setdefault('items', [])
        target = next((i for i in dest_items
                       if i.get('container') == dest_container and i.get('slot') == req.to_slot), None)
        if target is dragged:
            await self.reply(
                DragItemAck(result=0, items=[Item(owner=_wire_owner(dest_container, dest_char), **dragged)]),
                correlation, note='drag item ack (no move)',
            )
            return
        if target:
            if old_container == EQUIPPED and not fits_equip_slot(target.get('code', ''), old_slot):
                await self.reply(DragItemAck(result=1), correlation,
                                 note='drag item fail (displaced item does not fit equip slot %d)' % old_slot)
                return
            if src_char is not dest_char:
                src_items.remove(dragged)
                dest_items.remove(target)
                src_items.append(target)
                dest_items.append(dragged)
            target['container'], target['slot'] = old_container, old_slot
            dragged['container'], dragged['slot'] = dest_container, req.to_slot
            self._save_drag_chars(src_char, dest_char)
            wire_items = [
                Item(owner=_wire_owner(old_container, src_char), **target),
                Item(owner=_wire_owner(dest_container, dest_char), **dragged),
            ]
        else:
            if src_char is not dest_char:
                src_items.remove(dragged)
                dest_items.append(dragged)
            dragged['container'], dragged['slot'] = dest_container, req.to_slot
            self._save_drag_chars(src_char, dest_char)
            wire_items = [
                Item(owner=_wire_owner(dest_container, dest_char), **dragged),
                Item(owner=_wire_owner(old_container, src_char), uid=0, code='',
                     container=old_container, slot=old_slot, count=0),
            ]
        await self.reply(DragItemAck(result=0, items=wire_items), correlation,
                         note='drag item ack (uid=%d to c=%d s=%d)' % (req.item_uid, dest_container, req.to_slot))

    async def _apply_special_consumable(self, char: dict, item_str_code: str, item_code: int, use_count: int):
        """Apply side effects of special consumable items (Book of AP, Dual Skill, Agreement of Rune, Pets/Mounts)."""
        if item_str_code == 'Ispaa0001':
            from darkblood.games.network.messages.skills import InsertApNot
            from darkblood.games.progression import add_ap
            add_ap(char, max(1, use_count))
            self.save_char()
            await self.send_msg(
                InsertApNot(current_ap=char['sp'], total_ap=char['total_ap']),
                note='book of ap used (+%d AP -> sp=%d total=%d)' % (max(1, use_count), char['sp'], char['total_ap']),
            )
        elif item_str_code in DUAL_SKILL_ITEM_DAYS:
            from darkblood.games.network.messages.skills import DualSkillActiveNot
            add_days = DUAL_SKILL_ITEM_DAYS[item_str_code] * max(1, int(use_count))
            now = int(time.time())
            base_expire = max(now, int(char.get('dual_skill_expire', 0)))
            new_expire = base_expire + add_days * 86400
            char['dual_skill_expire'] = new_expire
            remain_sec = new_expire - now
            cur_idx = int(char.get('dual_skill_index', 0))
            self.save_char()
            await self.send_msg(
                DualSkillActiveNot(
                    extend_time=remain_sec,
                    add_day=add_days,
                    cur_dual_skill_index=cur_idx,
                    item_id=item_code,
                ),
                note=f'dual skill active not (+{add_days}d, remain={remain_sec}s, idx={cur_idx})',
            )
        elif item_str_code == 'IAMk1R190':
            from darkblood.games.entities.character import mark_base_count
            from darkblood.games.network.messages.inventory import MarkItemActiveNot, MarkTabActiveNot
            char['mark_active'] = True
            base_cnt = max(int(char.get('mark_base_cnt', 0)), mark_base_count(char.get('level', 1)), 3)
            bonus_cnt = min(3, int(char.get('mark_bonus_cnt', 0)) + max(1, int(use_count)))
            char['mark_base_cnt'] = base_cnt
            char['mark_bonus_cnt'] = bonus_cnt
            self.save_char()
            await self.send_msg(MarkTabActiveNot(active_mark=True), note='mark tab active not (IAMk1R190)')
            await self.send_msg(
                MarkItemActiveNot(base_count=base_cnt, bonus_count=bonus_cnt),
                note=f'mark item active not (base={base_cnt}, bonus={bonus_cnt})',
            )
        await self.session.pets.apply_pet_or_mount_item(char, item_str_code)

    async def _grant_opened_box_contents(self, char: dict, box_code: str, contents: list, random_box: bool):
        stored = add_reward_items(char, contents)
        self.save_char()
        wire_items = [Item(owner=UPDATE_OWNER, **i) for i in stored]
        await self.send_msg(
            DragItemAck(result=0, items=wire_items),
            note='cash box opened (%s -> %s)' % (box_code, ', '.join(i['code'] for i in stored)),
        )
        if random_box:
            reward_code, reward_count = contents[0]
            reward_hash = jhash(reward_code)
            if reward_hash >= 0x80000000:
                reward_hash -= 0x100000000
            await self.send_msg(
                RandomboxResultItemNot(item_code=reward_hash, count=reward_count, is_jackpot=True),
                note='random box result (%s x%d)' % (reward_code, reward_count),
            )

    @packet_handler(UseItemReq)
    async def handle_use_item(self, correlation, body):
        """Opcode 2038 (eEGS_USE_ITEM_REQ) -> 2039 (eEGS_USE_ITEM_ACK): consume an item, open cash boxes or pet/mount items."""
        req = UseItemReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(UseItemAck(result=1), correlation, note='use item fail (no char)')
            return
        items = char.get('items', [])
        used_item = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not used_item:
            await self.reply(UseItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note='use item fail (not found)')
            return
        item_str_code = used_item.get('code', '')
        contents, random_box = self._cash_box_contents(item_str_code)
        if contents:
            free = free_bag_slots(char)
            if free is not None and slots_needed(contents) > free:
                await self.reply(UseItemAck(result=results.INVEN_FULL), correlation,
                                 note='use item fail (bag full: need %d, free %d)' % (slots_needed(contents), free))
                return
        item_code = jhash(item_str_code)
        count = used_item.get('count', 1) - req.use_count
        updated = []
        if count <= 0:
            items.remove(used_item)
            # Send a zero-count tombstone at the item's slot so the client
            # clears the icon from the bag (same pattern as 2211 dye consume).
            updated.append(Item(
                owner=UPDATE_OWNER,
                uid=0,
                code='',
                container=used_item.get('container', 1),
                slot=used_item.get('slot', 0),
                count=0,
            ))
        else:
            used_item['count'] = count
            updated.append(Item(owner=UPDATE_OWNER, **used_item))
        self.save_char()

        await self.reply(UseItemAck(result=0, items=updated, item_id=item_code, use_count=req.use_count),
                         correlation, note='use item ack (uid=%d code=%08x)' % (req.item_uid, item_code))
        await self._apply_special_consumable(char, item_str_code, item_code, req.use_count)
        if contents:
            await self._grant_opened_box_contents(char, item_str_code, contents, random_box)

    @packet_handler(UseDyeingItemReq)
    async def handle_use_dyeing_item(self, correlation, body):
        """Opcode 2210 (eEGS_USE_DYEING_ITEM_REQ) -> 2211 (eEGS_USE_DYEING_ITEM_ACK): apply hair/skin/item dye and consume it."""
        try:
            req = UseDyeingItemReq.decode(body)
        except struct.error:
            await self.reply(UseDyeingItemAck(result=results.INVALID_STATE), correlation,
                             note='use dyeing item fail (bad request)')
            return
        char = self.current_char()
        items = char.get('items', []) if char else []
        dye_item = next((i for i in items if i.get('uid') == req.dye_uid), None)
        if dye_item is None:
            await self.reply(UseDyeingItemAck(result=results.INVEN_ITEM_NOT_FOUND, dye=req.dye), correlation,
                             note='use dyeing item fail (uid %d not found)' % req.dye_uid)
            return
        count = dye_item.get('count', 1) - 1
        if count <= 0:
            items.remove(dye_item)
            update = Item(owner=UPDATE_OWNER, uid=0, code='', container=dye_item['container'],
                          slot=dye_item['slot'], count=0)
        else:
            dye_item['count'] = count
            update = Item(owner=UPDATE_OWNER, **dye_item)
        from darkblood.games.game_data import client_dict
        stain = client_dict.cash_items().get(dye_item.get('code', ''), {}).get('type')
        slot = {2: 'hair_dye', 3: 'skin_dye'}.get(stain)
        if slot and req.target_uid == -1:
            char[slot] = [req.dye.part, req.dye.option, req.dye.color]
        self.save_char()
        await self.reply(UseDyeingItemAck(result=0, dye=req.dye, items=[update]), correlation,
                         note='use dyeing item ack (%s target=%d color=%08x)' % (
                             dye_item.get('code'), req.target_uid, req.dye.color))

    def _cash_box_contents(self, code):
        from darkblood.games.game_data import client_dict
        info = client_dict.cash_items().get(code)
        if not info or not info['adj']:
            return [], False
        adj = info['adj']
        if adj.startswith('PACKAGE'):
            return list(client_dict.cash_packages().get(adj, [])), False
        states, groups = client_dict.random_boxes()
        grades = states.get(adj)
        if not grades:
            return [], False
        weights = [p for p, _ in grades]
        _, names = random.choices(grades, weights=weights)[0]
        pool = [entry for name in names for entry in groups.get(name, [])]
        return ([random.choice(pool)], True) if pool else ([], False)

    @packet_handler(EquipItemReq)
    async def handle_equip_item(self, correlation, body):
        """Opcode 2042 (eEGS_EQUIP_ITEM_REQ) -> 2043 (eEGS_EQUIP_ITEM_ACK): equip or unequip a gear piece."""
        req = EquipItemReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(EquipItemAck(result=1), correlation, note='equip item fail (no char)')
            return
        items = char.get('items', [])
        target_item = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target_item:
            await self.reply(EquipItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note='equip item fail (not found)')
            return

        old_container, old_slot = target_item.get('container'), target_item.get('slot')

        if old_container == EQUIPPED:
            bag_id = INVENTORY_BAG_CONTAINER
            bag = next((b for b in char.get('bags', []) if b.get('bag_id') not in (EQUIPPED, 2)), None)
            if bag:
                bag_id = bag.get('bag_id', INVENTORY_BAG_CONTAINER)
            used_slots = {i.get('slot') for i in items if i.get('container') == bag_id}
            capacity = bag.get('b29', DEFAULT_BAG_CAPACITY) if bag else DEFAULT_BAG_CAPACITY
            free_slot = next((s for s in range(capacity) if s not in used_slots), None)
            if free_slot is None:
                free_slot = max(used_slots, default=-1) + 1
            target_item['container'], target_item['slot'] = bag_id, free_slot
            self.save_char()
            wire_items = [
                Item(owner=UPDATE_OWNER, **target_item),
                Item(owner=UPDATE_OWNER, uid=0, code='', container=EQUIPPED, slot=old_slot, count=0),
            ]
        else:
            code = target_item.get('code', '')
            if req.equip_slot >= 0:
                target_slot = req.equip_slot
            else:
                taken = {i.get('slot') for i in items if i.get('container') == EQUIPPED}
                fitting = [s for s in range(31) if fits_equip_slot(code, s)]
                free = [s for s in fitting if s not in taken]
                target_slot = (free or fitting or [None])[0]
            if target_slot is None or not fits_equip_slot(code, target_slot):
                await self.reply(EquipItemAck(result=1), correlation,
                                 note='equip item fail (%s does not fit slot %s)' % (code, target_slot))
                return
            previous_equipped = next(
                (i for i in items if i.get('container') == EQUIPPED and i.get('slot') == target_slot), None)
            if previous_equipped and previous_equipped is not target_item:
                previous_equipped['container'], previous_equipped['slot'] = old_container, old_slot
                target_item['container'], target_item['slot'] = EQUIPPED, target_slot
                self.save_char()
                wire_items = [Item(owner=UPDATE_OWNER, **previous_equipped), Item(owner=UPDATE_OWNER, **target_item)]
            else:
                target_item['container'], target_item['slot'] = EQUIPPED, target_slot
                self.save_char()
                wire_items = [
                    Item(owner=UPDATE_OWNER, **target_item),
                    Item(owner=UPDATE_OWNER, uid=0, code='', container=old_container, slot=old_slot, count=0),
                ]
        await self.reply(EquipItemAck(result=0, items=wire_items), correlation,
                         note='equip item ack (uid=%d slot=%d)' % (req.item_uid, target_item.get('slot', 0)))

    @packet_handler(DeleteItemReq)
    async def handle_delete_item(self, correlation, body):
        """Opcode 2040 (eEGS_DELETE_ITEM_REQ) -> 2041 (eEGS_DELETE_ITEM_ACK): discard an item or stack portion."""
        req = DeleteItemReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(DeleteItemAck(result=1, item_uid=req.item_uid, del_amount=0),
                             correlation, note='delete item fail (no char)')
            return
        items = char.get('items', [])
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(DeleteItemAck(result=1, item_uid=req.item_uid, del_amount=0),
                             correlation, note='delete item fail (not found)')
            return
        current_count = target.get('count', 1)
        del_amount = min(req.amount if req.amount > 0 else 1, current_count)
        removed = current_count <= del_amount
        cleared_slots = []
        if removed:
            items.remove(target)
            # Clear item quickslots bound directly to this item's UID (non-stackable items).
            # Stackable items are bound by ref_id with ref_uid=-1 and stay on the bar at 0.
            qs = char.get('quickslots')
            if isinstance(qs, dict):
                for key, entry in list(qs.items()):
                    if entry.get('type') == 0 and entry.get('ref_uid') == req.item_uid:
                        cleared_slots.append((entry.get('type', 0), entry.get('slot', 0)))
                        qs.pop(key, None)
        else:
            target['count'] = current_count - del_amount
        self.save_char()
        await self.reply(DeleteItemAck(result=0, item_uid=req.item_uid, del_amount=del_amount),
                         correlation, note=f'delete item ack (uid={req.item_uid} amount={del_amount})')
        for slot_type, slot_num in cleared_slots:
            await self.send_msg(
                AssignQuickslotAck(result=0, slot_type=slot_type, slot_num=slot_num, ref_id=-1, ref_uid=-1),
                note=f'clear deleted item quickslot (type={slot_type} slot={slot_num})',
            )
        # Client 0x00557420 (2041 DeleteItemAck) only refreshes UI 0 (Inventory) and omits
        # UI 7 (Quickslot); an empty 2037 DragItemAck triggers 0x0077F570 to refresh [0, 7, 2, 0xc, 0xe].
        await self.send_msg(DragItemAck(result=0, items=[]), note='refresh quickslot ui after delete')

    @packet_handler(BuyLifeWaterReq)
    async def handle_buy_life_water(self, correlation, body):
        """Opcode 2086 (eEGS_BUY_LIFE_WATER_REQ) -> 2087 (eEGS_BUY_LIFE_WATER_ACK): cure dungeon penalty for AR."""
        from darkblood.games.progression import clear_dungeon_penalty, life_water_cost
        req = BuyLifeWaterReq.decode(body)
        self.transport.record('buy-life-water-req', body, flag=req.flag)
        char = self.current_char()
        if char is None:
            await self.reply(BuyLifeWaterAck(result=1, flag=req.flag, remain_currency=0),
                             correlation, note='buy life water ack (no char)')
            return
        penalty_type = 1 if req.flag else 0
        gold = int(char.get('gold', 0))
        cost = life_water_cost(char, penalty_type=penalty_type)
        if cost > gold:
            await self.reply(BuyLifeWaterAck(result=1, flag=req.flag, remain_currency=gold),
                             correlation, note=f'buy life water refused (need {cost} AR, have {gold})')
            return
        gold -= cost
        char['gold'] = gold
        clear_not = clear_dungeon_penalty(char, penalty_type=penalty_type)
        self.save_char()
        await self.reply(BuyLifeWaterAck(result=0, flag=req.flag, remain_currency=gold),
                         correlation, note=f'buy life water ack (flag={req.flag}, -{cost} AR)')
        if cost > 0:
            await self.transport.send_event(
                event(2085, clear_not.encode()),
                note=f'clear dungeon penalty (type={penalty_type})',
            )

    @packet_handler(2119)
    async def handle_alarm_update(self, correlation, body):
        """Opcode 2119 (eEGS_ALARM_UPDATE_REQ) -> 2120 (eEGS_ALARM_UPDATE_ACK): acknowledge alarm flags."""
        rest = body[4:] if len(body) >= 7 else b'\x00\x00\x10\x80'
        await self.transport.send_event(event(2120, struct.pack('<I', 0) + rest, correlation),
                                        note='alarm update ack')

    @packet_handler(SealItemReq)
    async def handle_seal_item(self, correlation, body):
        """Opcode 2147 (eEGS_SEAL_ITEM_REQ) -> 2148 (eEGS_SEAL_ITEM_ACK): seal a tradable equipment piece."""
        req = SealItemReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(SealItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'seal item fail (uid={req.item_uid} not found)')
            return
        await self.reply(SealItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **target)]), correlation,
                         note=f'seal item ack (uid={req.item_uid})')

    @packet_handler(DivideItemReq)
    async def handle_divide_item(self, correlation, body):
        """Opcode 2250 (eEGS_DIVIDE_ITEM_REQ) -> 2251 (eEGS_DIVIDE_ITEM_ACK): split a stacked item."""
        req = DivideItemReq.decode(body)
        self.transport.record('divide-item-req', body, source_uid=req.source_item_uid, count=req.count)
        await self.reply(DivideItemAck(result=0, items=[]), correlation,
                         note=f'divide item ack (item={req.source_item_uid})')

    @packet_handler(CharVerifyStatReq)
    async def handle_char_verify_stat(self, correlation, body):
        """Opcode 2406 (eEGS_CHAR_VERIFY_STAT_REQ) -> 2407 (eEGS_CHAR_VERIFY_STAT_ACK): accept client combat stat report."""
        await self.reply(CharVerifyStatAck(result=0), correlation, note='char verify stat ack')

    @packet_handler(UseSelectedSkillChangeItemReq)
    async def handle_use_selected_skill_change_item(self, correlation, body):
        """Opcode 2428 (eEGS_USE_SELECTED_SKILL_CHANGE_ITEM_REQ) -> 2429: reset/change a selected skill via item."""
        req = UseSelectedSkillChangeItemReq.decode(body)
        char = self.current_char()
        sp = char.get('sp', 0) if char else 0
        await self.reply(
            UseSelectedSkillChangeItemAck(result=0, margin_ap=sp, learned_skills={}, items=[], quickslots=[]),
            correlation, note=f'use selected skill change item ack (item={req.item_uid})')

    @packet_handler(ItemDecomposeReq)
    async def handle_item_decompose(self, correlation, body):
        """Opcode 2545 (eEGS_ITEM_DECOMPOSE_REQ) -> 2546 (eEGS_ITEM_DECOMPOSE_ACK): dismantle an item."""
        req = ItemDecomposeReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(ItemDecomposeAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'item decompose fail (uid={req.item_uid} not found)')
            return
        items.remove(target)
        self.save_char()
        vacated = Item(owner=UPDATE_OWNER, uid=0, code='', container=target['container'],
                       slot=target['slot'], count=0)
        await self.reply(ItemDecomposeAck(result=0, items=[vacated]), correlation,
                         note=f'item decompose ack (uid={req.item_uid})')

    @packet_handler(UseItemLeaguePointAddReq)
    async def handle_use_league_point_item(self, correlation, body):
        """Opcode 2573 (eEGS_USE_ITEM_LEAGUE_POINT_ADD_REQ) -> 2574: consume an item that awards league points."""
        req = UseItemLeaguePointAddReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(UseItemLeaguePointAddAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'use league point item fail (uid={req.item_uid} not found)')
            return
        count = target.get('count', 1) - 1
        if count <= 0:
            items.remove(target)
            update = Item(owner=UPDATE_OWNER, uid=0, code='', container=target['container'],
                          slot=target['slot'], count=0)
        else:
            target['count'] = count
            update = Item(owner=UPDATE_OWNER, **target)
        char['league_points'] = char.get('league_points', 0) + 100
        self.save_char()
        await self.reply(
            UseItemLeaguePointAddAck(result=0, items=[update], league_point=char['league_points']),
            correlation, note=f'use league point item ack (uid={req.item_uid} pts={char["league_points"]})')

    @packet_handler(UseArenaSpItemReq)
    async def handle_use_arena_sp_item(self, correlation, body):
        """Opcode 2709 (eEGS_USE_ARENA_SP_ITEM_REQ) -> 2710 (eEGS_USE_ARENA_SP_ITEM_ACK): consume an arena SP item."""
        req = UseArenaSpItemReq.decode(body)
        self.transport.record('use-arena-sp-item-req', body, item_uid=req.item_uid)
        await self.reply(UseArenaSpItemAck(result=0, consumed_items=[], arena_sp=100), correlation,
                         note=f'use arena sp item ack (item={req.item_uid})')
