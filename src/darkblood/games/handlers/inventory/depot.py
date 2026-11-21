"""Depot / warehouse gold and slot handlers (2228, 2230, 2242, 2461)."""
import struct

from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler
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

    def _depot_target_char(self, depot_uid: int):
        char = self.current_char()
        if char is None:
            return None, None
        if depot_uid and depot_uid != char.get('id'):
            other = self.store().get(self.account, depot_uid)
            if other is not None:
                return char, other
        return char, char

    @packet_handler(DepotSaveArReq)
    async def handle_depot_save_ar(self, correlation, body):
        """Opcode 2228 (eEGS_DEPOT_SAVE_AR_REQ) -> 2229 (eEGS_DEPOT_SAVE_AR_ACK): deposit AR into depot."""
        req = DepotSaveArReq.decode(body)
        self.transport.record('depot-save-ar-req', body, depot_uid=req.depot_uid, gold=req.gold)
        char, target = self._depot_target_char(req.depot_uid)
        depot_ar = {}
        if char and target:
            gold = int(char.get('gold', 0))
            deposit = min(max(0, req.gold), gold) if gold > 0 else 0
            char['gold'] = gold - deposit
            char['u66'] = char['gold']
            target['depot_gold'] = int(target.get('depot_gold', 0)) + deposit
            current_gold = char['gold']
            target_id = int(target.get('id', self.char_id))
            depot_ar[target_id] = target['depot_gold']
            self.store().save_char(self.account, char['id'])
            if target is not char:
                self.store().save_char(self.account, target['id'])
        else:
            current_gold = 0
        await self.reply(DepotSaveArAck(result=0, depot_ar=depot_ar, new_gold=current_gold), correlation,
                         note=f'depot save ar ack (depot={req.depot_uid} deposit={req.gold} remain_player_gold={current_gold})')

    @packet_handler(DepotLoadArReq)
    async def handle_depot_load_ar(self, correlation, body):
        """Opcode 2230 (eEGS_DEPOT_LOAD_AR_REQ) -> 2231 (eEGS_DEPOT_LOAD_AR_ACK): withdraw AR from depot."""
        req = DepotLoadArReq.decode(body)
        self.transport.record('depot-load-ar-req', body, depot_uid=req.depot_uid, gold=req.gold)
        char, target = self._depot_target_char(req.depot_uid)
        depot_ar = {}
        if char and target:
            stored_gold = int(target.get('depot_gold', 0))
            withdraw = min(max(0, req.gold), stored_gold)
            target['depot_gold'] = stored_gold - withdraw
            char['gold'] = int(char.get('gold', 0)) + withdraw
            char['u66'] = char['gold']
            current_gold = char['gold']
            target_id = int(target.get('id', self.char_id))
            depot_ar[target_id] = target['depot_gold']
            self.store().save_char(self.account, char['id'])
            if target is not char:
                self.store().save_char(self.account, target['id'])
        else:
            current_gold = 0
        await self.reply(DepotLoadArAck(result=0, depot_ar=depot_ar, new_gold=current_gold), correlation,
                         note=f'depot load ar ack (depot={req.depot_uid} withdraw={req.gold} new_player_gold={current_gold})')

    @packet_handler(2242)
    async def handle_depot_share_expire_time(self, correlation, body):
        """Opcode 2242 (eEGS_DEPOT_SHARE_EXPIRE_TIME_GET_REQ) -> 2243: return shared depot expiration map."""
        await self.transport.send_event(event(2243, struct.pack('<I', 0) + bytes.fromhex('1780'), correlation),
                                        note='depot share expire time ack (none)')

    @packet_handler(DepotSlotExtendReq)
    async def handle_depot_slot_extend(self, correlation, body):
        """Opcode 2461 (eEGS_DEPOT_SLOT_EXTEND_REQ) -> 2462 (eEGS_DEPOT_SLOT_EXTEND_ACK): expand depot storage slots."""
        req = DepotSlotExtendReq.decode(body)
        self.transport.record('depot-slot-extend-req', body, item_uid=req.item_uid, slot_index=req.slot_index)
        remain_sec = 30 * 86400
        char = self.current_char()
        if char:
            extend_remain = list(char.get('depot_extend_remain', [0, 0]))
            while len(extend_remain) < 2:
                extend_remain.append(0)
            if 0 <= req.slot_index < 2:
                extend_remain[req.slot_index] = int(extend_remain[req.slot_index]) + remain_sec
                remain_sec = extend_remain[req.slot_index]
            char['depot_extend_remain'] = extend_remain
            char['depot_slots'] = char.get('depot_slots', 20) + 20
            self.save_char()
        await self.reply(DepotSlotExtendAck(result=0, slot_index=req.slot_index, expire_time=remain_sec, items=[]),
                         correlation, note=f'depot slot extend ack (slot={req.slot_index} remain={remain_sec})')
