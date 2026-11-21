"""Depot / warehouse gold and slot handlers (2228, 2230, 2242, 2461)."""
import struct

from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import (
    DepotLoadArAck,
    DepotLoadArReq,
    DepotSaveArAck,
    DepotSaveArReq,
    DepotSlotExtendAck,
    DepotSlotExtendReq,
)


class DepotHandlersMixin:
    """Character and shared depot storage operations."""

    async def on_2228(self, correlation, body):
        # eEGS_DEPOT_SAVE_AR_REQ -> 2229 eEGS_DEPOT_SAVE_AR_ACK (0x00795220).
        req = DepotSaveArReq.decode(body)
        self.transport.record('depot-save-ar-req', body, gold=req.gold)
        char = self.current_char()
        if char:
            gold = char.get('gold', 0)
            deposit = min(max(0, req.gold), gold) if gold > 0 else req.gold
            char['gold'] = gold - deposit if gold >= deposit else 0
            char['u66'] = char['gold']
            char['depot_gold'] = char.get('depot_gold', 0) + deposit
            current_gold = char['gold']
            self.save_char()
        else:
            current_gold = req.gold
        await self.reply(DepotSaveArAck(result=0, new_gold=current_gold), correlation,
                         note=f'depot save ar ack (deposit={req.gold} remain_player_gold={current_gold})')

    async def on_2230(self, correlation, body):
        # eEGS_DEPOT_LOAD_AR_REQ -> 2231 eEGS_DEPOT_LOAD_AR_ACK (0x00795490).
        req = DepotLoadArReq.decode(body)
        self.transport.record('depot-load-ar-req', body, gold=req.gold)
        char = self.current_char()
        if char:
            depot_gold = char.get('depot_gold', req.gold)
            withdraw = min(max(0, req.gold), depot_gold)
            char['depot_gold'] = depot_gold - withdraw
            char['gold'] = char.get('gold', 0) + withdraw
            char['u66'] = char['gold']
            current_gold = char['gold']
            self.save_char()
        else:
            current_gold = req.gold
        await self.reply(DepotLoadArAck(result=0, new_gold=current_gold), correlation,
                         note=f'depot load ar ack (withdraw={req.gold} new_player_gold={current_gold})')

    async def on_2242(self, correlation, body):
        # eEGS_DEPOT_SHARE_EXPIRE_TIME_GET_REQ -> 2243 (0x0076C040).
        await self.transport.send_event(event(2243, struct.pack('<I', 0) + bytes.fromhex('1780'), correlation),
                                        note='depot share expire time ack (none)')

    async def on_2461(self, correlation, body):
        # eEGS_DEPOT_SLOT_EXTEND_REQ -> 2462 eEGS_DEPOT_SLOT_EXTEND_ACK (0x00651B20).
        req = DepotSlotExtendReq.decode(body)
        self.transport.record('depot-slot-extend-req', body, item_uid=req.item_uid, slot_index=req.slot_index)
        char = self.current_char()
        if char:
            char['depot_slots'] = char.get('depot_slots', 16) + 8
            self.save_char()
        await self.reply(DepotSlotExtendAck(result=0, slot_index=req.slot_index, expire_time=0, items=[]),
                         correlation, note=f'depot slot extend ack (slot={req.slot_index})')
