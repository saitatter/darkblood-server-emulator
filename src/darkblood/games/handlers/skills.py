"""Skill learning, quickslots, locked skills and speech handlers."""
from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import (
    DeleteSkillSpeechAck,
    DeleteSkillSpeechReq,
    LearnSkillAck,
    LearnSkillListAck,
    LearnSkillListReq,
    LearnSkillReq,
    ModifySkillSpeechAck,
    ModifySkillSpeechReq,
    UpdateSkillLockedAck,
    UpdateSkillLockedReq,
    UseLearnSkillItemAck,
    UseLearnSkillItemReq,
)
from darkblood.games.handlers.base import BaseDomainService


class SkillHandlers(BaseDomainService):
    """Skill learning, skill trees, quickslots and skill custom speech."""

    def _charge_skills(self, char, wanted):
        """Deduct the SP/AR (skill.lua DemandPoint/DemandAr) for raising each
        (skill index, level) from its stored level. False, and nothing
        charged, when the character cannot pay."""
        from darkblood.games.game_data.client_dict import skill_learn_cost
        skills = char.get('skills', {})
        sp = ar = 0
        for sidx, lvl in wanted:
            s, a = skill_learn_cost(int(sidx), int(skills.get(str(sidx), 0)), int(lvl))
            sp, ar = sp + s, ar + a
        if sp > char.get('sp', 0) or ar > char.get('gold', 0):
            return False
        char['sp'] = char.get('sp', 0) - sp
        if ar:
            char['gold'] = char.get('gold', 0) - ar
            char['u66'] = char['gold']
        return True

    async def on_2050(self, correlation, body):
        # eEGS_LEARN_SKILL_REQ (0x00780000.c:9504) -> 2051 eEGS_LEARN_SKILL_ACK (0x0078DBE0).
        req = LearnSkillReq.decode(body)
        char = self.current_char()
        remain_sp = remain_gold = 0
        if char:
            if not self._charge_skills(char, [(req.skill_index, req.level)]):
                await self.transport.send_event(event(2051, LearnSkillAck(result=1).encode(), correlation),
                                                note='learn skill fail (not enough SP/AR)')
                return
            char.setdefault('skills', {})[str(req.skill_index)] = req.level
            self.store().save()
            remain_gold = char.get('gold', 0)
            remain_sp = char.get('sp', 0)
        ack = LearnSkillAck(result=0, skill_index=req.skill_index, level=req.level,
                            remain_sp=remain_sp, remain_gold=remain_gold).encode()
        await self.transport.send_event(event(2051, ack, correlation),
                                        note=f'learn skill ack (skill={req.skill_index} lvl={req.level})')

    async def on_2697(self, correlation, body):
        # eEGS_LEARN_SKILL_LIST_REQ (0x007A73D0) -> 2698 eEGS_LEARN_SKILL_LIST_ACK (0x007A74A0).
        req = LearnSkillListReq.decode(body)
        char = self.current_char()
        remain_sp = remain_gold = 0
        learned_skills = {}
        if char:
            if not self._charge_skills(char, req.skills):
                await self.transport.send_event(event(2698, LearnSkillListAck(result=1).encode(), correlation),
                                                note='learn skill list fail (not enough SP/AR)')
                return
            skills = char.setdefault('skills', {})
            for sidx, lvl in req.skills:
                skills[str(sidx)] = lvl
                learned_skills[sidx] = lvl
            self.store().save()
            remain_gold = char.get('gold', 0)
            remain_sp = char.get('sp', 0)
        else:
            learned_skills = {sidx: lvl for sidx, lvl in req.skills}
        ack = LearnSkillListAck(result=0, skills=learned_skills,
                                remain_sp=remain_sp, remain_gold=remain_gold).encode()
        await self.transport.send_event(event(2698, ack, correlation),
                                        note=f'learn skill list ack ({len(learned_skills)} skills)')

    async def on_2053(self, correlation, body):
        # eEGS_MODIFY_SKILL_SPEECH_REQ (0x00780000.c:9674) -> 2054 eEGS_MODIFY_SKILL_SPEECH_ACK (0x0078E090).
        req = ModifySkillSpeechReq.decode(body)
        char = self.current_char()
        if char:
            speeches = char.setdefault('skill_speeches', {})
            speeches[str(req.skill_index)] = req.speech
            self.store().save()
        ack = ModifySkillSpeechAck(result=0, skill_index=req.skill_index, speech=req.speech).encode()
        await self.transport.send_event(event(2054, ack, correlation),
                                        note=f'modify skill speech ack (skill={req.skill_index})')

    async def on_2055(self, correlation, body):
        # eEGS_DELETE_SKILL_SPEECH_REQ (0x00780000.c:9708) -> 2056 eEGS_DELETE_SKILL_SPEECH_ACK (0x0078E270).
        req = DeleteSkillSpeechReq.decode(body)
        char = self.current_char()
        if char:
            speeches = char.setdefault('skill_speeches', {})
            speeches.pop(str(req.skill_index), None)
            self.store().save()
        ack = DeleteSkillSpeechAck(result=0, skill_index=req.skill_index).encode()
        await self.transport.send_event(event(2056, ack, correlation),
                                        note=f'delete skill speech ack (skill={req.skill_index})')

    async def on_2117(self, correlation, body):
        # eEGS_UPDATE_SKILL_LOCKED_REQ (0x00790000.c:1390) -> 2118 eEGS_UPDATE_SKILL_LOCKED_ACK (0x00752C70).
        req = UpdateSkillLockedReq.decode(body)
        self.transport.record('update-skill-locked-req', body, skill=req.skill_index, locked=req.locked)
        char = self.current_char()
        if char:
            locked = set(char.setdefault('locked_skills', []))
            if req.locked:
                locked.add(req.skill_index)
            else:
                locked.discard(req.skill_index)
            char['locked_skills'] = sorted(list(locked))
            self.store().save()
        ack = UpdateSkillLockedAck(result=0, skill_index=req.skill_index, locked=req.locked).encode()
        await self.transport.send_event(event(2118, ack, correlation),
                                        note=f'update skill locked ack (skill={req.skill_index} locked={req.locked})')

    async def on_2111(self, correlation, body):
        # eEGS_USE_LEARN_SKILL_ITEM_REQ -> 2112 eEGS_USE_LEARN_SKILL_ITEM_ACK (0x0078BCD0).
        req = UseLearnSkillItemReq.decode(body)
        self.transport.record('use-learn-skill-item-req', body, item_uid=req.item_uid, skill_id=req.skill_id)
        ack = UseLearnSkillItemAck(result=0, skill_id=req.skill_id, skill_level=1, item_code=0, count=1, items=[], sp=10).encode()
        await self.transport.send_event(event(2112, ack, correlation), note=f'use learn skill item ack (skill={req.skill_id})')
