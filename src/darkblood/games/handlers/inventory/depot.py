"""Depot / warehouse gold and slot handlers (2228, 2230, 2242, 2461)."""

from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages import (
    DepotShareExpireTimeGetAck,
    DepotLoadArAck,
    DepotLoadArReq,
    DepotSaveArAck,
    DepotSaveArReq,
    DepotSlotExtendAck,
    DepotSlotExtendReq,
)
from darkblood.player_management.characters import add_gold, gold_of


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

    def _save_depot_ar(self, char, target, previous_gold, previous_depot_gold):
        characters = [(self.account, char['id'])]
        if target is not char:
            characters.append((self.account, target['id']))
        try:
            self.store().save_chars(characters)
        except Exception:
            char['gold'] = previous_gold
            target['depot_gold'] = previous_depot_gold
            raise

    @packet_handler(DepotSaveArReq)
    async def handle_depot_save_ar(self, correlation, body):
        """Opcode 2228 (eEGS_DEPOT_SAVE_AR_REQ) -> 2229 (eEGS_DEPOT_SAVE_AR_ACK): deposit AR into depot."""
        req = DepotSaveArReq.decode(body)
        self.transport.record('depot-save-ar-req', body, depot_uid=req.depot_uid, gold=req.gold)
        char, target = self._depot_target_char(req.depot_uid)
        depot_ar = {}
        if char and target:
            gold = gold_of(char)
            deposit = min(max(0, req.gold), gold) if gold > 0 else 0
            char['gold'] = gold - deposit
            stored_gold = int(target.get('depot_gold', 0))
            target['depot_gold'] = stored_gold + deposit
            current_gold = char['gold']
            target_id = int(target.get('id', self.char_id))
            depot_ar[target_id] = target['depot_gold']
            self._save_depot_ar(char, target, gold, stored_gold)
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
            gold = gold_of(char)
            stored_gold = int(target.get('depot_gold', 0))
            withdraw = min(max(0, req.gold), stored_gold)
            target['depot_gold'] = stored_gold - withdraw
            add_gold(char, withdraw)
            current_gold = char['gold']
            target_id = int(target.get('id', self.char_id))
            depot_ar[target_id] = target['depot_gold']
            self._save_depot_ar(char, target, gold, stored_gold)
        else:
            current_gold = 0
        await self.reply(DepotLoadArAck(result=0, depot_ar=depot_ar, new_gold=current_gold), correlation,
                         note=f'depot load ar ack (depot={req.depot_uid} withdraw={req.gold} new_player_gold={current_gold})')

    @packet_handler(2242)
    async def handle_depot_share_expire_time(self, correlation, body):
        """Opcode 2242 (eEGS_DEPOT_SHARE_EXPIRE_TIME_GET_REQ) -> 2243: return shared depot expiration map."""
        await self.reply(DepotShareExpireTimeGetAck(), correlation, note='depot share expire time ack (none)')

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
