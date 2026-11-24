"""Dungeon completion, rank calculation, card rewards, floor loot drops and pickups."""
import random
import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import JSerBufferReader, WireError, event
from darkblood.games import loot
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data.client_dict import (
    dungeon_maps,
    money_drops,
    quest_dungeon_objectives,
)
from darkblood.games.network import results
from darkblood.games.network.messages import (
    ChoiceRewardPartyRankAck,
    ChoiceRewardPartyRankReq,
    DragItemAck,
    DropItemNot,
    FinishGameAck,
    FinishGameReq,
    GetDropArNot,
    ItemDropEntry,
    PickUpItemReq,
    PickUpItemResultAck,
    QuestObjective,
    QuestUpdateNot,
    SingleReward,
)
from darkblood.player_management.characters import (
    add_reward_items,
    free_bag_slots,
    slots_needed,
)

# DictDungeonReward:LoadDungeonReward Exp_Reward bonus rates per rank (0=D..6=SSS).
_RANK_EXP_BONUS = {0: 0.065, 1: 0.07, 2: 0.075, 3: 0.10, 4: 0.13, 5: 0.17, 6: 0.20}
# DictDungeonReward:LoadDungeonReward BoxGrade: D/C/B->0, A->1, S->2, SS->3, SSS->4.
_RANK_BOX_GRADE = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4}


def _ratio_to_rank(ratio: float) -> int:
    # Client rank enum (0x007101F0 / 0x00720000:530 Lua_OnChecked_5) and
    # DictMap:LoadDungeonRank (dungeonrank.lua):
    # 0=D (0.0), 1=C (0.1), 2=B (0.225), 3=A (0.375), 4=S (0.625), 5=SS (0.75), 6=SSS (0.9).
    if ratio >= 0.9:
        return 6
    if ratio >= 0.75:
        return 5
    if ratio >= 0.625:
        return 4
    if ratio >= 0.375:
        return 3
    if ratio >= 0.225:
        return 2
    if ratio >= 0.1:
        return 1
    return 0


def _fallback_rank_from_stats(score: int, kill_count: int) -> int:
    if score >= 50000 or kill_count >= 25:
        return 6
    if score >= 30000 or kill_count >= 20:
        return 5
    if score >= 15000 or kill_count >= 15:
        return 4
    if score >= 8000 or kill_count >= 10:
        return 3
    if score >= 3000 or kill_count >= 5:
        return 2
    if score >= 1000 or kill_count >= 2:
        return 1
    return 0


def _parse_finish_game_tail(tail: bytes):
    """Parse optional mapPartyScoreList, mapPartyDPS, nTotalMosterHP from 5017 tail."""
    if not tail:
        return {}, 0
    try:
        reader = JSerBufferReader(tail)
        party_scores = reader.read_tagged_map(JSerBufferReader.read_i64, JSerBufferReader.read_i32)
        reader.read_tagged_map(JSerBufferReader.read_i64, JSerBufferReader.read_i32)  # mapPartyDPS
        total_monster_hp = reader.read_i32() if reader.remaining >= 4 else 0
        return party_scores, total_monster_hp
    except (WireError, struct.error, IndexError):
        return {}, 0


class DungeonRewardsHandlers:
    async def _update_quest_dungeon_clear(self, map_code, char):
        """Advance dungeon-clear objectives (mission types 2 and 3) on 5017 clear."""
        if not map_code:
            return
        by_dungeon, by_map = quest_dungeon_objectives()
        info = dungeon_maps().get(map_code)
        dungeon_id = info[0] if info else ''

        candidates = list(by_map.get(map_code, ()))
        if dungeon_id:
            candidates.extend(by_dungeon.get(dungeon_id, ()))
        if not candidates:
            return

        active = char.get('quests_active', {})
        seen = set()
        for q_hash, obj_idx, target_count in candidates:
            key = (q_hash, obj_idx)
            if key in seen:
                continue
            seen.add(key)
            q_key = str(q_hash)
            if q_key in active:
                q_record = active[q_key]
                counters = q_record.setdefault('counters', [])
                while len(counters) <= obj_idx:
                    counters.append(0)
                if counters[obj_idx] < target_count:
                    counters[obj_idx] += 1
                    await self.send_msg(
                        QuestUpdateNot(updates=[QuestObjective(q_hash, obj_idx, counters[obj_idx])]),
                        note=f'quest dungeon clear not ({q_key} map={map_code} obj={obj_idx} count={counters[obj_idx]}/{target_count})',
                    )

    @packet_handler(5017)
    async def handle_finish_game(self, correlation, body):
        # eERC_FINISH_GAME_REQ (sender 0x007AD380) -> 5018 eERC_FINISH_GAME_ACK (handler 0x007ADB60).
        req = FinishGameReq.decode(body)
        self.transport.record('finish-game-req', body, is_clear=req.is_clear)
        run_char_id = self.char_id if getattr(self, 'in_dungeon', False) else None
        if run_char_id and self._finish_game_reply is not None:
            finished_char_id, finished_ack = self._finish_game_reply
            if finished_char_id == run_char_id:
                await self.transport.send_event(event(5018, finished_ack, correlation),
                                                note='repeat finish game ack')
                return

        map_code = getattr(self, 'map_code', '')
        room = self._shared_run()
        # Only the host's client sends 5017 in a party run (live 2026-11-21): its
        # result goes to every member. A member's own 5017 stays a solo result.
        if room is not None and room.host is self.session:
            members = self._run_members()
        else:
            char = self._current_char()
            members = [(self.session, char)] if char is not None else []

        party_scores, total_monster_hp = _parse_finish_game_tail(req.tail)
        fallback_rank = _fallback_rank_from_stats(
            getattr(self, 'dungeon_score', 0),
            getattr(self, 'dungeon_kill_count', 0),
        )

        # The player's UID is the character id (2007 details +0x1C, copied to
        # player +0x10 by 0x0095A150). Characters have no 'char_uid' key, so
        # mapSingleReward used to go out empty and the result screen froze.
        rewards = {}
        member_ranks = []
        for member, char in members:
            dungeon = member.dungeon
            dungeon.dungeon_cleared = bool(req.is_clear)
            if req.is_clear:
                dungeon._record_dungeon_clear(char, map_code)
                await dungeon._update_quest_dungeon_clear(map_code, char)
            uid = int(char.get('id', 0))
            if req.is_clear and getattr(dungeon, 'in_dungeon', False) and dungeon.reward_card is None:
                dungeon.reward_card = (uid, map_code)
            gained = getattr(dungeon, 'dungeon_exp', 0)
            if total_monster_hp > 0 and uid in party_scores:
                user_rank = _ratio_to_rank(party_scores[uid] / total_monster_hp)
            else:
                user_rank = fallback_rank
            member_ranks.append(user_rank)
            bonus_exp = round(gained * _RANK_EXP_BONUS.get(user_rank, 0.0)) if (req.is_clear and gained > 0) else 0
            if bonus_exp > 0:
                await member.quests.grant_exp(char, bonus_exp)
            rewards[uid] = SingleReward(
                total=gained,
                exp=gained,
                bonus_exp=bonus_exp,
                final_total_exp=gained + bonus_exp,
                rank=user_rank,
            )
        if members and req.is_clear:
            self.store().save_chars([(member.account, member.char_id) for member, _ in members])

        # Party rank uses the exact same 0..6 (D..SSS) scale as SingleReward.rank.
        # In solo runs sum(party_scores) == member score, so party_rank == user_rank.
        if total_monster_hp > 0 and party_scores:
            party_rank = _ratio_to_rank(sum(party_scores.values()) / total_monster_hp)
        else:
            party_rank = round(sum(member_ranks) / len(member_ranks)) if member_ranks else fallback_rank

        ack = FinishGameAck(
            result=0,
            is_clear=req.is_clear,
            map_code=map_code,
            rewards={uid: reward for uid, reward in rewards.items() if uid},
            rank_first=party_rank,
            rank_final=party_rank,
            box_grade=_RANK_BOX_GRADE.get(party_rank, 0),
            extra_box_cost=0,
        ).encode()
        if run_char_id:
            self._finish_game_reply = (run_char_id, ack)
        await self.transport.send_event(
            event(5018, ack, correlation),
            note=f'finish game ack ({map_code} clear={req.is_clear} rank={party_rank})',
        )
        await self._send_to(
            [member for member, _ in members if member is not self.session],
            event(5018, ack),
            f'finish game (party, {map_code} rank={party_rank})',
        )

    async def _drop_loot(self, source_id, monster, char):
        """Roll itemlooting.lua drops for a kill and announce them with 5064.

        source_id is the 5063 instance id: 0x0078A870 looks the monster up by
        it (0x00859C60) and spawns the drops there. In a party run the drops
        are rolled once, kept in the room and shown to every member; the first
        to pick one up gets it (free for all; random looting is not applied yet).
        """
        codes = loot.roll_drops(getattr(self, 'map_code', ''), monster, int(char.get('char_class', 0)))
        if not codes:
            return
        holder = self._loot_holder()
        entries = []
        for code in codes:
            holder.next_drop_uid += 1
            uid = holder.next_drop_uid
            holder.floor_drops[uid] = code
            count = 1
            money = money_drops().get(code)
            if money:
                # Roll the AR now so the floor label (count, passed to
                # 0x004C8CA0 as the amount) matches what 5114 awards.
                low = int(money[0])
                count = min(0xFFFF, random.randint(low, max(low, int(money[1]))))
                holder.floor_gold[uid] = count
            entries.append(ItemDropEntry(drop_uid=uid, item_id=jhash(code), count=count))
        packet = event(5064, DropItemNot(source_id=source_id, drops=entries).encode())
        for member, _ in self._run_members():
            try:
                await member.transport.send_event(
                    packet, note='drop item not (%s: %s)' % (monster['id'], ', '.join(codes))
                )
            except (ConnectionError, OSError):
                pass

    @packet_handler(ChoiceRewardPartyRankReq)
    async def handle_choice_reward_party_rank(self, correlation, body):
        # eERC_CHOICE_REWARD_PARTYRANK_REQ (0x00780000.c:9280) -> 5091 eERC_CHOICE_REWARD_PARTYRANK_ACK (0x0078D660).
        req = ChoiceRewardPartyRankReq.decode(body)
        char = self._current_char()
        card = self.reward_card
        if (char is None or card is None or card[0] != char['id'] or self.reward_card_claimed
                or not getattr(self, 'in_dungeon', False) or not getattr(self, 'dungeon_cleared', False)):
            await self.reply(ChoiceRewardPartyRankAck(result=results.INVALID_STATE), correlation,
                             note='reward card unavailable')
            return

        char_id, map_code = card
        reward_code, reward_count = loot.roll_dungeon_reward(map_code, int(char.get('char_class', 0)))
        grant = [(reward_code, reward_count)]
        free = free_bag_slots(char)
        if free is not None and free < slots_needed(grant):
            await self.reply(ChoiceRewardPartyRankAck(result=results.INVEN_FULL), correlation,
                             note='reward card refused (bag full)')
            return

        stored_items = add_reward_items(char, grant)
        self.save_char()
        self.reward_card_claimed = True
        ack = ChoiceRewardPartyRankAck(
            char_uid=char_id,
            item_id=jhash(reward_code) & 0xFFFFFFFF,
            count=reward_count,
            items=[Item(owner=UPDATE_OWNER, **item) for item in stored_items],
            gold=char.get('gold', char.get('u66', 0)),
        )
        await self.reply(
            ack, correlation,
            note=f'choice reward partyrank ack (card={req.card_index} item={reward_code} x{reward_count})',
        )

    @packet_handler(5065)
    async def handle_pick_up_item(self, correlation, body):
        # eERC_PICK_UP_ITEM_REQ (prefix + u32 drop uid). 5066 has no client
        # handler; 5068 (global 0x0078AD80) removes the drop and prints the
        # message, and an unsolicited 2037 puts the item into the bag.
        req = PickUpItemReq.decode(body)
        holder = self._loot_holder()
        drops = holder.floor_drops
        code = drops.get(req.drop_uid)
        char = self._current_char()
        self.transport.record('pick-up-item-req', body, drop_uid=req.drop_uid, code=code or '')
        if not code or char is None:
            return
        run = self._run_members()
        room = self._shared_run()
        is_random = room is not None and room.loot_mode == 0 and bool(run)
        money = money_drops().get(code)
        if money:
            await self._pickup_gold_drop(req.drop_uid, code, money, holder, drops, run, is_random, char)
            return
        await self._pickup_item_drop(req.drop_uid, code, drops, run, is_random, char)

    async def _pickup_gold_drop(self, drop_uid, code, money, holder, drops, run, is_random, char):
        # AR drop: 5114 eERC_GET_DROP_AR_NOT (0x00792700) removes the drop
        # (0x0086AFF0) and plays the picker's pickup before it checks the
        # result; only result 0 adds the amount to the *local* player +0x70.
        # The other members get the same notice with a nonzero result.
        if is_random:
            winner, char = random.choice(run)
        else:
            winner = self.session
        others = [member for member, _ in run if member is not winner]
        del drops[drop_uid]
        amount = holder.floor_gold.pop(drop_uid, None)
        if amount is None:
            amount = random.randint(int(money[0]), max(int(money[0]), int(money[1])))
        char['gold'] = char.get('gold', 0) + amount
        char['u66'] = char['gold']
        self.store().save_char(winner.account, winner.char_id)
        ack = GetDropArNot(result=0, gold=amount, drop_id=drop_uid, picker_uid=char['id']).encode()
        await winner.transport.send_event(
            event(5114, ack),
            note='picked AR (%s: +%d, total %d)' % (code, amount, char['gold']),
        )
        seen = GetDropArNot(result=1, gold=amount, drop_id=drop_uid, picker_uid=char['id']).encode()
        await self._send_to(others, event(5114, seen), 'AR picked by %s' % char.get('name'))

    async def _pickup_item_drop(self, drop_uid, code, drops, run, is_random, char):
        needed = slots_needed([(code, 1)])
        if is_random:
            # Random looting: choose randomly among members who have free bag space,
            # so one member's full bag does not block the whole party from looting.
            eligible = [(m, c) for m, c in run
                        if free_bag_slots(c) is None or free_bag_slots(c) >= needed]
            if not eligible:
                await self.send_msg(
                    PickUpItemResultAck(result=results.INVEN_FULL, picker_uid=char['id']),
                    note='pick up item refused (all party bags full, drop %d)' % drop_uid,
                )
                return
            winner, char = random.choice(eligible)
        else:
            winner = self.session
            free = free_bag_slots(char)
            if free is not None and needed > free:
                await self.send_msg(
                    PickUpItemResultAck(result=results.INVEN_FULL, picker_uid=char['id']),
                    note='pick up item refused (bag full, drop %d)' % drop_uid,
                )
                return
        others = [member for member, _ in run if member is not winner]
        del drops[drop_uid]
        stored = add_reward_items(char, [(code, 1)])
        self.store().save_char(winner.account, winner.char_id)
        entry = ItemDropEntry(drop_uid=drop_uid, item_id=jhash(code))
        result = event(5068, PickUpItemResultAck(result=0, picker_uid=char['id'], drop=entry).encode())
        await winner.transport.send_event(result, note='pick up item result (drop %d: %s)' % (drop_uid, code))
        # The bag update (2037) goes to the winner only; 5068 removes the drop for all.
        await self._send_to(others, result, 'item picked by %s' % char.get('name'))
        await winner.transport.send_event(
            event(2037, DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **i) for i in stored]).encode()),
            note='picked item into bag (%s)' % code,
        )
        await winner.quests.check_quest_item_objectives(char)
