"""Bag management and quickslot handlers (2026, 2028, 2030, 2032, 2044, 2046, 2048)."""
from darkblood.games.entities.items import Bag, Item, UPDATE_OWNER
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
from darkblood.player_management.characters import INVENTORY_BAG_CONTAINER, add_reward_items


class BagHandlersMixin:
    """Bag equip/close/switch/rename/property and hotbar quickslot operations."""

    async def on_2026(self, correlation, body):
        # eEGS_OPEN_BAG_REQ -> 2027 eEGS_OPEN_BAG_ACK (0x00557860).
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
            await self.reply(OpenBagAck(result=1), correlation,
                             note=f'open bag fail ({reason}, uid={req.item_uid})')
            return
        record = dict(bag_id=req.item_uid, code=item['code'], b28=0, b29=size, w2a=free[0])
        items.remove(item)
        bags.append(record)
        self.save_char()
        await self.reply(OpenBagAck(result=0, bag=Bag(**record)), correlation,
                         note=f'open bag ack ({item["code"]} uid={req.item_uid} size={size} slot={free[0]})')

    async def on_2028(self, correlation, body):
        # eEGS_CLOSE_BAG_REQ (0x005520B0) -> 2029 eEGS_CLOSE_BAG_ACK (0x00558050).
        req = CloseBagReq.decode(body)
        self.transport.record('close-bag', body, bag_id=req.bag_id)
        char = self.current_char()
        bags = char.get('bags', []) if char else []
        bag = next((b for b in bags if b.get('bag_id') == req.bag_id), None)
        items = char.get('items', []) if char else []
        if not bag or any(i.get('container') == req.bag_id for i in items):
            await self.reply(CloseBagAck(result=1), correlation, note=f'close bag fail (bag_id={req.bag_id})')
            return
        bags.remove(bag)
        stored = add_reward_items(char, [(bag.get('code', 'Ibaga0004'), 1)])
        if stored:
            stored[0]['uid'] = req.bag_id
            bag_item = Item(owner=UPDATE_OWNER, **stored[0])
        else:
            bag_item = Item(owner=UPDATE_OWNER, uid=req.bag_id, code=bag.get('code', ''),
                            container=INVENTORY_BAG_CONTAINER, slot=0, count=1)
        self.save_char()
        await self.reply(CloseBagAck(result=0, bag_item=bag_item, bags=[Bag(**b) for b in bags]),
                         correlation, note=f'close bag ack (bag_id={req.bag_id})')

    async def on_2030(self, correlation, body):
        # eEGS_SWITCH_BAG_REQ -> 2031 eEGS_SWITCH_BAG_ACK (0x00557680).
        req = SwitchBagReq.decode(body)
        char = self.current_char()
        if char:
            bags = char.get('bags', [])
            if req.from_index < len(bags) and req.to_index < len(bags):
                bags[req.from_index], bags[req.to_index] = bags[req.to_index], bags[req.from_index]
                self.save_char()
        await self.reply(SwitchBagAck(result=0, from_index=req.from_index, to_index=req.to_index),
                         correlation, note=f'switch bag ack ({req.from_index} <-> {req.to_index})')

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
            self.save_char()
        await self.reply(ChangeBagNameAck(result=0, bag_uid=req.bag_uid, name=req.name),
                         correlation, note=f'change bag name ack (bag={req.bag_uid} name={req.name})')

    async def on_2044(self, correlation, body):
        # eEGS_ASSIGN_QUICKSLOT_REQ -> 2045 eEGS_ASSIGN_QUICKSLOT_ACK (0x0078C4A0).
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

    async def on_2046(self, correlation, body):
        # eEGS_SWITCH_QUCIKSLOT_REQ -> 2047 eEGS_SWITCH_QUCIKSLOT_ACK (0x0078C790).
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

    async def on_2048(self, correlation, body):
        # eEGS_CHANGE_BAG_PROPERTY_REQ -> 2049 eEGS_CHANGE_BAG_PROPERTY_ACK (0x00774040).
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
