"""Inventory, bag, item drag/use/equip, crafting and depot handlers."""
import random
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.entities.items import Item, UPDATE_OWNER, EQUIPPED
from darkblood.games.network.messages import (
    AssignQuickslotAck,
    AssignQuickslotReq,
    AvatarZamEraseAck,
    AvatarZamEraseReq,
    AvatarZamInsertAck,
    AvatarZamInsertReq,
    BuyLifeWaterAck,
    BuyLifeWaterReq,
    ChangeBagNameAck,
    ChangeBagNameReq,
    ChangeBagPropertyAck,
    ChangeBagPropertyReq,
    CharVerifyStatAck,
    CloseBagReq,
    DeleteItemAck,
    DeleteItemReq,
    DepotLoadArAck,
    DepotLoadArReq,
    DepotSaveArAck,
    DepotSaveArReq,
    DepotSlotExtendAck,
    DepotSlotExtendReq,
    DivideItemAck,
    DivideItemReq,
    DurabilityRepairAck,
    DurabilityRepairReq,
    DragItemAck,
    DragItemReq,
    DurabilityChangeAck,
    DurabilityChangeReq,
    EquipItemAck,
    EquipItemReq,
    FixItemUpgradeAck,
    FixItemUpgradeReq,
    ItemUpgradeAck,
    ItemUpgradeReq,
    ItemRemainTimeNot,
    ItemSpiritChangeAck,
    ItemSpiritChangeReq,
    MagicEnchantEnchantAck,
    MagicEnchantEnchantReq,
    MagicEnchantEraseOptionAck,
    MagicEnchantEraseOptionReq,
    MagicEnchantExpendSlotAck,
    MagicEnchantExpendSlotReq,
    RandomItemUpgradeAck,
    RandomItemUpgradeReq,
    SwitchBagAck,
    SwitchBagReq,
    SwitchQuickslotAck,
    SwitchQuickslotReq,
    UseArenaSpItemAck,
    UseArenaSpItemReq,
    UseItemAck,
    UseItemReq,
    OpenBagAck,
    OpenBagReq,
)
from darkblood.player_management.characters import (
    DEFAULT_BAG_CAPACITY,
    INVENTORY_BAG_CONTAINER,
    add_reward_items,
    fits_equip_slot,
    free_bag_slots,
    slots_needed,
)


class InventoryHandlers:
    """Item management: equip, drag, split, use, bag switching, durability and storage."""

    async def on_2026(self, correlation, body):
        # eEGS_OPEN_BAG_REQ -> 2027 eEGS_OPEN_BAG_ACK (0x00557860): equip a
        # bag item into the first free UI bag slot (0..4).
        from darkblood.games.entities.items import Bag
        from darkblood.games.game_data.client_dict import item_field
        req = OpenBagReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        item = next((i for i in items if i.get('uid') == req.item_uid), None)
        size = item_field(item['code'], 'BagSize') if item else None
        bags = char.setdefault('bags', []) if char else []
        used = {int(b.get('w2a', 0xFFFF)) for b in bags}
        free = [s for s in range(5) if s not in used]
        if not item or not size or not free:
            reason = 'no item' if not item else 'not a bag' if not size else 'no free slot'
            await self.transport.send_event(event(2027, OpenBagAck(result=1).encode(), correlation),
                                            note=f'open bag fail ({reason}, uid={req.item_uid})')
            return
        record = dict(bag_id=req.item_uid, code=item['code'], b28=0, b29=size, w2a=free[0])
        items.remove(item)  # the bag item now lives in the bag list
        bags.append(record)
        self.store().save()
        ack = OpenBagAck(result=0, bag=Bag(**record)).encode()
        await self.transport.send_event(event(2027, ack, correlation),
                                        note=f'open bag ack ({item["code"]} uid={req.item_uid} size={size} slot={free[0]})')

    async def on_2028(self, correlation, body):
        # eEGS_CLOSE_BAG_REQ (0x00550000.c:1773).
        req = CloseBagReq.decode(body)
        self.transport.record('close-bag', body, bag_id=req.bag_id)

    async def on_2036(self, correlation, body):
        # eEGS_DRAG_ITEM_REQ (0x00790000.c:4212) -> 2037 eEGS_DRAG_ITEM_ACK (0x0077F570).
        req = DragItemReq.decode(body)
        char = self.current_char()
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

        if req.to_container == EQUIPPED and not fits_equip_slot(dragged.get('code', ''), req.to_slot):
            ack = DragItemAck(result=1).encode()
            await self.transport.send_event(event(2037, ack, correlation),
                                            note='drag item fail (item does not fit equip slot %d)' % req.to_slot)
            return

        target = next((i for i in items if i.get('container') == req.to_container and i.get('slot') == req.to_slot), None)
        if target is dragged:
            ack = DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **dragged)]).encode()
            await self.transport.send_event(event(2037, ack, correlation), note='drag item ack (no move)')
            return
        if target:
            if old_container == EQUIPPED and not fits_equip_slot(target.get('code', ''), old_slot):
                ack = DragItemAck(result=1).encode()
                await self.transport.send_event(event(2037, ack, correlation),
                                                note='drag item fail (displaced item does not fit equip slot %d)' % old_slot)
                return
            target['container'], target['slot'] = old_container, old_slot
            dragged['container'], dragged['slot'] = req.to_container, req.to_slot
            self.store().save()
            wire_items = [
                Item(owner=UPDATE_OWNER, **target),
                Item(owner=UPDATE_OWNER, **dragged)
            ]
        else:
            dragged['container'] = req.to_container
            dragged['slot'] = req.to_slot
            self.store().save()
            wire_items = [
                Item(owner=UPDATE_OWNER, **dragged),
                Item(owner=UPDATE_OWNER, uid=0, code='', container=old_container, slot=old_slot, count=0)
            ]

        ack = DragItemAck(result=0, items=wire_items).encode()
        await self.transport.send_event(event(2037, ack, correlation),
                                        note='drag item ack (uid=%d to c=%d s=%d)' % (req.item_uid, req.to_container, req.to_slot))

    async def on_2038(self, correlation, body):
        # eEGS_USE_ITEM_REQ (0x00780000.c:8159) -> 2039 eEGS_USE_ITEM_ACK (0x0077D4C0).
        req = UseItemReq.decode(body)
        char = self.current_char()
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
        contents = self._cash_box_contents(used_item.get('code', ''))
        if contents:
            free = free_bag_slots(char)
            if free is not None and slots_needed(contents) > free:
                ack = UseItemAck(result=1).encode()
                await self.transport.send_event(event(2039, ack, correlation),
                                                note='use item fail (bag full: need %d, free %d)'
                                                % (slots_needed(contents), free))
                return
        item_code = jhash(used_item.get('code', ''))
        count = used_item.get('count', 1) - req.use_count
        updated = []
        if count <= 0:
            items.remove(used_item)
        else:
            used_item['count'] = count
            updated.append(Item(owner=UPDATE_OWNER, **used_item))
        self.store().save()

        ack = UseItemAck(result=0, items=updated, item_id=item_code, use_count=req.use_count).encode()
        await self.transport.send_event(event(2039, ack, correlation),
                                        note='use item ack (uid=%d code=%08x)' % (req.item_uid, item_code))
        if hasattr(self, '_apply_pet_or_mount_item'):
            await self._apply_pet_or_mount_item(char, used_item.get('code', ''))
        if contents:
            stored = add_reward_items(char, contents)
            self.store().save()
            items = [Item(owner=UPDATE_OWNER, **i) for i in stored]
            await self.transport.send_event(event(2037, DragItemAck(result=0, items=items).encode()),
                                            note='cash box opened (%s -> %s)' % (
                                                used_item.get('code'), ', '.join(i['code'] for i in stored)))

    def _cash_box_contents(self, code):
        from darkblood.games.game_data import client_dict
        info = client_dict.cash_items().get(code)
        if not info or not info['adj']:
            return []
        adj = info['adj']
        if adj.startswith('PACKAGE'):
            return list(client_dict.cash_packages().get(adj, []))
        states, groups = client_dict.random_boxes()
        grades = states.get(adj)
        if not grades:
            return []
        weights = [p for p, _ in grades]
        _, names = random.choices(grades, weights=weights)[0]
        pool = [entry for name in names for entry in groups.get(name, [])]
        return [random.choice(pool)] if pool else []

    async def on_2042(self, correlation, body):
        # eEGS_EQUIP_ITEM_REQ (0x00800000.c:500) -> 2043 eEGS_EQUIP_ITEM_ACK (0x007AE940).
        req = EquipItemReq.decode(body)
        char = self.current_char()
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

        old_container = target_item.get('container')
        old_slot = target_item.get('slot')

        if old_container == EQUIPPED:
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
                Item(owner=UPDATE_OWNER, **target_item),
                Item(owner=UPDATE_OWNER, uid=0, code='', container=EQUIPPED, slot=old_slot, count=0)
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
                    Item(owner=UPDATE_OWNER, **previous_equipped),
                    Item(owner=UPDATE_OWNER, **target_item)
                ]
            else:
                target_item['container'] = EQUIPPED
                target_item['slot'] = target_slot
                self.store().save()
                wire_items = [
                    Item(owner=UPDATE_OWNER, **target_item),
                    Item(owner=UPDATE_OWNER, uid=0, code='', container=old_container, slot=old_slot, count=0)
                ]

        ack = EquipItemAck(result=0, items=wire_items).encode()
        await self.transport.send_event(event(2043, ack, correlation),
                                        note='equip item ack (uid=%d slot=%d)' % (req.item_uid, target_item.get('slot', 0)))

    async def on_2044(self, correlation, body):
        # eEGS_ASSIGN_QUICKSLOT_REQ (0x00780000.c:8513) -> 2045 eEGS_ASSIGN_QUICKSLOT_ACK (0x0078C4A0).
        req = AssignQuickslotReq.decode(body)
        char = self.current_char()
        if char:
            qs = char.setdefault('quickslots', {})
            # Item bar (type 0) and skill bar (type 1) share slot numbers.
            qs['%d:%d' % (req.slot_type, req.slot_num)] = dict(
                type=req.slot_type, slot=req.slot_num, ref_id=req.ref_id, ref_uid=req.ref_uid)
            self.store().save()

        ack = AssignQuickslotAck(result=0, slot_type=req.slot_type, slot_num=req.slot_num,
                                 ref_id=req.ref_id, ref_uid=req.ref_uid).encode()
        await self.transport.send_event(event(2045, ack, correlation),
                                        note='assign quickslot ack (slot=%d ref=%08x)' % (req.slot_num, req.ref_id))

    async def on_2046(self, correlation, body):
        # eEGS_SWITCH_QUCIKSLOT_REQ (0x00780000.c:8591) -> 2047 eEGS_SWITCH_QUCIKSLOT_ACK (0x0078C790).
        req = SwitchQuickslotReq.decode(body)
        char = self.current_char()
        if char:
            qs = char.setdefault('quickslots', {})
            a = qs.pop('%d:%d' % (req.slot_type, req.from_slot), None)
            b = qs.pop('%d:%d' % (req.slot_type, req.to_slot), None)
            if a:
                qs['%d:%d' % (req.slot_type, req.to_slot)] = dict(a, slot=req.to_slot)
            if b:
                qs['%d:%d' % (req.slot_type, req.from_slot)] = dict(b, slot=req.from_slot)
            self.store().save()
        ack = SwitchQuickslotAck(result=0, slot_type=req.slot_type,
                                 from_slot=req.from_slot, to_slot=req.to_slot).encode()
        await self.transport.send_event(event(2047, ack, correlation),
                                        note=f'switch quickslot ack ({req.from_slot} -> {req.to_slot})')

    async def on_2040(self, correlation, body):
        # eEGS_DELETE_ITEM_REQ (0x00550000.c:769) -> 2041 eEGS_DELETE_ITEM_ACK (0x00557420).
        req = DeleteItemReq.decode(body)
        char = self.current_char()
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
        char = self.current_char()
        if char:
            bags = char.get('bags', [])
            if req.from_index < len(bags) and req.to_index < len(bags):
                bags[req.from_index], bags[req.to_index] = bags[req.to_index], bags[req.from_index]
                self.store().save()
        ack = SwitchBagAck(result=0, from_index=req.from_index, to_index=req.to_index).encode()
        await self.transport.send_event(event(2031, ack, correlation),
                                        note=f'switch bag ack ({req.from_index} <-> {req.to_index})')

    async def on_2048(self, correlation, body):
        # eEGS_CHANGE_BAG_PROPERTY_REQ (0x00550000.c:676) -> 2049 eEGS_CHANGE_BAG_PROPERTY_ACK (0x00774040).
        req = ChangeBagPropertyReq.decode(body)
        char = self.current_char()
        if char:
            for bag in char.get('bags', []):
                if bag.get('bag_id') == req.bag_uid:
                    bag['b28'] = req.property
                    break
            self.store().save()
        ack = ChangeBagPropertyAck(result=0, bag_uid=req.bag_uid, property=req.property).encode()
        await self.transport.send_event(event(2049, ack, correlation),
                                        note=f'change bag property ack (bag={req.bag_uid} prop={req.property})')

    async def on_2032(self, correlation, body):
        # eEGS_CHANGE_BAG_NAME_REQ -> 2033 eEGS_CHANGE_BAG_NAME_ACK (0x007528B0).
        req = ChangeBagNameReq.decode(body)
        self.transport.record('change-bag-name-req', body, bag_uid=req.bag_uid, name=req.name)
        char = self.current_char()
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
        char = self.current_char()
        gold = char.get('gold', 100000) if char else 100000
        ack = BuyLifeWaterAck(result=0, flag=req.flag, remain_currency=gold).encode()
        await self.transport.send_event(event(2087, ack, correlation),
                                        note=f'buy life water ack (flag={req.flag})')

    async def on_2115(self, correlation, body):
        # eEGS_ITEM_UPGRADE_REQ (0x00790000.c:296) -> 2116 eEGS_ITEM_UPGRADE_ACK (0x007909C0).
        req = ItemUpgradeReq.decode(body)
        self.transport.record('item-upgrade-req', body, target=req.target_uid, catalyst=req.catalyst_uid, protect=req.protect_uid)
        ack = ItemUpgradeAck(result=1).encode()
        await self.transport.send_event(event(2116, ack, correlation),
                                        note=f'item upgrade ack (target={req.target_uid})')

    async def on_2119(self, correlation, body):
        # eEGS_ALARM_UPDATE_REQ (observed: i32 0x7FFFFFFF, i16, tag 0x10 vector<i32>)
        rest = body[4:] if len(body) >= 7 else b'\x00\x00\x10\x80'
        await self.transport.send_event(event(2120, struct.pack('<I', 0) + rest, correlation),
                                        note='alarm update ack')

    async def on_2145(self, correlation, body):
        # eEGS_DURABILITY_REPAIR_REQ (0x00790000.c:2123) -> 2146 eEGS_DURABILITY_REPAIR_ACK (0x007930D0).
        req = DurabilityRepairReq.decode(body)
        self.transport.record('durability-repair-req', body)
        char = self.current_char()
        gold = char.get('gold', 100000) if char else 100000
        ack = DurabilityRepairAck(result=0, remain_gold=gold).encode()
        await self.transport.send_event(event(2146, ack, correlation),
                                        note='durability repair ack (success, 0 items repaired)')

    async def on_2406(self, correlation, body):
        # eEGS_CHAR_VERIFY_STAT_REQ -> 2407 eEGS_CHAR_VERIFY_STAT_ACK (0x0074B830).
        ack = CharVerifyStatAck(result=0).encode()
        await self.transport.send_event(event(2407, ack, correlation), note='char verify stat ack')

    async def on_2254(self, correlation, body):
        # eEGS_MAGICENCHANT_ENCHANT_REQ -> 2255 eEGS_MAGICENCHANT_ENCHANT_ACK (0x00796DC0).
        req = MagicEnchantEnchantReq.decode(body)
        self.transport.record('magicenchant-enchant-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = char.get('gold', 1000) if char else 1000
        ack = MagicEnchantEnchantAck(result=0, items=[], gold=gold).encode()
        await self.transport.send_event(event(2255, ack, correlation), note=f'magicenchant enchant ack (item={req.item_uid})')

    async def on_2256(self, correlation, body):
        # eEGS_MAGICENCHANT_ERASE_OPTION_REQ -> 2257 eEGS_MAGICENCHANT_ERASE_OPTION_ACK (0x00797120).
        req = MagicEnchantEraseOptionReq.decode(body)
        self.transport.record('magicenchant-erase-option-req', body, item_uid=req.item_uid)
        char = self.current_char()
        gold = char.get('gold', 1000) if char else 1000
        ack = MagicEnchantEraseOptionAck(result=0, items=[], gold=gold).encode()
        await self.transport.send_event(event(2257, ack, correlation), note=f'magicenchant erase option ack (item={req.item_uid})')

    async def on_2258(self, correlation, body):
        # eEGS_MAGICENCHANT_EXPEND_SLOT_REQ -> 2259 eEGS_MAGICENCHANT_EXPEND_SLOT_ACK (0x0077FC60).
        req = MagicEnchantExpendSlotReq.decode(body)
        self.transport.record('magicenchant-expend-slot-req', body, item_uid=req.item_uid)
        ack = MagicEnchantExpendSlotAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2259, ack, correlation), note=f'magicenchant expend slot ack (item={req.item_uid})')

    async def on_2284(self, correlation, body):
        # eEGS_RANDOM_ITEM_UPGRADE_REQ -> 2285 eEGS_RANDOM_ITEM_UPGRADE_ACK (0x0077FED0).
        req = RandomItemUpgradeReq.decode(body)
        self.transport.record('random-item-upgrade-req', body, item_uid=req.item_uid)
        ack = RandomItemUpgradeAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2285, ack, correlation), note=f'random item upgrade ack (item={req.item_uid})')

    async def on_2672(self, correlation, body):
        # eEGS_FIX_ITEM_UPGRADE_REQ -> 2673 eEGS_FIX_ITEM_UPGRADE_ACK (0x00783C40).
        req = FixItemUpgradeReq.decode(body)
        self.transport.record('fix-item-upgrade-req', body, item_uid=req.item_uid)
        ack = FixItemUpgradeAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2673, ack, correlation), note=f'fix item upgrade ack (item={req.item_uid})')

    async def on_2338(self, correlation, body):
        # eEGS_ITEM_SPIRIT_CHANGE_REQ -> 2339 eEGS_ITEM_SPIRIT_CHANGE_ACK (0x00780860).
        req = ItemSpiritChangeReq.decode(body)
        self.transport.record('item-spirit-change-req', body, item_uid=req.item_uid)
        ack = ItemSpiritChangeAck(result=0, spirit_uid=req.spirit_item_uid, items=[]).encode()
        await self.transport.send_event(event(2339, ack, correlation), note=f'item spirit change ack (spirit={req.spirit_item_uid})')

    async def on_2362(self, correlation, body):
        # eEGS_AVATAR_ZAM_INSERT_REQ -> 2363 eEGS_AVATAR_ZAM_INSERT_ACK (0x00782D00).
        req = AvatarZamInsertReq.decode(body)
        self.transport.record('avatar-zam-insert-req', body, avatar_uid=req.avatar_item_uid, zam_uid=req.zam_item_uid)
        ack = AvatarZamInsertAck(result=0, updated_items=[]).encode()
        await self.transport.send_event(event(2363, ack, correlation), note=f'avatar zam insert ack (avatar={req.avatar_item_uid})')

    async def on_2364(self, correlation, body):
        # eEGS_AVATAR_ZAM_ERASE_REQ -> 2365 eEGS_AVATAR_ZAM_ERASE_ACK (0x00782F40).
        req = AvatarZamEraseReq.decode(body)
        self.transport.record('avatar-zam-erase-req', body, avatar_uid=req.avatar_item_uid)
        ack = AvatarZamEraseAck(result=0, updated_items=[]).encode()
        await self.transport.send_event(event(2365, ack, correlation), note=f'avatar zam erase ack (avatar={req.avatar_item_uid})')

    async def on_2709(self, correlation, body):
        # eEGS_USE_ARENA_SP_ITEM_REQ -> 2710 eEGS_USE_ARENA_SP_ITEM_ACK (0x007A7CA0).
        req = UseArenaSpItemReq.decode(body)
        self.transport.record('use-arena-sp-item-req', body, item_uid=req.item_uid)
        ack = UseArenaSpItemAck(result=0, consumed_items=[], arena_sp=100).encode()
        await self.transport.send_event(event(2710, ack, correlation), note=f'use arena sp item ack (item={req.item_uid})')

    async def on_2250(self, correlation, body):
        # eEGS_DIVIDE_ITEM_REQ -> 2251 eEGS_DIVIDE_ITEM_ACK (0x0077F570).
        req = DivideItemReq.decode(body)
        self.transport.record('divide-item-req', body, source_uid=req.source_item_uid, count=req.count)
        ack = DivideItemAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2251, ack, correlation), note=f'divide item ack (item={req.source_item_uid})')

    # Depot / Warehouse operations
    async def on_2228(self, correlation, body):
        # eEGS_DEPOT_SAVE_AR_REQ -> 2229 eEGS_DEPOT_SAVE_AR_ACK (0x00795220).
        req = DepotSaveArReq.decode(body)
        self.transport.record('depot-save-ar-req', body, gold=req.gold)
        char = self.current_char()
        current_gold = 0
        if char:
            gold = char.get('gold', 0)
            deposit = min(max(0, req.gold), gold) if gold > 0 else req.gold
            char['gold'] = gold - deposit if gold >= deposit else 0
            char['u66'] = char['gold']
            char['depot_gold'] = char.get('depot_gold', 0) + deposit
            current_gold = char['gold']
            self.store().save()
        else:
            current_gold = req.gold
        ack = DepotSaveArAck(result=0, new_gold=current_gold).encode()
        await self.transport.send_event(event(2229, ack, correlation),
                                        note=f'depot save ar ack (deposit={req.gold} remain_player_gold={current_gold})')

    async def on_2230(self, correlation, body):
        # eEGS_DEPOT_LOAD_AR_REQ -> 2231 eEGS_DEPOT_LOAD_AR_ACK (0x00795490).
        req = DepotLoadArReq.decode(body)
        self.transport.record('depot-load-ar-req', body, gold=req.gold)
        char = self.current_char()
        current_gold = 0
        if char:
            depot_gold = char.get('depot_gold', req.gold)
            withdraw = min(max(0, req.gold), depot_gold)
            char['depot_gold'] = depot_gold - withdraw
            char['gold'] = char.get('gold', 0) + withdraw
            char['u66'] = char['gold']
            current_gold = char['gold']
            self.store().save()
        else:
            current_gold = req.gold
        ack = DepotLoadArAck(result=0, new_gold=current_gold).encode()
        await self.transport.send_event(event(2231, ack, correlation),
                                        note=f'depot load ar ack (withdraw={req.gold} new_player_gold={current_gold})')

    async def on_2242(self, correlation, body):
        # eEGS_DEPOT_SHARE_EXPIRE_TIME_GET_REQ (empty body, sent when opening storage) -> 2243 (0x0076C040)
        await self.transport.send_event(event(2243, struct.pack('<I', 0) + bytes.fromhex('1780'), correlation),
                                        note='depot share expire time ack (none)')

    async def on_2461(self, correlation, body):
        # eEGS_DEPOT_SLOT_EXTEND_REQ -> 2462 eEGS_DEPOT_SLOT_EXTEND_ACK (0x00651B20).
        req = DepotSlotExtendReq.decode(body)
        self.transport.record('depot-slot-extend-req', body, item_uid=req.item_uid, slot_index=req.slot_index)
        char = self.current_char()
        if char:
            depot_slots = char.get('depot_slots', 16) + 8
            char['depot_slots'] = depot_slots
            self.store().save()
        ack = DepotSlotExtendAck(result=0, slot_index=req.slot_index, expire_time=0, items=[]).encode()
        await self.transport.send_event(event(2462, ack, correlation),
                                        note=f'depot slot extend ack (slot={req.slot_index})')
