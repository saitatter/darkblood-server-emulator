"""Monster Card & Card Lotto domain handlers (2601 - 2639)."""
from darkblood.core.hashing import jhash
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages.inventory import DragItemAck
from darkblood.games.network.messages.pets import (
    MonsterCardAlbumAck,
    MonsterCardChangeListNot,
    MonsterCardDeckAck,
    MonsterCardExtendSlotAck,
    MonsterCardExtendSlotReq,
    MonsterCardGetRewardLottoAck,
    MonsterCardGetRewardLottoReq,
    MonsterCardGetRewardPointArrivalAck,
    MonsterCardGetRewardPointArrivalReq,
    MonsterCardInfo,
    MonsterCardInsertAck,
    MonsterCardInsertAlbumNot,
    MonsterCardInsertReq,
    MonsterCardListAck,
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
from darkblood.player_management.characters import gold_of, spend_gold

# DictMonsterCard:LoadSettings (monstercard.lua)
MONSTER_CARD_BASE_SLOTS = 60
MONSTER_CARD_EXTEND_STEP = 10
MONSTER_CARD_MAX_SLOTS = 200
MONSTER_CARD_EXTEND_PRICE = 500_000


def free_monster_card_slots(char) -> int:
    capacity = int(char.get('monster_card_max_slots', MONSTER_CARD_BASE_SLOTS))
    return max(0, capacity - len(char.get('monster_cards', [])))


def _card_info_from_record(rec: dict, owner_uid: int) -> MonsterCardInfo:
    return MonsterCardInfo(
        card_uid=int(rec.get('uid', 0)),
        card_id=jhash(rec.get('code', '')),
        level=int(rec.get('level', 1)),
        owner_uid=owner_uid,
    )


class MonsterCardHandlersMixin:
    """Monster Card deck, collection, merge, slot extension and Card Lotto."""

    @packet_handler(2601)
    async def handle_monster_card_list(self, correlation, body):
        """Opcode 2601 (eEGS_MONSTERCARD_GET_LIST_REQ) -> 2602."""
        char = self.current_char()
        owner_uid = self.char_id or 0
        deck = list((char or {}).get('monster_card_deck', []))
        cards = {
            int(c['uid']): _card_info_from_record(c, owner_uid)
            for c in (char or {}).get('monster_cards', [])
        }
        await self.reply(
            MonsterCardListAck(result=0, deck_uids=deck, cards=cards),
            correlation,
            note=f'monster card list ack (deck={len(deck)}, cards={len(cards)})',
        )

    @packet_handler(2608)
    async def handle_monster_card_deck(self, correlation, body):
        """Opcode 2608 (eEGS_MONSTERCARD_GET_CHAR_DECK_REQ) -> 2609."""
        char = self.current_char()
        deck = list((char or {}).get('monster_card_deck', []))
        await self.reply(
            MonsterCardDeckAck(result=0, card_uids=deck),
            correlation,
            note=f'monster card deck ack ({len(deck)})',
        )

    @packet_handler(2617)
    async def handle_monster_card_album(self, correlation, body):
        """Opcode 2617 (eEGS_MONSTERCARD_GET_ALBUM_REQ) -> 2618."""
        char = self.current_char()
        seen = []
        seen_set = set()
        for code in (char or {}).get('monster_card_album', []):
            if code and code not in seen_set:
                seen_set.add(code)
                seen.append(code)
        for rec in (char or {}).get('monster_cards', []):
            code = rec.get('code', '')
            if code and code not in seen_set:
                seen_set.add(code)
                seen.append(code)
        album_ids = [jhash(code) for code in seen]
        await self.reply(
            MonsterCardAlbumAck(result=0, album_ids=album_ids),
            correlation,
            note=f'monster card album ack ({len(album_ids)})',
        )

    @packet_handler(2604)
    async def handle_monster_card_insert(self, correlation, body):
        req = MonsterCardInsertReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not char or target is None:
            await self.reply(MonsterCardInsertAck(result=0), correlation,
                             note=f'monster card insert ack (item={req.item_uid})')
            return
        if not free_monster_card_slots(char):
            await self.reply(MonsterCardInsertAck(result=results.INVEN_FULL), correlation,
                             note='monster card insert refused (card inventory full)')
            return
        item_code = target.get('code', '')
        card_code = item_code[1:] if item_code.startswith('MCard') else item_code
        count = int(target.get('count', 1)) - 1
        if count <= 0:
            items.remove(target)
            updated = Item(
                owner=UPDATE_OWNER,
                uid=0,
                code='',
                container=target.get('container', 1),
                slot=target.get('slot', 0),
                count=0,
            )
        else:
            target['count'] = count
            updated = Item(owner=UPDATE_OWNER, **target)
        cards = char.setdefault('monster_cards', [])
        uid = max((int(c.get('uid', 0)) for c in cards), default=0) + 1
        rec = {'uid': uid, 'code': card_code, 'level': 1}
        cards.append(rec)
        album = char.setdefault('monster_card_album', [])
        new_album = card_code not in album
        if new_album:
            album.append(card_code)
        self.save_char()
        await self.reply(MonsterCardInsertAck(result=0), correlation,
                         note=f'monster card insert ack (item={req.item_uid} -> {card_code})')
        await self.send_msg(DragItemAck(result=0, items=[updated]),
                            note=f'monster card item consumed ({item_code})')
        await self.send_msg(
            MonsterCardChangeListNot(
                new_cards=[_card_info_from_record(rec, self.char_id or 0)],
                del_cards=[],
                from_random_card=False,
            ),
            note=f'monster card added ({card_code})',
        )
        if new_album:
            await self.send_msg(
                MonsterCardInsertAlbumNot(album_card_id=jhash(card_code)),
                note=f'monster card album insert ({card_code})',
            )

    @packet_handler(2606)
    async def handle_monster_card_merge(self, correlation, body):
        req = MonsterCardMergeReq.decode(body)
        char = self.current_char()
        cur_ar = gold_of(char)
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
        MonsterCardExtendSlotReq.decode(body)
        char = self.current_char()
        cur_ar = gold_of(char)
        cur_max = int((char or {}).get('monster_card_max_slots', MONSTER_CARD_BASE_SLOTS))
        if cur_max >= MONSTER_CARD_MAX_SLOTS:
            await self.reply(
                MonsterCardExtendSlotAck(result=results.INVALID_STATE, max_inven_cnt=cur_max, cur_ar=cur_ar),
                correlation,
                note=f'monster card extend slot refused (already at max {cur_max})',
            )
            return
        if char is not None:
            if not spend_gold(char, MONSTER_CARD_EXTEND_PRICE):
                await self.reply(
                    MonsterCardExtendSlotAck(result=results.NOT_ENOUGH_AR, max_inven_cnt=cur_max, cur_ar=cur_ar),
                    correlation,
                    note=f'monster card extend slot refused (need {MONSTER_CARD_EXTEND_PRICE} AR, have {cur_ar})',
                )
                return
            max_cnt = min(MONSTER_CARD_MAX_SLOTS, cur_max + MONSTER_CARD_EXTEND_STEP)
            char['monster_card_max_slots'] = max_cnt
            cur_ar = gold_of(char)
            self.save_char()
        else:
            max_cnt = min(MONSTER_CARD_MAX_SLOTS, cur_max + MONSTER_CARD_EXTEND_STEP)
        await self.reply(MonsterCardExtendSlotAck(result=0, max_inven_cnt=max_cnt, cur_ar=cur_ar),
                         correlation, note=f'monster card extend slot ack (max={max_cnt} ar={cur_ar})')

    @packet_handler(2633)
    async def handle_monster_card_lotto_reg(self, correlation, body):
        req = MonsterCardLottoRegReq.decode(body)
        char = self.current_char()
        cur_ar = gold_of(char)
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
