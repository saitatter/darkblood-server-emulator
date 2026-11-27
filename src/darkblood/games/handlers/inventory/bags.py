"""Bag management and quickslot handlers (2026, 2028, 2030, 2032, 2044, 2046, 2048)."""
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Bag, Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages import (
    AssignQuickslotAck,
    AssignQuickslotReq,
    ChangeBagNameAck,
    ChangeBagNameReq,
    ChangeBagPropertyAck,
    ChangeBagPropertyReq,
    CloseBagAck,
    CloseBagReq,
    OpenBagAck,
    OpenBagReq,
    SwitchBagAck,
    SwitchBagReq,
    SwitchQuickslotAck,
    SwitchQuickslotReq,
)
from darkblood.player_management.characters import add_reward_items, free_cells, UI_BAG_SLOTS
from darkblood.games.game_data.client_dict import item_field


class BagHandlersMixin:
    """Bag equip/close/switch/rename/property and hotbar quickslot operations."""

    @packet_handler(OpenBagReq)
    async def handle_open_bag(self, correlation, body):
        """Opcode 2026 (eEGS_OPEN_BAG_REQ) -> 2027 (eEGS_OPEN_BAG_ACK): equip a bag item into a free UI slot."""
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
            result = (results.INVEN_ITEM_NOT_FOUND if not item else results.INVALID_STATE if not size
                      else results.INVEN_NO_BAG_SPACE)
            await self.reply(OpenBagAck(result=result), correlation,
                             note=f'open bag fail ({reason}, uid={req.item_uid})')
            return
        record = dict(bag_id=req.item_uid, code=item['code'], b28=0, b29=size, w2a=free[0])
        items.remove(item)
        bags.append(record)
        self.save_char()
        await self.reply(OpenBagAck(result=0, bag=Bag(**record)), correlation,
                         note=f'open bag ack ({item["code"]} uid={req.item_uid} size={size} slot={free[0]})')

    @packet_handler(CloseBagReq)
    async def handle_close_bag(self, correlation, body):
        """Opcode 2028 (eEGS_CLOSE_BAG_REQ) -> 2029 (eEGS_CLOSE_BAG_ACK): unequip an empty bag back to inventory."""
        req = CloseBagReq.decode(body)
        self.transport.record('close-bag', body, bag_id=req.bag_id)
        char = self.current_char()
        bags = char.get('bags', []) if char else []
        bag = next((b for b in bags if b.get('bag_id') == req.bag_id), None)
        items = char.get('items', []) if char else []
        if not bag or any(i.get('container') == req.bag_id for i in items):
            await self.reply(CloseBagAck(result=results.INVALID_STATE), correlation, note=f'close bag fail (bag_id={req.bag_id})')
            return
        if not any(container != req.bag_id for container, _ in free_cells(char)):
            await self.reply(CloseBagAck(result=results.INVEN_FULL), correlation,
                             note=f'close bag fail (no slot for bag_id={req.bag_id})')
            return

        bags.remove(bag)
        stored, = add_reward_items(char, [(bag.get('code', 'Ibaga0004'), 1)])
        stored['uid'] = req.bag_id
        bag_item = Item(owner=UPDATE_OWNER, **stored)
        self.save_char()
        await self.reply(CloseBagAck(result=0, bag_item=bag_item, bags=[Bag(**b) for b in bags]),
                         correlation, note=f'close bag ack (bag_id={req.bag_id})')

    @packet_handler(SwitchBagReq)
    async def handle_switch_bag(self, correlation, body):
        """Opcode 2030 (eEGS_SWITCH_BAG_REQ) -> 2031 (eEGS_SWITCH_BAG_ACK): swap two equipped bag slots."""

        req = SwitchBagReq.decode(body)
        char = self.current_char()
        source_slot, target_slot = req.from_index, req.to_index
        if char and source_slot != target_slot and max(source_slot, target_slot) < UI_BAG_SLOTS:
            bags_by_slot = {bag.get('w2a'): bag for bag in char.get('bags', [])}
            source = bags_by_slot.get(source_slot)
            target = bags_by_slot.get(target_slot)
            if source is not None:
                source['w2a'] = target_slot
            if target is not None:
                target['w2a'] = source_slot
            if source is not None or target is not None:
                self.save_char()
        await self.reply(SwitchBagAck(result=0, from_index=req.from_index, to_index=req.to_index),
                         correlation, note=f'switch bag ack ({req.from_index} <-> {req.to_index})')

    @packet_handler(ChangeBagNameReq)
    async def handle_change_bag_name(self, correlation, body):
        """Opcode 2032 (eEGS_CHANGE_BAG_NAME_REQ) -> 2033 (eEGS_CHANGE_BAG_NAME_ACK): rename an equipped bag."""
        req = ChangeBagNameReq.decode(body)
        self.transport.record('change-bag-name-req', body, bag_uid=req.bag_uid, name=req.name)
        char = self.current_char()
        if char:
            for b in char.get('bags', []):
                if b.get('bag_id') == req.bag_uid:
                    b['name'] = req.name
                    break
            self.save_char()
        await self.reply(ChangeBagNameAck(result=0, bag_uid=req.bag_uid, name=req.name),
                         correlation, note=f'change bag name ack (bag={req.bag_uid} name={req.name})')

    @packet_handler(AssignQuickslotReq)
    async def handle_assign_quickslot(self, correlation, body):
        """Opcode 2044 (eEGS_ASSIGN_QUICKSLOT_REQ) -> 2045 (eEGS_ASSIGN_QUICKSLOT_ACK): bind an item or skill to a hotbar slot."""
        req = AssignQuickslotReq.decode(body)
        char = self.current_char()
        if char:
            qs = char.setdefault('quickslots', {})
            qs['%d:%d' % (req.slot_type, req.slot_num)] = dict(
                type=req.slot_type, slot=req.slot_num, ref_id=req.ref_id, ref_uid=req.ref_uid)
            self.save_char()
        await self.reply(
            AssignQuickslotAck(result=0, slot_type=req.slot_type, slot_num=req.slot_num,
                               ref_id=req.ref_id, ref_uid=req.ref_uid),
            correlation, note='assign quickslot ack (slot=%d ref=%08x)' % (req.slot_num, req.ref_id))

    @packet_handler(SwitchQuickslotReq)
    async def handle_switch_quickslot(self, correlation, body):
        """Opcode 2046 (eEGS_SWITCH_QUCIKSLOT_REQ) -> 2047 (eEGS_SWITCH_QUCIKSLOT_ACK): swap two hotbar quickslots."""
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
            self.save_char()
        await self.reply(
            SwitchQuickslotAck(result=0, slot_type=req.slot_type,
                               from_slot=req.from_slot, to_slot=req.to_slot),
            correlation, note=f'switch quickslot ack ({req.from_slot} -> {req.to_slot})')

    @packet_handler(ChangeBagPropertyReq)
    async def handle_change_bag_property(self, correlation, body):
        """Opcode 2048 (eEGS_CHANGE_BAG_PROPERTY_REQ) -> 2049 (eEGS_CHANGE_BAG_PROPERTY_ACK): update bag filter property."""
        req = ChangeBagPropertyReq.decode(body)
        char = self.current_char()
        if char:
            for bag in char.get('bags', []):
                if bag.get('bag_id') == req.bag_uid:
                    bag['b28'] = req.property
                    break
            self.save_char()
        await self.reply(ChangeBagPropertyAck(result=0, bag_uid=req.bag_uid, property=req.property),
                         correlation, note=f'change bag property ack (bag={req.bag_uid} prop={req.property})')
