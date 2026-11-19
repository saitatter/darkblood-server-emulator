import struct
import time
from dataclasses import dataclass, field

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import WireError, event, read_varuint
from darkblood.frontend.relay import relay_address
from darkblood.games.entities.character import Character
from darkblood.games.network.messages import (
    ActiveWarFlagReq,
    ChangeDungeonLayerNot,
    ChangeMapCodeAck,
    ChangeTeamAck,
    ChangeTeamReq,
    ChoiceRewardPartyRankAck,
    ChoiceRewardPartyRankReq,
    CreateRoomAck,
    DailyRebirthCoinUseAck,
    DailyRebirthCoinUseReq,
    DropItemNot,
    GameplayDieCharAck,
    GameplayDieCharReq,
    GuideBeginnerUpdateReq,
    JoinRoomAck,
    JoinRoomReq,
    LeaveRoomAck,
    MonsterDeadReq,
    PartyAcceptInviteAck,
    PartyAcceptInviteReq,
    PartyInviteAck,
    PartyInviteReq,
    RebirthCoinChangeNot,
    RoomInfo,
    RoomInfoListAck,
    RoomMember,
    RoomMemberJoinedNot,
    RoomMemberLeftNot,
    SelectDungeonAck,
    StartGameAck,
    StartGameReq,
)
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.network import results

# The daily-claim sender refuses when owned or received coins reach 3.
DAILY_REBIRTH_COINS = 3


@dataclass
class DungeonRoom:
    info: RoomInfo
    host: object
    members: dict = field(default_factory=dict)
    started: bool = False


class DungeonHandlers(BaseDomainService):
    """Rooms, dungeon gate, map code and game start."""

    def __init__(self, session):
        super().__init__(session)
        self.room = None

    async def on_2010(self, correlation, body):
        # eEGS_GET_ROOMINFOLIST_REQ (sender 0x7AB140) -> 2011: no open rooms.
        await self.transport.send_event(event(2011, RoomInfoListAck().encode(), correlation),
                                        note='room info list ack')

    async def on_5001(self, correlation, body):
        # eERC_CREATE_ROOM_REQ (writer 0x58B060): wstring name, i32, i32, i16,
        # i16 (observed: "_singleplay", -1, -1, -1, 1) -> 5002 CREATE_ROOM_ACK.
        name, a, b, c, d = '', -1, -1, -1, 1
        try:
            length, offset = read_varuint(body, 0)
            name = body[offset:offset + length].decode('utf-16le')
            a, b, c, d = struct.unpack_from('<iihh', body, offset + length)
        except (WireError, struct.error, UnicodeDecodeError):
            pass
        char = self.current_char()
        if char is None:
            await self.transport.send_event(event(5002, CreateRoomAck(result=results.NO_EXIST_CHAR).encode(), correlation),
                                            note='create room refused (no character)')
            return
        await self.leave_room()
        server = self.transport.server
        info = RoomInfo(room_id=next(server.room_ids), name=name, req_a=a, req_b=b, req_c=c, req_d=d,
                        host_uid=char['id'])
        self.room = DungeonRoom(info, self.session, {self.session: char})
        server.dungeon_rooms[info.room_id] = self.room
        ack = CreateRoomAck(room=info, relay=relay_address())
        await self.transport.send_event(event(5002, ack.encode(), correlation),
                                        note='create room ack (%s)' % name)

    async def on_5003(self, correlation, body):
        try:
            req = JoinRoomReq.decode(body)
        except WireError:
            room = None
        else:
            room = self.transport.server.dungeon_rooms.get(req.room_id)
        char = self.current_char()
        result = results.OK
        if char is None:
            result = results.NO_EXIST_CHAR
        elif room is None or room.info.name == '_singleplay':
            result = results.ROOM_NOT_EXISTS
        elif room is not self.room:
            if self.room is not None or any(record['id'] == char['id'] for record in room.members.values()):
                result = results.INVALID_STATE
            elif room.started:
                result = results.ALREADY_PLAY_GAME
            elif len(room.members) >= 4:
                result = results.JOIN_FAIL_ROOM_FULL
        if result:
            await self.transport.send_event(event(5004, JoinRoomAck(result=result).encode(), correlation),
                                            note='join room refused (%d)' % result)
            return

        is_new = self.room is not room
        peers = [member for member in room.members if member is not self.session]
        room.members[self.session] = char
        self.room = room
        roster = [RoomMember(Character.from_dict(record)) for record in room.members.values()]
        ack = JoinRoomAck(room=room.info, members=roster, relay=relay_address())
        await self.transport.send_event(event(5004, ack.encode(), correlation), note='join room ack')
        if is_new and self.room is room:
            joined = RoomMemberJoinedNot(RoomMember(Character.from_dict(char)))
            await self._notify_room(room, peers, event(5035, joined.encode()), 'room member joined')

    async def _notify_room(self, room, peers, packet, note):
        for peer in peers:
            if peer.dungeon.room is room:
                try:
                    await peer.transport.send_event(packet, note=note)
                except (ConnectionError, OSError):
                    continue

    async def leave_room(self):
        room = self.room
        if room is None:
            return
        self.room = None
        char = room.members.pop(self.session)
        notice = event(5036, RoomMemberLeftNot(char['id']).encode())
        peers = list(room.members)
        if self.session is room.host:
            self.transport.server.dungeon_rooms.pop(room.info.room_id, None)
        await self._notify_room(room, peers, notice, 'room member left')
        if self.session is room.host:
            for peer in peers:
                if peer.dungeon.room is room:
                    peer.dungeon.room = None
            room.members.clear()

    async def on_5043(self, correlation, body):
        # eERC_SELECT_DUNGEON_REQ (sender 0x7AC1C0), observed body:
        # ffffff7f + J-wstring gate id ("Act1_G1") -> 5044.
        gate = ''
        try:
            length, offset = read_varuint(body, 4)
            gate = body[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        from darkblood.games.game_data.client_dict import gate_dungeons
        dungeons = gate_dungeons().get(gate, [])
        if not dungeons:
            dungeons = [f"{gate}_A1", f"{gate}_A2", f"{gate}_A3", f"{gate}_A4"]
        dun_history = {d: (d, 3, 1) for d in dungeons}
        ack = SelectDungeonAck(gate_id=gate, dun_history=dun_history).encode()
        await self.transport.send_event(event(5044, ack, correlation),
                                        note=f'select dungeon ack ({gate}, {len(dun_history)} dungeons unlocked)')

    async def on_5009(self, correlation, body):
        # eERC_CHANGE_MAPCODE_REQ (sender 0x7AD680), observed body: ffffff7f
        # + J-wstring map code ("Act1_G1_A10") + bool -> 5010, consumed by
        # JAppStateDungeonGate vf20 -> 0x6D4A00 (only in app state 8).
        code, flag = '', False
        try:
            length, offset = read_varuint(body, 4)
            code = body[offset:offset + length].decode('utf-16le')
            flag = body[offset + length:offset + length + 1] == bytes([1])
        except (WireError, UnicodeDecodeError):
            pass
        self.map_code = code
        ack = ChangeMapCodeAck(map_code=code, flag=flag).encode()
        await self.transport.send_event(event(5010, ack, correlation),
                                        note='change mapcode ack (%s)' % code)

    async def on_5013(self, correlation, body):
        try:
            request = StartGameReq.decode(body)
        except (WireError, UnicodeDecodeError):
            # The success path assumes the map code resolves to a client property.
            ack = StartGameAck(result=1)
        else:
            ack = StartGameAck(map_code=request.map_code)
            if self.room is not None and self.room.host is self.session:
                self.room.started = True
        await self.transport.send_event(event(5014, ack.encode(), correlation),
                                        note='start game ack')

    async def on_5095(self, correlation, body):
        # eERC_CHANGE_DUNGEON_LAYER_NOT (sender 0x7900B0): ffffff7f + i64 layer_net_id.
        try:
            msg = ChangeDungeonLayerNot.decode(body)
            self.current_dungeon_layer = msg.layer_id
            self.current_dungeon_map_hash = msg.map_hash
            self.transport.record('dungeon-layer', body, layer_id=msg.layer_id, map_hash='0x%08x' % msg.map_hash)
        except (struct.error, ValueError):
            pass

    async def on_2509(self, correlation, body):
        # eEGS_MONSTER_LAYER_MOVE_NOT: notification without an ACK opcode
        # (2510 is PET_NICK_CHANGE_REQ). Live: ffffff7f 13270006 + two
        # (u32 layer, u32 hash) pairs, e.g. 2 -> 5 in 0x32ADCD46. Recorded only.
        self.transport.record('monster-layer-move', body)

    async def on_2422(self, correlation, body):
        # eEGS_ACTIVE_WARFLAG_REQ (sender 0x79C300): ffffff7f + u32 war_flag_id.
        try:
            msg = ActiveWarFlagReq.decode(body)
            self.active_war_flag = msg.war_flag_id
            self.transport.record('active-warflag', body, war_flag_id=msg.war_flag_id)
        except (struct.error, ValueError):
            pass

    async def on_2358(self, correlation, body):
        # eEGS_GUIDE_BEGINNER_UPDATE_REQ (sender 0x79A3B0): ffffff7f + vector<u32> guide_ids.
        try:
            msg = GuideBeginnerUpdateReq.decode(body)
            self.transport.record('guide-beginner-update', body, guide_ids=msg.guide_ids)
        except (struct.error, ValueError):
            pass

    async def on_5063(self, correlation, body):
        # eERC_MONSTER_DEAD_REQ (sender 0x78A690): ffffff7f + u32 monster_id + u32 param.
        try:
            msg = MonsterDeadReq.decode(body)
        except (struct.error, ValueError):
            return
        self.transport.record('monster-dead', body, monster_id=msg.monster_id, param=msg.param)
        self.dungeon_kill_count = getattr(self, 'dungeon_kill_count', 0) + 1
        from darkblood.games.game_data.client_dict import monsters
        info = monsters().get(msg.monster_id)
        exp = round(info['exp']) if info else 0
        if info:
            self.dungeon_score = getattr(self, 'dungeon_score', 0) + max(1, exp) * 10
        char = self._current_char()
        if exp > 0 and char is not None:
            await self.session.quests.grant_exp(char, exp)
            self.store().save()
        if char is not None:
            if info:
                await self._drop_loot(msg.param, info, char)
            mon_target = info['id'] if info else msg.monster_id
            await self._update_quest_monsters(mon_target, char)

    async def _update_quest_monsters(self, mon_code, char):
        """Advance kill counters for active quests targeting mon_code."""
        from darkblood.games.game_data.client_dict import quest_monster_objectives
        from darkblood.games.network.messages import QuestUpdateNot
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
                    update = QuestUpdateNot(updates=[(q_hash, obj_idx, counters[obj_idx])]).encode()
                    await self.transport.send_event(
                        event(2075, update),
                        note=f'quest update not ({q_key} obj={obj_idx} count={counters[obj_idx]}/{target_count})'
                    )

    async def on_5017(self, correlation, body):
        # eERC_FINISH_GAME_REQ (sender 0x007AD380) -> 5018 eERC_FINISH_GAME_ACK (handler 0x007ADB60).
        from darkblood.games.network.messages import FinishGameAck, FinishGameReq
        req = FinishGameReq.decode(body)
        self.transport.record('finish-game-req', body, is_clear=req.is_clear)
        map_code = getattr(self, 'map_code', '')
        char = self.current_char()
        # The player's UID is the character id (2007 details +0x1C, copied to
        # player +0x10 by 0x0095A150). Characters have no 'char_uid' key, so
        # mapSingleReward used to go out empty and the result screen froze.
        char_uid = char.get('id', 0) if char else 0

        kill_count = getattr(self, 'dungeon_kill_count', 0)
        max_combo = getattr(self, 'dungeon_max_combo', 0)
        score = getattr(self, 'dungeon_score', 0)
        clear_time = getattr(self, 'dungeon_clear_time', 0)
        damage_dealt = getattr(self, 'dungeon_damage_dealt', 0)

        # Ensure realistic stats for gauge and ranking calculations
        if kill_count > 0:
            if score == 0:
                score = kill_count * 1250
            if max_combo == 0:
                max_combo = min(50, max(5, kill_count * 3))
            if clear_time == 0:
                clear_time = max(20, kill_count * 8)
            if damage_dealt == 0:
                damage_dealt = kill_count * 450
        else:
            if score == 0:
                score = 10000
            if max_combo == 0:
                max_combo = 10
            if clear_time == 0:
                clear_time = 35
            if damage_dealt == 0:
                damage_dealt = 2500

        # Ranks: 1=SSS, 2=SS, 3=S, 4=A, 5=B, 6=C, 7=D
        if score >= 50000 or kill_count >= 20:
            rank = 1
            box_grade = 4
        elif score >= 20000 or kill_count >= 10:
            rank = 2
            box_grade = 3
        elif score >= 5000 or kill_count >= 5:
            rank = 3
            box_grade = 2
        else:
            rank = 4
            box_grade = 1

        ack = FinishGameAck(
            result=0,
            is_clear=req.is_clear,
            map_code=map_code,
            char_uid=char_uid,
            rank_first=rank,
            rank_final=rank,
            box_grade=box_grade,
            extra_box_cost=0,
            score=score,
            kill_count=kill_count,
            max_combo=max_combo,
            clear_time=clear_time,
            damage_dealt=damage_dealt,
        ).encode()
        await self.transport.send_event(event(5018, ack, correlation),
                                        note=f'finish game ack ({map_code} clear={req.is_clear} rank={rank})')

    async def _drop_loot(self, source_id, monster, char):
        """Roll itemlooting.lua drops for a kill and announce them with 5064.

        source_id is the 5063 instance id: 0x0078A870 looks the monster up by
        it (0x00859C60) and spawns the drops there. Drop uids are kept per
        session until picked up (5065).
        """
        from darkblood.games import loot
        from darkblood.games.network.messages import DropItemNot, ItemDropEntry
        codes = loot.roll_drops(getattr(self, 'map_code', ''), monster, int(char.get('char_class', 0)))
        if not codes:
            return
        drops = self.__dict__.setdefault('floor_drops', {})
        entries = []
        for code in codes:
            self.next_drop_uid = getattr(self, 'next_drop_uid', 0) + 1
            drops[self.next_drop_uid] = code
            entries.append(ItemDropEntry(drop_uid=self.next_drop_uid, item_id=jhash(code)))
        await self.transport.send_event(event(5064, DropItemNot(source_id=source_id, drops=entries).encode()),
                                        note='drop item not (%s: %s)' % (monster['id'], ', '.join(codes)))

    def _current_char(self):
        char = self.current_char()
        return char

    async def on_5093(self, correlation, body):
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
        max_hp = req.max_hp if req.max_hp > 0 else 1000
        cur_hp = req.cur_hp if req.bDie else max_hp

        ack = GameplayDieCharAck(
            result=0,
            char_uid=char_uid,
            other_uid=reviver_uid,
            bDie=req.bDie,
            damage=req.damage,
            cur_hp=cur_hp,
            max_hp=max_hp,
            die_count=self.die_count,
            rebirth_coin=coins,
        ).encode()
        await self.transport.send_event(event(5094, ack, correlation),
                                        note='gameplay die char ack (die=%d uid=%d coins=%d)' % (req.bDie, char_uid, coins))
        if not req.bDie:
            await self.transport.send_event(event(2286, RebirthCoinChangeNot(result=0, coins=coins).encode()),
                                            note='rebirth coin change not (%d)' % coins)

    async def on_2448(self, correlation, body):
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

    async def on_5005(self, correlation, body):
        # eERC_LEAVE_ROOM_REQ (0x0058B240) -> 5006 eERC_LEAVE_ROOM_ACK (0x00598A00).
        # Acknowledges leaving game room before eERC_BACK_TO_SQUARE_REQ (5045).
        await self.leave_room()
        ack = LeaveRoomAck(result=0).encode()
        await self.transport.send_event(event(5006, ack, correlation), note='leave room ack')

    async def on_5090(self, correlation, body):
        # eERC_CHOICE_REWARD_PARTYRANK_REQ (0x00780000.c:9280) -> 5091 eERC_CHOICE_REWARD_PARTYRANK_ACK (0x0078D660).
        req = ChoiceRewardPartyRankReq.decode(body)
        char = self._current_char()
        char_id = self.char_id
        reward_code = 'Ihppa0001'
        item_id = jhash(reward_code) & 0xFFFFFFFF
        from darkblood.games.entities.items import UPDATE_OWNER, Item
        from darkblood.player_management.characters import add_reward_items
        stored_items = []
        if char:
            stored_items = add_reward_items(char, [(reward_code, 1)])
            self.store().save()
        reward_item = [Item(owner=UPDATE_OWNER, **i) for i in stored_items] if stored_items else []
        gold = char.get('gold', char.get('u66', 0)) if char else 0
        ack = ChoiceRewardPartyRankAck(
            result=0,
            char_uid=char_id,
            reward_uid=1,
            item_id=item_id,
            count=1,
            drop_type=0,
            box_type=0,
            box_cost=0,
            items=reward_item,
            gold=gold,
        ).encode()
        await self.transport.send_event(event(5091, ack, correlation),
                                        note=f'choice reward partyrank ack (card={req.card_index} item={reward_code})')

    async def on_5015(self, correlation, body):
        # eERC_CHANGE_TEAM_REQ -> 5016 eERC_CHANGE_TEAM_ACK.
        req = ChangeTeamReq.decode(body)
        self.transport.record('change-team-req', body, team_id=req.team_id)
        ack = ChangeTeamAck(result=0, team_id=req.team_id).encode()
        await self.transport.send_event(event(5016, ack, correlation), note=f'change team ack (team={req.team_id})')

    async def on_5065(self, correlation, body):
        # eERC_PICK_UP_ITEM_REQ (prefix + u32 drop uid). 5066 has no client
        # handler; 5068 (global 0x0078AD80) removes the drop and prints the
        # message, and an unsolicited 2037 puts the item into the bag.
        from darkblood.games.entities.items import UPDATE_OWNER, Item
        from darkblood.games.network.messages import DragItemAck, ItemDropEntry, PickUpItemReq, PickUpItemResultAck
        from darkblood.player_management.characters import add_reward_items, free_bag_slots, slots_needed
        req = PickUpItemReq.decode(body)
        drops = getattr(self, 'floor_drops', {})
        code = drops.get(req.drop_uid)
        char = self._current_char()
        self.transport.record('pick-up-item-req', body, drop_uid=req.drop_uid, code=code or '')
        if not code or char is None:
            return
        from darkblood.games.game_data.client_dict import money_drops
        money = money_drops().get(code)
        if money:
            # AR drop: 5114 eERC_GET_DROP_AR_NOT (0x00792700) adds the amount
            # to player +0x70, removes the drop (0x0086AFF0) and prints it.
            import random
            from darkblood.games.network.messages import GetDropArNot
            del drops[req.drop_uid]
            amount = random.randint(int(money[0]), max(int(money[0]), int(money[1])))
            char['gold'] = char.get('gold', 0) + amount
            char['u66'] = char['gold']
            self.store().save()
            ack = GetDropArNot(result=0, gold=amount, drop_id=req.drop_uid, picker_uid=char['id']).encode()
            await self.transport.send_event(event(5114, ack),
                                            note='picked AR (%s: +%d, total %d)' % (code, amount, char['gold']))
            return
        free = free_bag_slots(char)
        if free is not None and slots_needed([(code, 1)]) > free:
            await self.transport.send_event(event(5068, PickUpItemResultAck(result=results.INVEN_FULL, picker_uid=char['id']).encode()),
                                            note='pick up item refused (bag full, drop %d)' % req.drop_uid)
            return
        del drops[req.drop_uid]
        stored = add_reward_items(char, [(code, 1)])
        self.store().save()
        entry = ItemDropEntry(drop_uid=req.drop_uid, item_id=jhash(code))
        await self.transport.send_event(event(5068, PickUpItemResultAck(result=0, picker_uid=char['id'], drop=entry).encode()),
                                        note='pick up item result (drop %d: %s)' % (req.drop_uid, code))
        await self.transport.send_event(event(2037, DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **i) for i in stored]).encode()),
                                        note='picked item into bag (%s)' % code)
        if hasattr(self, 'check_quest_item_objectives'):
            await self.check_quest_item_objectives(char)

    async def on_5363(self, correlation, body):
        # eERC_GOLDGOBLIEN_ATTACK_REQ -> 5364 eERC_GOLDGOBLIEN_ATTACK_ACK (0x00784A10).
        from darkblood.games.network.messages import GoldGoblinAttackAck, GoldGoblinAttackReq
        req = GoldGoblinAttackReq.decode(body)
        self.transport.record('gold-goblin-attack-req', body, goblin_id=req.goblin_id, damage=req.damage)
        ack = GoldGoblinAttackAck(result=0).encode()
        await self.transport.send_event(event(5364, ack, correlation), note=f'gold goblin attack ack (goblin={req.goblin_id})')

    async def on_5365(self, correlation, body):
        # eERC_GOLDGOBLIEN_DEAD_REQ -> 5366 eERC_GOLDGOBLIEN_DEAD_ACK (0x00784CA0).
        from darkblood.games.network.messages import GoldGoblinDeadAck, GoldGoblinDeadReq
        req = GoldGoblinDeadReq.decode(body)
        self.transport.record('gold-goblin-dead-req', body, goblin_id=req.goblin_id)
        ack = GoldGoblinDeadAck(result=0, goblin_id=req.goblin_id, items=[]).encode()
        await self.transport.send_event(event(5366, ack, correlation), note=f'gold goblin dead ack (goblin={req.goblin_id})')


