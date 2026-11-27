"""Guild creation, roster, bank, skills, broker, siege and citadel handlers."""
from darkblood.core.serialization.jser import event
from darkblood.games.dispatcher import packet_handler


class GuildHandlers:
    @packet_handler(2150)
    async def handle_guild_create(self, correlation, body):
        # eEGS_GUILD_CREATE_REQ -> 2151 eEGS_GUILD_CREATE_ACK (0x00793720).
        from darkblood.games.network.messages import GuildCreateAck, GuildCreateReq
        req = GuildCreateReq.decode(body)
        self.transport.record('guild-create-req', body, name=req.guild_name)
        char = self.current_char()
        if char is None:
            await self.reply(GuildCreateAck(result=1), correlation, note='guild create fail (no character)')
            return
        char['guild_name'] = req.guild_name
        gold = char.get('gold', 100000)
        self.save_char()
        ack = GuildCreateAck(result=0, guild_uid=1001, guild_name=req.guild_name, remain_gold=gold)
        await self.reply(ack, correlation, note=f'guild create ack (name={req.guild_name})')


    @packet_handler(5121)
    async def handle_guild_create_proposal(self, correlation, body):
        # eERC_GUILD_CREATE_PROPOSAL_REQ (0x00790000.c:2514) -> 5122 eERC_GUILD_CREATE_PROPOSAL_ACK (0x00759750).
        from darkblood.games.network.messages import GuildCreateProposalAck, GuildCreateProposalReq
        req = GuildCreateProposalReq.decode(body)
        self.transport.record('guild-proposal-req', body, name=req.guild_name)
        ack = GuildCreateProposalAck(result=0)
        await self.reply(ack, correlation, note=f'guild create proposal ack (name={req.guild_name})')


    @packet_handler(2155)
    async def handle_guild_person_join(self, correlation, body):
        # eEGS_GUILD_PERSON_JOIN_REQ (0x00790000.c:2837) -> 2156 eEGS_GUILD_PERSON_JOIN_ACK (0x0075A220).
        from darkblood.games.network.messages import GuildPersonJoinAck, GuildPersonJoinReq
        req = GuildPersonJoinReq.decode(body)
        self.transport.record('guild-join-req', body, guild_uid=req.guild_uid)
        char = self.current_char()
        if char:
            char['guild_uid'] = req.guild_uid
            self.save_char()
        ack = GuildPersonJoinAck(result=0)
        await self.reply(ack, correlation, note=f'guild person join ack (guild={req.guild_uid})')


    @packet_handler(2160)
    async def handle_guild_invite(self, correlation, body):
        # eEGS_GUILD_INVITE_REQ -> 2161 eEGS_GUILD_INVITE_ACK (0x00759870)
        # + 6015 eERT_GUILD_INVITE_REQ (0x00759AB0) delivered to online invitee.
        from darkblood.games.network.messages import GuildInviteAck, GuildInviteNot, GuildInviteReq
        from darkblood.games.world import GameWorldManager
        req = GuildInviteReq.decode(body)
        self.transport.record('guild-invite-req', body, target=req.char_name)
        char = self.current_char()
        target_name = req.char_name.strip('\x00').strip()
        target = next((p for p in GameWorldManager.get().players.values()
                       if p.char_data.get('name', '').lower() == target_name.lower()), None)
        if target and target.session and getattr(target.session, 'transport', None) and char:
            inviter_name = char.get('name', '')
            guild_uid = int(char.get('guild_uid', 1001) or 1001)
            guild_name = char.get('guild_name', '')
            guild_lv = int(char.get('guild_level', 1) or 1)
            notice = GuildInviteNot(
                recv_char_nick=target.char_data.get('name', target_name),
                guild_uid=guild_uid,
                guild_name=guild_name,
                invite_name=inviter_name,
                master_name=inviter_name,
                guild_lv=guild_lv,
                member_count=1,
            ).encode()
            await target.session.transport.send_event(event(6015, notice), note=f'guild invite not to {target_name}')
        ack = GuildInviteAck(result=0)
        await self.reply(ack, correlation, note=f'guild invite ack (target={target_name})')


    @packet_handler(2162)
    async def handle_guild_person_leave(self, correlation, body):
        # eEGS_GUILD_PERSON_LEAVE_REQ (0x00790000.c:2761) -> 2163 eEGS_GUILD_PERSON_LEAVE_ACK (0x00759CA0).
        from darkblood.games.network.messages import GuildPersonLeaveAck, GuildPersonLeaveReq
        req = GuildPersonLeaveReq.decode(body)
        self.transport.record('guild-leave-req', body)
        char = self.current_char()
        if char:
            char.pop('guild_uid', None)
            char.pop('guild_name', None)
            self.save_char()
        ack = GuildPersonLeaveAck(result=0)
        await self.reply(ack, correlation, note='guild person leave ack')


    @packet_handler(2179)
    async def handle_guild_money_in(self, correlation, body):
        # eEGS_GUILD_MONEY_IN_REQ (0x00790000.c:3031) -> 2180 eEGS_GUILD_MONEY_IN_ACK (0x00794250).
        from darkblood.games.network.messages import GuildMoneyInAck, GuildMoneyInReq
        req = GuildMoneyInReq.decode(body)
        self.transport.record('guild-money-in-req', body, amount=req.amount)
        char = self.current_char()
        guild_money = req.amount
        if char:
            current_gold = char.get('gold', 0)
            deposit = req.amount
            if current_gold >= deposit:
                char['gold'] = current_gold - deposit
            guild_money = char.setdefault('guild_money', 0) + deposit
            char['guild_money'] = guild_money
            self.save_char()
        ack = GuildMoneyInAck(result=0, remain_gold=guild_money)
        await self.reply(ack, correlation, note=f'guild money in ack (deposited={req.amount} guild_money={guild_money})')


    @packet_handler(2181)
    async def handle_guild_money_out(self, correlation, body):
        # eEGS_GUILD_MONEY_OUT_REQ (0x00790000.c:3141) -> 2182 eEGS_GUILD_MONEY_OUT_ACK (0x00794470).
        from darkblood.games.network.messages import GuildMoneyOutAck, GuildMoneyOutReq
        req = GuildMoneyOutReq.decode(body)
        self.transport.record('guild-money-out-req', body, amount=req.amount)
        char = self.current_char()
        guild_money = 0
        if char:
            curr_guild = char.get('guild_money', req.amount)
            withdraw = min(max(0, req.amount), curr_guild)
            char['guild_money'] = curr_guild - withdraw
            char['gold'] = char.get('gold', 0) + withdraw
            guild_money = char['guild_money']
            self.save_char()
        ack = GuildMoneyOutAck(result=0, remain_gold=guild_money)
        await self.reply(ack, correlation, note=f'guild money out ack (withdrawn={req.amount} remain_guild_money={guild_money})')


    @packet_handler(2183)
    async def handle_guild_level_up(self, correlation, body):
        # eEGS_GUILD_LEVEL_UP_REQ (0x00790000.c:3250) -> 2184 eEGS_GUILD_LEVEL_UP_ACK (0x00753380).
        from darkblood.games.network.messages import GuildLevelUpAck, GuildLevelUpReq
        req = GuildLevelUpReq.decode(body)
        self.transport.record('guild-level-up-req', body)
        char = self.current_char()
        new_level = 1
        if char:
            new_level = char.get('guild_level', 1) + 1
            char['guild_level'] = new_level
            self.save_char()
        ack = GuildLevelUpAck(result=0, new_level=new_level)
        await self.reply(ack, correlation, note=f'guild level up ack (new_level={new_level})')


    @packet_handler(2185)
    async def handle_guild_notice_modify(self, correlation, body):
        # eEGS_GUILD_NOTICE_MODIFY_REQ (0x00790000.c:3278) -> 2186 eEGS_GUILD_NOTICE_MODIFY_ACK (0x0075A120).
        from darkblood.games.network.messages import GuildNoticeModifyAck, GuildNoticeModifyReq
        req = GuildNoticeModifyReq.decode(body)
        self.transport.record('guild-notice-modify-req', body, notice=req.notice)
        char = self.current_char()
        if char:
            char['guild_notice'] = req.notice
            self.save_char()
        ack = GuildNoticeModifyAck(result=0)
        await self.reply(ack, correlation, note='guild notice modify ack')


    @packet_handler(2188)
    async def handle_guild_notice_delete(self, correlation, body):
        # eEGS_GUILD_NOTICE_DELETE_REQ (0x00790000.c:3388) -> 2189 eEGS_GUILD_NOTICE_DELETE_ACK (0x0074B830).
        from darkblood.games.network.messages import GuildNoticeDeleteAck, GuildNoticeDeleteReq
        req = GuildNoticeDeleteReq.decode(body)
        self.transport.record('guild-notice-delete-req', body)
        char = self.current_char()
        if char:
            char.pop('guild_notice', None)
            self.save_char()
        ack = GuildNoticeDeleteAck(result=0)
        await self.reply(ack, correlation, note='guild notice delete ack')


    @packet_handler(2214)
    async def handle_guild_all_skill_init(self, correlation, body):
        # eEGS_GUILD_ALL_SKILL_INIT_REQ -> 2215 eEGS_GUILD_ALL_SKILL_INIT_ACK (0x00752D80).
        from darkblood.games.network.messages import GuildAllSkillInitAck, GuildAllSkillInitReq
        req = GuildAllSkillInitReq.decode(body)
        self.transport.record('guild-all-skill-init-req', body)
        char = self.current_char()
        if char:
            char['guild_skills'] = {}
            self.save_char()
        ack = GuildAllSkillInitAck(result=0, param=0)
        await self.reply(ack, correlation, note='guild all skill init ack')


    @packet_handler(2314)
    async def handle_guild_name_change(self, correlation, body):
        # eEGS_GUILD_NAME_CHANGE_REQ -> 2315 eEGS_GUILD_NAME_CHANGE_ACK (0x00780590).
        from darkblood.games.network.messages import GuildNameChangeAck, GuildNameChangeReq
        req = GuildNameChangeReq.decode(body)
        new_name = req.new_name.strip()
        self.transport.record('guild-name-change-req', body, new_name=new_name)
        ack = GuildNameChangeAck(result=0, items=[], new_name=new_name)
        await self.reply(ack, correlation, note=f'guild name change ack ({new_name})')


    @packet_handler(2164)
    async def handle_guild_person_grade_modify(self, correlation, body):
        # eEGS_GUILD_PERSON_GRADE_MODIFY_REQ -> 2165 eEGS_GUILD_PERSON_GRADE_MODIFY_ACK (0x00753170).
        from darkblood.games.network.messages import GuildPersonGradeModifyAck, GuildPersonGradeModifyReq
        req = GuildPersonGradeModifyReq.decode(body)
        member_uid = req.member_uids[0] if req.member_uids else 0
        self.transport.record('guild-person-grade-modify-req', body, member_uids=req.member_uids, new_grade=req.new_grade)
        ack = GuildPersonGradeModifyAck(result=0, member_uid=member_uid, new_grade=req.new_grade)
        await self.reply(ack, correlation, note=f'guild person grade modify ack (member={member_uid})')


    @packet_handler(2166)
    async def handle_guild_fallout_start(self, correlation, body):
        # eEGS_GUILD_FALLOUT_START_REQ (0x00793EA0) -> 2167 eEGS_GUILD_FALLOUT_START_ACK (0x00759D60).
        from darkblood.games.network.messages.guild import GuildFalloutStartAck
        char = self.current_char()
        if char is not None:
            char['guild_fallout'] = True
            self.save_char()
        await self.reply(GuildFalloutStartAck(result=0), correlation, note='guild fallout start ack')


    @packet_handler(2168)
    async def handle_guild_fallout_stop(self, correlation, body):
        # eEGS_GUILD_FALLOUT_STOP_REQ (0x00793FA0) -> 2169 eEGS_GUILD_FALLOUT_STOP_ACK (0x0074B830).
        from darkblood.games.network.messages.guild import GuildFalloutStopAck
        char = self.current_char()
        if char is not None:
            char.pop('guild_fallout', None)
            self.save_char()
        await self.reply(GuildFalloutStopAck(result=0), correlation, note='guild fallout stop ack')


    @packet_handler(2173)
    async def handle_guild_grade_delegation(self, correlation, body):
        # eEGS_GUILD_GRADE_DELEGATION_REQ (0x00794020) -> 2174 eEGS_GUILD_GRADE_DELEGATION_ACK (0x0074B830).
        from darkblood.games.network.messages.guild import GuildGradeDelegationAck, GuildGradeDelegationReq
        req = GuildGradeDelegationReq.decode(body)
        self.transport.record('guild-grade-delegation-req', body, target_uid=req.target_uid)
        await self.reply(GuildGradeDelegationAck(result=0), correlation,
                         note=f'guild grade delegation ack (target={req.target_uid})')


    @packet_handler(2175)
    async def handle_guild_person_expulsion(self, correlation, body):
        # eEGS_GUILD_PERSON_EXPULSION_REQ (0x007940D0) -> 2176 eEGS_GUILD_PERSON_EXPULSION_ACK (0x0074B830).
        from darkblood.games.network.messages.guild import (
            GuildPersonExpulsionAck, GuildPersonExpulsionCompleteNot, GuildPersonExpulsionReq,
        )
        from darkblood.games.world import GameWorldManager
        req = GuildPersonExpulsionReq.decode(body)
        self.transport.record('guild-person-expulsion-req', body, member_uids=req.member_uids)
        world = GameWorldManager.get()
        for uid in req.member_uids:
            target = world.get_player(self.char_id_from_uid(uid))
            if target and target.session and getattr(target.session, 'transport', None):
                target.char_data.pop('guild_uid', None)
                target.char_data.pop('guild_name', None)
                await target.session.transport.send_event(
                    event(6017, GuildPersonExpulsionCompleteNot().encode()),
                    note=f'guild expulsion complete not ({uid})',
                )
        await self.reply(GuildPersonExpulsionAck(result=0), correlation,
                         note=f'guild person expulsion ack (count={len(req.member_uids)})')


    @packet_handler(2187)
    async def handle_guild_viewed_notice(self, correlation, body):
        # eEGS_GUILD_VIEWED_NOTICE_NOT (0x00794700): fire-and-forget.
        from darkblood.games.network.messages.guild import GuildViewedNoticeNot
        req = GuildViewedNoticeNot.decode(body)
        self.transport.record('guild-viewed-notice-not', body, notice_time=req.notice_time)


    @packet_handler(2190)
    async def handle_guild_dismissal_start(self, correlation, body):
        # eEGS_GUILD_DISMISSAL_START_REQ (0x007947A0) -> 2191 eEGS_GUILD_DISMISSAL_START_ACK (0x0074B830).
        from darkblood.games.network.messages.guild import GuildDismissalStartAck
        char = self.current_char()
        if char is not None:
            char['guild_dismissal'] = True
            self.save_char()
        await self.reply(GuildDismissalStartAck(result=0), correlation, note='guild dismissal start ack')


    @packet_handler(2192)
    async def handle_guild_dismissal_stop(self, correlation, body):
        # eEGS_GUILD_DISMISSAL_STOP_REQ (0x00794820) -> 2193 eEGS_GUILD_DISMISSAL_STOP_ACK (0x0074B830).
        from darkblood.games.network.messages.guild import GuildDismissalStopAck
        char = self.current_char()
        if char is not None:
            char.pop('guild_dismissal', None)
            self.save_char()
        await self.reply(GuildDismissalStopAck(result=0), correlation, note='guild dismissal stop ack')


    @packet_handler(2206)
    async def handle_guild_learn_skill(self, correlation, body):
        # eEGS_GUILD_LEARN_SKILL_REQ (0x00794B10) -> 2207 eEGS_GUILD_LEARN_SKILL_ACK (0x0074B820).
        from darkblood.games.network.messages.guild import (
            GuildLearnSkillAck, GuildLearnSkillReq, GuildSkillEntry, GuildSkillNot,
        )
        req = GuildLearnSkillReq.decode(body)
        char = self.current_char()
        entries = []
        if char is not None:
            skills = char.setdefault('guild_skills', {})
            skills[str(req.skill_id)] = {'level': req.skill_level, 'is_used': False}
            self.save_char()
            entries = [
                GuildSkillEntry(skill_id=int(sid) & 0xFFFF, skill_level=int(info.get('level', 1)),
                                is_used=bool(info.get('is_used', False)))
                for sid, info in skills.items()
            ]
        await self.reply(GuildLearnSkillAck(result=0), correlation,
                         note=f'guild learn skill ack (skill={req.skill_id} lv={req.skill_level})')
        await self.send_msg(GuildSkillNot(flag=True, skills=entries), note='guild skill not')


    @packet_handler(2208)
    async def handle_guild_skill_change_use_state(self, correlation, body):
        # eEGS_GUILD_SKILL_CHANGE_USE_STATE_REQ (0x00794BC0) -> 2209 eEGS_GUILD_SKILL_CHANGE_USE_STATE_ACK (0x0074B820).
        from darkblood.games.network.messages.guild import (
            CurrentGuildSkillNot, GuildSkillChangeUseStateAck, GuildSkillChangeUseStateReq, GuildSkillEntry,
        )
        req = GuildSkillChangeUseStateReq.decode(body)
        char = self.current_char()
        active = []
        guild_uid = 0
        if char is not None:
            guild_uid = int(char.get('guild_uid', 1001) or 1001)
            skills = char.setdefault('guild_skills', {})
            entry = skills.setdefault(str(req.skill_id), {'level': 1, 'is_used': False})
            entry['is_used'] = not bool(entry.get('is_used', False))
            self.save_char()
            active = [
                GuildSkillEntry(skill_id=int(sid) & 0xFFFF, skill_level=int(info.get('level', 1)), is_used=True)
                for sid, info in skills.items() if info.get('is_used')
            ]
        await self.reply(GuildSkillChangeUseStateAck(result=0), correlation,
                         note=f'guild skill use state ack (skill={req.skill_id})')
        await self.send_msg(
            CurrentGuildSkillNot(guild_uid=guild_uid, send_char_uid=self.char_id or 0, use_skills=active),
            note='current guild skill not',
        )


    @packet_handler(2218)
    async def handle_refuse_guild_invite(self, correlation, body):
        # eEGS_REFUSE_GUILD_INVITE_NOT (0x00795000) -> forwards 6019 to online inviter.
        from darkblood.games.network.messages.guild import RefuseGuildInviteForwardNot, RefuseGuildInviteNot
        from darkblood.games.world import GameWorldManager
        req = RefuseGuildInviteNot.decode(body)
        char = self.current_char()
        my_nick = char.get('name', '') if char else ''
        inviter = next((p for p in GameWorldManager.get().players.values()
                        if p.char_data.get('name', '').lower() == req.inviter_name.lower()), None)
        if inviter and inviter.session and getattr(inviter.session, 'transport', None):
            fwd = RefuseGuildInviteForwardNot(my_nick=req.inviter_name, refuser_nick=my_nick).encode()
            await inviter.session.transport.send_event(event(6019, fwd),
                                                       note=f'refuse guild invite forward to {req.inviter_name}')


    @packet_handler(2674)
    async def handle_guild_person_introduction(self, correlation, body):
        # eEGS_GUILD_PERSON_INTRODUTION_REQ (0x007A67D0) -> 2675 eEGS_GUILD_PERSON_INTRODUTION_ACK (0x0075CCA0).
        from darkblood.games.network.messages.guild import GuildPersonIntroductionAck, GuildPersonIntroductionReq
        req = GuildPersonIntroductionReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['guild_greeting'] = req.greeting
            char['guild_memo'] = req.memo
            self.save_char()
        await self.reply(GuildPersonIntroductionAck(result=0, greeting=req.greeting, memo=req.memo), correlation,
                         note='guild person introduction ack')


    @packet_handler(2678)
    async def handle_guild_broker_list(self, correlation, body):
        # eEGS_GUILD_BROKER_LIST_REQ (0x007A6880) -> 2679 eEGS_GUILD_BROKER_LIST_ACK (0x00776950).
        from darkblood.games.network.messages.guild import GuildBrokerListAck
        await self.reply(GuildBrokerListAck(result=0, brokers={}, remain_second=3600), correlation,
                         note='guild broker list ack')


    @packet_handler(2680)
    async def handle_guild_broker_bid(self, correlation, body):
        # eEGS_GUILD_BROKER_BID_REQ (0x007A6900) -> 2681 eEGS_GUILD_BROKER_BID_ACK (0x0075D040).
        from darkblood.games.network.messages.guild import GuildBrokerBidAck, GuildBrokerBidReq
        req = GuildBrokerBidReq.decode(body)
        await self.reply(GuildBrokerBidAck(result=0, broker_id=req.broker_id, bid_point=req.bid_point), correlation,
                         note=f'guild broker bid ack (id={req.broker_id} pts={req.bid_point})')


    @packet_handler(2682)
    async def handle_guild_broker_return_point(self, correlation, body):
        # eEGS_GUILD_BROKER_RETURN_POINT_REQ (0x007A6A50) -> 2683 eEGS_GUILD_BROKER_RETURN_POINT_ACK (0x0075D180).
        from darkblood.games.network.messages.guild import GuildBrokerReturnPointAck, GuildBrokerReturnPointReq
        req = GuildBrokerReturnPointReq.decode(body)
        await self.reply(GuildBrokerReturnPointAck(result=0, broker_id=req.broker_id, return_point=0), correlation,
                         note=f'guild broker return point ack (id={req.broker_id})')


    @packet_handler(2684)
    async def handle_guild_supply_get_reward(self, correlation, body):
        # eEGS_GUILD_SUPPLY_GET_REWARD_REQ (0x007A6AF0) -> 2685 eEGS_GUILD_SUPPLY_GET_REWARD_ACK (0x00783F70).
        from darkblood.games.network.messages.guild import GuildSupplyGetRewardAck, GuildSupplyGetRewardReq
        req = GuildSupplyGetRewardReq.decode(body)
        await self.reply(GuildSupplyGetRewardAck(result=0, supply_reward_uid=req.supply_reward_uid, items=[]),
                         correlation, note=f'guild supply get reward ack (uid={req.supply_reward_uid})')


    @packet_handler(2426)
    async def handle_guild_person_arena_grade_modify(self, correlation, body):
        # eEGS_GUILD_PERSON_ARENA_GRADE_MODIFY_REQ -> 2427 eEGS_GUILD_PERSON_ARENA_GRADE_MODIFY_ACK (0x00771D70).
        from darkblood.games.network.messages.guild import (
            GuildPersonArenaGradeModifyAck, GuildPersonArenaGradeModifyReq,
        )
        req = GuildPersonArenaGradeModifyReq.decode(body)
        await self.reply(
            GuildPersonArenaGradeModifyAck(result=0, char_uids=req.char_uids, arena_permission=req.arena_permission),
            correlation, note=f'guild arena grade modify ack (count={len(req.char_uids)})',
        )


    @packet_handler(2450)
    async def handle_guild_siege_change_officer(self, correlation, body):
        # eEGS_GUILD_SIEGE_CHANGE_OFFICER_REQ -> 2451 eEGS_GUILD_SIEGE_CHANGE_OFFICER_ACK (0x0076CA40).
        from darkblood.games.network.messages.guild import GuildSiegeChangeOfficerAck, GuildSiegeChangeOfficerReq
        req = GuildSiegeChangeOfficerReq.decode(body)
        await self.reply(
            GuildSiegeChangeOfficerAck(result=0, change_char_uid=req.change_char_uid, changed_chars={}),
            correlation, note=f'guild siege change officer ack (uid={req.change_char_uid})',
        )


    @packet_handler(2453)
    async def handle_guild_person_siege_team_idx_modify(self, correlation, body):
        # eEGS_GUILD_PERSON_SIEGE_TEAMIDX_MODIFY_REQ (0x0079DE80) -> 2454 ACK (0x0077C550).
        from darkblood.games.network.messages.guild import (
            GuildPersonSiegeTeamIdxModifyAck, GuildPersonSiegeTeamIdxModifyReq, SiegeTeamMembers,
        )
        req = GuildPersonSiegeTeamIdxModifyReq.decode(body)
        teams = {}
        for char_uid, team_idx in req.team_changes.items():
            teams.setdefault(team_idx, []).append(char_uid)
        team_map = {idx: SiegeTeamMembers(member_uids=uids) for idx, uids in teams.items()}
        await self.reply(
            GuildPersonSiegeTeamIdxModifyAck(result=0, team_char_list=team_map),
            correlation, note=f'guild siege team modify ack ({len(req.team_changes)} changes)',
        )


    @packet_handler(2599)
    async def handle_citadel_round_clear(self, correlation, body):
        # eEGS_CITADEL_ROUND_CLEAR_REQ (0x007A4D80) -> 2600 eEGS_CITADEL_ROUND_CLEAR_ACK (0x0075BF20).
        from darkblood.games.network.messages.guild import CitadelRoundClearAck, CitadelRoundClearReq
        req = CitadelRoundClearReq.decode(body)
        await self.reply(
            CitadelRoundClearAck(result=0, next_round=req.cur_round + 1),
            correlation, note=f'citadel round clear ack (next={req.cur_round + 1})',
        )

