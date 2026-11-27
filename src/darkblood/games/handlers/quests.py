"""Quest start/complete, failure, abandon, and tutorial quest handlers."""
import struct

from darkblood.core.serialization.jser import WireError, event, read_varuint
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data.client_dict import char_level_stat
from darkblood.games.missions.quests import ActiveQuest
from darkblood.games.network.messages import (
    ChangeExpNot,
    DragItemAck,
    GetQuestTagAck,
    GetQuestTagReq,
    LearnSkillAck,
    MarkItemActiveNot,
    MarkTabActiveNot,
    PromotionNot,
    QuestAlimiChangeNot,
    QuestCompleteAck,
    QuestDiscardAck,
    QuestDiscardReq,
    QuestFailAck,
    QuestFailReq,
    QuestGiveupAck,
    QuestGiveupReq,
    QuestObjective,
    QuestSpecialInfo,
    QuestStartAck,
    QuestUpdateMissionAck,
    QuestUpdateNot,
    RoulettePointInsertNot,
    TutorialQuestStartAck,
)
from darkblood.games.progression import MAX_LEVEL, advance_level, level_up_not, total_ap


def _quest_id_after_tag(body: bytes) -> int:
    """2073/2346 bodies: J-wstring tag, then u32 quest id (0 if malformed)."""
    try:
        length, offset = read_varuint(body, 0)
        return struct.unpack_from('<I', body, offset + length)[0]
    except (WireError, struct.error):
        return 0


def _parse_quest_start_body(body: bytes):
    """Parse 2073 body -> (quest_id, target_class, [skill_hash_1, skill_hash_2]).

    Observed wire format for 2073: J-wstring tag + u32 quest_id + optional 18-byte
    QuestSpecialInfo (i32 action_type, u16 target_class, u32 skill_1_hash,
    u32 skill_2_hash, u32 quest_id). For promotion trial quests (PromotionLv=1),
    the client populates target_class and the jhashes of the 2 chosen tempSkills.
    """
    try:
        length, offset = read_varuint(body, 0)
        tail_off = offset + length
        quest_id = struct.unpack_from('<I', body, tail_off)[0]
        if len(body) >= tail_off + 22:
            _, target_class, s1, s2, _ = struct.unpack_from('<iHIII', body, tail_off + 4)
            return quest_id, target_class, [s1, s2]
        return quest_id, 0xFFFF, []
    except (WireError, struct.error):
        return 0, 0xFFFF, []


def _to_i32(val: int) -> int:
    val &= 0xFFFFFFFF
    return val - 0x100000000 if val >= 0x80000000 else val


from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.handlers.quest_npc import QuestNpcHandlers
from darkblood.player_management.characters import gold_of


def _take_quest_items(char, quest_id):
    """Remove the items a collection quest asked for (MissionType 1 targets) from the bags."""
    from darkblood.games.game_data.client_dict import quest_item_objectives
    for item_code, q_list in quest_item_objectives().items():
        for target_qid, _, target_val in q_list:
            if target_qid != quest_id:
                continue
            remaining, kept = target_val, []
            for item in char.get('items', []):
                if item.get('code') == item_code and remaining > 0:
                    count = item.get('count', 1)
                    if count <= remaining:
                        remaining -= count
                        continue
                    item['count'] = count - remaining
                    remaining = 0
                kept.append(item)
            char['items'] = kept


class QuestHandlers(QuestNpcHandlers, BaseDomainService):
    """Quest start/complete and tutorial quests."""

    @packet_handler(2073)
    async def handle_quest_start(self, correlation: int, body: bytes):
        """Opcode 2073 (eEGS_QUEST_START_REQ) -> 2074 (eEGS_QUEST_START_ACK).

        Client dispatcher: 0x00659F00 -> 0x00659790.
        Decodes target quest ID hash, assigns new active quest UID, initializes
        objective counters, and persists in character's active quest list.
        For class-promotion trial quests (PromotionLv=1), resolves the 2 chosen
        tempSkill jhashes into numeric skill indices, grants them at level 1,
        and echoes QuestSpecialInfo(action_type=1) so the HUD TempSkillSet activates.
        """
        from darkblood.games.game_data.client_dict import quest_temp_skill_index
        quest_id, target_class, skill_hashes = _parse_quest_start_body(body)
        char = self.store().get(self.account, self.char_id)
        is_new = bool(char) and str(quest_id) not in char.get('quests_active', {})
        uid = self._activate_quest(quest_id)

        temp_indices = [
            idx for h in skill_hashes
            for idx in (quest_temp_skill_index(h),)
            if idx is not None
        ]
        special_info = QuestSpecialInfo()
        if char and temp_indices:
            skills_map = char.setdefault('skills', {})
            granted = []
            for idx in temp_indices[:2]:
                key = str(idx)
                if key not in skills_map:
                    skills_map[key] = 1
                    granted.append(idx)
            char['temp_skills'] = {
                'quest_id': quest_id,
                'target_class': target_class,
                'skills': temp_indices[:2],
                'granted': granted,
            }
            self.save_char()
            sp = int(char.get('sp', 0))
            gold = gold_of(char)
            for idx in temp_indices[:2]:
                await self.send_msg(
                    LearnSkillAck(
                        result=0,
                        skill_index=idx,
                        level=int(skills_map.get(str(idx), 1)),
                        remain_sp=sp,
                        remain_gold=gold,
                    ),
                    note=f'promotion trial temp skill ({idx})',
                )
            special_info = QuestSpecialInfo(
                action_type=1,
                skill_1_index=target_class & 0xFFFF,
                skill_1_value=temp_indices[0],
                skill_2_index=temp_indices[1] if len(temp_indices) > 1 else -1,
                skill_2_value=_to_i32(quest_id),
            )

        ack = QuestStartAck(quest_id=quest_id, quest_uid=uid, info=special_info)
        await self.reply(ack, correlation, note='quest start ack (%08x)' % quest_id)
        if is_new:
            await self._give_offer_items(char, quest_id)
        await self.check_quest_item_objectives(char)

    async def _give_offer_items(self, char, quest_id):
        """Hand over the quest's OfferItemG items (e.g. a letter to deliver).

        2074's own item vector (reader 0x4B9210) is not recovered, so the items
        go out as an unsolicited 2037 like floor pick-ups.
        """
        from darkblood.games.game_data.client_dict import item_groups, quests
        from darkblood.player_management.characters import add_reward_items
        group = (quests().get(quest_id) or {}).get('offer')
        offered = [(code, count) for code, _, count in item_groups().get(group or '', [])]
        if not offered:
            return
        stored = add_reward_items(char, offered)
        self.save_char()
        await self.send_msg(DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **i) for i in stored]), note='quest offer items (%s: %s)' % (group, ', '.join(c for c, _ in offered)))
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
                            updates.append(QuestObjective(qid, obj_idx, new_val))

        if updates:
            self.save_char()
            await self.send_msg(QuestUpdateNot(updates=updates), note=f'quest update not (item objectives: {updates})')

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
            self.save_char()
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
            level_notifications.append(level_up_not(char))
        char['exp'] = char_exp
        for level_not in level_notifications:
            await self.send_msg(level_not,
                                note=f'level up not (level={level_not.new_level})')
        if level_notifications and level >= 30:
            from darkblood.games.entities.character import mark_base_count
            new_base = max(int(char.get('mark_base_cnt', 0)), mark_base_count(level))
            if not char.get('mark_active') or new_base > int(char.get('mark_base_cnt', 0)):
                char['mark_active'] = True
                char['mark_base_cnt'] = new_base
                await self.send_msg(MarkTabActiveNot(active_mark=True), note=f'mark tab active not (lv={level})')
                await self.send_msg(
                    MarkItemActiveNot(base_count=new_base, bonus_count=int(char.get('mark_bonus_cnt', 0))),
                    note=f'mark item active not (base={new_base})',
                )
        # The client displays the gained XP from jGainExp +0x08.
        exp_ack = ChangeExpNot(exp_total=char_exp, total_gain_exp=exp)
        await self.send_msg(exp_ack, note=f'change exp not (+{exp}, total={char_exp})')

    @packet_handler(2076)
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
        total = gold_of(char) + gold
        if char:
            char.setdefault('quests_active', {}).pop(str(quest_id), None)
            done = char.setdefault('quests_done', [])
            if quest_id not in done:
                done.append(quest_id)
            char['gold'] = total
            await self.grant_exp(char, exp)
            _take_quest_items(char, quest_id)
            from darkblood.player_management.characters import add_reward_items
            reward_items = [] if already else add_reward_items(char, items)
            self.save_char()
        else:
            reward_items = []
        self.transport.record('quest-rewards', b'', quest='%08x' % quest_id, exp=str(exp),
                              gold=str(gold), gp=str(gp), items=repr(items))
        owner = UPDATE_OWNER  # see items.UPDATE_OWNER
        ack = QuestCompleteAck(quest_id=quest_id, total=total, exp=exp, gp=gp,
                               items=[Item(owner=owner, **i) for i in reward_items])
        await self.reply(ack, correlation, note='quest complete ack (%08x)' % quest_id)
        if char and not already:
            await self._quest_roulette_points(char, gold)
            await self._promote_after_quest(char, quest_id)

    async def _quest_roulette_points(self, char, gold):
        """A first completion adds 2 roulette points and feeds the quest gold to the jackpot."""
        from darkblood.games.handlers.commerce.stores import add_roulette_points, contribute_roulette_jackpot
        new_pts = add_roulette_points(char, 2)
        if gold > 0:
            contribute_roulette_jackpot(gold)
        self.save_char()
        await self.send_msg(RoulettePointInsertNot(roulette_points=new_pts),
                            note=f'roulette point not (quest, pts={new_pts:.1f})')

    async def _promote_after_quest(self, char, quest_id):
        """Final class-promotion quests switch the class, reset skills and refund AP (2283)."""
        from darkblood.games.game_data.client_dict import quest_promotion_class
        promo_class = quest_promotion_class(quest_id)
        cur_class = int(char.get('char_class', 0))
        if promo_class is None or (cur_class & 0x0F) != (promo_class & 0x0F) or cur_class == promo_class:
            return
        from darkblood.games.handlers.skills import LIFE_SKILL_TO_PROFICIENCY, learned_skill_map

        new_sp = total_ap(char)
        life_skills = {key: level for key, level in char.get('skills', {}).items()
                       if int(key) in LIFE_SKILL_TO_PROFICIENCY}
        char.update(char_class=promo_class, sp=new_sp, total_ap=new_sp, skills=life_skills,
                    locked_skills=[], skill_show_cooltime=[])
        char.pop('temp_skills', None)
        self.save_char()
        await self.send_msg(PromotionNot(result=0, new_class=promo_class, sp=new_sp,
                                         skills=learned_skill_map(life_skills)),
                            note=f'promotion not (class {cur_class:#x} -> {promo_class:#x}, sp={new_sp})')

    @packet_handler(2346)
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
            self.save_char()
        ack = TutorialQuestStartAck()
        await self.reply(ack, correlation, note='tutorial quest start ack')
        start = QuestStartAck(quest_id=quest_id, quest_uid=uid)
        await self.send_msg(start, note='tutorial quest start -> quest start ack (%08x)' % quest_id)

    @packet_handler(2113)
    async def handle_quest_update_mission(self, correlation: int, body: bytes):
        """Opcode 2113 (eEGS_QUEST_UPDATE_MISSION_REQ) -> 2114 (eEGS_QUEST_UPDATE_MISSION_ACK).

        Observed body: 0x7FFFFFFF prefix + J-wstring mission id ("QM807",
        MissionType 5, sent after meeting the NPC). The ack (JAppPageTalkBox
        case 0x00659F00 -> 0x006481E0) reads only u32 result. Progress is
        reported like kill counters: 2075 with (quest, objective, count).
        """
        from darkblood.games.game_data.client_dict import quest_mission_objectives
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
            updates.append(QuestObjective(q_hash, idx, target))
        if updates:
            self.save_char()
            await self.send_msg(QuestUpdateNot(updates=updates), note='quest update not (mission %s: %s)' % (mission, updates))
        await self.reply(QuestUpdateMissionAck(), correlation,
                         note='quest update mission ack (%s, %d quests)' % (mission, len(updates)))

    def _clear_temp_skills_for_quest(self, char, quest_id: int) -> QuestSpecialInfo:
        """Remove promotion trial temporary skills if `quest_id` owns them."""
        if not char:
            return QuestSpecialInfo()
        ts = char.get('temp_skills')
        if not isinstance(ts, dict) or ts.get('quest_id') != quest_id:
            return QuestSpecialInfo()
        skills_map = char.get('skills') or {}
        for idx in ts.get('granted', ts.get('skills', [])):
            skills_map.pop(str(idx), None)
        t_skills = ts.get('skills') or []
        info = QuestSpecialInfo(
            action_type=3,
            skill_1_index=int(ts.get('target_class', 0xFFFF)) & 0xFFFF,
            skill_1_value=t_skills[0] if len(t_skills) > 0 else -1,
            skill_2_index=t_skills[1] if len(t_skills) > 1 else -1,
            skill_2_value=_to_i32(quest_id),
        )
        char.pop('temp_skills', None)
        return info

    @packet_handler(QuestGiveupReq)
    async def handle_quest_giveup(self, correlation: int, body: bytes):
        """Opcode 2078 (eEGS_QUEST_GIVEUP_REQ) -> 2079 (eEGS_QUEST_GIVEUP_ACK).

        Client handler: 0x006223B0.
        Removes active quest from character's tracked log upon abandonment.
        """
        req = QuestGiveupReq.decode(body)
        char = self.current_char()
        special_info = QuestSpecialInfo()
        if char and str(req.quest_id) in char.get('quests_active', {}):
            del char['quests_active'][str(req.quest_id)]
            special_info = self._clear_temp_skills_for_quest(char, req.quest_id)
            self.save_char()
        self.transport.record('quest-giveup', body, quest_id=req.quest_id)
        ack = QuestGiveupAck(
            result=0,
            quest_ids=[req.quest_id] if req.quest_id else [],
            info=special_info,
        )
        await self.reply(ack, correlation, note=f'quest giveup ack ({req.quest_id:#010x})')

    @packet_handler(QuestFailReq)
    async def handle_quest_fail(self, correlation: int, body: bytes):
        """Opcode 2080 (eEGS_QUEST_FAIL_REQ) -> 2081 (eEGS_QUEST_FAIL_ACK).

        Client handler: 0x006223B0.
        Processes quest objective expiration or failure condition.
        """
        req = QuestFailReq.decode(body)
        char = self.current_char()
        if char and str(req.quest_id) in char.get('quests_active', {}):
            del char['quests_active'][str(req.quest_id)]
            self.save_char()
        self.transport.record('quest-fail', body, quest_id=req.quest_id)
        ack = QuestFailAck(result=0, quest_ids=[req.quest_id] if req.quest_id else [])
        await self.reply(ack, correlation, note=f'quest fail ack ({req.quest_id:#010x})')

    @packet_handler(QuestDiscardReq)
    async def handle_quest_discard(self, correlation: int, body: bytes):
        """Opcode 2090 (eEGS_QUEST_DISCARD_REQ) -> 2091 (eEGS_QUEST_DISCARD_ACK): discard an active quest."""
        req = QuestDiscardReq.decode(body)
        char = self.current_char()
        if char and str(req.quest_id) in char.get('quests_active', {}):
            del char['quests_active'][str(req.quest_id)]
            self.save_char()
        self.transport.record('quest-discard', body, quest_id=req.quest_id)
        await self.reply(
            QuestDiscardAck(result=0, quest_ids=[req.quest_id] if req.quest_id else []),
            correlation, note=f'quest discard ack ({req.quest_id:#010x})',
        )

    @packet_handler(QuestAlimiChangeNot)
    async def handle_quest_alimi_change(self, correlation: int, body: bytes):
        """Opcode 2098 (eEGS_QUEST_ALIMI_CHANGE_NOT): persist quest tracker (Alimi) checkbox state."""
        req = QuestAlimiChangeNot.decode(body)
        self.transport.record('quest-alimi-change', body, quest_id=req.quest_id, tracked=req.tracked)
        char = self.current_char()
        if char:
            record = char.get('quests_active', {}).get(str(req.quest_id))
            if isinstance(record, dict):
                record['tracked'] = bool(req.tracked)
                self.save_char()

    @packet_handler(GetQuestTagReq)
    async def handle_get_quest_tag(self, correlation: int, body: bytes):
        """Opcode 2126 (eEGS_GET_QUEST_TAG_REQ) -> 2127 (eEGS_GET_QUEST_TAG_ACK): return quest tag string."""
        await self.reply(GetQuestTagAck(result=0, tag=''), correlation, note='get quest tag ack')


