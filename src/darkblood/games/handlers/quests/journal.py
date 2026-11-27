"""Quest log changes: give up (2078), fail (2080), discard (2090), tracker checkbox (2098) and quest tag (2126)."""
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages import (
    GetQuestTagAck,
    GetQuestTagReq,
    QuestAlimiChangeNot,
    QuestDiscardAck,
    QuestDiscardReq,
    QuestFailAck,
    QuestFailReq,
    QuestGiveupAck,
    QuestGiveupReq,
    QuestSpecialInfo,
)


class QuestJournalHandlers:
    def _drop_active_quest(self, quest_id: int) -> QuestSpecialInfo:
        """Remove `quest_id` from the active quests, undo its promotion-trial skills and save.

        Returns QuestSpecialInfo action 3 when trial skills were removed (empty otherwise).
        """
        char = self.current_char()
        info = QuestSpecialInfo()
        if char and str(quest_id) in char.get('quests_active', {}):
            del char['quests_active'][str(quest_id)]
            info = self._clear_temp_skills_for_quest(char, quest_id)
            self.save_char()
        return info

    @packet_handler(QuestGiveupReq)
    async def handle_quest_giveup(self, correlation: int, body: bytes):
        """Opcode 2078 (eEGS_QUEST_GIVEUP_REQ) -> 2079 (eEGS_QUEST_GIVEUP_ACK).

        Client handler: 0x006223B0.
        Removes active quest from character's tracked log upon abandonment.
        """
        req = QuestGiveupReq.decode(body)
        special_info = self._drop_active_quest(req.quest_id)
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
        special_info = self._drop_active_quest(req.quest_id)
        self.transport.record('quest-fail', body, quest_id=req.quest_id)
        ack = QuestFailAck(result=0, quest_ids=[req.quest_id] if req.quest_id else [], info=special_info)
        await self.reply(ack, correlation, note=f'quest fail ack ({req.quest_id:#010x})')

    @packet_handler(QuestDiscardReq)
    async def handle_quest_discard(self, correlation: int, body: bytes):
        """Opcode 2090 (eEGS_QUEST_DISCARD_REQ) -> 2091 (eEGS_QUEST_DISCARD_ACK): discard an active quest."""
        req = QuestDiscardReq.decode(body)
        special_info = self._drop_active_quest(req.quest_id)
        self.transport.record('quest-discard', body, quest_id=req.quest_id)
        await self.reply(
            QuestDiscardAck(result=0, quest_ids=[req.quest_id] if req.quest_id else [], info=special_info),
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
