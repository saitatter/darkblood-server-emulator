"""Native GM Console & Cheat command handlers (eEGS_CHEAT_* / eERC_CHEAT_*).

See docs/GM_COMMANDS.md for the full list of 123 native in-game console commands
and their syntax. Enabled when `[server] gm_mode = 1` (sets nAuthLevel = 1 in 5020).
"""
from __future__ import annotations

import struct
import time

from darkblood.core.hashing import jhash
from darkblood.core.network.proudnet import square_uid
from darkblood.games.game_data.client_dict import quest_mission_objectives
from darkblood.games.game_data.world import dungeon_maps
from darkblood.games.world import GameWorldManager
from darkblood.player_management.characters import gold_of

from darkblood.games.network import results
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.gm_commands import (
    apply_ap_delta,
    apply_ar_delta,
    apply_clear_bag,
    apply_depot_expand,
    apply_item_call,
    apply_learn_skill,
    apply_level_up,
    apply_quest_reset,
    apply_rebirth_coins_delta,
    apply_skill_reset,
    apply_stress,
    resolve_item_code_by_hash,
)
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.network.messages.gm import (
    AcknowledgeTeleportNot,
    ArenaGradeInfo,
    CheatAchieveCompleteReq,
    CheatArenaLevelUpAck,
    CheatArenaLevelUpReq,
    CheatBillingCashChangeAck,
    CheatBillingCashChangeReq,
    CheatDepotShareExpireTimeAddReq,
    CheatDungeonCountClearReq,
    CheatDungeonMasterReq,
    CheatForceItemUpgradeAck,
    CheatForceItemUpgradeReq,
    CheatFullItemDropNot,
    CheatInitProficiencyAck,
    CheatInitProficiencyReq,
    CheatInitSkillReq,
    CheatInsertPvpPointAck,
    CheatInsertPvpPointReq,
    CheatKickCharReq,
    CheatLeagueSeasonArenaStatExpReq,
    CheatMissionCompleteReq,
    CheatMonsterCardInsertReq,
    CheatPersonalShopExpireTimeClearReq,
    CheatPersonalShopExpireTimeUpdateReq,
    CheatPetLevelAck,
    CheatPetLevelReq,
    CheatRequestTeleportNot,
    CheatTeachingChangeInfoAck,
    CheatTeachingChangeInfoReq,
    CheatViewItemDropNot,
    CheatVisibleChangeAck,
    CheatVisibleChangeReq,
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
from darkblood.games.progression import level_up_not
from darkblood.games.network.messages import (
    CheatInsertApAck,
    DepotShareExpireTimeAddNot,
    InitSkillNot,
    QuestObjective,
    QuestUpdateNot,
    CheatInsertArAck,
    CheatInsertCoinAck,
    ItemUpgradeAck,
    MarkItemActiveNot,
    MarkTabActiveNot,
    QuestCompleteAck,
    QuestStartAck,
    RebirthCoinChangeNot,
    StressChangedNot,
)
from darkblood.games.handlers.pets.cards import monster_card_code
from darkblood.games.handlers.skills import learned_skill_map, reset_proficiency


class GmHandlers(BaseDomainService):
    """Native GM console & cheat domain handlers."""

    @packet_handler(CheatLevelUpReq)
    async def handle_cheat_level_up(self, correlation: int, body: bytes):
        # 2057 -> 2058 (0x004EC120): lv <level>
        req = CheatLevelUpReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(CheatLevelUpAck(result=results.NO_EXIST_CHAR), correlation, note='cheat lv fail (no char)')
            return
        target, mark_base = apply_level_up(char, req.target_level)
        self.save_char()
        await self.reply(
            CheatLevelUpAck(result=0, character=Character.from_dict(char)),
            correlation,
            note=f'cheat level up ack (lv={target})',
        )
        await self.send_msg(level_up_not(char), note=f'cheat levelup not (lv={target})')
        if mark_base is not None:
            await self.send_msg(MarkTabActiveNot(active_mark=True), note=f'mark tab active not (lv={target})')
            await self.send_msg(
                MarkItemActiveNot(base_count=mark_base, bonus_count=int(char.get('mark_bonus_cnt', 0))),
                note=f'mark item active not (base={mark_base})',
            )

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
            apply_learn_skill(char, req.skill_id, req.skill_level)
            self.save_char()
        skills = learned_skill_map(char.get('skills', {}) if char else {})
        await self.reply(CheatLearnSkillAck(result=0, skills=[s for i, s in skills.items() if i == req.skill_id]),
                         correlation,
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
        # questclear <quest_id> (2093 -> 2077): the quest leaves the active set and
        # counts as done, without rewards.
        req = CheatQuestCompleteReq.decode(body)
        quest_id = jhash(req.quest_code)
        char = self.current_char()
        total = 0
        if char is not None:
            char.setdefault('quests_active', {}).pop(str(quest_id), None)
            done = char.setdefault('quests_done', [])
            if quest_id not in done:
                done.append(quest_id)
            total = gold_of(char)
            self.save_char()
        await self.reply(QuestCompleteAck(result=0, quest_id=quest_id, total=total), correlation,
                         note=f'cheat quest complete ack ({req.quest_code})')

    @packet_handler(CheatQuestResetReq)
    async def handle_cheat_quest_reset(self, correlation: int, body: bytes):
        # questcancel <quest_id> (2096 -> 2097): forget the quest's completion and
        # progress so it can be taken again.
        req = CheatQuestResetReq.decode(body)
        quest_id = jhash(req.quest_code)
        char = self.current_char()
        if char is not None:
            char.setdefault('quests_active', {}).pop(str(quest_id), None)
            char['quests_done'] = [q for q in char.get('quests_done', []) if q != quest_id]
            self.save_char()
        await self.reply(CheatQuestResetAck(result=0, quest_id=quest_id), correlation,
                         note=f'cheat quest reset ack ({req.quest_code})')

    @packet_handler(CheatQuestStartReq)
    async def handle_cheat_quest_start(self, correlation: int, body: bytes):
        # queststart <quest_id> (2099 -> 2074, as a normal quest start).
        req = CheatQuestStartReq.decode(body)
        quest_id = req.quest_id & 0xFFFFFFFF
        uid = self.session.quests._activate_quest(quest_id) if self.current_char() is not None else 1
        await self.reply(QuestStartAck(result=0, quest_id=quest_id, quest_uid=uid), correlation,
                         note=f'cheat quest start ack ({quest_id:#010x})')

    @packet_handler(CheatInsertCoinReq)
    async def handle_cheat_insert_coin(self, correlation: int, body: bytes):
        # 2101 -> 2102 (0x004ECD30: u32 result, i16 sTotalRebirthCoin) + 2286
        req = CheatInsertCoinReq.decode(body)
        char = self.current_char()
        total = max(0, int(req.coins))
        if char is not None:
            total = apply_rebirth_coins_delta(char, req.coins)
            self.save_char()
        await self.reply(CheatInsertCoinAck(total_coins=min(total, 32767)), correlation,
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
            cur_ar = apply_ar_delta(char, req.amount)
            self.save_char()
        await self.reply(CheatInsertArAck(cur_ar=cur_ar), correlation,
                         note=f'cheat insert ar ack (ar={cur_ar})')

    @packet_handler(CheatInsertApReq)
    async def handle_cheat_insert_ap(self, correlation: int, body: bytes):
        # 2105 -> 2106 (0x004CE620: u32 result): ap <amount>
        req = CheatInsertApReq.decode(body)
        char = self.current_char()
        if char is not None:
            apply_ap_delta(char, req.amount)
            self.save_char()
        await self.reply(CheatInsertApAck(), correlation,
                         note=f'cheat insert ap ack (added={req.amount})')

    @packet_handler(CheatDeleteAllInvenItemReq)
    async def handle_cheat_delete_all_inven_item(self, correlation: int, body: bytes):
        # 2107 -> 2108 (0x004E4430): clearbag
        char = self.current_char()
        deleted = []
        if char is not None:
            deleted = apply_clear_bag(char)
            self.save_char()
        await self.reply(CheatDeleteAllInvenItemAck(result=0, items=deleted), correlation,
                         note=f'cheat clearbag ack (deleted={len(deleted)})')

    @packet_handler(CheatItemUpgradeReq)
    async def handle_cheat_item_upgrade(self, correlation: int, body: bytes):
        # 2123 -> 2116 (ItemUpgradeAck): forceupgrade
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
        req = CheatChangeStressReq.decode(body)
        char = self.current_char()
        if char is not None:
            msg = apply_stress(char, req.stress, req.stress_pcb, req.stress_week)
            self.save_char()
        else:
            msg = StressChangedNot(stress=req.stress, stress_pcb=req.stress_pcb, stress_week=req.stress_week)
        await self.send_msg(msg, note=f'cheat stress changed not ({msg.stress})')

    @packet_handler(CheatItemCallReq)
    async def handle_cheat_item_call(self, correlation: int, body: bytes):
        # 2137 -> 2138 (0x004E3F90): itemcall <item_id> <count>
        req = CheatItemCallReq.decode(body)
        char = self.current_char()
        if not char:
            await self.reply(CheatItemCallAck(result=results.NO_EXIST_CHAR), correlation, note='cheat itemcall fail (no char)')
            return
        code = resolve_item_code_by_hash(req.item_id)
        granted = []
        if code:
            granted = apply_item_call(char, code, req.count, owner=char['id'])
            self.save_char()
        await self.reply(
            CheatItemCallAck(result=results.OK if code else results.INVALID_STATE, char_uid=char['id'], items=granted),
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
        char = self.current_char()
        if char is not None:
            apply_depot_expand(char, days=30)
            self.save_char()
        await self.reply(CheatDepotSizeIncreaseAck(result=0), correlation, note='cheat depot size increase ack')

    @packet_handler(CheatProficiencyChangeReq)
    async def handle_cheat_proficiency_change(self, correlation: int, body: bytes):
        req = CheatProficiencyChangeReq.decode(body)
        char = self.current_char()
        if char is not None and 0 <= int(req.prof_type) < 10:
            profs = list(char.get('proficiencies', []))
            while len(profs) < 10:
                profs.append(0.0)
            profs[int(req.prof_type)] = float(req.value)
            char['proficiencies'] = profs
            self.save_char()
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
        # forcedrop: every monster runs its drop logic (client side); nothing to store.
        self.transport.record('cheat-force-drop', body)

    @packet_handler(CheatSecondPassDeleteReq)
    async def handle_cheat_second_pass_delete(self, correlation: int, body: bytes):
        await self.reply(CheatSecondPassDeleteAck(result=0), correlation, note='cheat second pass delete ack')

    # ---- Cheats recovered from the client's command table (JAppPageCheat 0x004EF790) ----

    def _online_player(self, nick: str):
        nick = (nick or '').strip().lower()
        world = GameWorldManager.get()
        return next((p for p in world.players.values()
                     if str((p.char_data or {}).get('name', '')).lower() == nick), None)

    @packet_handler(CheatDepotShareExpireTimeAddReq)
    async def handle_cheat_depot_share_expire_add(self, correlation: int, body: bytes):
        # sharedepot <days> (2240). The client has no 2241 handler; 2400 announces the
        # new expiry (field semantics inferred: absolute expiry and per-character map).
        req = CheatDepotShareExpireTimeAddReq.decode(body)
        char = self.current_char()
        if char is None:
            return
        now = int(time.time())
        expire = max(now, int(char.get('share_depot_expire', 0))) + max(0, int(req.days)) * 86400
        char['share_depot_expire'] = expire
        self.save_char()
        await self.send_msg(DepotShareExpireTimeAddNot(cur_expire_time=expire, add_day=req.days,
                                                       share_expire_times={int(self.char_id): expire}),
                            note=f'cheat share depot +{req.days}d')

    @packet_handler(CheatVisibleChangeReq)
    async def handle_cheat_visible_change(self, correlation: int, body: bytes):
        # showme / hideme (2260 -> 2261 bIsHide).
        req = CheatVisibleChangeReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['gm_hidden'] = not req.visible
            self.save_char()
        await self.reply(CheatVisibleChangeAck(result=0, is_hide=not req.visible), correlation,
                         note=f'cheat visible change ack (visible={req.visible})')

    @packet_handler(CheatRequestTeleportNot)
    async def handle_cheat_request_teleport(self, correlation: int, body: bytes):
        # movetouser <name> (2274 -> 2275 with the target's position and layer).
        req = CheatRequestTeleportNot.decode(body)
        target = self._online_player(req.target_nick)
        if target is None:
            await self.send_msg(AcknowledgeTeleportNot(result=results.NO_EXIST_CHAR),
                                note=f'cheat teleport refused ({req.target_nick} offline)')
            return
        await self.send_msg(AcknowledgeTeleportNot(result=0, char_id=int(target.char_id), pos_x=target.x,
                                                   pos_y=target.y, layer_net_id=target.layer_id,
                                                   square_uid=square_uid(target.square_id)),
                            note=f'cheat teleport to {req.target_nick}')

    @packet_handler(CheatKickCharReq)
    async def handle_cheat_kick_char(self, correlation: int, body: bytes):
        # kick <name> (2277): close the target's connection. No ACK in the client.
        req = CheatKickCharReq.decode(body)
        target = self._online_player(req.target_nick)
        writer = getattr(getattr(getattr(target, 'session', None), 'transport', None), 'writer', None)
        self.transport.record('cheat-kick', body, target=req.target_nick, found=target is not None)
        if writer is not None:
            writer.close()

    @packet_handler(CheatInitSkillReq)
    async def handle_cheat_init_skill(self, correlation: int, body: bytes):
        # skillinit (2279 -> 2280 eEGS_INIT_SKILL_NOT: refunded AP and the skill map).
        char = self.current_char()
        sp = 0
        if char is not None:
            sp = apply_skill_reset(char)
            self.save_char()
        await self.send_msg(InitSkillNot(result=0, sp=sp, skills={}), note=f'cheat skill init (sp={sp})')

    @packet_handler(CheatInitProficiencyReq)
    async def handle_cheat_init_proficiency(self, correlation: int, body: bytes):
        # proficiencyinit <index> (2281 -> 2282), same reset as the 2384 item.
        req = CheatInitProficiencyReq.decode(body)
        char = self.current_char()
        skills = {}
        if char is not None:
            skills = reset_proficiency(char, int(req.pf_index))
            self.save_char()
        await self.reply(CheatInitProficiencyAck(result=0, pf_index=req.pf_index, skills=skills), correlation,
                         note=f'cheat proficiency init ack (pf={req.pf_index})')

    def _arena_info(self, char):
        return ArenaGradeInfo(exp=int(char.get('arena_exp', 0)), level=int(char.get('arena_level', 0)),
                              pvp_point_total=int(char.get('pvp_points', 0)), pvp_point_used=0)

    @packet_handler(CheatArenaLevelUpReq)
    async def handle_cheat_arena_level_up(self, correlation: int, body: bytes):
        # arenagrade <level> <exp_percent> (2312 -> 2313 jInfo). EXP is stored as the
        # percentage given (its scale in jInfo +0x04 is not recovered).
        req = CheatArenaLevelUpReq.decode(body)
        char = self.current_char()
        if char is None:
            await self.reply(CheatArenaLevelUpAck(result=results.NO_EXIST_CHAR), correlation)
            return
        char['arena_level'] = max(0, int(req.level))
        char['arena_exp'] = max(0, int(req.exp_percent))
        self.save_char()
        await self.reply(CheatArenaLevelUpAck(result=0, info=self._arena_info(char)), correlation,
                         note=f'cheat arena grade ack (lv={req.level} exp={req.exp_percent})')

    @packet_handler(CheatInsertPvpPointReq)
    async def handle_cheat_insert_pvp_point(self, correlation: int, body: bytes):
        # arenapoint <points> (2316 -> 2317 nCurPVPPoint); the same total 2068 sends.
        req = CheatInsertPvpPointReq.decode(body)
        char = self.current_char()
        total = 0
        if char is not None:
            total = max(0, int(char.get('pvp_points', 0)) + int(req.points))
            char['pvp_points'] = total
            self.save_char()
        await self.reply(CheatInsertPvpPointAck(result=0, cur_pvp_point=total), correlation,
                         note=f'cheat pvp point ack (+{req.points} = {total})')

    @packet_handler(CheatDungeonCountClearReq)
    async def handle_cheat_dungeon_count_clear(self, correlation: int, body: bytes):
        # dungeonenterinit (2375): reset the daily dungeon entry/clear counts (2007 sends them).
        char = self.current_char()
        if char is not None:
            char['daily_dun_enter_counts'] = {}
            char['daily_dun_clear_counts'] = {}
            self.save_char()
        self.transport.record('cheat-dungeon-count-clear', body)

    @packet_handler(CheatPersonalShopExpireTimeUpdateReq)
    async def handle_cheat_personal_shop_time(self, correlation: int, body: bytes):
        # pstoretime <value> (2378): extend the personal store time by <value> days
        # (unit inferred); 2007 sends the remaining seconds (+0x40C).
        req = CheatPersonalShopExpireTimeUpdateReq.decode(body)
        char = self.current_char()
        if char is not None:
            now = int(time.time())
            base = max(now, int(char.get('personal_store_expire_at', 0)))
            char['personal_store_expire_at'] = base + max(0, int(req.value)) * 86400
            self.save_char()

    @packet_handler(CheatPersonalShopExpireTimeClearReq)
    async def handle_cheat_personal_shop_time_clear(self, correlation: int, body: bytes):
        # pstoreinit (2379): reset the personal store time.
        char = self.current_char()
        if char is not None:
            char.pop('personal_store_expire_at', None)
            self.save_char()

    @packet_handler(CheatBillingCashChangeReq)
    async def handle_cheat_billing_cash_change(self, correlation: int, body: bytes):
        # cash <amount> (2396 -> 2397 nCurCash): the account's Cash Shop balance.
        req = CheatBillingCashChangeReq.decode(body)
        cash = self.store().add_account_cash(self.account, int(req.amount))
        await self.reply(CheatBillingCashChangeAck(result=0, cur_cash=cash), correlation,
                         note=f'cheat cash +{req.amount} = {cash}')

    @packet_handler(CheatMissionCompleteReq)
    async def handle_cheat_mission_complete(self, correlation: int, body: bytes):
        # missionclear <quest>,<index> (2412): fill the mission's objective like 2113 does.
        # The client has no 2413 handler.
        req = CheatMissionCompleteReq.decode(body)
        char = self.current_char()
        active = char.get('quests_active', {}) if char else {}
        updates = []
        for q_hash, idx, target in quest_mission_objectives().get(req.mission_code, []):
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
            await self.send_msg(QuestUpdateNot(updates=updates), note=f'cheat mission clear {req.mission_code}')

    @packet_handler(CheatForceItemUpgradeReq)
    async def handle_cheat_force_item_upgrade(self, correlation: int, body: bytes):
        # forceupgrade <weapon|cloth>,<level> (2414 per item -> 2415 vecItemOut).
        req = CheatForceItemUpgradeReq.decode(body)
        char = self.current_char()
        target = next((i for i in (char or {}).get('items', []) if i.get('uid') == req.item_uid), None)
        if target is None:
            await self.reply(CheatForceItemUpgradeAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'cheat force upgrade refused (uid={req.item_uid})')
            return
        target['upgrade'] = max(0, min(20, int(req.level)))
        self.save_char()
        await self.reply(CheatForceItemUpgradeAck(result=0, items=[Item(owner=UPDATE_OWNER, **target)]),
                         correlation, note=f'cheat force upgrade {target.get("code")} +{target["upgrade"]}')

    @packet_handler(CheatDungeonMasterReq)
    async def handle_cheat_dungeon_master(self, correlation: int, body: bytes):
        # dungeonmaster (2430): record every dungeon as cleared at its highest
        # difficulty, which opens all difficulties at the gate (5052 history).
        char = self.current_char()
        if char is None:
            return
        best = {}
        for map_code, (dungeon, diff, flag) in dungeon_maps().items():
            if flag:
                continue
            if dungeon not in best or diff > best[dungeon][1]:
                best[dungeon] = (map_code, diff)
        history = char.setdefault('dungeon_history', {})
        for dungeon, (map_code, diff) in best.items():
            history[dungeon] = {'map': map_code, 'diff': diff}
        self.save_char()
        self.transport.record('cheat-dungeon-master', body, dungeons=len(best))

    @packet_handler(CheatPetLevelReq)
    async def handle_cheat_pet_level(self, correlation: int, body: bytes):
        # petlv <level> (2486 -> 2487 nPetUID >> ucLv >> nExp) on the summoned pet.
        req = CheatPetLevelReq.decode(body)
        char = self.current_char() or {}
        pet_uid = char.get('summoned_pet')
        pet = next((p for p in char.get('pets') or [] if p.get('uid') == pet_uid), None)
        if pet is None:
            await self.reply(CheatPetLevelAck(result=results.INVALID_STATE), correlation,
                             note='cheat pet level refused (no summoned pet)')
            return
        pet['level'] = max(1, int(req.level))
        pet['exp'] = 0
        self.save_char()
        await self.reply(CheatPetLevelAck(result=0, pet_uid=int(pet_uid), level=pet['level'], exp=0),
                         correlation, note=f'cheat pet level {pet["level"]}')

    @packet_handler(CheatLeagueSeasonArenaStatExpReq)
    async def handle_cheat_league_stat_exp(self, correlation: int, body: bytes):
        # statexp <exp> (2560): stored; no ACK in the client.
        req = CheatLeagueSeasonArenaStatExpReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['league_stat_exp'] = int(req.exp)
            self.save_char()

    @packet_handler(CheatMonsterCardInsertReq)
    async def handle_cheat_monster_card_insert(self, correlation: int, body: bytes):
        # moncard <card> <grade> (2612): add the card to the account's card book.
        req = CheatMonsterCardInsertReq.decode(body)
        code = monster_card_code(req.card_id)
        if code is None:
            self.transport.record('cheat-moncard-unknown', body, card_id=req.card_id)
            return
        await self.session.pets.grant_monster_card(code, note='cheat moncard')

    @packet_handler(CheatTeachingChangeInfoReq)
    async def handle_cheat_teaching_change_info(self, correlation: int, body: bytes):
        # teachinfo <novice|request>,<on|off> (2670 -> 2671 bNovice >> bRequest).
        # kind 0 = novice, 1 = request (inferred from the argument order).
        req = CheatTeachingChangeInfoReq.decode(body)
        char = self.current_char() or {}
        key = 'teach_novice' if int(req.kind) == 0 else 'teach_request'
        if char:
            char[key] = bool(req.on)
            self.save_char()
        await self.reply(CheatTeachingChangeInfoAck(result=0, novice=bool(char.get('teach_novice')),
                                                    request=bool(char.get('teach_request'))), correlation,
                         note=f'cheat teach info {key}={req.on}')

    @packet_handler(CheatFullItemDropNot)
    async def handle_cheat_full_item_drop(self, correlation: int, body: bytes):
        # alldrop (5115): every drop group drops one item in this session's dungeon rolls.
        self.session.gm_all_drop = True
        self.transport.record('cheat-all-drop', body)

    @packet_handler(CheatViewItemDropNot)
    async def handle_cheat_view_item_drop(self, correlation: int, body: bytes):
        # viewdrop (5116): drop probabilities are logged by the client; nothing to store.
        self.transport.record('cheat-view-drop', body)
