"""Quest start (2073) and tutorial quest start (2346): active-quest records and offered items."""
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data.client_dict import item_groups, quest_mission_counts, quests
from darkblood.games.handlers.quests.wire import parse_quest_start_body, quest_id_after_tag
from darkblood.games.missions.quests import ActiveQuest
from darkblood.games.network.messages import DragItemAck, QuestStartAck, TutorialQuestStartAck
from darkblood.player_management.characters import add_reward_items


class QuestStartHandlers:
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
        quest_id, target_class, skill_hashes = parse_quest_start_body(body)
        char = self.store().get(self.account, self.char_id)
        is_new = bool(char) and str(quest_id) not in char.get('quests_active', {})
        uid = self._activate_quest(quest_id)
        special_info = await self._grant_temp_skills(char, quest_id, target_class, skill_hashes)

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
        group = (quests().get(quest_id) or {}).get('offer')
        offered = [(code, count) for code, _, count in item_groups().get(group or '', [])]
        if not offered:
            return
        stored = add_reward_items(char, offered)
        self.save_char()
        await self.send_msg(DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **i) for i in stored]), note='quest offer items (%s: %s)' % (group, ', '.join(c for c, _ in offered)))
        await self.check_quest_item_objectives(char)

    def _activate_quest(self, quest_id: int) -> int:
        """Add quest_id to the selected character's active quests; return its UID."""
        char = self.store().get(self.account, self.char_id)
        active = char.setdefault('quests_active', {}) if char else {}
        quests = {q: ActiveQuest.from_store(q, r) for q, r in active.items()}
        if str(quest_id) in quests:
            return quests[str(quest_id)].uid
        uid = max([0] + [q.uid for q in quests.values()]) + 1
        tracked = sum(q.tracked for q in quests.values()) < 5  # 0x00A60960
        num_missions = quest_mission_counts().get(quest_id, 2 if quest_id == 0x34c58e7c else 0)
        counters = [0] * num_missions
        active[str(quest_id)] = dict(uid=uid, tracked=tracked, counters=counters)
        if char:
            self.save_char()
        return uid

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
        quest_id = quest_id_after_tag(body)
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
