import struct

from darkblood.core.serialization.jser import WireError, event, read_varuint
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import Item
from darkblood.games.missions.quests import ActiveQuest
from darkblood.games.network.messages import QuestCompleteAck, QuestStartAck, TutorialQuestStartAck
from darkblood.games.state import selected_character


class QuestHandlers:
    """Quest start/complete and tutorial quests."""

    async def on_2073(self, correlation, body):
        # eEGS_QUEST_START_REQ (zlib body; observed: wstring, u32 quest id =
        # jhash('Q0001S01'), ...) -> eEGS_QUEST_START_ACK 2074, case in
        # JAppPageTalkBox dispatcher 0x659F00 -> 0x659790.
        quest_id = 0
        try:
            length, offset = read_varuint(body, 0)
            quest_id = struct.unpack_from('<I', body, offset + length)[0]
        except (WireError, struct.error):
            pass
        char = self.store().get(self.account, selected_character.get('id', 1))
        active = char.setdefault('quests_active', {}) if char else {}
        quests = {q: ActiveQuest.from_store(q, r) for q, r in active.items()}
        if str(quest_id) in quests:
            uid = quests[str(quest_id)].uid
        else:
            uid = max([0] + [q.uid for q in quests.values()]) + 1
            tracked = sum(q.tracked for q in quests.values()) < 5  # 0x00A60960
            active[str(quest_id)] = dict(uid=uid, tracked=tracked, counters=[])
        if char:
            self.store().save()
        ack = QuestStartAck(quest_id=quest_id, quest_uid=uid).encode()
        await self.transport.send_event(event(2074, ack, correlation),
                                        note='quest start ack (%08x)' % quest_id)

    async def on_2076(self, correlation, body):
        # eEGS_QUEST_COMPLETE_REQ (same observed prefix as 2073: wstring, u32
        # quest id, i32 selected reward index, -1 = none) -> 2077. Rewards come
        # from the client's DictQuest tables (client_dict.quest_rewards).
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
        if char:  # persist completion (sent back in 2410 at the next selection)
            char.setdefault('quests_active', {}).pop(str(quest_id), None)
            done = char.setdefault('quests_done', [])
            if quest_id not in done:
                done.append(quest_id)
            char['u66'] = total
            char['gold'] = total
            from darkblood.games.game_data.client_dict import char_level_stat
            from darkblood.games.network.messages import ChangeExpNot, LevelUpNot
            char_class = char.get('class', 1)
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

    async def on_2346(self, correlation, body):
        # eEGS_TUTORIAL_QUEST_START_REQ -> eEGS_TUTORIAL_QUEST_START_ACK (2347), handler 0x6481E0:
        # u32 result (0 = success).
        ack = TutorialQuestStartAck().encode()
        await self.transport.send_event(event(2347, ack, correlation), note='tutorial quest start ack')
