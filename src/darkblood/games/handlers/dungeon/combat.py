"""Dungeon layer transitions, monster kills, death/revive, rebirth coins, and combat events."""
import struct

from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.game_data.client_dict import monsters, quest_monster_objectives
from darkblood.games.network.messages import (
    ChangeDungeonLayerNot,
    DailyRebirthCoinUseAck,
    DailyRebirthCoinUseReq,
    GameplayDieCharAck,
    GameplayDieCharReq,
    GoldGoblinAttackAck,
    GoldGoblinAttackReq,
    GoldGoblinDeadAck,
    GoldGoblinDeadReq,
    MonsterDeadReq,
    QuestObjective,
    QuestUpdateNot,
    RebirthCoinChangeNot,
    RoulettePointInsertNot,
)
from darkblood.games.network.messages.dungeon import (
    MonsterRegenAck,
    MonsterRegenReq,
    TreasureFindAck,
    TreasureFindReq,
)

from darkblood.games.progression import refresh_daily_rebirth


# The daily-claim sender refuses when owned or received coins reach 3.
DAILY_REBIRTH_COINS = 3


class DungeonCombatHandlers:
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
            visited = self.visited_dungeon_layers
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
        code = self.map_code
        out = []
        for member in room.members:
            if member.dungeon.room is room and member.dungeon.map_code == code:
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
        info = monsters().get(msg.monster_id)
        exp = round(info['exp']) if info else 0
        mon_target = info['id'] if info else msg.monster_id
        members = self._run_members()
        # Every member of the run gets the kill's EXP, score, roulette points and quest progress.
        from darkblood.games.handlers.commerce.stores import add_roulette_points
        from darkblood.games.handlers.pets.pets import grant_pet_exp
        for member, char in members:
            run = member.dungeon
            run.dungeon_kill_count = getattr(run, 'dungeon_kill_count', 0) + 1
            if info:
                run.dungeon_score = getattr(run, 'dungeon_score', 0) + max(1, exp) * 10
            if exp > 0:
                run.dungeon_exp = getattr(run, 'dungeon_exp', 0) + exp
                await member.quests.grant_exp(char, exp)
                await grant_pet_exp(member, char, exp)
            new_pts = add_roulette_points(char, 0)
            await member.transport.send_event(
                event(2389, RoulettePointInsertNot(roulette_points=new_pts).encode()),
                note=f'roulette point not (kill, pts={new_pts:.1f})',
            )
            await run._update_quest_monsters(mon_target, char)
        if members:
            self.store().save_chars([(member.account, member.char_id) for member, _ in members])
        char = self._current_char()
        if char is not None and info:
            await self._drop_loot(msg.param, info, char)

    async def _update_quest_monsters(self, mon_code, char):
        """Advance kill counters for active quests targeting mon_code."""
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
                    self.save_char()
                    await self.send_msg(
                        QuestUpdateNot(updates=[QuestObjective(q_hash, obj_idx, counters[obj_idx])]),
                        note=f'quest update not ({q_key} obj={obj_idx} count={counters[obj_idx]}/{target_count})',
                    )

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
                self.save_char()
        self.die_count = self.die_count + (1 if req.bDie else 0)

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
        )
        await self.reply(
            ack, correlation,
            note='gameplay die char ack (die=%d uid=%d coins=%d)' % (req.bDie, char_uid, coins),
        )
        if not req.bDie:
            await self.send_msg(
                RebirthCoinChangeNot(result=0, coins=coins),
                note='rebirth coin change not (%d)' % coins,
            )

    @packet_handler(DailyRebirthCoinUseReq)
    async def handle_daily_rebirth_coin_use(self, correlation, body):
        # eEGS_DAILY_REBIRTH_COIN_USE_REQ -> 2449 (0x0079DC70) + 2286 (0x007983B0).
        # Daily claim of free rebirth coins: top the owned coins up to 3, count
        # them as received today, then announce the new total with 2286.
        req = DailyRebirthCoinUseReq.decode(body)
        char = self._current_char()
        if char is None:
            await self.reply(DailyRebirthCoinUseAck(result=results.NO_EXIST_CHAR), correlation,
                             note='daily rebirth coin fail (no char)')
            return
        refresh_daily_rebirth(char)
        coins = int(char.get('rebirth_coins', 3))
        received = int(char.get('daily_rebirth_recv', 0))
        granted = max(0, min(DAILY_REBIRTH_COINS - coins, DAILY_REBIRTH_COINS - received))
        coins += granted
        received += granted
        char['rebirth_coins'] = coins
        char['daily_rebirth_recv'] = received
        self.save_char()
        await self.reply(
            DailyRebirthCoinUseAck(result=0, daily_recv_cnt=received, pcbang_coin_remain=0),
            correlation,
            note='daily rebirth coin use ack (pcbang=%d +%d)' % (req.coin_type, granted),
        )
        await self.send_msg(
            RebirthCoinChangeNot(result=0, coins=coins),
            note='rebirth coin change not (%d)' % coins,
        )

    @packet_handler(5363)
    async def handle_gold_goblin_attack(self, correlation, body):
        # eERC_GOLDGOBLIEN_ATTACK_REQ -> 5364 eERC_GOLDGOBLIEN_ATTACK_ACK (0x00784A10).
        req = GoldGoblinAttackReq.decode(body)
        self.transport.record('gold-goblin-attack-req', body, goblin_id=req.goblin_id, damage=req.damage)
        await self.reply(GoldGoblinAttackAck(result=0), correlation,
                         note=f'gold goblin attack ack (goblin={req.goblin_id})')

    @packet_handler(5365)
    async def handle_gold_goblin_dead(self, correlation, body):
        # eERC_GOLDGOBLIEN_DEAD_REQ -> 5366 eERC_GOLDGOBLIEN_DEAD_ACK (0x00784CA0).
        req = GoldGoblinDeadReq.decode(body)
        self.transport.record('gold-goblin-dead-req', body, goblin_id=req.goblin_id)
        await self.reply(GoldGoblinDeadAck(result=0, goblin_id=req.goblin_id, items=[]), correlation,
                         note=f'gold goblin dead ack (goblin={req.goblin_id})')

    @packet_handler(5240)
    async def handle_monster_regen(self, correlation, body):
        # eERC_MONSTER_REGEN_REQ (0x00799150) -> 5241 eERC_MONSTER_REGEN_ACK (0x0074B830).
        req = MonsterRegenReq.decode(body)
        self.transport.record('monster-regen-req', body, mob_id=req.regen_mob_id, slot_id=req.slot_id)
        await self.reply(MonsterRegenAck(result=0), correlation,
                         note=f'monster regen ack (mob={req.regen_mob_id} slot={req.slot_id})')

    @packet_handler(5342)
    async def handle_treasure_find(self, correlation, body):
        # eERC_TREASURE_FIND_REQ (0x007A4580) -> 5343 eERC_TREASURE_FIND_ACK (0x00782A80).
        req = TreasureFindReq.decode(body)
        self.transport.record('treasure-find-req', body, treasure_id=req.treasure_id)
        await self.reply(TreasureFindAck(result=0, items=[], success=True), correlation,
                         note=f'treasure find ack (id={req.treasure_id})')
