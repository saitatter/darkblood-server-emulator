"""Dungeon start, layer transitions, monster kills, loot drops/pickups, death/revive and clear rewards."""
import struct
import time

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import WireError, event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network import results
from darkblood.games.network.messages import (
    ChangeDungeonLayerNot,
    ChoiceRewardPartyRankAck,
    ChoiceRewardPartyRankReq,
    DailyRebirthCoinUseAck,
    DailyRebirthCoinUseReq,
    DropItemNot,
    GameplayDieCharAck,
    GameplayDieCharReq,
    MonsterDeadReq,
    RebirthCoinChangeNot,
    StartGameAck,
    StartGameReq,
)

# The daily-claim sender refuses when owned or received coins reach 3.
DAILY_REBIRTH_COINS = 3


class DungeonCombatHandlers:
    @packet_handler(StartGameReq)
    async def handle_start_game(self, correlation, body):
        try:
            request = StartGameReq.decode(body)
            if not request.map_code or '\x00' in request.map_code:
                raise WireError('Missing or invalid dungeon map code')
        except (WireError, UnicodeDecodeError):
            # The success path assumes the map code resolves to a client property.
            ack = StartGameAck(result=1)
        else:
            participants = [self.session]
            if self.room is not None and self.room.host is self.session and self.room.info.name != '_singleplay':
                participants = [
                    m for m in list(self.room.members)
                    if m is self.session or m.dungeon.room is self.room
                ]
            entry_err = await self._validate_dungeon_entry(request.map_code, participants)
            if entry_err is not None:
                fail_opcode, fail_uid = entry_err
                await self._notify_dungeon_entry_failure(participants, fail_opcode, fail_uid)
                # 0x007880A0 skips duplicate chat output specifically for 0x8A (138, item) and 0x8B (139, limit)
                # because 5136/5222 already displayed the error and re-enabled the gate UI.
                ack = StartGameAck(result=138 if fail_opcode == 5136 else 139)
            else:
                await self._consume_dungeon_entry(request.map_code, participants)
                ack = StartGameAck(map_code=request.map_code)
                self.map_code = request.map_code
                self._reset_dungeon_stats()
                if self.room is not None and self.room.host is self.session:
                    self.room.started = True
                    self.room.dead.clear()
                    self.room.floor_drops.clear()
                    self.room.floor_gold.clear()
        await self.transport.send_event(event(5014, ack.encode(), correlation),
                                        note='start game ack')
        if ack.result == 0:
            self.in_dungeon = True
            self.dungeon_cleared = False
            await self._consume_session_stress(self.session)
        room = self.room
        if ack.result == 0 and room is not None and room.host is self.session and room.info.name != '_singleplay':
            # Shared dungeon, step 1: the members sit in the same gate (5044 at the
            # host's 5043), whose dispatcher handles 5014 (0x007880A0). Start them on
            # the host's map so all clients load it and meet in its relay group.
            for member in list(room.members):
                if member is self.session or member.dungeon.room is not room:
                    continue
                member.dungeon.map_code = request.map_code
                member.dungeon.in_dungeon = True
                member.dungeon.dungeon_cleared = False
                member.dungeon._reset_dungeon_stats()
                try:
                    await member.transport.send_event(event(5014, ack.encode()),
                                                      note='start game (party, %s)' % request.map_code)
                    await self._consume_session_stress(member)
                except (ConnectionError, OSError):
                    pass


    async def _validate_dungeon_entry(self, map_code: str, participants):
        """Enforce Fortress/Special dungeon entry limits and required entry items (#22).

        Returns None when all participants may enter, or (fail_opcode, fail_char_uid)
        where fail_opcode is 5222 (FailDungeonEnterLimitNot) or 5136 (FailDungeonEnterItemNot).
        """
        from darkblood.games.entities.items import DEPOT_CONTAINER, EQUIPPED
        from darkblood.games.game_data.world import dungeon_entry_rule
        from darkblood.games.progression import refresh_dungeon_entry_limits

        rule = dungeon_entry_rule(map_code)
        if not rule:
            return None

        for member in participants:
            char = member.dungeon.current_char()
            if char is None:
                continue
            if refresh_dungeon_entry_limits(char):
                member.dungeon.save_char()
            cid = int(member.active_char_id or char.get('id', 0))

            if rule.get('is_citadel') and int(char.get('citadel_play_count', 0)) <= 0:
                return (5222, cid)

            limit = int(rule.get('enter_limit', 0))
            if limit > 0:
                used = int(char.get('daily_dun_enter_counts', {}).get(map_code, 0))
                if used >= limit:
                    return (5222, cid)

            req_item = rule.get('enter_item_id') or ''
            req_amt = int(rule.get('enter_item_amount', 0))
            if req_item and req_amt > 0:
                owned = sum(
                    int(it.get('count', 1))
                    for it in char.get('items', [])
                    if it.get('code') == req_item and it.get('container') not in (EQUIPPED, DEPOT_CONTAINER)
                )
                if owned < req_amt:
                    return (5136, cid)
        return None

    async def _notify_dungeon_entry_failure(self, participants, fail_opcode: int, fail_char_uid: int):
        from darkblood.games.network.messages.dungeon import (
            FailDungeonEnterItemNot, FailDungeonEnterLimitNot,
        )
        msg = (
            FailDungeonEnterItemNot(fail_char_uid=fail_char_uid)
            if fail_opcode == 5136
            else FailDungeonEnterLimitNot(fail_char_uid=fail_char_uid)
        )
        payload = event(fail_opcode, msg.encode())
        for member in participants:
            try:
                await member.transport.send_event(
                    payload, note=f'dungeon entry fail {fail_opcode} (char={fail_char_uid})',
                )
            except (ConnectionError, OSError):
                pass

    async def _consume_dungeon_entry(self, map_code: str, participants):
        """Decrement Citadel/daily entry counts and consume required entry items on dungeon start."""
        from darkblood.games.entities.items import DEPOT_CONTAINER, EQUIPPED, Item, UPDATE_OWNER
        from darkblood.games.game_data.world import dungeon_entry_rule
        from darkblood.games.network.messages.dungeon import DailyDunEnterCountUpdateNot
        from darkblood.games.network.messages.guild import CitadelPlayCountUpdateNot
        from darkblood.games.network.messages.inventory import DragItemAck

        rule = dungeon_entry_rule(map_code)
        if not rule:
            return

        for member in participants:
            char = member.dungeon.current_char()
            if char is None:
                continue
            changed = False

            if rule.get('is_citadel'):
                remain = max(0, int(char.get('citadel_play_count', 0)) - 1)
                char['citadel_play_count'] = remain
                changed = True
                try:
                    await member.transport.send_event(
                        event(2631, CitadelPlayCountUpdateNot(remain_play_count=remain).encode()),
                        note=f'citadel play count update ({remain})',
                    )
                except (ConnectionError, OSError):
                    pass

            if int(rule.get('enter_limit', 0)) > 0:
                counts = char.setdefault('daily_dun_enter_counts', {})
                counts[map_code] = int(counts.get(map_code, 0)) + 1
                changed = True
                try:
                    await member.transport.send_event(
                        event(2318, DailyDunEnterCountUpdateNot(
                            enter_counts={str(k): int(v) for k, v in counts.items()}
                        ).encode()),
                        note=f'daily dun enter count ({map_code}={counts[map_code]})',
                    )
                except (ConnectionError, OSError):
                    pass

            req_item = rule.get('enter_item_id') or ''
            req_amt = int(rule.get('enter_item_amount', 0))
            if req_item and req_amt > 0:
                items = char.get('items', [])
                remaining_to_take = req_amt
                wire_updates = []
                for it in list(items):
                    if remaining_to_take <= 0:
                        break
                    if it.get('code') != req_item or it.get('container') in (EQUIPPED, DEPOT_CONTAINER):
                        continue
                    stack = int(it.get('count', 1))
                    if stack <= remaining_to_take:
                        remaining_to_take -= stack
                        items.remove(it)
                        wire_updates.append(Item(
                            owner=UPDATE_OWNER, uid=0, code='',
                            container=it.get('container', 1), slot=it.get('slot', 0), count=0,
                        ))
                    else:
                        it['count'] = stack - remaining_to_take
                        remaining_to_take = 0
                        wire_updates.append(Item(owner=UPDATE_OWNER, **it))
                if wire_updates:
                    changed = True
                    try:
                        await member.transport.send_event(
                            event(2037, DragItemAck(result=0, items=wire_updates).encode()),
                            note=f'consume dungeon entry item ({req_item} x{req_amt})',
                        )
                    except (ConnectionError, OSError):
                        pass

            if changed:
                member.dungeon.save_char()


    def _reset_dungeon_stats(self):
        self.dungeon_kill_count = 0
        self.dungeon_score = 0
        self.dungeon_exp = 0
        self.visited_dungeon_layers = set()
        self._finish_game_reply = None
        self.reward_card = None
        self.reward_card_claimed = False


    async def _consume_session_stress(self, session, amount=None):
        from darkblood.games.progression import STRESS_PER_DUNGEON_ROOM, consume_stress, stress_changed_not
        char = session.dungeon.current_char()
        if char is None:
            return
        pts = STRESS_PER_DUNGEON_ROOM if amount is None else amount
        if consume_stress(char, pts):
            session.dungeon.save_char()
            await session.transport.send_event(
                event(2023, stress_changed_not(char).encode()),
                note=f"stress changed not ({char['stress']})",
            )


    @packet_handler(ChangeDungeonLayerNot)
    async def handle_change_dungeon_layer(self, correlation, body):
        # eERC_CHANGE_DUNGEON_LAYER_NOT (sender 0x7900B0): ffffff7f + i64 layer_net_id.
        try:
            msg = ChangeDungeonLayerNot.decode(body)
            # layer_net_id = (jhash(map_code) << 32) | layer_id
            layer_id, map_hash = msg.layer_net_id & 0xFFFFFFFF, (msg.layer_net_id >> 32) & 0xFFFFFFFF
            self.current_dungeon_layer = layer_id
            self.current_dungeon_map_hash = map_hash
            self.transport.record('dungeon-layer', body, layer_id=layer_id, map_hash='0x%08x' % map_hash)
            visited = getattr(self, 'visited_dungeon_layers', None)
            if visited is None:
                visited = set()
                self.visited_dungeon_layers = visited
            if layer_id not in visited:
                visited.add(layer_id)
                # First layer of a run was already charged on 5013 StartGame; charge subsequent rooms.
                if len(visited) > 1:
                    await self._consume_session_stress(self.session)
        except (struct.error, ValueError):
            pass


    @packet_handler(2509)
    async def handle_monster_layer_move(self, correlation, body):
        # eEGS_MONSTER_LAYER_MOVE_NOT: notification without an ACK opcode
        # (2510 is PET_NICK_CHANGE_REQ). Live: ffffff7f 13270006 + two
        # (u32 layer, u32 hash) pairs, e.g. 2 -> 5 in 0x32ADCD46. Recorded only.
        self.transport.record('monster-layer-move', body)


    def _shared_run(self):
        """The party room this session plays a dungeon in with others, or None.

        The host's client runs the monsters: only it sends 5063 and 5017 (live
        2026-11-21), so kills, drops and the result are shared through the room.
        """
        room = self.room
        if room is None or not room.started or room.info.name == '_singleplay':
            return None
        return room


    def _run_members(self):
        """(session, character) of every member in this session's dungeon run."""
        room = self._shared_run()
        if room is None:
            char = self._current_char()
            return [(self.session, char)] if char is not None else []
        code = getattr(self, 'map_code', '')
        out = []
        for member, record in room.members.items():
            if member.dungeon.room is room and getattr(member.dungeon, 'map_code', '') == code:
                char = member.current_char()
                if char is not None:
                    out.append((member, char))
        return out


    def _loot_holder(self):
        """Where the floor drops live: the shared room, or this session alone."""
        room = self._shared_run()
        if room is not None:
            return room
        if not hasattr(self, 'floor_drops'):
            self.floor_drops, self.floor_gold, self.next_drop_uid = {}, {}, 0
        return self


    @packet_handler(MonsterDeadReq)
    async def handle_monster_dead(self, correlation, body):
        # eERC_MONSTER_DEAD_REQ (sender 0x78A690): ffffff7f + u32 monster_id + u32 param.
        try:
            msg = MonsterDeadReq.decode(body)
        except (struct.error, ValueError):
            return
        self.transport.record('monster-dead', body, monster_id=msg.monster_id, param=msg.param)
        room = self._shared_run()
        if room is not None:
            key = (msg.monster_id, msg.param)
            if key in room.dead:
                return  # already credited from another member's report
            room.dead.add(key)
        from darkblood.games.game_data.client_dict import monsters
        info = monsters().get(msg.monster_id)
        exp = round(info['exp']) if info else 0
        mon_target = info['id'] if info else msg.monster_id
        members = self._run_members()
        # Every member of the run gets the kill's EXP, score and quest progress.
        for member, char in members:
            run = member.dungeon
            run.dungeon_kill_count = getattr(run, 'dungeon_kill_count', 0) + 1
            if info:
                run.dungeon_score = getattr(run, 'dungeon_score', 0) + max(1, exp) * 10
            if exp > 0:
                run.dungeon_exp = getattr(run, 'dungeon_exp', 0) + exp
                await member.quests.grant_exp(char, exp)
            await run._update_quest_monsters(mon_target, char)
        if members:
            self.store().save()
        char = self._current_char()
        if char is not None and info:
            await self._drop_loot(msg.param, info, char)


    async def _update_quest_monsters(self, mon_code, char):
        """Advance kill counters for active quests targeting mon_code."""
        from darkblood.games.game_data.client_dict import quest_monster_objectives
        from darkblood.games.network.messages import QuestObjective, QuestUpdateNot
        objectives = quest_monster_objectives().get(mon_code, [])
        if not objectives:
            return
        active = char.get('quests_active', {})
        for q_hash, obj_idx, target_count in objectives:
            q_key = str(q_hash)
            if q_key in active:
                q_record = active[q_key]
                counters = q_record.setdefault('counters', [])
                while len(counters) <= obj_idx:
                    counters.append(0)
                if counters[obj_idx] < target_count:
                    counters[obj_idx] += 1
                    self.store().save()
                    update = QuestUpdateNot(updates=[QuestObjective(q_hash, obj_idx, counters[obj_idx])]).encode()
                    await self.transport.send_event(
                        event(2075, update),
                        note=f'quest update not ({q_key} obj={obj_idx} count={counters[obj_idx]}/{target_count})'
                    )


    async def _update_quest_dungeon_clear(self, map_code, char):
        """Advance dungeon-clear objectives (mission types 2 and 3) on 5017 clear."""
        if not map_code:
            return
        from darkblood.games.game_data.client_dict import dungeon_maps, quest_dungeon_objectives
        from darkblood.games.network.messages import QuestObjective, QuestUpdateNot
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
                    update = QuestUpdateNot(updates=[QuestObjective(q_hash, obj_idx, counters[obj_idx])]).encode()
                    await self.transport.send_event(
                        event(2075, update),
                        note=f'quest dungeon clear not ({q_key} map={map_code} obj={obj_idx} count={counters[obj_idx]}/{target_count})'
                    )


    @packet_handler(5017)
    async def handle_finish_game(self, correlation, body):
        # eERC_FINISH_GAME_REQ (sender 0x007AD380) -> 5018 eERC_FINISH_GAME_ACK (handler 0x007ADB60).
        from darkblood.games.network.messages import FinishGameAck, FinishGameReq, SingleReward
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
        # 5017 sender 0x007AD380 (assert 0x00D00E08):
        #   bVictory << mapPartyScoreList << mapPartyDPS << nTotalMosterHP << vecUnderling << nInner
        # Headless tests may send a bare 1-byte body; parse defensively.
        party_scores = {}
        total_monster_hp = 0
        if req.tail:
            from darkblood.core.serialization.jser import JSerBufferReader
            try:
                r = JSerBufferReader(req.tail)
                party_scores = r.read_tagged_map(JSerBufferReader.read_i64, JSerBufferReader.read_i32)
                r.read_tagged_map(JSerBufferReader.read_i64, JSerBufferReader.read_i32)  # mapPartyDPS
                if r.remaining >= 4:
                    total_monster_hp = r.read_i32()  # nTotalMosterHP
            except (WireError, struct.error, IndexError):
                party_scores = {}
                total_monster_hp = 0

        # Client rank enum (0x007101F0 / 0x00720000:530 Lua_OnChecked_5) and
        # DictMap:LoadDungeonRank (dungeonrank.lua) / LoadDungeonReward (dungeonreward.lua):
        # 0=D (0.0), 1=C (0.1), 2=B (0.225), 3=A (0.375), 4=S (0.625), 5=SS (0.75), 6=SSS (0.9).
        kill_count = getattr(self, 'dungeon_kill_count', 0)
        score = getattr(self, 'dungeon_score', 0)
        if score >= 50000 or kill_count >= 25:
            fallback_rank = 6
        elif score >= 30000 or kill_count >= 20:
            fallback_rank = 5
        elif score >= 15000 or kill_count >= 15:
            fallback_rank = 4
        elif score >= 8000 or kill_count >= 10:
            fallback_rank = 3
        elif score >= 3000 or kill_count >= 5:
            fallback_rank = 2
        elif score >= 1000 or kill_count >= 2:
            fallback_rank = 1
        else:
            fallback_rank = 0

        def _ratio_to_rank(ratio: float) -> int:
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

        # DictDungeonReward:LoadDungeonReward Exp_Reward bonus rates per rank (0=D..6=SSS).
        rank_exp_bonus = {0: 0.065, 1: 0.07, 2: 0.075, 3: 0.10, 4: 0.13, 5: 0.17, 6: 0.20}

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
            bonus_exp = round(gained * rank_exp_bonus.get(user_rank, 0.0)) if (req.is_clear and gained > 0) else 0
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
            self.store().save()

        # Party rank uses the exact same 0..6 (D..SSS) scale as SingleReward.rank.
        # In solo runs sum(party_scores) == member score, so party_rank == user_rank.
        if total_monster_hp > 0 and party_scores:
            party_rank = _ratio_to_rank(sum(party_scores.values()) / total_monster_hp)
        else:
            party_rank = round(sum(member_ranks) / len(member_ranks)) if member_ranks else fallback_rank
        # DictDungeonReward:LoadDungeonReward BoxGrade: D/C/B->0, A->1, S->2, SS->3, SSS->4.
        box_grade = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 3, 6: 4}.get(party_rank, 0)

        ack = FinishGameAck(
            result=0,
            is_clear=req.is_clear,
            map_code=map_code,
            rewards={uid: reward for uid, reward in rewards.items() if uid},
            rank_first=party_rank,
            rank_final=party_rank,
            box_grade=box_grade,
            extra_box_cost=0,
        ).encode()
        if run_char_id:
            self._finish_game_reply = (run_char_id, ack)
        await self.transport.send_event(event(5018, ack, correlation),
                                        note=f'finish game ack ({map_code} clear={req.is_clear} rank={party_rank})')
        await self._send_to([member for member, _ in members if member is not self.session], event(5018, ack),
                            f'finish game (party, {map_code} rank={party_rank})')


    async def _drop_loot(self, source_id, monster, char):
        """Roll itemlooting.lua drops for a kill and announce them with 5064.

        source_id is the 5063 instance id: 0x0078A870 looks the monster up by
        it (0x00859C60) and spawns the drops there. In a party run the drops
        are rolled once, kept in the room and shown to every member; the first
        to pick one up gets it (free for all; random looting is not applied yet).
        """
        from darkblood.games import loot
        from darkblood.games.network.messages import DropItemNot, ItemDropEntry
        codes = loot.roll_drops(getattr(self, 'map_code', ''), monster, int(char.get('char_class', 0)))
        if not codes:
            return
        import random
        from darkblood.games.game_data.client_dict import money_drops
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
                await member.transport.send_event(packet, note='drop item not (%s: %s)' % (monster['id'], ', '.join(codes)))
            except (ConnectionError, OSError):
                pass


    @packet_handler(GameplayDieCharReq)
    async def handle_gameplay_die_char(self, correlation, body):
        # eERC_GAMEPLAY_DIE_CHAR_REQ (writer 0x0078EDF0) -> 5094 (0x0078F090).
        # bDie = 1: echo the client's own UID so the handler opens the revive
        # window (page 0x6B). bDie = 0: revive; spend one rebirth coin and
        # report the remaining count in the trailing u16.
        req = GameplayDieCharReq.decode(body)
        char = self._current_char()
        # Echo the client's own UID unchanged (0x00946570; live: 0, because
        # details +0x1C is 0). Substituting the character id (1) made the
        # death page 0x0055BEF0 look up an unknown user through 0x00966470,
        # get NULL and read [0x10] (live crash at 0x0055BF71, 2026-11-17).
        char_uid = req.char_uid

        coins = 0
        if char is not None:
            coins = int(char.get('rebirth_coins', 3))
            if not req.bDie and coins > 0:
                coins -= 1
                char['rebirth_coins'] = coins
                self.store().save()
        self.die_count = getattr(self, 'die_count', 0) + (1 if req.bDie else 0)

        # On revive (bDie = False), other_uid must match the reviving player UID (0x0055C354)
        # to execute the revival routine (0x00548D80).
        reviver_uid = char_uid if not req.bDie else 0
        # nLayerID/nX/nY place the revived unit (0x0055BEF0). Echo the position
        # the client reported; these fields were once sent as HP values, which
        # revived the player far from where they died.
        ack = GameplayDieCharAck(
            result=0,
            char_uid=char_uid,
            other_uid=reviver_uid,
            bDie=req.bDie,
            layer_id=req.layer_id,
            x=req.x,
            y=req.y,
            party_rebirth_limit=self.die_count,  # previous value kept; meaning not recovered
            rebirth_coin=coins,
        ).encode()
        await self.transport.send_event(event(5094, ack, correlation),
                                        note='gameplay die char ack (die=%d uid=%d coins=%d)' % (req.bDie, char_uid, coins))
        if not req.bDie:
            await self.transport.send_event(event(2286, RebirthCoinChangeNot(result=0, coins=coins).encode()),
                                            note='rebirth coin change not (%d)' % coins)


    @packet_handler(DailyRebirthCoinUseReq)
    async def handle_daily_rebirth_coin_use(self, correlation, body):
        # eEGS_DAILY_REBIRTH_COIN_USE_REQ -> 2449 (0x0079DC70) + 2286 (0x007983B0).
        # Daily claim of free rebirth coins: top the owned coins up to 3, count
        # them as received today, then announce the new total with 2286.
        req = DailyRebirthCoinUseReq.decode(body)
        char = self._current_char()
        if char is None:
            await self.transport.send_event(event(2449, struct.pack('<I', 1), correlation),
                                            note='daily rebirth coin fail (no char)')
            return
        today = time.strftime('%Y-%m-%d')
        if char.get('daily_rebirth_day') != today:
            char['daily_rebirth_day'] = today
            char['daily_rebirth_recv'] = 0
        coins = int(char.get('rebirth_coins', 3))
        received = int(char.get('daily_rebirth_recv', 0))
        granted = max(0, min(DAILY_REBIRTH_COINS - coins, DAILY_REBIRTH_COINS - received))
        coins += granted
        received += granted
        char['rebirth_coins'] = coins
        char['daily_rebirth_recv'] = received
        self.store().save()
        ack = DailyRebirthCoinUseAck(result=0, daily_recv_cnt=received, pcbang_coin_remain=0).encode()
        await self.transport.send_event(event(2449, ack, correlation),
                                        note='daily rebirth coin use ack (pcbang=%d +%d)' % (req.coin_type, granted))
        await self.transport.send_event(event(2286, RebirthCoinChangeNot(result=0, coins=coins).encode()),
                                        note='rebirth coin change not (%d)' % coins)


    @packet_handler(ChoiceRewardPartyRankReq)
    async def handle_choice_reward_party_rank(self, correlation, body):
        # eERC_CHOICE_REWARD_PARTYRANK_REQ (0x00780000.c:9280) -> 5091 eERC_CHOICE_REWARD_PARTYRANK_ACK (0x0078D660).
        from darkblood.games import loot
        from darkblood.games.entities.items import UPDATE_OWNER, Item
        from darkblood.player_management.characters import add_reward_items, free_bag_slots, slots_needed
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
        await self.reply(ack, correlation,
                         note=f'choice reward partyrank ack (card={req.card_index} item={reward_code} x{reward_count})')


    @packet_handler(5065)
    async def handle_pick_up_item(self, correlation, body):
        # eERC_PICK_UP_ITEM_REQ (prefix + u32 drop uid). 5066 has no client
        # handler; 5068 (global 0x0078AD80) removes the drop and prints the
        # message, and an unsolicited 2037 puts the item into the bag.
        from darkblood.games.entities.items import UPDATE_OWNER, Item
        from darkblood.games.network.messages import DragItemAck, ItemDropEntry, PickUpItemReq, PickUpItemResultAck
        from darkblood.player_management.characters import add_reward_items, free_bag_slots, slots_needed
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
        from darkblood.games.game_data.client_dict import money_drops
        money = money_drops().get(code)
        if money:
            # AR drop: 5114 eERC_GET_DROP_AR_NOT (0x00792700) removes the drop
            # (0x0086AFF0) and plays the picker's pickup before it checks the
            # result; only result 0 adds the amount to the *local* player +0x70.
            # The other members get the same notice with a nonzero result.
            import random
            if is_random:
                winner, char = random.choice(run)
            else:
                winner = self.session
            others = [member for member, _ in run if member is not winner]
            from darkblood.games.network.messages import GetDropArNot
            del drops[req.drop_uid]
            amount = holder.floor_gold.pop(req.drop_uid, None)
            if amount is None:
                amount = random.randint(int(money[0]), max(int(money[0]), int(money[1])))
            char['gold'] = char.get('gold', 0) + amount
            char['u66'] = char['gold']
            self.store().save()
            ack = GetDropArNot(result=0, gold=amount, drop_id=req.drop_uid, picker_uid=char['id']).encode()
            await winner.transport.send_event(event(5114, ack),
                                              note='picked AR (%s: +%d, total %d)' % (code, amount, char['gold']))
            seen = GetDropArNot(result=1, gold=amount, drop_id=req.drop_uid, picker_uid=char['id']).encode()
            await self._send_to(others, event(5114, seen), 'AR picked by %s' % char.get('name'))
            return
        needed = slots_needed([(code, 1)])
        if is_random:
            # Random looting: choose randomly among members who have free bag space,
            # so one member's full bag does not block the whole party from looting.
            import random
            eligible = [(m, c) for m, c in run
                        if free_bag_slots(c) is None or free_bag_slots(c) >= needed]
            if not eligible:
                await self.transport.send_event(
                    event(5068, PickUpItemResultAck(result=results.INVEN_FULL, picker_uid=char['id']).encode()),
                    note='pick up item refused (all party bags full, drop %d)' % req.drop_uid)
                return
            winner, char = random.choice(eligible)
        else:
            winner = self.session
            free = free_bag_slots(char)
            if free is not None and needed > free:
                await self.transport.send_event(
                    event(5068, PickUpItemResultAck(result=results.INVEN_FULL, picker_uid=char['id']).encode()),
                    note='pick up item refused (bag full, drop %d)' % req.drop_uid)
                return
        others = [member for member, _ in run if member is not winner]
        del drops[req.drop_uid]
        stored = add_reward_items(char, [(code, 1)])
        self.store().save()
        entry = ItemDropEntry(drop_uid=req.drop_uid, item_id=jhash(code))
        result = event(5068, PickUpItemResultAck(result=0, picker_uid=char['id'], drop=entry).encode())
        await winner.transport.send_event(result, note='pick up item result (drop %d: %s)' % (req.drop_uid, code))
        # The bag update (2037) goes to the winner only; 5068 removes the drop for all.
        await self._send_to(others, result, 'item picked by %s' % char.get('name'))
        await winner.transport.send_event(event(2037, DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **i) for i in stored]).encode()),
                                        note='picked item into bag (%s)' % code)
        await winner.quests.check_quest_item_objectives(char)


    @packet_handler(5363)
    async def handle_gold_goblin_attack(self, correlation, body):
        # eERC_GOLDGOBLIEN_ATTACK_REQ -> 5364 eERC_GOLDGOBLIEN_ATTACK_ACK (0x00784A10).
        from darkblood.games.network.messages import GoldGoblinAttackAck, GoldGoblinAttackReq
        req = GoldGoblinAttackReq.decode(body)
        self.transport.record('gold-goblin-attack-req', body, goblin_id=req.goblin_id, damage=req.damage)
        ack = GoldGoblinAttackAck(result=0).encode()
        await self.transport.send_event(event(5364, ack, correlation), note=f'gold goblin attack ack (goblin={req.goblin_id})')


    @packet_handler(5365)
    async def handle_gold_goblin_dead(self, correlation, body):
        # eERC_GOLDGOBLIEN_DEAD_REQ -> 5366 eERC_GOLDGOBLIEN_DEAD_ACK (0x00784CA0).
        from darkblood.games.network.messages import GoldGoblinDeadAck, GoldGoblinDeadReq
        req = GoldGoblinDeadReq.decode(body)
        self.transport.record('gold-goblin-dead-req', body, goblin_id=req.goblin_id)
        ack = GoldGoblinDeadAck(result=0, goblin_id=req.goblin_id, items=[]).encode()
        await self.transport.send_event(event(5366, ack, correlation), note=f'gold goblin dead ack (goblin={req.goblin_id})')


    @packet_handler(5240)
    async def handle_monster_regen(self, correlation, body):
        # eERC_MONSTER_REGEN_REQ (0x00799150) -> 5241 eERC_MONSTER_REGEN_ACK (0x0074B830).
        from darkblood.games.network.messages.dungeon import MonsterRegenAck, MonsterRegenReq
        req = MonsterRegenReq.decode(body)
        self.transport.record('monster-regen-req', body, mob_id=req.regen_mob_id, slot_id=req.slot_id)
        await self.reply(MonsterRegenAck(result=0), correlation,
                         note=f'monster regen ack (mob={req.regen_mob_id} slot={req.slot_id})')


    @packet_handler(5342)
    async def handle_treasure_find(self, correlation, body):
        # eERC_TREASURE_FIND_REQ (0x007A4580) -> 5343 eERC_TREASURE_FIND_ACK (0x00782A80).
        from darkblood.games.network.messages.dungeon import TreasureFindAck, TreasureFindReq
        req = TreasureFindReq.decode(body)
        self.transport.record('treasure-find-req', body, treasure_id=req.treasure_id)
        await self.reply(TreasureFindAck(result=0, items=[], success=True), correlation,
                         note=f'treasure find ack (id={req.treasure_id})')

