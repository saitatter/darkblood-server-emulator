"""Native GM Console & Cheat command handlers (eEGS_CHEAT_* / eERC_CHEAT_*).

See docs/GM_COMMANDS.md for the full list of 123 native in-game console commands
and their syntax. Enabled when `[server] gm_mode = 1` (sets nAuthLevel = 1 in 5020).
"""
from __future__ import annotations

import struct

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import EQUIPPED, Item
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.network.messages.gm import (
    CheatAchieveCompleteReq,
    CheatChangeItemQualityAck,
    CheatChangeItemQualityReq,
    CheatChangeStressReq,
    CheatChangeValidGuildCountAck,
    CheatChangeValidGuildCountReq,
    CheatDeleteAllInvenItemAck,
    CheatDeleteAllInvenItemReq,
    CheatDepotSizeIncreaseAck,
    CheatDepotSizeIncreaseReq,
    CheatExploreCompleteAck,
    CheatExploreCompleteReq,
    CheatForceItemDropNot,
    CheatGuildAddPointAck,
    CheatGuildAddPointReq,
    CheatGuildAllSkillInitAck,
    CheatGuildAllSkillInitReq,
    CheatGuildBrokerExitAck,
    CheatGuildBrokerExitReq,
    CheatGuildBrokerRewardAck,
    CheatGuildBrokerRewardReq,
    CheatGuildDismissalFinishAck,
    CheatGuildDismissalFinishReq,
    CheatGuildFalloutFinishAck,
    CheatGuildFalloutFinishReq,
    CheatGuildLevelAck,
    CheatGuildLevelReq,
    CheatIndulgenceTimeChangeReq,
    CheatInsertApReq,
    CheatInsertArReq,
    CheatInsertCoinReq,
    CheatItemCallAck,
    CheatItemCallReq,
    CheatItemDropAck,
    CheatItemDropReq,
    CheatItemUpgradeReq,
    CheatLearnAllSkillAck,
    CheatLearnAllSkillReq,
    CheatLearnSkillAck,
    CheatLearnSkillReq,
    CheatLevelUpAck,
    CheatLevelUpReq,
    CheatMonsterCardClearAck,
    CheatMonsterCardClearReq,
    CheatPetEvolutionAck,
    CheatPetEvolutionReq,
    CheatPetSatietyAck,
    CheatPetSatietyReq,
    CheatPleaseAck,
    CheatPleaseReq,
    CheatProficiencyChangeAck,
    CheatProficiencyChangeReq,
    CheatPromotionAck,
    CheatPromotionReq,
    CheatQuestCompleteReq,
    CheatQuestResetAck,
    CheatQuestResetReq,
    CheatQuestStartReq,
    CheatSecondPassDeleteAck,
    CheatSecondPassDeleteReq,
    CheatSummonRequestNot,
    CheatTitleChangeReq,
    CheatTitleGetAllReq,
)
from darkblood.games.progression import MAX_LEVEL, add_ap, advance_level, level_up_not
from darkblood.player_management.characters import add_reward_items


class GmHandlers(BaseDomainService):
    """Native GM console & cheat domain handlers."""

    @packet_handler(CheatLevelUpReq)
    async def handle_cheat_level_up(self, correlation: int, body: bytes):
        # 2057 -> 2058 (0x004EC120): lv <level>
        req = CheatLevelUpReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(CheatLevelUpAck(result=1), correlation, note='cheat lv fail (no char)')
            return
        target = max(1, min(int(req.target_level), MAX_LEVEL))
        advance_level(char, target, exp=0)
        self.save_char()
        await self.reply(
            CheatLevelUpAck(result=0, character=Character.from_dict(char)),
            correlation,
            note=f'cheat level up ack (lv={target})',
        )
        await self.send_msg(level_up_not(char), note=f'cheat levelup not (lv={target})')

    @packet_handler(CheatItemDropReq)
    async def handle_cheat_item_drop(self, correlation: int, body: bytes):
        # 2059 -> 2060 (0x004EC5D0): itemdrop <item_id>
        req = CheatItemDropReq.decode(body)
        await self.reply(
            CheatItemDropAck(result=0, drop_char_uid=self.char_id or 0),
            correlation,
            note=f'cheat item drop ack (item_id={req.item_id})',
        )

    @packet_handler(CheatLearnAllSkillReq)
    async def handle_cheat_learn_all_skill(self, correlation: int, body: bytes):
        # 2061 -> 2062 (0x004EC950): allskill
        CheatLearnAllSkillReq.decode(body)
        await self.reply(CheatLearnAllSkillAck(result=0), correlation, note='cheat learn all skill ack')

    @packet_handler(CheatLearnSkillReq)
    async def handle_cheat_learn_skill(self, correlation: int, body: bytes):
        # 2063 -> 2064 (0x004EC950): skill <id> <lv>
        req = CheatLearnSkillReq.decode(body)
        char = self.current_char()
        if char is not None:
            skills = char.setdefault('skills', {})
            skills[str(req.skill_id)] = max(1, int(req.skill_level))
            self.save_char()
        await self.reply(CheatLearnSkillAck(result=0), correlation,
                         note=f'cheat learn skill ack (id={req.skill_id} lv={req.skill_level})')

    @packet_handler(CheatPleaseReq)
    async def handle_cheat_please(self, correlation: int, body: bytes):
        # 2088 -> 2089 (0x004ED150): generic GM cheat router
        req = CheatPleaseReq.decode(body)
        self.transport.record('cheat-please-req', body, index=req.cheat.cheat_index,
                              s1=req.cheat.str_arg1, i1=req.cheat.int_arg1)
        await self.reply(CheatPleaseAck(result=0, cheat=req.cheat), correlation,
                         note=f'cheat please ack (idx={req.cheat.cheat_index})')

    @packet_handler(CheatQuestCompleteReq)
    async def handle_cheat_quest_complete(self, correlation: int, body: bytes):
        # 2093 -> 2077: questclear
        from darkblood.games.network.messages.quests import QuestCompleteAck
        req = CheatQuestCompleteReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['quests'] = [q for q in char.get('quests', []) if int(q.get('id', 0)) != req.quest_id]
            done = char.setdefault('quests_done', [])
            if req.quest_id not in done:
                done.append(req.quest_id)
            self.save_char()
        await self.reply(QuestCompleteAck(result=0, quest_id=req.quest_id), correlation,
                         note=f'cheat quest complete ack (quest={req.quest_id:#x})')

    @packet_handler(CheatQuestResetReq)
    async def handle_cheat_quest_reset(self, correlation: int, body: bytes):
        # 2096 -> 2097: questcancel / questreset
        char = self.current_char()
        if char is not None:
            char['quests'] = []
            self.save_char()
        await self.reply(CheatQuestResetAck(result=0), correlation, note='cheat quest reset ack')

    @packet_handler(CheatQuestStartReq)
    async def handle_cheat_quest_start(self, correlation: int, body: bytes):
        # 2099 -> 2074: queststart
        from darkblood.games.network.messages.quests import QuestStartAck
        req = CheatQuestStartReq.decode(body)
        char = self.current_char()
        if char is not None:
            quests = char.setdefault('quests', [])
            if not any(int(q.get('id', 0)) == req.quest_id for q in quests):
                quests.append({'id': req.quest_id, 'counters': [0] * 5, 'tracked': True})
                self.save_char()
        await self.reply(QuestStartAck(result=0, quest_id=req.quest_id), correlation,
                         note=f'cheat quest start ack (quest={req.quest_id:#x})')

    @packet_handler(CheatInsertCoinReq)
    async def handle_cheat_insert_coin(self, correlation: int, body: bytes):
        # 2101 -> 2102 (0x004ECD30: u32 result, i16 sTotalRebirthCoin) + 2286
        from darkblood.games.network.messages.system import RebirthCoinChangeNot
        req = CheatInsertCoinReq.decode(body)
        char = self.current_char()
        total = max(0, int(req.coins))
        if char is not None:
            total = max(0, int(char.get('rebirth_coins', 3)) + int(req.coins))
            char['rebirth_coins'] = total
            self.save_char()
        await self.transport.send_event(event(2102, struct.pack('<Ih', 0, min(total, 32767)), correlation),
                                        note=f'cheat insert coin ack (total={total})')
        await self.send_msg(RebirthCoinChangeNot(result=0, coins=min(total, 32767)),
                            note=f'cheat rebirth coin not ({total})')

    @packet_handler(CheatInsertArReq)
    async def handle_cheat_insert_ar(self, correlation: int, body: bytes):
        # 2103 -> 2104 (0x004ECEA0: u32 result, i64 nCurAr): ar <amount>
        req = CheatInsertArReq.decode(body)
        char = self.current_char()
        cur_ar = 0
        if char is not None:
            cur_ar = max(0, int(char.get('gold', 0)) + int(req.amount))
            char['gold'] = cur_ar
            char['u66'] = cur_ar
            self.save_char()
        await self.transport.send_event(event(2104, struct.pack('<Iq', 0, cur_ar), correlation),
                                        note=f'cheat insert ar ack (ar={cur_ar})')

    @packet_handler(CheatInsertApReq)
    async def handle_cheat_insert_ap(self, correlation: int, body: bytes):
        # 2105 -> 2106 (0x004CE620: u32 result): ap <amount>
        req = CheatInsertApReq.decode(body)
        char = self.current_char()
        if char is not None:
            add_ap(char, int(req.amount))
            self.save_char()
        await self.transport.send_event(event(2106, struct.pack('<I', 0), correlation),
                                        note=f'cheat insert ap ack (added={req.amount})')

    @packet_handler(CheatDeleteAllInvenItemReq)
    async def handle_cheat_delete_all_inven_item(self, correlation: int, body: bytes):
        # 2107 -> 2108 (0x004E4430): clearbag
        char = self.current_char()
        deleted = []
        if char is not None:
            kept = []
            for it in char.get('items', []):
                if it.get('container') == EQUIPPED:
                    kept.append(it)
                else:
                    deleted.append(Item(code=it.get('code', ''), uid=it.get('uid', 0),
                                        owner=-1, container=it.get('container', 3),
                                        slot=it.get('slot', 0), count=0))
            char['items'] = kept
            self.save_char()
        await self.reply(CheatDeleteAllInvenItemAck(result=0, items=deleted), correlation,
                         note=f'cheat clearbag ack (deleted={len(deleted)})')

    @packet_handler(CheatItemUpgradeReq)
    async def handle_cheat_item_upgrade(self, correlation: int, body: bytes):
        # 2123 -> 2116 (ItemUpgradeAck): forceupgrade
        from darkblood.games.network.messages.inventory import ItemUpgradeAck
        req = CheatItemUpgradeReq.decode(body)
        char = self.current_char()
        if char is not None:
            target = next((i for i in char.get('items', []) if i.get('uid') == req.upg_item_uid), None)
            if target is not None:
                target['upgrade'] = int(target.get('upgrade', 0)) + 1
                self.save_char()
        await self.reply(ItemUpgradeAck(result=0), correlation,
                         note=f'cheat item upgrade ack (uid={req.upg_item_uid})')

    @packet_handler(CheatPromotionReq)
    async def handle_cheat_promotion(self, correlation: int, body: bytes):
        # 2124 -> 2125 (0x004ED2E0)
        req = CheatPromotionReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['char_class'] = int(req.target_job) & 0xFF
            self.save_char()
        await self.reply(CheatPromotionAck(result=0, job=req.target_job), correlation,
                         note=f'cheat promotion ack (job={req.target_job})')

    @packet_handler(CheatChangeStressReq)
    async def handle_cheat_change_stress(self, correlation: int, body: bytes):
        # 2130 -> 2023 StressChangedNot: stress
        from darkblood.games.network.messages.system import StressChangedNot
        req = CheatChangeStressReq.decode(body)
        await self.send_msg(
            StressChangedNot(stress=req.stress, stress_pcb=req.stress_pcb, stress_week=req.stress_week),
            note=f'cheat stress changed not ({req.stress})',
        )

    @packet_handler(CheatItemCallReq)
    async def handle_cheat_item_call(self, correlation: int, body: bytes):
        # 2137 -> 2138 (0x004E3F90): itemcall <item_id> <count>
        from darkblood.games.game_data import client_dict
        req = CheatItemCallReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(CheatItemCallAck(result=1), correlation, note='cheat itemcall fail (no char)')
            return
        # Resolve item_id hash back to item code from item/durability/store dicts
        code = None
        for table in (client_dict.item_int_fields(), client_dict.item_durabilities()):
            for c in table:
                if jhash(c) == (req.item_id & 0xFFFFFFFF):
                    code = c
                    break
            if code:
                break
        if code is None:
            for entries in client_dict.store_items().values():
                for c, _ in entries:
                    if jhash(c) == (req.item_id & 0xFFFFFFFF):
                        code = c
                        break
                if code:
                    break
        granted = []
        if code:
            added = add_reward_items(char, [(code, max(1, int(req.count)))])
            self.save_char()
            granted = [Item(owner=char['id'], **i) for i in added]
        await self.reply(
            CheatItemCallAck(result=0 if code else 1, char_uid=char['id'], items=granted),
            correlation,
            note=f'cheat itemcall ack (id={req.item_id} code={code} count={req.count})',
        )

    @packet_handler(CheatChangeItemQualityReq)
    async def handle_cheat_change_item_quality(self, correlation: int, body: bytes):
        # 2141 -> 2142 (0x004E46F0): quality
        req = CheatChangeItemQualityReq.decode(body)
        char = self.current_char()
        updated = []
        if char is not None:
            target = next((i for i in char.get('items', []) if i.get('uid') == req.item_uid), None)
            if target is not None:
                target['quality'] = int(req.quality)
                self.save_char()
                updated.append(Item(owner=char['id'], **target))
        await self.reply(CheatChangeItemQualityAck(result=0, items=updated), correlation,
                         note=f'cheat item quality ack (uid={req.item_uid} q={req.quality})')

    @packet_handler(CheatGuildFalloutFinishReq)
    async def handle_cheat_guild_fallout_finish(self, correlation: int, body: bytes):
        await self.reply(CheatGuildFalloutFinishAck(result=0), correlation, note='cheat guild fallout finish ack')

    @packet_handler(CheatGuildDismissalFinishReq)
    async def handle_cheat_guild_dismissal_finish(self, correlation: int, body: bytes):
        await self.reply(CheatGuildDismissalFinishAck(result=0), correlation, note='cheat guild dismissal finish ack')

    @packet_handler(CheatGuildAddPointReq)
    async def handle_cheat_guild_add_point(self, correlation: int, body: bytes):
        req = CheatGuildAddPointReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['guild_points'] = int(char.get('guild_points', 0)) + req.points
            self.save_char()
        await self.reply(CheatGuildAddPointAck(result=0), correlation,
                         note=f'cheat guild add point ack ({req.points})')

    @packet_handler(CheatGuildLevelReq)
    async def handle_cheat_guild_level(self, correlation: int, body: bytes):
        req = CheatGuildLevelReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['guild_level'] = req.level
            self.save_char()
        await self.reply(CheatGuildLevelAck(result=0, level=req.level), correlation,
                         note=f'cheat guild level ack (lv={req.level})')

    @packet_handler(CheatGuildAllSkillInitReq)
    async def handle_cheat_guild_all_skill_init(self, correlation: int, body: bytes):
        char = self.current_char()
        if char is not None:
            char['guild_skills'] = {}
            self.save_char()
        await self.reply(CheatGuildAllSkillInitAck(result=0), correlation, note='cheat guild skill init ack')

    @packet_handler(CheatDepotSizeIncreaseReq)
    async def handle_cheat_depot_size_increase(self, correlation: int, body: bytes):
        await self.reply(CheatDepotSizeIncreaseAck(result=0), correlation, note='cheat depot size increase ack')

    @packet_handler(CheatProficiencyChangeReq)
    async def handle_cheat_proficiency_change(self, correlation: int, body: bytes):
        req = CheatProficiencyChangeReq.decode(body)
        await self.reply(CheatProficiencyChangeAck(result=0, prof_type=req.prof_type, value=req.value),
                         correlation, note=f'cheat proficiency ack (type={req.prof_type} val={req.value})')

    @packet_handler(CheatPetSatietyReq)
    async def handle_cheat_pet_satiety(self, correlation: int, body: bytes):
        req = CheatPetSatietyReq.decode(body)
        await self.reply(CheatPetSatietyAck(result=0, satiety=req.satiety, is_cash_food=req.is_cash_food),
                         correlation, note=f'cheat pet satiety ack ({req.satiety})')

    @packet_handler(CheatPetEvolutionReq)
    async def handle_cheat_pet_evolution(self, correlation: int, body: bytes):
        req = CheatPetEvolutionReq.decode(body)
        await self.reply(CheatPetEvolutionAck(result=0, pet_uid=1, new_pet_id=req.pet_id), correlation,
                         note=f'cheat pet evolution ack (id={req.pet_id})')

    @packet_handler(CheatTitleGetAllReq)
    async def handle_cheat_title_get_all(self, correlation: int, body: bytes):
        self.transport.record('cheat-title-get-all', body)

    @packet_handler(CheatTitleChangeReq)
    async def handle_cheat_title_change(self, correlation: int, body: bytes):
        req = CheatTitleChangeReq.decode(body)
        self.transport.record('cheat-title-change', body, title_id=req.title_id)

    @packet_handler(CheatAchieveCompleteReq)
    async def handle_cheat_achieve_complete(self, correlation: int, body: bytes):
        req = CheatAchieveCompleteReq.decode(body)
        self.transport.record('cheat-achieve-complete', body, achieve_id=req.achieve_id)

    @packet_handler(CheatMonsterCardClearReq)
    async def handle_cheat_monster_card_clear(self, correlation: int, body: bytes):
        char = self.current_char()
        if char is not None:
            char['monster_card_deck'] = []
            self.save_char()
        await self.reply(CheatMonsterCardClearAck(result=0), correlation, note='cheat monster card clear ack')

    @packet_handler(CheatIndulgenceTimeChangeReq)
    async def handle_cheat_indulgence_time_change(self, correlation: int, body: bytes):
        req = CheatIndulgenceTimeChangeReq.decode(body)
        self.transport.record('cheat-indulgence-time', body, time_val=req.time_val)

    @packet_handler(CheatExploreCompleteReq)
    async def handle_cheat_explore_complete(self, correlation: int, body: bytes):
        await self.reply(CheatExploreCompleteAck(result=0), correlation, note='cheat explore complete ack')

    @packet_handler(CheatGuildBrokerExitReq)
    async def handle_cheat_guild_broker_exit(self, correlation: int, body: bytes):
        await self.reply(CheatGuildBrokerExitAck(result=0), correlation, note='cheat guild broker exit ack')

    @packet_handler(CheatGuildBrokerRewardReq)
    async def handle_cheat_guild_broker_reward(self, correlation: int, body: bytes):
        await self.reply(CheatGuildBrokerRewardAck(result=0), correlation, note='cheat guild broker reward ack')

    @packet_handler(CheatChangeValidGuildCountReq)
    async def handle_cheat_change_valid_guild_count(self, correlation: int, body: bytes):
        await self.reply(CheatChangeValidGuildCountAck(result=0), correlation,
                         note='cheat change valid guild count ack')

    @packet_handler(CheatSummonRequestNot)
    async def handle_cheat_summon_request(self, correlation: int, body: bytes):
        req = CheatSummonRequestNot.decode(body)
        self.transport.record('cheat-summon-req', body, target=req.target_nick, x=req.pos_x, y=req.pos_y)

    @packet_handler(CheatForceItemDropNot)
    async def handle_cheat_force_item_drop(self, correlation: int, body: bytes):
        req = CheatForceItemDropNot.decode(body)
        self.transport.record('cheat-force-drop', body, item_id=req.item_id)

    @packet_handler(CheatSecondPassDeleteReq)
    async def handle_cheat_second_pass_delete(self, correlation: int, body: bytes):
        await self.reply(CheatSecondPassDeleteAck(result=0), correlation, note='cheat second pass delete ack')
