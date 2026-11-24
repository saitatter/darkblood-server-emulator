"""Skill learning, quickslots, locked skills, cooltime display, dual skill, proficiency and speech handlers."""
from darkblood.core.serialization.jser import event
from darkblood.games.entities.items import Item, UPDATE_OWNER
from darkblood.games.network import results
from darkblood.games.network.messages import (
    DeleteSkillSpeechAck,
    DeleteSkillSpeechReq,
    DualSkillChangeIndexAck,
    DualSkillChangeIndexReq,
    InitProficiencyAck,
    InitProficiencyReq,
    LearnSkillAck,
    LearnedSkill,
    LearnSkillListAck,
    LearnSkillListReq,
    LearnSkillReq,
    ModifySkillSpeechAck,
    ModifySkillSpeechReq,
    QuickSlot,
    ReadjustQualityAck,
    ReadjustQualityReq,
    SkillUpdateShowCoolTimeReq,
    UpdateSkillLockedAck,
    UpdateSkillLockedReq,
    UseLearnSkillItemAck,
    UseLearnSkillItemReq,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService


def learned_skill_map(skills, speeches=None, locked=(), show_cooltime=()):
    """Stored skills ({index: level}, keys may be strings) -> map for 2698, 2007, 2280, 2385, 2580."""
    speeches = speeches or {}
    locked = {int(x) for x in locked}
    show_cooltime = {int(x) for x in show_cooltime}
    result = {}
    for sidx, lvl in ((int(k), int(v)) for k, v in skills.items()):
        result[sidx] = LearnedSkill(
            sidx, lvl, speeches.get(str(sidx), ''), sidx in locked, sidx in show_cooltime
        )
    return result


class SkillHandlers(BaseDomainService):
    """Skill learning, skill trees, quickslots and skill custom speech."""

    def _charge_skills(self, char, wanted):
        """Deduct the SP/AR (skill.lua DemandPoint/DemandAr) for raising each
        (skill index, level) from its stored level. False, and nothing
        charged, when the character cannot pay."""
        from darkblood.games.game_data.client_dict import skill_learn_cost
        running = {str(k): int(v) for k, v in char.get('skills', {}).items()}
        sp = ar = 0
        for sidx, lvl in wanted:  # (index, level) pairs; 2697 sends one entry per level step
            key = str(int(sidx))
            cur = running.get(key, 0)
            target = int(lvl)
            if target > cur:
                s, a = skill_learn_cost(int(sidx), cur, target)
                sp, ar = sp + s, ar + a
                running[key] = target
        if sp > char.get('sp', 0) or ar > char.get('gold', 0):
            return False
        char['sp'] = char.get('sp', 0) - sp
        if ar:
            char['gold'] = char.get('gold', 0) - ar
            char['u66'] = char['gold']
        return True

    @packet_handler(LearnSkillReq)
    async def handle_learn_skill(self, correlation, body):
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
            self.save_char()
            remain_gold = char.get('gold', 0)
            remain_sp = char.get('sp', 0)
        ack = LearnSkillAck(result=0, skill_index=req.skill_index, level=req.level,
                            remain_sp=remain_sp, remain_gold=remain_gold).encode()
        await self.transport.send_event(event(2051, ack, correlation),
                                        note=f'learn skill ack (skill={req.skill_index} lvl={req.level})')

    @packet_handler(LearnSkillListReq)
    async def handle_learn_skill_list(self, correlation, body):
        # eEGS_LEARN_SKILL_LIST_REQ (0x007A73D0) -> 2698 eEGS_LEARN_SKILL_LIST_ACK (0x007A74A0).
        req = LearnSkillListReq.decode(body)
        char = self.current_char()
        remain_sp = remain_gold = 0
        learned_skills = {}
        if char:
            if not self._charge_skills(char, [(s.skill_index, s.level) for s in req.skills]):
                await self.transport.send_event(event(2698, LearnSkillListAck(result=1).encode(), correlation),
                                                note='learn skill list fail (not enough SP/AR)')
                return
            skills = char.setdefault('skills', {})
            for s in req.skills:
                new_lv = max(int(skills.get(str(s.skill_index), 0)), int(s.level))
                skills[str(s.skill_index)] = new_lv
                learned_skills[s.skill_index] = new_lv
            self.save_char()
            remain_gold = char.get('gold', 0)
            remain_sp = char.get('sp', 0)
        else:
            learned_skills = {s.skill_index: s.level for s in req.skills}
        ack = LearnSkillListAck(result=0, skills=learned_skill_map(learned_skills),
                                remain_sp=remain_sp, remain_gold=remain_gold).encode()
        await self.transport.send_event(event(2698, ack, correlation),
                                        note=f'learn skill list ack ({len(learned_skills)} skills)')

    @packet_handler(ModifySkillSpeechReq)
    async def handle_modify_skill_speech(self, correlation, body):
        # eEGS_MODIFY_SKILL_SPEECH_REQ (0x00780000.c:9674) -> 2054 eEGS_MODIFY_SKILL_SPEECH_ACK (0x0078E090).
        req = ModifySkillSpeechReq.decode(body)
        char = self.current_char()
        if char:
            speeches = char.setdefault('skill_speeches', {})
            speeches[str(req.skill_index)] = req.speech
            self.save_char()
        ack = ModifySkillSpeechAck(result=0, skill_index=req.skill_index, speech=req.speech).encode()
        await self.transport.send_event(event(2054, ack, correlation),
                                        note=f'modify skill speech ack (skill={req.skill_index})')

    @packet_handler(DeleteSkillSpeechReq)
    async def handle_delete_skill_speech(self, correlation, body):
        # eEGS_DELETE_SKILL_SPEECH_REQ (0x00780000.c:9708) -> 2056 eEGS_DELETE_SKILL_SPEECH_ACK (0x0078E270).
        req = DeleteSkillSpeechReq.decode(body)
        char = self.current_char()
        if char:
            speeches = char.setdefault('skill_speeches', {})
            speeches.pop(str(req.skill_index), None)
            self.save_char()
        ack = DeleteSkillSpeechAck(result=0, skill_index=req.skill_index).encode()
        await self.transport.send_event(event(2056, ack, correlation),
                                        note=f'delete skill speech ack (skill={req.skill_index})')

    @packet_handler(UpdateSkillLockedReq)
    async def handle_update_skill_locked(self, correlation, body):
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
            self.save_char()
        ack = UpdateSkillLockedAck(result=0, skill_index=req.skill_index, locked=req.locked).encode()
        await self.transport.send_event(event(2118, ack, correlation),
                                        note=f'update skill locked ack (skill={req.skill_index} locked={req.locked})')

    @packet_handler(UseLearnSkillItemReq)
    async def handle_use_learn_skill_item(self, correlation, body):
        # eEGS_USE_LEARN_SKILL_ITEM_REQ -> 2112 eEGS_USE_LEARN_SKILL_ITEM_ACK (0x0078BCD0).
        from darkblood.core.hashing import jhash
        req = UseLearnSkillItemReq.decode(body)
        self.transport.record('use-learn-skill-item-req', body, item_uid=req.item_uid, skill_id=req.skill_id)
        char = self.current_char()
        if not char:
            await self.transport.send_event(
                event(2112, UseLearnSkillItemAck(result=results.NO_EXIST_CHAR).encode(), correlation),
                note='use learn skill item fail (no char)',
            )
            return
        skills = char.setdefault('skills', {})
        new_lv = int(skills.get(str(req.skill_id), 0)) + 1
        skills[str(req.skill_id)] = new_lv

        items = char.get('items', [])
        used = next((i for i in items if i.get('uid') == req.item_uid), None)
        wire_items = []
        item_code = 0
        if used is not None:
            raw_hash = jhash(used.get('code', '')) & 0xFFFFFFFF
            item_code = raw_hash - 0x100000000 if raw_hash >= 0x80000000 else raw_hash
            rem = int(used.get('count', 1)) - 1
            if rem <= 0:
                items.remove(used)
                wire_items.append(Item(
                    owner=UPDATE_OWNER,
                    uid=0,
                    code='',
                    container=used.get('container', 3),
                    slot=used.get('slot', 0),
                    count=0,
                ))
            else:
                used['count'] = rem
                wire_items.append(Item(owner=UPDATE_OWNER, **used))
        self.save_char()
        ack = UseLearnSkillItemAck(
            result=0,
            skill_id=req.skill_id,
            skill_level=new_lv,
            item_code=item_code,
            count=1,
            items=wire_items,
            sp=int(char.get('sp', 0)),
        ).encode()
        await self.transport.send_event(
            event(2112, ack, correlation),
            note=f'use learn skill item ack (skill={req.skill_id} lv={new_lv} sp={char.get("sp", 0)})',
        )

    @packet_handler(SkillUpdateShowCoolTimeReq)
    async def handle_skill_update_show_cooltime(self, correlation, body):
        """Opcode 2152 (eEGS_SKILL_UPDATE_SHOWCOOLTIME_REQ): persist skill cooldown display toggle (no ACK)."""
        req = SkillUpdateShowCoolTimeReq.decode(body)
        self.transport.record('skill-show-cooltime', body, skill=req.skill_index, show=req.show_cooltime)
        char = self.current_char()
        if char:
            shown = set(char.setdefault('skill_show_cooltime', []))
            if req.show_cooltime:
                shown.add(req.skill_index)
            else:
                shown.discard(req.skill_index)
            char['skill_show_cooltime'] = sorted(shown)
            self.save_char()

    @packet_handler(ReadjustQualityReq)
    async def handle_readjust_quality(self, correlation, body):
        """Opcode 2302 (eEGS_READJUST_QUALITY_REQ) -> 2303 (eEGS_READJUST_QUALITY_ACK): re-roll equipment quality."""
        req = ReadjustQualityReq.decode(body)
        self.transport.record('readjust-quality-req', body,
                              target=req.target_item_uid, material=req.material_item_uid)
        char = self.current_char()
        items = char.get('items', []) if char else []
        target = next((i for i in items if i.get('uid') == req.target_item_uid), None)
        if not target:
            await self.reply(ReadjustQualityAck(result=results.INVEN_ITEM_NOT_FOUND), correlation,
                             note=f'readjust quality fail (target={req.target_item_uid} not found)')
            return
        updated = [Item(owner=UPDATE_OWNER, **target)]
        mat = next((i for i in items if i.get('uid') == req.material_item_uid), None)
        if mat is not None and mat is not target:
            cnt = mat.get('count', 1) - 1
            if cnt <= 0:
                items.remove(mat)
                updated.append(Item(owner=UPDATE_OWNER, uid=0, code='',
                                    container=mat['container'], slot=mat['slot'], count=0))
            else:
                mat['count'] = cnt
                updated.append(Item(owner=UPDATE_OWNER, **mat))
            self.save_char()
        await self.reply(ReadjustQualityAck(result=0, items=updated), correlation,
                         note=f'readjust quality ack (target={req.target_item_uid})')

    @packet_handler(InitProficiencyReq)
    async def handle_init_proficiency(self, correlation, body):
        """Opcode 2384 (eEGS_INIT_PROFICIENCY_REQ) -> 2385 (eEGS_INIT_PROFICIENCY_ACK): reset a proficiency."""
        req = InitProficiencyReq.decode(body)
        self.transport.record('init-proficiency-req', body, item_uid=req.item_uid, pf_index=req.pf_index)
        char = self.current_char()
        if not char:
            await self.reply(InitProficiencyAck(result=results.NO_EXIST_CHAR), correlation,
                             note='init proficiency fail (no char)')
            return
        items = char.get('items', [])
        updated = []
        used = next((i for i in items if i.get('uid') == req.item_uid), None)
        if used is not None:
            cnt = used.get('count', 1) - 1
            if cnt <= 0:
                items.remove(used)
                updated.append(Item(owner=UPDATE_OWNER, uid=0, code='',
                                    container=used['container'], slot=used['slot'], count=0))
            else:
                used['count'] = cnt
                updated.append(Item(owner=UPDATE_OWNER, **used))
            self.save_char()
        skills_map = learned_skill_map(
            char.get('skills', {}),
            char.get('skill_speeches', {}),
            char.get('locked_skills', []),
            char.get('skill_show_cooltime', []),
        )
        await self.reply(
            InitProficiencyAck(result=0, item_uid=req.item_uid, items=updated,
                               pf_index=req.pf_index, skills=skills_map),
            correlation,
            note=f'init proficiency ack (pf={req.pf_index} item={req.item_uid})',
        )

    @packet_handler(DualSkillChangeIndexReq)
    async def handle_dual_skill_change_index(self, correlation, body):
        """Opcode 2579 (eEGS_DUALSKILL_CHANGE_INDEX_REQ) -> 2580 (eEGS_DUALSKILL_CHANGE_INDEX_ACK): switch active skill set."""
        req = DualSkillChangeIndexReq.decode(body)
        self.transport.record('dual-skill-change-index-req', body, index=req.dual_skill_index)
        char = self.current_char()
        if not char:
            await self.reply(DualSkillChangeIndexAck(result=results.NO_EXIST_CHAR), correlation,
                             note='dual skill change index fail (no char)')
            return
        old_idx = str(char.get('dual_skill_index', 0))
        new_idx = str(req.dual_skill_index)
        sets = char.setdefault('dual_skill_sets', {})
        # Save current active build into its slot before switching
        sets[old_idx] = {
            'skills': dict(char.get('skills', {})),
            'quickslots': dict(char.get('quickslots', {})),
            'sp': int(char.get('sp', 0)),
        }
        if new_idx in sets:
            target = sets[new_idx]
            char['skills'] = dict(target.get('skills', {}))
            char['quickslots'] = dict(target.get('quickslots', {}))
            char['sp'] = int(target.get('sp', char.get('sp', 0)))
        else:
            from darkblood.games.progression import total_ap
            char['skills'] = {}
            char['quickslots'] = {}
            char['sp'] = total_ap(char)
        char['dual_skill_index'] = req.dual_skill_index
        self.save_char()
        skills_map = learned_skill_map(
            char.get('skills', {}),
            char.get('skill_speeches', {}),
            char.get('locked_skills', []),
            char.get('skill_show_cooltime', []),
        )
        quickslots = [
            QuickSlot(*q) for q in sorted(
                (q['type'], q['slot'], q['ref_id'], q['ref_uid'])
                for q in char.get('quickslots', {}).values()
                if 'slot' in q
            )
        ]
        await self.reply(
            DualSkillChangeIndexAck(
                result=0,
                skills=skills_map,
                quickslots=quickslots,
                remain_sp=int(char.get('sp', 0)),
                dual_skill_index=req.dual_skill_index,
            ),
            correlation,
            note=f'dual skill change index ack (index={req.dual_skill_index} sp={char.get("sp", 0)})',
        )
