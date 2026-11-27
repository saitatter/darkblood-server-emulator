"""Item use: consumables, cash boxes, dyes, Life Water, seals, decomposition and point/skill items."""
import random
import struct
import time
from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages import (
    BuyLifeWaterAck,
    BuyLifeWaterReq,
    DragItemAck,
    DualSkillActiveNot,
    InsertApNot,
    ItemDecomposeAck,
    ItemDecomposeReq,
    MarkItemActiveNot,
    MarkTabActiveNot,
    MonsterCardChangeListNot,
    MonsterCardInfo,
    MonsterCardInsertAlbumNot,
    RandomboxResultItemNot,
    SealItemAck,
    SealItemReq,
    UseArenaSpItemAck,
    UseArenaSpItemReq,
    UseDyeingItemAck,
    UseDyeingItemReq,
    UseItemAck,
    UseItemLeaguePointAddAck,
    UseItemLeaguePointAddReq,
    UseItemReq,
    UseSelectedSkillChangeItemAck,
    UseSelectedSkillChangeItemReq,
)
from darkblood.player_management.characters import (
    add_reward_items,
    free_bag_slots,
    gold_of,
    slots_needed,
)
from darkblood.games.game_data import client_dict
from darkblood.games.progression import clear_dungeon_penalty, life_water_cost, add_ap
from darkblood.games.entities.character import mark_base_count

# Dual Skill Activation Order items (Type=54 in item_cash.lua / item_disposable.lua): ItemID -> AdjValue (days).
DUAL_SKILL_ITEM_DAYS = {
    'IDSk1Cash269': 30,
    'IDSk20S159': 10,
    'IDSk20R434': 30,
}


class ConsumableHandlersMixin:
    async def _apply_special_consumable(self, char: dict, item_str_code: str, item_code: int, use_count: int):
        """Apply side effects of special consumable items (Book of AP, Dual Skill, Agreement of Rune, Pets/Mounts)."""
        if item_str_code == 'Ispaa0001':
            add_ap(char, max(1, use_count))
            self.save_char()
            await self.send_msg(
                InsertApNot(current_ap=char['sp'], total_ap=char['total_ap']),
                note='book of ap used (+%d AP -> sp=%d total=%d)' % (max(1, use_count), char['sp'], char['total_ap']),
            )
        elif item_str_code in DUAL_SKILL_ITEM_DAYS:
            add_days = DUAL_SKILL_ITEM_DAYS[item_str_code] * max(1, int(use_count))
            now = int(time.time())
            base_expire = max(now, int(char.get('dual_skill_expire', 0)))
            new_expire = base_expire + add_days * 86400
            char['dual_skill_expire'] = new_expire
            remain_sec = new_expire - now
            cur_idx = int(char.get('dual_skill_index', 0))
            self.save_char()
            await self.send_msg(
                DualSkillActiveNot(
                    extend_time=remain_sec,
                    add_day=add_days,
                    cur_dual_skill_index=cur_idx,
                    item_id=item_code,
                ),
                note=f'dual skill active not (+{add_days}d, remain={remain_sec}s, idx={cur_idx})',
            )
        elif item_str_code == 'IAMk1R190':
            char['mark_active'] = True
            base_cnt = max(int(char.get('mark_base_cnt', 0)), mark_base_count(char.get('level', 1)), 3)
            bonus_cnt = min(3, int(char.get('mark_bonus_cnt', 0)) + max(1, int(use_count)))
            char['mark_base_cnt'] = base_cnt
            char['mark_bonus_cnt'] = bonus_cnt
            self.save_char()
            await self.send_msg(MarkTabActiveNot(active_mark=True), note='mark tab active not (IAMk1R190)')
            await self.send_msg(
                MarkItemActiveNot(base_count=base_cnt, bonus_count=bonus_cnt),
                note=f'mark item active not (base={base_cnt}, bonus={bonus_cnt})',
            )
        await self.session.pets.apply_pet_or_mount_item(char, item_str_code)
        await self.session.life.use_fishing_proficiency_item(char, item_str_code, use_count)

    async def _grant_opened_box_contents(self, char: dict, box_code: str, contents: list, box_kind: str):
        if box_kind == 'monster_card':
            acct = self.store().account_data(self.account)
            cards = acct.setdefault('monster_cards', [])
            album = acct.setdefault('monster_card_album', [])
            next_uid = max((int(c.get('uid', 0)) for c in cards), default=0) + 1
            new_cards = []
            new_album_codes = []
            granted_names = []
            for item_code, qty in contents:
                card_code = item_code[1:] if item_code.startswith('MCard') else item_code
                if card_code not in album:
                    album.append(card_code)
                    new_album_codes.append(card_code)
                for _ in range(max(1, int(qty))):
                    uid = next_uid
                    next_uid += 1
                    cards.append({'uid': uid, 'code': card_code, 'level': 1, 'owner_uid': 0})
                    new_cards.append(MonsterCardInfo(
                        card_uid=uid,
                        card_id=jhash(card_code),
                        level=1,
                        owner_uid=0,
                    ))
                    granted_names.append(card_code)
            self.store().save_account_data(self.account)
            await self.send_msg(
                MonsterCardChangeListNot(new_cards=new_cards, del_cards=[], from_random_card=True),
                note='monster card booster opened (%s -> %s)' % (box_code, ', '.join(granted_names)),
            )
            for card_code in new_album_codes:
                await self.send_msg(
                    MonsterCardInsertAlbumNot(album_card_id=jhash(card_code)),
                    note='monster card album insert (%s)' % card_code,
                )
            return
        stored = add_reward_items(char, contents)
        self.save_char()
        wire_items = [Item(owner=UPDATE_OWNER, **i) for i in stored]
        await self.send_msg(
            DragItemAck(result=0, items=wire_items),
            note='cash box opened (%s -> %s)' % (box_code, ', '.join(i['code'] for i in stored)),
        )
        if box_kind == 'random_box':
            reward_code, reward_count = contents[0]
            reward_hash = jhash(reward_code)
            if reward_hash >= 0x80000000:
                reward_hash -= 0x100000000
            await self.send_msg(
                RandomboxResultItemNot(item_code=reward_hash, count=reward_count, is_jackpot=True),
                note='random box result (%s x%d)' % (reward_code, reward_count),
            )

    @packet_handler(UseItemReq)
    async def handle_use_item(self, correlation, body):
        """Opcode 2038 (eEGS_USE_ITEM_REQ) -> 2039 (eEGS_USE_ITEM_ACK): consume an item, open cash boxes or pet/mount items."""
        req = UseItemReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(UseItemAck(result=results.NO_EXIST_CHAR), correlation, note='use item fail (no char)')
            return
        items = char.get('items', [])
        used_item = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not used_item:
            await self.reply(UseItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note='use item fail (not found)')
            return
        item_str_code = used_item.get('code', '')
        if self.session.life.fishing_proficiency_item_at_cap(char, item_str_code):
            await self.reply(UseItemAck(result=results.INVALID_STATE), correlation,
                             note='fishing proficiency item refused (already at cap)')
            return
        if item_str_code == 'IAMk1R190' and int(char.get('mark_bonus_cnt', 0)) >= 3:
            await self.reply(UseItemAck(result=results.INVALID_STATE), correlation,
                             note='rune agreement refused (all bonus slots unlocked)')
            return
        contents, box_kind = self._cash_box_contents(item_str_code)
        count = used_item.get('count', 1) - req.use_count
        if contents and box_kind != 'monster_card':
            inventory = char
            if count <= 0:
                inventory = dict(char, items=[item for item in items if item is not used_item])
            free = free_bag_slots(inventory)
            needed = slots_needed(contents, inventory)
            if free is not None and needed > free:
                await self.reply(UseItemAck(result=results.INVEN_FULL), correlation,
                                 note='use item fail (bag full: need %d, free %d)' % (needed, free))
                return
        item_code = jhash(item_str_code)
        updated = []
        if count <= 0:
            items.remove(used_item)
            # Send a zero-count tombstone at the item's slot so the client
            # clears the icon from the bag (same pattern as 2211 dye consume).
            updated.append(Item(
                owner=UPDATE_OWNER,
                uid=0,
                code='',
                container=used_item.get('container', 1),
                slot=used_item.get('slot', 0),
                count=0,
            ))
        else:
            used_item['count'] = count
            updated.append(Item(owner=UPDATE_OWNER, **used_item))
        self.save_char()

        await self.reply(UseItemAck(result=0, items=updated, item_id=item_code, use_count=req.use_count),
                         correlation, note='use item ack (uid=%d code=%08x)' % (req.item_uid, item_code))
        await self._apply_special_consumable(char, item_str_code, item_code, req.use_count)
        if contents:
            await self._grant_opened_box_contents(char, item_str_code, contents, box_kind)

    @packet_handler(UseDyeingItemReq)
    async def handle_use_dyeing_item(self, correlation, body):
        """Opcode 2210 (eEGS_USE_DYEING_ITEM_REQ) -> 2211 (eEGS_USE_DYEING_ITEM_ACK): apply hair/skin/item dye and consume it."""
        try:
            req = UseDyeingItemReq.decode(body)
        except struct.error:
            await self.reply(UseDyeingItemAck(result=results.INVALID_STATE), correlation,
                             note='use dyeing item fail (bad request)')
            return
        char = self.current_char()
        items = char.get('items', []) if char else []
        dye_item = next((i for i in items if i.get('uid') == req.dye_uid), None)
        if dye_item is None:
            await self.reply(UseDyeingItemAck(result=results.INVEN_ITEM_NOT_FOUND, dye=req.dye), correlation,
                             note='use dyeing item fail (uid %d not found)' % req.dye_uid)
            return
        count = dye_item.get('count', 1) - 1
        if count <= 0:
            items.remove(dye_item)
            update = Item(owner=UPDATE_OWNER, uid=0, code='', container=dye_item['container'],
                          slot=dye_item['slot'], count=0)
        else:
            dye_item['count'] = count
            update = Item(owner=UPDATE_OWNER, **dye_item)
        stain = client_dict.cash_items().get(dye_item.get('code', ''), {}).get('type')
        slot = {2: 'hair_dye', 3: 'skin_dye'}.get(stain)
        if slot and req.target_uid == -1:
            char[slot] = [req.dye.part, req.dye.option, req.dye.color]
        self.save_char()
        await self.reply(UseDyeingItemAck(result=0, dye=req.dye, items=[update]), correlation,
                         note='use dyeing item ack (%s target=%d color=%08x)' % (
                             dye_item.get('code'), req.target_uid, req.dye.color))

    def _cash_box_contents(self, code):
        info = client_dict.cash_items().get(code)
        if not info or not info['adj']:
            return [], ''
        adj = info['adj']
        if adj.startswith('PACKAGE'):
            return list(client_dict.cash_packages().get(adj, [])), 'package'
        states, groups = client_dict.random_boxes()
        grades = states.get(adj)
        if not grades:
            return [], ''
        weights = [p for p, _ in grades]
        _, names = random.choices(grades, weights=weights)[0]
        pool = [entry for name in names for entry in groups.get(name, [])]
        if not pool:
            return [], ''
        # Type 58 items (Card Booster Packs) are handled by JAppPageMonsterCard (0x93)
        # via 2603 MonsterCardChangeListNot(from_random_card=True), not Page_RandomBox (0x41).
        kind = 'monster_card' if info.get('type') == 58 else 'random_box'
        return [random.choice(pool)], kind

    @packet_handler(BuyLifeWaterReq)
    async def handle_buy_life_water(self, correlation, body):
        """Opcode 2086 (eEGS_BUY_LIFE_WATER_REQ) -> 2087 (eEGS_BUY_LIFE_WATER_ACK): cure dungeon penalty for AR."""
        req = BuyLifeWaterReq.decode(body)
        self.transport.record('buy-life-water-req', body, flag=req.flag)
        char = self.current_char()
        if char is None:
            await self.reply(BuyLifeWaterAck(result=1, flag=req.flag, remain_currency=0),
                             correlation, note='buy life water ack (no char)')
            return
        penalty_type = 1 if req.flag else 0
        gold = gold_of(char)
        cost = life_water_cost(char, penalty_type=penalty_type)
        if cost > gold:
            await self.reply(BuyLifeWaterAck(result=results.NOT_ENOUGH_AR, flag=req.flag, remain_currency=gold),
                             correlation, note=f'buy life water refused (need {cost} AR, have {gold})')
            return
        gold -= cost
        char['gold'] = gold
        clear_not = clear_dungeon_penalty(char, penalty_type=penalty_type)
        self.save_char()
        await self.reply(BuyLifeWaterAck(result=0, flag=req.flag, remain_currency=gold),
                         correlation, note=f'buy life water ack (flag={req.flag}, -{cost} AR)')
        if cost > 0:
            await self.transport.send_event(
                event(2085, clear_not.encode()),
                note=f'clear dungeon penalty (type={penalty_type})',
            )

    @packet_handler(SealItemReq)
    async def handle_seal_item(self, correlation, body):
        """Opcode 2147 (eEGS_SEAL_ITEM_REQ) -> 2148 (eEGS_SEAL_ITEM_ACK): seal a tradable equipment piece."""
        req = SealItemReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(SealItemAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'seal item fail (uid={req.item_uid} not found)')
            return
        await self.reply(SealItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **target)]), correlation,
                         note=f'seal item ack (uid={req.item_uid})')

    @packet_handler(UseSelectedSkillChangeItemReq)
    async def handle_use_selected_skill_change_item(self, correlation, body):
        """Opcode 2428 (eEGS_USE_SELECTED_SKILL_CHANGE_ITEM_REQ) -> 2429: reset/change a selected skill via item."""
        req = UseSelectedSkillChangeItemReq.decode(body)
        char = self.current_char()
        sp = char.get('sp', 0) if char else 0
        await self.reply(
            UseSelectedSkillChangeItemAck(result=0, margin_ap=sp, learned_skills={}, items=[], quickslots=[]),
            correlation, note=f'use selected skill change item ack (item={req.item_uid})')

    @packet_handler(ItemDecomposeReq)
    async def handle_item_decompose(self, correlation, body):
        """Opcode 2545 (eEGS_ITEM_DECOMPOSE_REQ) -> 2546 (eEGS_ITEM_DECOMPOSE_ACK): dismantle an item."""
        req = ItemDecomposeReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(ItemDecomposeAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'item decompose fail (uid={req.item_uid} not found)')
            return
        items.remove(target)
        self.save_char()
        vacated = Item(owner=UPDATE_OWNER, uid=0, code='', container=target['container'],
                       slot=target['slot'], count=0)
        await self.reply(ItemDecomposeAck(result=0, items=[vacated]), correlation,
                         note=f'item decompose ack (uid={req.item_uid})')

    @packet_handler(UseItemLeaguePointAddReq)
    async def handle_use_league_point_item(self, correlation, body):
        """Opcode 2573 (eEGS_USE_ITEM_LEAGUE_POINT_ADD_REQ) -> 2574: consume an item that awards league points."""
        req = UseItemLeaguePointAddReq.decode(body)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.item_uid), None)
        if not target:
            await self.reply(UseItemLeaguePointAddAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'use league point item fail (uid={req.item_uid} not found)')
            return
        count = target.get('count', 1) - 1
        if count <= 0:
            items.remove(target)
            update = Item(owner=UPDATE_OWNER, uid=0, code='', container=target['container'],
                          slot=target['slot'], count=0)
        else:
            target['count'] = count
            update = Item(owner=UPDATE_OWNER, **target)
        char['league_points'] = char.get('league_points', 0) + 100
        self.save_char()
        await self.reply(
            UseItemLeaguePointAddAck(result=0, items=[update], league_point=char['league_points']),
            correlation, note=f'use league point item ack (uid={req.item_uid} pts={char["league_points"]})')

    @packet_handler(UseArenaSpItemReq)
    async def handle_use_arena_sp_item(self, correlation, body):
        """Opcode 2709 (eEGS_USE_ARENA_SP_ITEM_REQ) -> 2710 (eEGS_USE_ARENA_SP_ITEM_ACK): consume an arena SP item."""
        req = UseArenaSpItemReq.decode(body)
        self.transport.record('use-arena-sp-item-req', body, item_uid=req.item_uid)
        await self.reply(UseArenaSpItemAck(result=0, consumed_items=[], arena_sp=100), correlation,
                         note=f'use arena sp item ack (item={req.item_uid})')
