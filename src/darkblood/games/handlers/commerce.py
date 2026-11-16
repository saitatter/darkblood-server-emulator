import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.entities.items import EQUIPPED, Item
from darkblood.games.network.messages import (
    AssignQuickslotAck,
    AssignQuickslotReq,
    BuyItemAck,
    BuyItemReq,
    BuyLifeWaterAck,
    BuyLifeWaterReq,
    ChangeBagNameAck,
    ChangeBagNameReq,
    ChangeBagPropertyAck,
    ChangeBagPropertyReq,
    CharVerifyStatAck,
    CloseBagReq,
    CurrentCashAck,
    DeleteItemAck,
    DeleteItemReq,
    DeleteSkillSpeechAck,
    DeleteSkillSpeechReq,
    DragItemAck,
    DragItemReq,
    DurabilityRepairAck,
    DurabilityRepairReq,
    EquipItemAck,
    EquipItemReq,
    HttpNoticeCheckAck,
    ItemUpgradeAck,
    ItemUpgradeReq,
    LearnSkillAck,
    LearnSkillReq,
    ModifySkillSpeechAck,
    ModifySkillSpeechReq,
    PlayOptionUpdateReq,
    RepurchaseItemAck,
    RepurchaseItemReq,
    RouletteManagerInfoAck,
    SellItemAck,
    SellItemReq,
    StoreInfoAck,
    SwitchBagAck,
    SwitchBagReq,
    SwitchQuickslotAck,
    SwitchQuickslotReq,
    TamingMonsterDeleteAck,
    TamingMonsterInsertAck,
    UpdateSkillLockedAck,
    UpdateSkillLockedReq,
    UseItemAck,
    UseItemReq,
)
from darkblood.games.state import selected_character



class CommerceHandlers:
    """Stores, cash, roulette, pets and alarm settings."""

    async def on_2065(self, correlation, body):
        # eEGS_GET_STORE_INFO_REQ (i32, u32 npc id; observed when talking to a
        # shop NPC) -> eEGS_GET_STORE_INFO_ACK 2066: empty store.
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        from darkblood.games.game_data import client_dict
        npc, items = client_dict.items_for_npc(npc_id)
        ack = StoreInfoAck(npc_id=npc_id, items=items).encode()
        await self.transport.send_event(event(2066, ack, correlation),
                                        note='store info ack (%s, %d items)' % (npc or '%08x' % npc_id, len(items)))

    async def on_2369(self, correlation, body):
        # eEGS_BILLING_GET_CURRENT_CASH_REQ -> 2370: result, u64 cash, u32 mileage.
        # Cash is per account (store meta, set from the dashboard); mileage 0.
        cash = self.store().account_cash(self.account)
        await self.transport.send_event(event(2370, CurrentCashAck(cash=cash).encode(), correlation),
                                        note='current cash ack (%d)' % cash)

    async def on_2390(self, correlation, body):
        # eEGS_ROULETTE_MANAGER_INFO_REQ -> eEGS_ROULETTE_MANAGER_INFO_ACK (2391), handler 0x6CC6B0:
        # u32 result (0), untagged 21 bytes (0xA48B80).
        ack = RouletteManagerInfoAck().encode()
        await self.transport.send_event(event(2391, ack, correlation), note='roulette manager info ack')

    async def on_2348(self, correlation, body):
        # eEGS_TAMEING_MONSTER_INSERT_REQ -> eEGS_TAMEING_MONSTER_INSERT_ACK (2349), handler 0x771A00:
        # u32 result (0 = success) + tag 0x10 vector.
        ack = TamingMonsterInsertAck().encode()
        await self.transport.send_event(event(2349, ack, correlation), note='taming monster insert ack')

    async def on_2350(self, correlation, body):
        # eEGS_TAMEING_MONSTER_DELETE_REQ -> eEGS_TAMEING_MONSTER_DELETE_ACK (2351), handler 0x771BB0:
        # u32 result (0 = success) + tag 0x10 vector.
        ack = TamingMonsterDeleteAck().encode()
        await self.transport.send_event(event(2351, ack, correlation), note='taming monster delete ack')

    async def on_2119(self, correlation, body):
        # eEGS_ALARM_UPDATE_REQ (observed: i32 0x7FFFFFFF, i16, tag 0x10
        # vector<i32>) -> eEGS_ALARM_UPDATE_ACK 2120 (handler 0x771150):
        # u32 result, i16, tag 0x10 vector<i32> (0x4D6E60). Echo the
        # requested settings so the client keeps what it asked for.
        rest = body[4:] if len(body) >= 7 else b'\x00\x00\x10\x80'
        await self.transport.send_event(event(2120, struct.pack('<I', 0) + rest, correlation),
                                        note='alarm update ack')

    async def on_2028(self, correlation, body):
        # eEGS_CLOSE_BAG_REQ (0x00550000.c:1773).
        req = CloseBagReq.decode(body)
        self.transport.record('close-bag', body, bag_id=req.bag_id)

    async def on_2036(self, correlation, body):
        # eEGS_DRAG_ITEM_REQ (0x00790000.c:4212) -> 2037 eEGS_DRAG_ITEM_ACK (0x0077F570).
        req = DragItemReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if not char:
            ack = DragItemAck(result=1).encode()
            await self.transport.send_event(event(2037, ack, correlation), note='drag item fail (no char)')
            return
        items = char.get('items', [])
        dragged = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not dragged:
            ack = DragItemAck(result=1).encode()
            await self.transport.send_event(event(2037, ack, correlation), note='drag item fail (not found)')
            return
        old_container = dragged.get('container')
        old_slot = dragged.get('slot')

        if req.to_container == 2:
            ack = DragItemAck(result=1).encode()
            await self.transport.send_event(event(2037, ack, correlation), note='drag item fail (invalid container 2)')
            return

        from darkblood.player_management.characters import fits_equip_slot
        if req.to_container == EQUIPPED and not fits_equip_slot(dragged.get('code', ''), req.to_slot):
            ack = DragItemAck(result=1).encode()
            await self.transport.send_event(event(2037, ack, correlation),
                                            note='drag item fail (item does not fit equip slot %d)' % req.to_slot)
            return

        target = next((i for i in items if i.get('container') == req.to_container and i.get('slot') == req.to_slot), None)
        from darkblood.games.entities.items import Item
        if target is dragged:
            # Dropped on its own cell: nothing moves. Sending the usual empty
            # record for the old cell would clear the item in the client
            # (live 2026-11-17: a repeated drag emptied the bag cell).
            ack = DragItemAck(result=0, items=[Item(owner=char.get('id', -1), **dragged)]).encode()
            await self.transport.send_event(event(2037, ack, correlation), note='drag item ack (no move)')
            return
        if target:
            # The displaced item takes the dragged item's old cell; an
            # equipment cell must accept it (live: a necklace landed in the
            # shoulder slot and shoulder pads in the glove slot).
            if old_container == EQUIPPED and not fits_equip_slot(target.get('code', ''), old_slot):
                ack = DragItemAck(result=1).encode()
                await self.transport.send_event(event(2037, ack, correlation),
                                                note='drag item fail (displaced item does not fit equip slot %d)' % old_slot)
                return
            target['container'], target['slot'] = old_container, old_slot
            dragged['container'], dragged['slot'] = req.to_container, req.to_slot
            self.store().save()
            wire_items = [
                Item(owner=char.get('id', -1), **dragged),
                Item(owner=char.get('id', -1), **target)
            ]
        else:
            dragged['container'] = req.to_container
            dragged['slot'] = req.to_slot
            self.store().save()
            wire_items = [
                Item(owner=char.get('id', -1), **dragged),
                Item(owner=char.get('id', -1), uid=0, code='', container=old_container, slot=old_slot, count=0)
            ]

        ack = DragItemAck(result=0, items=wire_items).encode()
        await self.transport.send_event(event(2037, ack, correlation),
                                        note='drag item ack (uid=%d to c=%d s=%d)' % (req.item_uid, req.to_container, req.to_slot))


    async def on_2406(self, correlation, body):
        # eEGS_CHAR_VERIFY_STAT_REQ -> 2407 eEGS_CHAR_VERIFY_STAT_ACK (0x0074B830).
        ack = CharVerifyStatAck(result=0).encode()
        await self.transport.send_event(event(2407, ack, correlation),
                                        note='char verify stat ack')

    async def on_2038(self, correlation, body):
        # eEGS_USE_ITEM_REQ (0x00780000.c:8159) -> 2039 eEGS_USE_ITEM_ACK (0x0077D4C0).
        req = UseItemReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if not char:
            ack = UseItemAck(result=1).encode()
            await self.transport.send_event(event(2039, ack, correlation), note='use item fail (no char)')
            return
        items = char.get('items', [])
        used_item = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not used_item:
            ack = UseItemAck(result=1).encode()
            await self.transport.send_event(event(2039, ack, correlation), note='use item fail (not found)')
            return
        # Consumable items decrement count or remove if exhausted
        item_code = jhash(used_item.get('code', ''))
        count = used_item.get('count', 1) - req.use_count
        updated = []
        if count <= 0:
            items.remove(used_item)
        else:
            used_item['count'] = count
            updated.append(Item(owner=char.get('id', -1), **used_item))
        self.store().save()

        ack = UseItemAck(result=0, items=updated, item_id=item_code, use_count=req.use_count).encode()
        await self.transport.send_event(event(2039, ack, correlation),
                                        note='use item ack (uid=%d code=%08x)' % (req.item_uid, item_code))

    async def on_2042(self, correlation, body):
        # eEGS_EQUIP_ITEM_REQ (0x00800000.c:500) -> 2043 eEGS_EQUIP_ITEM_ACK (0x007AE940).
        req = EquipItemReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if not char:
            ack = EquipItemAck(result=1).encode()
            await self.transport.send_event(event(2043, ack, correlation), note='equip item fail (no char)')
            return
        items = char.get('items', [])
        target_item = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target_item:
            ack = EquipItemAck(result=1).encode()
            await self.transport.send_event(event(2043, ack, correlation), note='equip item fail (not found)')
            return

        from darkblood.games.entities.items import Item
        old_container = target_item.get('container')
        old_slot = target_item.get('slot')

        if old_container == EQUIPPED:
            # Unequip action: move equipped item back to the first available bag slot
            from darkblood.player_management.characters import INVENTORY_BAG_CONTAINER, DEFAULT_BAG_CAPACITY
            bag_id = INVENTORY_BAG_CONTAINER
            bag = next((b for b in char.get('bags', []) if b.get('bag_id') != EQUIPPED and b.get('bag_id') != 2), None)
            if bag:
                bag_id = bag.get('bag_id', INVENTORY_BAG_CONTAINER)
            used_slots = {i.get('slot') for i in items if i.get('container') == bag_id}
            capacity = bag.get('b29', DEFAULT_BAG_CAPACITY) if bag else DEFAULT_BAG_CAPACITY
            free_slot = next((s for s in range(capacity) if s not in used_slots), None)
            if free_slot is None:
                free_slot = max(used_slots, default=-1) + 1
            target_item['container'] = bag_id
            target_item['slot'] = free_slot
            self.store().save()
            wire_items = [
                Item(owner=char.get('id', -1), **target_item),
                Item(owner=char.get('id', -1), uid=0, code='', container=EQUIPPED, slot=old_slot, count=0)
            ]
        else:
            # Equip action: move from bag to equipped slot
            from darkblood.player_management.characters import fits_equip_slot
            code = target_item.get('code', '')
            if req.equip_slot >= 0:
                target_slot = req.equip_slot
            else:
                # Right-click: the item's own slot (swapping out what is there);
                # accessories take the first free of slots 7-12.
                taken = {i.get('slot') for i in items if i.get('container') == EQUIPPED}
                fitting = [s for s in range(14) if fits_equip_slot(code, s)]
                free = [s for s in fitting if s not in taken]
                target_slot = (free or fitting or [None])[0]
            if target_slot is None or not fits_equip_slot(code, target_slot):
                ack = EquipItemAck(result=1).encode()
                await self.transport.send_event(event(2043, ack, correlation),
                                                note='equip item fail (%s does not fit slot %s)' % (code, target_slot))
                return
            previous_equipped = next((i for i in items if i.get('container') == EQUIPPED and i.get('slot') == target_slot), None)
            if previous_equipped and previous_equipped is not target_item:
                previous_equipped['container'] = old_container
                previous_equipped['slot'] = old_slot
                target_item['container'] = EQUIPPED
                target_item['slot'] = target_slot
                self.store().save()
                wire_items = [
                    Item(owner=char.get('id', -1), **target_item),
                    Item(owner=char.get('id', -1), **previous_equipped)
                ]
            else:
                target_item['container'] = EQUIPPED
                target_item['slot'] = target_slot
                self.store().save()
                wire_items = [
                    Item(owner=char.get('id', -1), **target_item),
                    Item(owner=char.get('id', -1), uid=0, code='', container=old_container, slot=old_slot, count=0)
                ]

        ack = EquipItemAck(result=0, items=wire_items).encode()
        await self.transport.send_event(event(2043, ack, correlation),
                                        note='equip item ack (uid=%d slot=%d)' % (req.item_uid, target_item.get('slot', 0)))

    async def on_2044(self, correlation, body):
        # eEGS_ASSIGN_QUICKSLOT_REQ (0x00780000.c:8513) -> 2045 eEGS_ASSIGN_QUICKSLOT_ACK (0x0078C4A0).
        req = AssignQuickslotReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            qs = char.setdefault('quickslots', {})
            qs[str(req.slot_num)] = dict(type=req.slot_type, ref_id=req.ref_id, ref_uid=req.ref_uid)
            self.store().save()

        ack = AssignQuickslotAck(result=0, slot_type=req.slot_type, slot_num=req.slot_num,
                                 ref_id=req.ref_id, ref_uid=req.ref_uid).encode()
        await self.transport.send_event(event(2045, ack, correlation),
                                        note='assign quickslot ack (slot=%d ref=%08x)' % (req.slot_num, req.ref_id))

    async def on_2040(self, correlation, body):
        # eEGS_DELETE_ITEM_REQ (0x00550000.c:769) -> 2041 eEGS_DELETE_ITEM_ACK (0x00557420).
        req = DeleteItemReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if not char:
            ack = DeleteItemAck(result=1, item_uid=req.item_uid, del_amount=0).encode()
            await self.transport.send_event(event(2041, ack, correlation), note='delete item fail (no char)')
            return
        items = char.get('items', [])
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            ack = DeleteItemAck(result=1, item_uid=req.item_uid, del_amount=0).encode()
            await self.transport.send_event(event(2041, ack, correlation), note='delete item fail (not found)')
            return
        current_count = target.get('count', 1)
        del_amount = min(req.amount if req.amount > 0 else 1, current_count)
        if current_count <= del_amount:
            items.remove(target)
        else:
            target['count'] = current_count - del_amount
        self.store().save()
        ack = DeleteItemAck(result=0, item_uid=req.item_uid, del_amount=del_amount).encode()
        await self.transport.send_event(event(2041, ack, correlation),
                                        note=f'delete item ack (uid={req.item_uid} amount={del_amount})')

    async def on_2030(self, correlation, body):
        # eEGS_SWITCH_BAG_REQ (0x00550000.c:626) -> 2031 eEGS_SWITCH_BAG_ACK (0x00557680).
        req = SwitchBagReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            bags = char.get('bags', [])
            if req.from_index < len(bags) and req.to_index < len(bags):
                bags[req.from_index], bags[req.to_index] = bags[req.to_index], bags[req.from_index]
                self.store().save()
        ack = SwitchBagAck(result=0, from_index=req.from_index, to_index=req.to_index).encode()
        await self.transport.send_event(event(2031, ack, correlation),
                                        note=f'switch bag ack ({req.from_index} <-> {req.to_index})')

    async def on_2046(self, correlation, body):
        # eEGS_SWITCH_QUCIKSLOT_REQ (0x00780000.c:8591) -> 2047 eEGS_SWITCH_QUCIKSLOT_ACK (0x0078C790).
        req = SwitchQuickslotReq.decode(body)
        ack = SwitchQuickslotAck(result=0, slot_type=req.slot_type,
                                 from_slot=req.from_slot, to_slot=req.to_slot).encode()
        await self.transport.send_event(event(2047, ack, correlation),
                                        note=f'switch quickslot ack ({req.from_slot} -> {req.to_slot})')

    async def on_2594(self, correlation, body):
        # eEGS_HTTPNOTICE_CHECK_REQ -> 2595 eEGS_HTTPNOTICE_CHECK_ACK (0x005A5110).
        ack = HttpNoticeCheckAck(result=0, watch=False).encode()
        await self.transport.send_event(event(2595, ack, correlation), note='http notice check ack')

    async def on_2216(self, correlation, body):
        # eEGS_PLAY_OPTION_UPDATE_REQ (0x00790000.c:3729) - fire and forget.
        req = PlayOptionUpdateReq.decode(body)
        self.transport.record('play-option-update', body, char_uid=req.char_uid)

    async def on_2050(self, correlation, body):
        # eEGS_LEARN_SKILL_REQ (0x00780000.c:9504) -> 2051 eEGS_LEARN_SKILL_ACK (0x0078DBE0).
        req = LearnSkillReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        remain_sp = 100
        remain_gold = 10000
        if char:
            skills = char.setdefault('skills', {})
            skills[str(req.skill_index)] = req.level
            self.store().save()
            remain_gold = char.get('gold', 10000)
            remain_sp = char.get('sp', 100)
        ack = LearnSkillAck(result=0, skill_index=req.skill_index, level=req.level,
                            remain_sp=remain_sp, remain_gold=remain_gold).encode()
        await self.transport.send_event(event(2051, ack, correlation),
                                        note=f'learn skill ack (skill={req.skill_index} lvl={req.level})')

    async def on_2048(self, correlation, body):
        # eEGS_CHANGE_BAG_PROPERTY_REQ (0x00550000.c:676) -> 2049 eEGS_CHANGE_BAG_PROPERTY_ACK (0x00774040).
        req = ChangeBagPropertyReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            for bag in char.get('bags', []):
                if bag.get('bag_id') == req.bag_uid:
                    bag['b28'] = req.property
                    break
            self.store().save()
        ack = ChangeBagPropertyAck(result=0, bag_uid=req.bag_uid, property=req.property).encode()
        await self.transport.send_event(event(2049, ack, correlation),
                                        note=f'change bag property ack (bag={req.bag_uid} prop={req.property})')

    async def on_2053(self, correlation, body):
        # eEGS_MODIFY_SKILL_SPEECH_REQ (0x00780000.c:9674) -> 2054 eEGS_MODIFY_SKILL_SPEECH_ACK (0x0078E090).
        req = ModifySkillSpeechReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            speeches = char.setdefault('skill_speeches', {})
            speeches[str(req.skill_index)] = req.speech
            self.store().save()
        ack = ModifySkillSpeechAck(result=0, skill_index=req.skill_index, speech=req.speech).encode()
        await self.transport.send_event(event(2054, ack, correlation),
                                        note=f'modify skill speech ack (skill={req.skill_index})')

    async def on_2055(self, correlation, body):
        # eEGS_DELETE_SKILL_SPEECH_REQ (0x00780000.c:9708) -> 2056 eEGS_DELETE_SKILL_SPEECH_ACK (0x0078E270).
        req = DeleteSkillSpeechReq.decode(body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            speeches = char.setdefault('skill_speeches', {})
            speeches.pop(str(req.skill_index), None)
            self.store().save()
        ack = DeleteSkillSpeechAck(result=0, skill_index=req.skill_index).encode()
        await self.transport.send_event(event(2056, ack, correlation),
                                        note=f'delete skill speech ack (skill={req.skill_index})')

    async def on_2067(self, correlation, body):
        # eEGS_BUY_ITEM_REQ (0x00780000.c:10667) -> 2068 eEGS_BUY_ITEM_ACK (0x0077E2F0).
        req = BuyItemReq.decode(body)
        self.transport.record('buy-item-req', body, store_id=req.store_id, item_id=req.item_id, count=req.count)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if not char:
            ack = BuyItemAck(result=1).encode()
            await self.transport.send_event(event(2068, ack, correlation), note='buy item fail (no char)')
            return

        from darkblood.games.game_data import client_dict
        from darkblood.player_management.characters import add_reward_items
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
        cost = 100 * count
        char_gold = char.get('gold', 100000)
        if char_gold >= cost:
            char_gold -= cost
            char['gold'] = char_gold
            char['u66'] = char_gold
            new_items = add_reward_items(char, [(item_code, count)])
            self.store().save()
            wire_items = [Item(owner=char.get('id', -1), **i) for i in new_items]
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
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
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

        earned = 50 * del_cnt
        char_gold = char.get('gold', 0) + earned
        char['gold'] = char_gold
        char['u66'] = char_gold
        self.store().save()

        wire_items = [Item(owner=char.get('id', -1), **i) for i in items]
        ack = SellItemAck(result=0, gold=char_gold, items=wire_items).encode()
        await self.transport.send_event(event(2070, ack, correlation),
                                        note=f'sell item ack (uid={req.item_uid} del={del_cnt} gold={char_gold})')

    async def on_2071(self, correlation, body):
        # eEGS_REPURCHASE_ITEM_REQ (0x00780000.c:10735) -> 2072 eEGS_REPURCHASE_ITEM_ACK (0x0077EC30).
        req = RepurchaseItemReq.decode(body)
        self.transport.record('repurchase-item-req', body, item_uid=req.item_uid)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        char_gold = char.get('gold', 0) if char else 0
        ack = RepurchaseItemAck(result=0, gold=char_gold, items=[]).encode()
        await self.transport.send_event(event(2072, ack, correlation),
                                        note=f'repurchase item ack (item={req.item_uid})')

    async def on_2032(self, correlation, body):
        # eEGS_CHANGE_BAG_NAME_REQ -> 2033 eEGS_CHANGE_BAG_NAME_ACK (0x007528B0).
        req = ChangeBagNameReq.decode(body)
        self.transport.record('change-bag-name-req', body, bag_uid=req.bag_uid, name=req.name)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            for b in char.get('bags', []):
                if b.get('bag_id') == req.bag_uid:
                    b['name'] = req.name
                    break
            self.store().save()
        ack = ChangeBagNameAck(result=0, bag_uid=req.bag_uid, name=req.name).encode()
        await self.transport.send_event(event(2033, ack, correlation),
                                        note=f'change bag name ack (bag={req.bag_uid} name={req.name})')

    async def on_2086(self, correlation, body):
        # eEGS_BUY_LIFE_WATER_REQ (0x00780000.c:11036) -> 2087 eEGS_BUY_LIFE_WATER_ACK (0x0078FF90).
        req = BuyLifeWaterReq.decode(body)
        self.transport.record('buy-life-water-req', body, flag=req.flag)
        char = None
        gold = 0
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            gold = char.get('gold', 100000)
        ack = BuyLifeWaterAck(result=0, flag=req.flag, remain_currency=gold).encode()
        await self.transport.send_event(event(2087, ack, correlation),
                                        note=f'buy life water ack (flag={req.flag})')

    async def on_2115(self, correlation, body):
        # eEGS_ITEM_UPGRADE_REQ (0x00790000.c:296) -> 2116 eEGS_ITEM_UPGRADE_ACK (0x007909C0).
        req = ItemUpgradeReq.decode(body)
        self.transport.record('item-upgrade-req', body, target=req.target_uid, catalyst=req.catalyst_uid, protect=req.protect_uid)
        # Result 1: generic failure until item upgrade engine is connected
        ack = ItemUpgradeAck(result=1).encode()
        await self.transport.send_event(event(2116, ack, correlation),
                                        note=f'item upgrade ack (target={req.target_uid})')

    async def on_2117(self, correlation, body):
        # eEGS_UPDATE_SKILL_LOCKED_REQ (0x00790000.c:1390) -> 2118 eEGS_UPDATE_SKILL_LOCKED_ACK (0x00752C70).
        req = UpdateSkillLockedReq.decode(body)
        self.transport.record('update-skill-locked-req', body, skill=req.skill_index, locked=req.locked)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            locked = set(char.setdefault('locked_skills', []))
            if req.locked:
                locked.add(req.skill_index)
            else:
                locked.discard(req.skill_index)
            char['locked_skills'] = sorted(list(locked))
            self.store().save()
        ack = UpdateSkillLockedAck(result=0, skill_index=req.skill_index, locked=req.locked).encode()
        await self.transport.send_event(event(2118, ack, correlation),
                                        note=f'update skill locked ack (skill={req.skill_index} locked={req.locked})')

    async def on_2145(self, correlation, body):
        # eEGS_DURABILITY_REPAIR_REQ (0x00790000.c:2123) -> 2146 eEGS_DURABILITY_REPAIR_ACK (0x007930D0).
        req = DurabilityRepairReq.decode(body)
        self.transport.record('durability-repair-req', body)
        char = None
        gold = 0
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            gold = char.get('gold', 100000)
        ack = DurabilityRepairAck(result=0, remain_gold=gold).encode()
        await self.transport.send_event(event(2146, ack, correlation),
                                        note='durability repair ack (success, 0 items repaired)')

    async def on_2121(self, correlation, body):
        # eEGS_CONTRACT_UPDATE_REQ -> 2122 eEGS_CONTRACT_UPDATE_ACK (0x00752D80).
        from darkblood.games.network.messages import ContractUpdateAck, ContractUpdateReq
        req = ContractUpdateReq.decode(body)
        self.transport.record('contract-update-req', body, contract_id=req.contract_id)
        ack = ContractUpdateAck(result=0, contract_id=req.contract_id).encode()
        await self.transport.send_event(event(2122, ack, correlation),
                                        note=f'contract update ack (contract={req.contract_id})')

    async def on_2143(self, correlation, body):
        # eEGS_DURABILITY_CHANGE_REQ (0x00790000.c:2049) -> 2144 eEGS_DURABILITY_CHANGE_ACK (0x00774AE0).
        from darkblood.games.network.messages import DurabilityChangeAck, DurabilityChangeReq
        req = DurabilityChangeReq.decode(body)
        self.transport.record('durability-change-req', body)
        ack = DurabilityChangeAck(result=0).encode()
        await self.transport.send_event(event(2144, ack, correlation), note='durability change ack')

    async def on_5069(self, correlation, body):
        # eERC_REQUEST_TRADE_REQ -> 5070 eERC_REQUEST_TRADE_ACK (0x00770E50).
        from darkblood.games.network.messages import RequestTradeAck, RequestTradeReq
        req = RequestTradeReq.decode(body)
        self.transport.record('trade-request-req', body, target=req.target_uid)
        ack = RequestTradeAck(result=0, target_uid=req.target_uid, target_name='Partner').encode()
        await self.transport.send_event(event(5070, ack, correlation), note=f'trade request ack (target={req.target_uid})')

    async def on_5071(self, correlation, body):
        # eERC_ACCEPT_REQUEST_TRADE_REQ -> 5072 eERC_ACCEPT_REQUEST_TRADE_ACK (0x007587B0).
        from darkblood.games.network.messages import AcceptRequestTradeAck, AcceptRequestTradeReq
        from darkblood.games.state import selected_character
        req = AcceptRequestTradeReq.decode(body)
        self.transport.record('trade-accept-request-req', body, source=req.source_uid)
        my_uid = selected_character.get('id', 1)
        ack = AcceptRequestTradeAck(result=0, source_uid=req.source_uid, target_uid=my_uid).encode()
        await self.transport.send_event(event(5072, ack, correlation), note='trade accept request ack')

    async def on_5073(self, correlation, body):
        # eERC_CANCEL_TRADE_REQ -> 5074 eERC_CANCEL_TRADE_ACK (0x0077DE00).
        from darkblood.games.network.messages import CancelTradeAck
        self.transport.record('trade-cancel-req', body)
        ack = CancelTradeAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5074, ack, correlation), note='trade cancel ack')

    async def on_5075(self, correlation, body):
        # eERC_INSERT_TRADE_ITEM_REQ -> 5076 eERC_INSERT_TRADE_ITEM_ACK (0x0077D980).
        from darkblood.games.network.messages import InsertTradeItemAck, InsertTradeItemReq
        req = InsertTradeItemReq.decode(body)
        self.transport.record('trade-insert-item-req', body, item_uid=req.item_uid, slot=req.slot)
        ack = InsertTradeItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5076, ack, correlation), note=f'trade insert item ack (item={req.item_uid})')

    async def on_5077(self, correlation, body):
        # eERC_DELETE_TRADE_ITEM_REQ -> 5078 eERC_DELETE_TRADE_ITEM_ACK (0x0077DBB0).
        from darkblood.games.network.messages import DeleteTradeItemAck, DeleteTradeItemReq
        req = DeleteTradeItemReq.decode(body)
        self.transport.record('trade-delete-item-req', body, item_uid=req.item_uid)
        ack = DeleteTradeItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(5078, ack, correlation), note=f'trade delete item ack (item={req.item_uid})')

    async def on_5079(self, correlation, body):
        # eERC_UPDATE_TRADE_AR_REQ -> 5080 eERC_UPDATE_TRADE_AR_ACK (0x00758940).
        from darkblood.games.network.messages import UpdateTradeArAck, UpdateTradeArReq
        from darkblood.games.state import selected_character
        req = UpdateTradeArReq.decode(body)
        self.transport.record('trade-update-ar-req', body, gold=req.gold)
        my_uid = selected_character.get('id', 1)
        ack = UpdateTradeArAck(result=0, char_uid=my_uid, gold=req.gold).encode()
        await self.transport.send_event(event(5080, ack, correlation), note=f'trade update ar ack (gold={req.gold})')

    async def on_5081(self, correlation, body):
        # eERC_ACCEPT_TRADE_REQ -> 5082 eERC_ACCEPT_TRADE_ACK (0x0078EB40).
        from darkblood.games.network.messages import AcceptTradeAck
        from darkblood.games.state import selected_character
        self.transport.record('trade-accept-req', body)
        my_uid = selected_character.get('id', 1)
        ack = AcceptTradeAck(result=0, char_uid=my_uid, accepted=True).encode()
        await self.transport.send_event(event(5082, ack, correlation), note='trade accept ack')

    async def on_5083(self, correlation, body):
        # eERC_FINALLY_ACCEPT_TRADE_REQ -> 5084 eERC_FINALLY_ACCEPT_TRADE_ACK.
        from darkblood.games.network.messages import FinallyAcceptTradeAck
        self.transport.record('trade-finally-accept-req', body)
        ack = FinallyAcceptTradeAck(result=0).encode()
        await self.transport.send_event(event(5084, ack, correlation), note='trade finally accept ack')

    async def on_2254(self, correlation, body):
        # eEGS_MAGICENCHANT_ENCHANT_REQ -> 2255 eEGS_MAGICENCHANT_ENCHANT_ACK (0x00796DC0).
        from darkblood.games.network.messages import MagicEnchantEnchantAck, MagicEnchantEnchantReq
        from darkblood.games.state import selected_character
        req = MagicEnchantEnchantReq.decode(body)
        self.transport.record('magicenchant-enchant-req', body, item_uid=req.item_uid)
        char = self.store().get(self.account, selected_character.get('id', 1)) if 'id' in selected_character else None
        gold = char.get('gold', 0) if char else 0
        ack = MagicEnchantEnchantAck(result=0, items=[], gold=gold).encode()
        await self.transport.send_event(event(2255, ack, correlation), note=f'magicenchant enchant ack (item={req.item_uid})')

    async def on_2256(self, correlation, body):
        # eEGS_MAGICENCHANT_ERASE_OPTION_REQ -> 2257 eEGS_MAGICENCHANT_ERASE_OPTION_ACK (0x00797120).
        from darkblood.games.network.messages import MagicEnchantEraseOptionAck, MagicEnchantEraseOptionReq
        from darkblood.games.state import selected_character
        req = MagicEnchantEraseOptionReq.decode(body)
        self.transport.record('magicenchant-erase-option-req', body, item_uid=req.item_uid)
        char = self.store().get(self.account, selected_character.get('id', 1)) if 'id' in selected_character else None
        gold = char.get('gold', 0) if char else 0
        ack = MagicEnchantEraseOptionAck(result=0, items=[], gold=gold).encode()
        await self.transport.send_event(event(2257, ack, correlation), note=f'magicenchant erase option ack (item={req.item_uid})')

    async def on_2258(self, correlation, body):
        # eEGS_MAGICENCHANT_EXPEND_SLOT_REQ -> 2259 eEGS_MAGICENCHANT_EXPEND_SLOT_ACK (0x0077FC60).
        from darkblood.games.network.messages import MagicEnchantExpendSlotAck, MagicEnchantExpendSlotReq
        req = MagicEnchantExpendSlotReq.decode(body)
        self.transport.record('magicenchant-expend-slot-req', body, item_uid=req.item_uid)
        ack = MagicEnchantExpendSlotAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2259, ack, correlation), note=f'magicenchant expend slot ack (item={req.item_uid})')

    async def on_2284(self, correlation, body):
        # eEGS_RANDOM_ITEM_UPGRADE_REQ -> 2285 eEGS_RANDOM_ITEM_UPGRADE_ACK (0x0077FED0).
        from darkblood.games.network.messages import RandomItemUpgradeAck, RandomItemUpgradeReq
        req = RandomItemUpgradeReq.decode(body)
        self.transport.record('random-item-upgrade-req', body, item_uid=req.item_uid)
        ack = RandomItemUpgradeAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2285, ack, correlation), note=f'random item upgrade ack (item={req.item_uid})')

    async def on_2672(self, correlation, body):
        # eEGS_FIX_ITEM_UPGRADE_REQ -> 2673 eEGS_FIX_ITEM_UPGRADE_ACK (0x00783C40).
        from darkblood.games.network.messages import FixItemUpgradeAck, FixItemUpgradeReq
        req = FixItemUpgradeReq.decode(body)
        self.transport.record('fix-item-upgrade-req', body, item_uid=req.item_uid)
        ack = FixItemUpgradeAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2673, ack, correlation), note=f'fix item upgrade ack (item={req.item_uid})')

    async def on_2338(self, correlation, body):
        # eEGS_ITEM_SPIRIT_CHANGE_REQ -> 2339 eEGS_ITEM_SPIRIT_CHANGE_ACK (0x00780860).
        from darkblood.games.network.messages import ItemSpiritChangeAck, ItemSpiritChangeReq
        req = ItemSpiritChangeReq.decode(body)
        self.transport.record('item-spirit-change-req', body, item_uid=req.item_uid)
        ack = ItemSpiritChangeAck(result=0, spirit_uid=req.spirit_item_uid, items=[]).encode()
        await self.transport.send_event(event(2339, ack, correlation), note=f'item spirit change ack (spirit={req.spirit_item_uid})')

    async def on_2362(self, correlation, body):
        # eEGS_AVATAR_ZAM_INSERT_REQ -> 2363 eEGS_AVATAR_ZAM_INSERT_ACK (0x00782D00).
        from darkblood.games.network.messages import AvatarZamInsertAck, AvatarZamInsertReq
        req = AvatarZamInsertReq.decode(body)
        self.transport.record('avatar-zam-insert-req', body, avatar_uid=req.avatar_item_uid, zam_uid=req.zam_item_uid)
        ack = AvatarZamInsertAck(result=0, updated_items=[]).encode()
        await self.transport.send_event(event(2363, ack, correlation), note=f'avatar zam insert ack (avatar={req.avatar_item_uid})')

    async def on_2364(self, correlation, body):
        # eEGS_AVATAR_ZAM_ERASE_REQ -> 2365 eEGS_AVATAR_ZAM_ERASE_ACK (0x00782F40).
        from darkblood.games.network.messages import AvatarZamEraseAck, AvatarZamEraseReq
        req = AvatarZamEraseReq.decode(body)
        self.transport.record('avatar-zam-erase-req', body, avatar_uid=req.avatar_item_uid)
        ack = AvatarZamEraseAck(result=0, updated_items=[]).encode()
        await self.transport.send_event(event(2365, ack, correlation), note=f'avatar zam erase ack (avatar={req.avatar_item_uid})')

    async def on_2709(self, correlation, body):
        # eEGS_USE_ARENA_SP_ITEM_REQ -> 2710 eEGS_USE_ARENA_SP_ITEM_ACK (0x007A7CA0).
        from darkblood.games.network.messages import UseArenaSpItemAck, UseArenaSpItemReq
        req = UseArenaSpItemReq.decode(body)
        self.transport.record('use-arena-sp-item-req', body, item_uid=req.item_uid)
        ack = UseArenaSpItemAck(result=0, consumed_items=[], arena_sp=100).encode()
        await self.transport.send_event(event(2710, ack, correlation), note=f'use arena sp item ack (item={req.item_uid})')

    async def on_2250(self, correlation, body):
        # eEGS_DIVIDE_ITEM_REQ -> 2251 eEGS_DIVIDE_ITEM_ACK (0x0077F570).
        from darkblood.games.network.messages import DivideItemAck, DivideItemReq
        req = DivideItemReq.decode(body)
        self.transport.record('divide-item-req', body, source_uid=req.source_item_uid, count=req.count)
        ack = DivideItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2251, ack, correlation), note=f'divide item ack (item={req.source_item_uid})')

    async def on_2111(self, correlation, body):
        # eEGS_USE_LEARN_SKILL_ITEM_REQ -> 2112 eEGS_USE_LEARN_SKILL_ITEM_ACK (0x0078BCD0).
        from darkblood.games.network.messages import UseLearnSkillItemAck, UseLearnSkillItemReq
        req = UseLearnSkillItemReq.decode(body)
        self.transport.record('use-learn-skill-item-req', body, item_uid=req.item_uid, skill_id=req.skill_id)
        ack = UseLearnSkillItemAck(result=0, skill_id=req.skill_id, skill_level=1, item_code=0, count=1, items=[], sp=10).encode()
        await self.transport.send_event(event(2112, ack, correlation), note=f'use learn skill item ack (skill={req.skill_id})')

    async def on_2228(self, correlation, body):
        # eEGS_DEPOT_SAVE_AR_REQ -> 2229 eEGS_DEPOT_SAVE_AR_ACK (0x00795220).
        from darkblood.games.network.messages import DepotSaveArAck, DepotSaveArReq
        req = DepotSaveArReq.decode(body)
        self.transport.record('depot-save-ar-req', body, gold=req.gold)
        ack = DepotSaveArAck(result=0, new_gold=req.gold).encode()
        await self.transport.send_event(event(2229, ack, correlation), note=f'depot save ar ack (gold={req.gold})')

    async def on_2230(self, correlation, body):
        # eEGS_DEPOT_LOAD_AR_REQ -> 2231 eEGS_DEPOT_LOAD_AR_ACK (0x00795490).
        from darkblood.games.network.messages import DepotLoadArAck, DepotLoadArReq
        req = DepotLoadArReq.decode(body)
        self.transport.record('depot-load-ar-req', body, gold=req.gold)
        ack = DepotLoadArAck(result=0, new_gold=req.gold).encode()
        await self.transport.send_event(event(2231, ack, correlation), note=f'depot load ar ack (gold={req.gold})')









