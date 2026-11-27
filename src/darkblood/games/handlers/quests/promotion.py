"""Class-promotion trial quests: temporary skills on start, removal on give-up, class switch on completion."""
from darkblood.games.game_data.client_dict import quest_promotion_class, quest_temp_skill_index
from darkblood.games.handlers.quests.wire import to_i32
from darkblood.games.network.messages import LearnSkillAck, PromotionNot, QuestSpecialInfo
from darkblood.games.progression import total_ap
from darkblood.player_management.characters import gold_of


class QuestPromotionHandlers:
    async def _grant_temp_skills(self, char, quest_id: int, target_class: int, skill_hashes) -> QuestSpecialInfo:
        """Grant the two tempSkills chosen for a promotion trial (PromotionLv=1) at level 1.

        Resolves the client's skill jhashes to skill indices, sends 2009 per skill,
        and returns QuestSpecialInfo(action_type=1) for 2074 so the HUD TempSkillSet
        activates. Returns an empty QuestSpecialInfo for ordinary quests.
        """
        temp_indices = [
            idx for h in skill_hashes
            for idx in (quest_temp_skill_index(h),)
            if idx is not None
        ]
        if not char or not temp_indices:
            return QuestSpecialInfo()
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
        return QuestSpecialInfo(
            action_type=1,
            skill_1_index=target_class & 0xFFFF,
            skill_1_value=temp_indices[0],
            skill_2_index=temp_indices[1] if len(temp_indices) > 1 else -1,
            skill_2_value=to_i32(quest_id),
        )

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
            skill_2_value=to_i32(quest_id),
        )
        char.pop('temp_skills', None)
        return info

    async def _promote_after_quest(self, char, quest_id):
        """Final class-promotion quests switch the class, reset skills and refund AP (2283)."""
        promo_class = quest_promotion_class(quest_id)
        cur_class = int(char.get('char_class', 0))
        if promo_class is None or (cur_class & 0x0F) != (promo_class & 0x0F) or cur_class == promo_class:
            return
        new_sp = total_ap(char)
        char.update(char_class=promo_class, sp=new_sp, total_ap=new_sp, skills={}, locked_skills=[],
                    skill_show_cooltime=[])
        char.pop('temp_skills', None)
        self.save_char()
        await self.send_msg(PromotionNot(result=0, new_class=promo_class, sp=new_sp, skills={}),
                            note=f'promotion not (class {cur_class:#x} -> {promo_class:#x}, sp={new_sp})')
