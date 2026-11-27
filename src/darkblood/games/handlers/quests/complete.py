"""Quest completion (2076): rewards, EXP and level-ups, roulette points and the class promotion."""
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.character import mark_base_count
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.game_data.client_dict import char_level_stat, quest_rewards
from darkblood.games.handlers.commerce.stores import add_roulette_points, contribute_roulette_jackpot
from darkblood.games.handlers.quests.objectives import take_quest_items
from darkblood.games.handlers.quests.wire import parse_quest_complete_body
from darkblood.games.network.messages import (
    ChangeExpNot,
    MarkItemActiveNot,
    MarkTabActiveNot,
    QuestCompleteAck,
    RoulettePointInsertNot,
)
from darkblood.games.progression import MAX_LEVEL, advance_level, level_up_not
from darkblood.player_management.characters import add_reward_items, gold_of


class QuestCompleteHandlers:
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
        quest_id, select = parse_quest_complete_body(body)
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
            take_quest_items(char, quest_id)
            reward_items = [] if already else add_reward_items(char, items)
            self.save_char()
        else:
            reward_items = []
        self.transport.record('quest-rewards', b'', quest='%08x' % quest_id, exp=str(exp),
                              gold=str(gold), gp=str(gp), items=repr(items))
        ack = QuestCompleteAck(quest_id=quest_id, total=total, exp=exp, gp=gp,
                               items=[Item(owner=UPDATE_OWNER, **i) for i in reward_items])
        await self.reply(ack, correlation, note='quest complete ack (%08x)' % quest_id)
        if char and not already:
            await self._quest_roulette_points(char, gold)
            await self._promote_after_quest(char, quest_id)

    async def _quest_roulette_points(self, char, gold):
        """A first completion adds 2 roulette points and feeds the quest gold to the jackpot."""
        new_pts = add_roulette_points(char, 2)
        if gold > 0:
            contribute_roulette_jackpot(gold)
        self.save_char()
        await self.send_msg(RoulettePointInsertNot(roulette_points=new_pts),
                            note=f'roulette point not (quest, pts={new_pts:.1f})')
