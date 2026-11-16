"""Quest start/complete, failure, abandon, and tutorial quest handlers."""
import struct

from darkblood.core.serialization.jser import WireError, event, read_varuint
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import Item
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
from darkblood.games.state import selected_character


def _quest_id_after_tag(body: bytes) -> int:
    """2073/2346 bodies: J-wstring tag, then u32 quest id (0 if malformed)."""
    try:
        length, offset = read_varuint(body, 0)
        return struct.unpack_from('<I', body, offset + length)[0]
    except (WireError, struct.error):
        return 0


class QuestHandlers:
    """Quest start/complete and tutorial quests."""

    async def handle_quest_start(self, correlation: int, body: bytes):
        """Opcode 2073 (eEGS_QUEST_START_REQ) -> 2074 (eEGS_QUEST_START_ACK).

        Client dispatcher: 0x00659F00 -> 0x00659790.
        Decodes target quest ID hash, assigns new active quest UID, initializes
        objective counters, and persists in character's active quest list.
        """
        quest_id = _quest_id_after_tag(body)
        uid = self._activate_quest(quest_id)
        ack = QuestStartAck(quest_id=quest_id, quest_uid=uid).encode()
        await self.transport.send_event(event(2074, ack, correlation),
                                        note='quest start ack (%08x)' % quest_id)

    def _activate_quest(self, quest_id: int) -> int:
        """Add quest_id to the selected character's active quests; return its UID."""
        char = self.store().get(self.account, selected_character.get('id', 1))
        active = char.setdefault('quests_active', {}) if char else {}
        quests = {q: ActiveQuest.from_store(q, r) for q, r in active.items()}
        if str(quest_id) in quests:
            return quests[str(quest_id)].uid
        uid = max([0] + [q.uid for q in quests.values()]) + 1
        tracked = sum(q.tracked for q in quests.values()) < 5  # 0x00A60960
        active[str(quest_id)] = dict(uid=uid, tracked=tracked, counters=[])
        if char:
            self.store().save()
        return uid

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
        char = self.store().get(self.account, selected_character.get('id', 1)) or {}
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
            from darkblood.games.game_data.client_dict import char_level_stat
            char_class = int(char.get('char_class', 1))
            level = char.get('level', 1)
            char_exp = char.get('exp', 0) + exp
            while level < 60:
                stat = char_level_stat(char_class, level)
                req_exp = stat.get('upexp', 999999)
                if char_exp >= req_exp:
                    char_exp -= req_exp
                    level += 1
                    char['level'] = level
                    char['sp'] = char.get('sp', 0) + 3
                    char['max_hp'] = stat.get('hp', 500)
                    char['max_mp'] = stat.get('mp', 200)
                    lvl_ack = LevelUpNot(
                        char_uid=char.get('id', 1),
                        new_level=level,
                        max_hp=char['max_hp'],
                        max_mp=char['max_mp'],
                        flag=True
                    ).encode()
                    await self.transport.send_event(event(5087, lvl_ack), note=f'level up not (level={level})')
                else:
                    break
            char['exp'] = char_exp
            char['u62'] = char_exp
            if exp > 0:
                exp_ack = ChangeExpNot(
                    exp_total=char_exp,
                    exp_details=(exp, 0, 0, 0, 0, 0, 0, 0, 0.0)
                ).encode()
                await self.transport.send_event(event(5086, exp_ack), note=f'change exp not (exp={char_exp})')
            from darkblood.player_management.characters import add_reward_items
            reward_items = [] if already else add_reward_items(char, items)
            self.store().save()
        else:
            reward_items = []
        self.transport.record('quest-rewards', b'', quest='%08x' % quest_id, exp=str(exp),
                              gold=str(gold), gp=str(gp), items=repr(items))
        owner = char.get('id', -1) if char else -1
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
        ack = TutorialQuestStartAck().encode()
        await self.transport.send_event(event(2347, ack, correlation), note='tutorial quest start ack')
        start = QuestStartAck(quest_id=quest_id, quest_uid=uid).encode()
        await self.transport.send_event(event(2074, start),
                                        note='tutorial quest start -> quest start ack (%08x)' % quest_id)

    async def handle_quest_giveup(self, correlation: int, body: bytes):
        """Opcode 2078 (eEGS_QUEST_GIVEUP_REQ) -> 2079 (eEGS_QUEST_GIVEUP_ACK).

        Client handler: 0x006223B0.
        Removes active quest from character's tracked log upon abandonment.
        """
        req = QuestGiveupReq.decode(body)
        char = self.store().get(self.account, selected_character.get('id', 1)) if 'id' in selected_character else None
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
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
        char = self.store().get(self.account, selected_character.get('id', 1)) if 'id' in selected_character else None
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char and str(req.quest_id) in char.get('quests_active', {}):
            del char['quests_active'][str(req.quest_id)]
            self.store().save()
        self.transport.record('quest-fail', body, quest_id=req.quest_id)
        ack = QuestFailAck(result=0, quest_id=req.quest_id).encode()
        await self.transport.send_event(event(2081, ack, correlation), note=f'quest fail ack ({req.quest_id:#010x})')

    # Opcode backward-compatibility aliases
    on_2073 = handle_quest_start
    on_2076 = handle_quest_complete
    on_2346 = handle_tutorial_quest_start
    on_2078 = handle_quest_giveup
    on_2080 = handle_quest_fail
