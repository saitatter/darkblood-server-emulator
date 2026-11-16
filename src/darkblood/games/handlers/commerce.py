import struct

from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import (
    CharVerifyStatAck,
    CloseBagReq,
    CurrentCashAck,
    DragItemAck,
    DragItemReq,
    RouletteManagerInfoAck,
    StoreInfoAck,
    TamingMonsterDeleteAck,
    TamingMonsterInsertAck,
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
        # eEGS_BILLING_GET_CURRENT_CASH_REQ -> 2370: u32 result + 12 raw bytes (zeros).
        await self.transport.send_event(event(2370, CurrentCashAck().encode(), correlation),
                                        note='current cash ack')

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
        from darkblood.player_management.characters import ensure_inventory
        ensure_inventory(char)
        items = char.get('items', [])
        dragged = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not dragged:
            ack = DragItemAck(result=1).encode()
            await self.transport.send_event(event(2037, ack, correlation), note='drag item fail (not found)')
            return
        target = next((i for i in items if i.get('container') == req.to_container and i.get('slot') == req.to_slot), None)
        updated = [dragged]
        if target and target is not dragged:
            target['container'], target['slot'] = dragged['container'], dragged['slot']
            updated.append(target)
        dragged['container'] = req.to_container
        dragged['slot'] = req.to_slot
        self.store().save()

        from darkblood.games.entities.items import Item
        wire_items = [Item(owner=char.get('id', -1), **i) for i in updated]
        ack = DragItemAck(result=0, items=wire_items).encode()
        await self.transport.send_event(event(2037, ack, correlation),
                                        note='drag item ack (uid=%d to c=%d s=%d)' % (req.item_uid, req.to_container, req.to_slot))


    async def on_2406(self, correlation, body):
        # eEGS_CHAR_VERIFY_STAT_REQ -> 2407 eEGS_CHAR_VERIFY_STAT_ACK (0x0074B830).
        ack = CharVerifyStatAck(result=0).encode()
        await self.transport.send_event(event(2407, ack, correlation),
                                        note='char verify stat ack')

