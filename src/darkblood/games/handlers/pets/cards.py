"""Monster Card & Card Lotto domain handlers (2604 - 2639)."""
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages.pets import (
    MonsterCardExtendSlotAck,
    MonsterCardExtendSlotReq,
    MonsterCardGetRewardLottoAck,
    MonsterCardGetRewardLottoReq,
    MonsterCardGetRewardPointArrivalAck,
    MonsterCardGetRewardPointArrivalReq,
    MonsterCardInfo,
    MonsterCardInsertAck,
    MonsterCardInsertReq,
    MonsterCardLottoEntry,
    MonsterCardLottoRegAck,
    MonsterCardLottoRegReq,
    MonsterCardMergeAck,
    MonsterCardMergeReq,
    MonsterCardReleaseAllCharAck,
    MonsterCardReleaseAllCharReq,
    MonsterCardSetCharDeckAck,
    MonsterCardSetCharDeckReq,
)


class MonsterCardHandlersMixin:
    """Monster Card deck, merge, slot extension and Card Lotto."""

    @packet_handler(2604)
    async def handle_monster_card_insert(self, correlation, body):
        req = MonsterCardInsertReq.decode(body)
        await self.reply(MonsterCardInsertAck(result=0), correlation,
                         note=f'monster card insert ack (item={req.item_uid})')

    @packet_handler(2606)
    async def handle_monster_card_merge(self, correlation, body):
        req = MonsterCardMergeReq.decode(body)
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        await self.reply(MonsterCardMergeAck(result=0, new_cards=[], del_cards=req.card_uids, cur_ar=cur_ar),
                         correlation, note=f'monster card merge ack (count={len(req.card_uids)})')

    @packet_handler(2610)
    async def handle_monster_card_set_char_deck(self, correlation, body):
        req = MonsterCardSetCharDeckReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['monster_card_deck'] = list(req.deck_uids)
            self.save_char()
        await self.reply(MonsterCardSetCharDeckAck(result=0, deck_uids=req.deck_uids, updated_cards=[]),
                         correlation, note=f'monster card set deck ack ({len(req.deck_uids)})')

    @packet_handler(2613)
    async def handle_monster_card_release_all_char(self, correlation, body):
        req = MonsterCardReleaseAllCharReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['monster_card_deck'] = []
            self.save_char()
        await self.reply(
            MonsterCardReleaseAllCharAck(result=0, deck_uids=[], card=MonsterCardInfo(card_uid=req.card_uid)),
            correlation, note='monster card release all ack',
        )

    @packet_handler(2615)
    async def handle_monster_card_extend_slot(self, correlation, body):
        req = MonsterCardExtendSlotReq.decode(body)
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        max_cnt = int((char or {}).get('monster_card_max_slots', 50)) + max(1, req.count) * 10
        if char is not None:
            char['monster_card_max_slots'] = max_cnt
            self.save_char()
        await self.reply(MonsterCardExtendSlotAck(result=0, max_inven_cnt=max_cnt, cur_ar=cur_ar),
                         correlation, note=f'monster card extend slot ack (max={max_cnt})')

    @packet_handler(2633)
    async def handle_monster_card_lotto_reg(self, correlation, body):
        req = MonsterCardLottoRegReq.decode(body)
        char = self.current_char()
        cur_ar = int(char.get('gold', 0)) if char else 0
        entry = MonsterCardLottoEntry(reg_uid=1, char_uid=self.char_id or 0, lotto_key=1, numbers=req.numbers)
        await self.reply(MonsterCardLottoRegAck(result=0, entry=entry, event_cards_out={}, cur_ar=cur_ar),
                         correlation, note='monster card lotto reg ack')

    @packet_handler(2636)
    async def handle_monster_card_get_reward_lotto(self, correlation, body):
        req = MonsterCardGetRewardLottoReq.decode(body)
        await self.reply(MonsterCardGetRewardLottoAck(result=0, lotto_reg_uid=req.lotto_reg_uid, rank=1, items=[]),
                         correlation, note=f'monster card lotto reward ack (uid={req.lotto_reg_uid})')

    @packet_handler(2638)
    async def handle_monster_card_get_reward_point_arrival(self, correlation, body):
        req = MonsterCardGetRewardPointArrivalReq.decode(body)
        await self.reply(MonsterCardGetRewardPointArrivalAck(result=0, choice_point=req.choice_point, items=[]),
                         correlation, note=f'monster card point reward ack (pt={req.choice_point})')
