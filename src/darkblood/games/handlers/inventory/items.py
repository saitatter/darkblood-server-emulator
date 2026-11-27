"""Item movement: drag, equip, delete, split and stat verification (item use is in consumables.py)."""
import struct

from darkblood.core.serialization.jser import event
from darkblood.core.serialization.jser import WireError
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import DEPOT_CONTAINER, EQUIPPED, Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages import (
    AlarmUpdateAck,
    AlarmUpdateReq,
    AssignQuickslotAck,
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
)
from darkblood.player_management.characters import fits_equip_slot, free_cells


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
            await self.reply(DragItemAck(result=results.NO_EXIST_CHAR), correlation, note='drag item fail (no char)')
            return
        account_chars = {int(c['id']): c for c in self.store().characters(self.account) if 'id' in c}
        src_char, dragged = self._locate_dragged_item(char, account_chars, req.item_uid)
        if not dragged:
            await self.reply(DragItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation, note='drag item fail (not found)')
            return

        old_container, old_slot = dragged.get('container'), dragged.get('slot')
        dest_char, dest_container = self._resolve_drag_destination(char, account_chars, req.to_container)
        if dest_container == EQUIPPED and not fits_equip_slot(dragged.get('code', ''), req.to_slot):
            await self.reply(DragItemAck(result=results.INVALID_STATE), correlation,
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
                await self.reply(DragItemAck(result=results.INVALID_STATE), correlation,
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
        if (old_container == DEPOT_CONTAINER) != (dest_container == DEPOT_CONTAINER):
            await self.session.quests.check_quest_item_objectives(char)


    @packet_handler(EquipItemReq)
    async def handle_equip_item(self, correlation, body):
        """Opcode 2042 (eEGS_EQUIP_ITEM_REQ) -> 2043 (eEGS_EQUIP_ITEM_ACK): equip or unequip a gear piece."""
        req = EquipItemReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(EquipItemAck(result=results.NO_EXIST_CHAR), correlation, note='equip item fail (no char)')
            return
        items = char.get('items', [])
        target_item = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target_item:
            await self.reply(EquipItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note='equip item fail (not found)')
            return

        old_container, old_slot = target_item.get('container'), target_item.get('slot')

        if old_container == EQUIPPED:
            free_cell = next(iter(free_cells(char)), None)
            if free_cell is None:
                await self.reply(EquipItemAck(result=results.INVEN_FULL), correlation,
                                 note='unequip item fail (bags full)')
                return
            bag_id, free_slot = free_cell
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
                await self.reply(EquipItemAck(result=results.INVALID_STATE), correlation,
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


    @packet_handler(2119)
    async def handle_alarm_update(self, correlation, body):
        """Opcode 2119 (eEGS_ALARM_UPDATE_REQ) -> 2120 (eEGS_ALARM_UPDATE_ACK): acknowledge alarm flags."""
        try:
            req = AlarmUpdateReq.decode(body)
            ack = AlarmUpdateAck(alarm_type=req.alarm_type, values=req.values)
        except (WireError, struct.error):
            ack = AlarmUpdateAck()
        await self.reply(ack, correlation, note='alarm update ack')


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


