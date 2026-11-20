"""Quest start/complete, failure, abandon, and tutorial quest handlers."""
import struct

from darkblood.core.serialization.jser import WireError, event, read_varuint
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data.client_dict import char_level_stat
from darkblood.games.missions.quests import ActiveQuest
from darkblood.games.network.messages import (
    ChangeExpNot,
    LevelUpNot,
    QuestCompleteAck,
    QuestFailAck,
    QuestFailReq,
    QuestGiveupAck,
    QuestGiveupReq,
    QuestStartAck,
    TutorialQuestStartAck,
)
from darkblood.games.progression import MAX_LEVEL, advance_level


def _quest_id_after_tag(body: bytes) -> int:
    """2073/2346 bodies: J-wstring tag, then u32 quest id (0 if malformed)."""
    try:
        length, offset = read_varuint(body, 0)
        return struct.unpack_from('<I', body, offset + length)[0]
    except (WireError, struct.error):
        return 0


from darkblood.games.handlers.base import BaseDomainService


class QuestHandlers(BaseDomainService):
    """Quest start/complete and tutorial quests."""

    async def handle_quest_start(self, correlation: int, body: bytes):
        """Opcode 2073 (eEGS_QUEST_START_REQ) -> 2074 (eEGS_QUEST_START_ACK).

        Client dispatcher: 0x00659F00 -> 0x00659790.
        Decodes target quest ID hash, assigns new active quest UID, initializes
        objective counters, and persists in character's active quest list.
        """
        quest_id = _quest_id_after_tag(body)
        char = self.store().get(self.account, self.char_id)
        is_new = bool(char) and str(quest_id) not in char.get('quests_active', {})
        uid = self._activate_quest(quest_id)
        ack = QuestStartAck(quest_id=quest_id, quest_uid=uid).encode()
        await self.transport.send_event(event(2074, ack, correlation),
                                        note='quest start ack (%08x)' % quest_id)
        if is_new:
            await self._give_offer_items(char, quest_id)
        await self.check_quest_item_objectives(char)

    async def _give_offer_items(self, char, quest_id):
        """Hand over the quest's OfferItemG items (e.g. a letter to deliver).

        2074's own item vector (reader 0x4B9210) is not recovered, so the items
        go out as an unsolicited 2037 like floor pick-ups.
        """
        from darkblood.games.game_data.client_dict import item_groups, quests
        from darkblood.games.network.messages import DragItemAck
        from darkblood.player_management.characters import add_reward_items
        group = (quests().get(quest_id) or {}).get('offer')
        offered = [(code, count) for code, _, count in item_groups().get(group or '', [])]
        if not offered:
            return
        stored = add_reward_items(char, offered)
        self.store().save()
        await self.transport.send_event(
            event(2037, DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **i) for i in stored]).encode()),
            note='quest offer items (%s: %s)' % (group, ', '.join(c for c, _ in offered)))
        await self.check_quest_item_objectives(char)

    async def check_quest_item_objectives(self, char=None):
        """Check active quests for item collection objectives (MissionType 1).

        Compares inventory quantities against quest targets, updates active quest
        objective counters, saves to character store, and dispatches Opcode 2075
        (eEGS_QUEST_UPDATE_NOT) for changed counters.
        """
        if char is None:
            char = self.current_char()
        if not char:
            return
        from darkblood.games.game_data.client_dict import quest_item_objectives, quest_mission_counts
        from darkblood.games.network.messages import QuestUpdateNot
        active = char.get('quests_active', {})
        if not active:
            return
        item_counts = {}
        for it in char.get('items', []):
            code = it.get('code')
            cnt = it.get('count', 1)
            item_counts[code] = item_counts.get(code, 0) + cnt

        obj_map = quest_item_objectives()
        mission_counts = quest_mission_counts()
        updates = []
        for q_str, record in active.items():
            try:
                qid = int(q_str)
            except ValueError:
                continue
            counters = record.setdefault('counters', [])
            needed = mission_counts.get(qid, 0)
            while len(counters) < needed:
                counters.append(0)
            for item_code, q_list in obj_map.items():
                cur_count = item_counts.get(item_code, 0)
                for target_qid, obj_idx, target_val in q_list:
                    if target_qid == qid:
                        while len(counters) <= obj_idx:
                            counters.append(0)
                        new_val = min(target_val, cur_count)
                        if counters[obj_idx] != new_val:
                            counters[obj_idx] = new_val
                            updates.append((qid, obj_idx, new_val))

        if updates:
            self.store().save()
            await self.transport.send_event(event(2075, QuestUpdateNot(updates=updates).encode()),
                                            note=f'quest update not (item objectives: {updates})')

    def _activate_quest(self, quest_id: int) -> int:
        """Add quest_id to the selected character's active quests; return its UID."""
        char = self.store().get(self.account, self.char_id)
        active = char.setdefault('quests_active', {}) if char else {}
        quests = {q: ActiveQuest.from_store(q, r) for q, r in active.items()}
        if str(quest_id) in quests:
            return quests[str(quest_id)].uid
        uid = max([0] + [q.uid for q in quests.values()]) + 1
        tracked = sum(q.tracked for q in quests.values()) < 5  # 0x00A60960
        from darkblood.games.game_data.client_dict import quest_mission_counts
        num_missions = quest_mission_counts().get(quest_id, 2 if quest_id == 0x34c58e7c else 0)
        counters = [0] * num_missions
        active[str(quest_id)] = dict(uid=uid, tracked=tracked, counters=counters)
        if char:
            self.store().save()
        return uid

    async def grant_exp(self, char, exp):
        """Add EXP, carry excess across levels, and publish the updated progress.

        Shared by quest completion (2076) and monster kills (5063). Level
        thresholds come from charstat.lua (upexp per class and level).
        """
        if not char or exp <= 0:
            return
        char_class = int(char.get('char_class', 0))
        level = char.get('level', 1)
        char_exp = char.get('exp', 0) + exp
        level_notifications = []
        while level < MAX_LEVEL:
            req_exp = char_level_stat(char_class, level)['upexp']
            if req_exp <= 0 or char_exp < req_exp:
                break
            char_exp -= req_exp
            level += 1
            advance_level(char, level, char_exp)
            level_notifications.append(LevelUpNot.from_character(char))
        char['exp'] = char_exp
        for level_not in level_notifications:
            await self.transport.send_event(event(5087, level_not.encode()),
                                            note=f'level up not (level={level_not.new_level})')
        # The client displays the gained XP from jGainExp +0x08.
        exp_ack = ChangeExpNot(exp_total=char_exp, exp_details=(0, 0, exp, 0, 0, 0, 0, 0)).encode()
        await self.transport.send_event(event(5086, exp_ack), note=f'change exp not (+{exp}, total={char_exp})')

    async def handle_quest_complete(self, correlation: int, body: bytes):
        """Opcode 2076 (eEGS_QUEST_COMPLETE_REQ) -> 2077 (eEGS_QUEST_COMPLETE_ACK).

        Client handler: 0x0065A1A0.
        Calculates quest rewards (experience, gold, game points, reward items) from client
        dictionaries, applies level-up progression if EXP threshold reached, moves quest
        from active to completed set, and saves state.
        """
        quest_id, select = 0, -1
        try:
            length, offset = read_varuint(body, 0)
            quest_id, select = struct.unpack_from('<Ii', body, offset + length)
        except (WireError, struct.error):
            pass
        from darkblood.games.game_data.client_dict import quest_rewards
        exp, gold, gp, items = quest_rewards(quest_id, select)
        char = self.store().get(self.account, self.char_id) or {}
        already = quest_id in char.get('quests_done', [])
        if already:
            exp = gold = gp = 0
        total = (Character.from_dict(char).u66 if char else Character().u66) + gold
        if char:
            char.setdefault('quests_active', {}).pop(str(quest_id), None)
            done = char.setdefault('quests_done', [])
            if quest_id not in done:
                done.append(quest_id)
            char['u66'] = total
            char['gold'] = total
            await self.grant_exp(char, exp)
            from darkblood.games.game_data.client_dict import quest_item_objectives
            for item_code, q_list in quest_item_objectives().items():
                for target_qid, _, target_val in q_list:
                    if target_qid == quest_id:
                        rem = target_val
                        new_items = []
                        for it in char.get('items', []):
                            if it.get('code') == item_code and rem > 0:
                                cnt = it.get('count', 1)
                                if cnt <= rem:
                                    rem -= cnt
                                    continue
                                else:
                                    it['count'] = cnt - rem
                                    rem = 0
                            new_items.append(it)
                        char['items'] = new_items
            from darkblood.player_management.characters import add_reward_items
            reward_items = [] if already else add_reward_items(char, items)
            self.store().save()
        else:
            reward_items = []
        self.transport.record('quest-rewards', b'', quest='%08x' % quest_id, exp=str(exp),
                              gold=str(gold), gp=str(gp), items=repr(items))
        owner = UPDATE_OWNER  # see items.UPDATE_OWNER
        ack = QuestCompleteAck(quest_id=quest_id, total=total, exp=exp, gp=gp,
                               items=[Item(owner=owner, **i) for i in reward_items]).encode()
        await self.transport.send_event(event(2077, ack, correlation),
                                        note='quest complete ack (%08x)' % quest_id)

    async def handle_tutorial_quest_start(self, correlation: int, body: bytes):
        """Opcode 2346 (eEGS_TUTORIAL_QUEST_START_REQ) -> 2347 (eEGS_TUTORIAL_QUEST_START_ACK).

        Sender: JBehaviorQuestStart (0x0089B020 -> 0x00799A60), a map trigger,
        writes J-wstring tag + u32 quest id (live: "2015-02-23 15:42:11, " +
        jhash('Q0882S01')). The 2347 reader (TalkBox 0x006481E0) only checks
        the result, and only the 2074 reader (0x00659790 -> 0x00A60960) adds
        a quest to the client's active list. Without it the tutorial NPC
        (0mok01n2) never offered the closing talk SQ0882S01c1
        (CompleteQuest + On_Tutorial_Exit(true)). The server therefore also
        sends 2074 for the quest. This is a hypothesis; a live run is pending.
        """
        quest_id = _quest_id_after_tag(body)
        uid = self._activate_quest(quest_id)
        # The tutorial map replays from the start and 2074 carries no progress,
        # so the client's counters begin at 0. Reset the stored ones to match;
        # otherwise counters left at 2/2 by an earlier run suppress every 2075.
        char = self.store().get(self.account, self.char_id)
        record = char.get('quests_active', {}).get(str(quest_id)) if char else None
        if record and record.get('counters'):
            record['counters'] = [0] * len(record['counters'])
            self.store().save()
        ack = TutorialQuestStartAck().encode()
        await self.transport.send_event(event(2347, ack, correlation), note='tutorial quest start ack')
        start = QuestStartAck(quest_id=quest_id, quest_uid=uid).encode()
        await self.transport.send_event(event(2074, start),
                                        note='tutorial quest start -> quest start ack (%08x)' % quest_id)

    async def on_2113(self, correlation: int, body: bytes):
        """Opcode 2113 (eEGS_QUEST_UPDATE_MISSION_REQ) -> 2114 (eEGS_QUEST_UPDATE_MISSION_ACK).

        Observed body: 0x7FFFFFFF prefix + J-wstring mission id ("QM807",
        MissionType 5, sent after meeting the NPC). The ack (JAppPageTalkBox
        case 0x00659F00 -> 0x006481E0) reads only u32 result. Progress is
        reported like kill counters: 2075 with (quest, objective, count).
        """
        from darkblood.games.game_data.client_dict import quest_mission_objectives
        from darkblood.games.network.messages import QuestUpdateNot
        from darkblood.core.serialization.jser import strip_prefix
        mission = ''
        try:
            data = strip_prefix(body)
            length, offset = read_varuint(data, 0)
            mission = data[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        char = self.current_char()
        active = char.get('quests_active', {}) if char else {}
        updates = []
        for q_hash, idx, target in quest_mission_objectives().get(mission, []):
            record = active.get(str(q_hash))
            if record is None:
                continue
            counters = record.setdefault('counters', [])
            while len(counters) <= idx:
                counters.append(0)
            counters[idx] = target
            updates.append((q_hash, idx, target))
        if updates:
            self.store().save()
            await self.transport.send_event(event(2075, QuestUpdateNot(updates=updates).encode()),
                                            note='quest update not (mission %s: %s)' % (mission, updates))
        await self.transport.send_event(event(2114, struct.pack('<I', 0), correlation),
                                        note='quest update mission ack (%s, %d quests)' % (mission, len(updates)))

    async def handle_quest_giveup(self, correlation: int, body: bytes):
        """Opcode 2078 (eEGS_QUEST_GIVEUP_REQ) -> 2079 (eEGS_QUEST_GIVEUP_ACK).

        Client handler: 0x006223B0.
        Removes active quest from character's tracked log upon abandonment.
        """
        req = QuestGiveupReq.decode(body)
        char = self.current_char()
        if char and str(req.quest_id) in char.get('quests_active', {}):
            del char['quests_active'][str(req.quest_id)]
            self.store().save()
        self.transport.record('quest-giveup', body, quest_id=req.quest_id)
        ack = QuestGiveupAck(result=0, quest_id=req.quest_id).encode()
        await self.transport.send_event(event(2079, ack, correlation), note=f'quest giveup ack ({req.quest_id:#010x})')

    async def handle_quest_fail(self, correlation: int, body: bytes):
        """Opcode 2080 (eEGS_QUEST_FAIL_REQ) -> 2081 (eEGS_QUEST_FAIL_ACK).

        Client handler: 0x006223B0.
        Processes quest objective expiration or failure condition.
        """
        req = QuestFailReq.decode(body)
        char = self.current_char()
        if char and str(req.quest_id) in char.get('quests_active', {}):
            del char['quests_active'][str(req.quest_id)]
            self.store().save()
        self.transport.record('quest-fail', body, quest_id=req.quest_id)
        ack = QuestFailAck(result=0, quest_id=req.quest_id).encode()
        await self.transport.send_event(event(2081, ack, correlation), note=f'quest fail ack ({req.quest_id:#010x})')

    # Client opcode bindings
    on_2073 = handle_quest_start
    on_2076 = handle_quest_complete
    on_2346 = handle_tutorial_quest_start

    on_2078 = handle_quest_giveup
    on_2080 = handle_quest_fail
