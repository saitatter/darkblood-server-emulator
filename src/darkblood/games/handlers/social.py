from darkblood.core.serialization.jser import event
from darkblood.games.network.messages import FriendListAck, GuildOrAttendanceAck, PostListAck


class SocialHandlers:
    """Mailbox, friends, block list and client notifications."""

    async def on_2219(self, correlation, body):
        # eEGS_POST_REQUEST_LIST_ACK (2220), handler 0x7AEF70:
        # result, two tagged maps, u32 unread count, bool notification flag.
        # Empty mailbox is a local offline default; notification stays false.
        ack = PostListAck().encode()
        await self.transport.send_event(event(2220, ack, correlation),
                                        note='empty post list ack')

    async def on_2131(self, correlation, body):
        # eEGS_FRIEND_LIST_REQUEST_REQ -> eEGS_FRIEND_LIST_REQUEST_ACK (2132), handler 0x7712E0:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        ack = FriendListAck().encode()
        await self.transport.send_event(event(2132, ack, correlation), note='friend list ack')

    async def on_2569(self, correlation, body):
        # Opcode 2569 -> 2570 ACK, handler 0x772160:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        ack = GuildOrAttendanceAck().encode()
        await self.transport.send_event(event(2570, ack, correlation), note='opcode 2570 ack')

    async def on_2352(self, correlation, body):
        # eEGS_IP_ADDRESS_NOT: client LAN/WAN IP notification only.
        pass

    async def on_2203(self, correlation, body):
        # eEGS_COMPUTER_STAT_NOT: client hardware report; notification only.
        pass

    async def on_0(self, correlation, body):
        # Application-level keepalive heartbeat sent by client periodically.
        pass

    async def on_2024(self, correlation, body):
        # eEGS_GET_INVITELIST_REQ -> 2025 eEGS_GET_INVITELIST_ACK (0x006A2E10).
        from darkblood.games.network.messages import GetInviteListAck
        ack = GetInviteListAck().encode()
        await self.transport.send_event(event(2025, ack, correlation), note='invite list ack')

    async def on_2139(self, correlation, body):
        # eEGS_FRIEND_LIST_ADD_REQ (0x00790000.c:1595) -> 2140 eEGS_FRIEND_LIST_ADD_ACK (0x007591A0).
        from darkblood.games.network.messages import FriendListAddAck, FriendListAddReq
        req = FriendListAddReq.decode(body)
        self.transport.record('friend-add', body, name=req.char_name)
        # Default response: 0xCE (player not found or offline)
        ack = FriendListAddAck(result=0xCE).encode()
        await self.transport.send_event(event(2140, ack, correlation), note=f'friend add ack ({req.char_name})')

    async def on_2135(self, correlation, body):
        # eEGS_FRIEND_LIST_DELETE_REQ (0x00790000.c:1824) -> 2136 eEGS_FRIEND_LIST_DELETE_ACK (0x00759560).
        from darkblood.games.network.messages import FriendListDeleteAck, FriendListDeleteReq
        req = FriendListDeleteReq.decode(body)
        self.transport.record('friend-delete', body, char_uid=req.char_uid)
        ack = FriendListDeleteAck(result=0, char_uid=req.char_uid).encode()
        await self.transport.send_event(event(2136, ack, correlation), note=f'friend delete ack ({req.char_uid})')

    async def on_2128(self, correlation, body):
        # eEGS_USE_SPEAKER_ITEM_REQ (0x00790000.c:1992) -> 2129 eEGS_USE_SPEAKER_ITEM_ACK (0x0077F320).
        from darkblood.games.network.messages import UseSpeakerItemAck, UseSpeakerItemReq
        req = UseSpeakerItemReq.decode(body)
        self.transport.record('use-speaker-req', body, speaker=req.speaker_uid, msg=req.message)
        ack = UseSpeakerItemAck(result=0, speaker_uid=req.speaker_uid).encode()
        await self.transport.send_event(event(2129, ack, correlation),
                                        note=f'use speaker ack (speaker={req.speaker_uid} msg={req.message[:20]})')

    async def on_2150(self, correlation, body):
        # eEGS_GUILD_CREATE_REQ -> 2151 eEGS_GUILD_CREATE_ACK (0x00793720).
        from darkblood.games.network.messages import GuildCreateAck, GuildCreateReq
        from darkblood.games.state import selected_character
        req = GuildCreateReq.decode(body)
        self.transport.record('guild-create-req', body, name=req.guild_name)
        char = None
        gold = 0
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            char['guild_name'] = req.guild_name
            gold = char.get('gold', 100000)
            self.store().save()
        ack = GuildCreateAck(result=0, guild_uid=1001, guild_name=req.guild_name, remain_gold=gold).encode()
        await self.transport.send_event(event(2151, ack, correlation),
                                        note=f'guild create ack (name={req.guild_name})')

    async def on_5121(self, correlation, body):
        # eERC_GUILD_CREATE_PROPOSAL_REQ (0x00790000.c:2514) -> 5122 eERC_GUILD_CREATE_PROPOSAL_ACK (0x00759750).
        from darkblood.games.network.messages import GuildCreateProposalAck, GuildCreateReq
        req = GuildCreateReq.decode(body)
        self.transport.record('guild-proposal-req', body, name=req.guild_name)
        ack = GuildCreateProposalAck(result=0).encode()
        await self.transport.send_event(event(5122, ack, correlation),
                                        note=f'guild create proposal ack (name={req.guild_name})')

    async def on_2133(self, correlation, body):
        # eEGS_FRIEND_LIST_UPDATE_REQ (0x00790000.c:1735) -> 2134 eEGS_FRIEND_LIST_UPDATE_ACK (0x00752E80).
        from darkblood.games.network.messages import FriendListUpdateAck, FriendListUpdateReq
        req = FriendListUpdateReq.decode(body)
        self.transport.record('friend-update-req', body, char_uid=req.char_uid, comment=req.comment)
        ack = FriendListUpdateAck(result=0, char_uid=req.char_uid, comment=req.comment).encode()
        await self.transport.send_event(event(2134, ack, correlation),
                                        note=f'friend list update ack (uid={req.char_uid})')

    async def on_2155(self, correlation, body):
        # eEGS_GUILD_PERSON_JOIN_REQ (0x00790000.c:2837) -> 2156 eEGS_GUILD_PERSON_JOIN_ACK (0x0075A220).
        from darkblood.games.network.messages import GuildPersonJoinAck, GuildPersonJoinReq
        from darkblood.games.state import selected_character
        req = GuildPersonJoinReq.decode(body)
        self.transport.record('guild-join-req', body, guild_uid=req.guild_uid)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            char['guild_uid'] = req.guild_uid
            self.store().save()
        ack = GuildPersonJoinAck(result=0).encode()
        await self.transport.send_event(event(2156, ack, correlation),
                                        note=f'guild person join ack (guild={req.guild_uid})')

    async def on_2160(self, correlation, body):
        # eEGS_GUILD_INVITE_REQ -> 2161 eEGS_GUILD_INVITE_ACK (0x00759870).
        from darkblood.games.network.messages import GuildInviteAck, GuildInviteReq
        req = GuildInviteReq.decode(body)
        self.transport.record('guild-invite-req', body, target=req.char_name)
        ack = GuildInviteAck(result=0).encode()
        await self.transport.send_event(event(2161, ack, correlation),
                                        note=f'guild invite ack (target={req.char_name})')

    async def on_2162(self, correlation, body):
        # eEGS_GUILD_PERSON_LEAVE_REQ (0x00790000.c:2761) -> 2163 eEGS_GUILD_PERSON_LEAVE_ACK (0x00759CA0).
        from darkblood.games.network.messages import GuildPersonLeaveAck, GuildPersonLeaveReq
        from darkblood.games.state import selected_character
        req = GuildPersonLeaveReq.decode(body)
        self.transport.record('guild-leave-req', body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            char.pop('guild_uid', None)
            char.pop('guild_name', None)
            self.store().save()
        ack = GuildPersonLeaveAck(result=0).encode()
        await self.transport.send_event(event(2163, ack, correlation), note='guild person leave ack')

    async def on_2179(self, correlation, body):
        # eEGS_GUILD_MONEY_IN_REQ (0x00790000.c:3031) -> 2180 eEGS_GUILD_MONEY_IN_ACK (0x00794250).
        from darkblood.games.network.messages import GuildMoneyInAck, GuildMoneyInReq
        from darkblood.games.state import selected_character
        req = GuildMoneyInReq.decode(body)
        self.transport.record('guild-money-in-req', body, amount=req.amount)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        remain_gold = 0
        if char:
            current_gold = char.get('gold', 0)
            deposit = min(max(0, req.amount), current_gold)
            char['gold'] = current_gold - deposit
            char['u66'] = char['gold']
            guild_money = char.setdefault('guild_money', 0) + deposit
            char['guild_money'] = guild_money
            remain_gold = char['gold']
            self.store().save()
        ack = GuildMoneyInAck(result=0, remain_gold=remain_gold).encode()
        await self.transport.send_event(event(2180, ack, correlation),
                                        note=f'guild money in ack (deposited={req.amount} remain={remain_gold})')

    async def on_2181(self, correlation, body):
        # eEGS_GUILD_MONEY_OUT_REQ (0x00790000.c:3141) -> 2182 eEGS_GUILD_MONEY_OUT_ACK (0x00794470).
        from darkblood.games.network.messages import GuildMoneyOutAck, GuildMoneyOutReq
        from darkblood.games.state import selected_character
        req = GuildMoneyOutReq.decode(body)
        self.transport.record('guild-money-out-req', body, amount=req.amount)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        remain_gold = 0
        if char:
            guild_money = char.get('guild_money', 0)
            withdraw = min(max(0, req.amount), guild_money)
            char['guild_money'] = guild_money - withdraw
            char['gold'] = char.get('gold', 0) + withdraw
            char['u66'] = char['gold']
            remain_gold = char['gold']
            self.store().save()
        ack = GuildMoneyOutAck(result=0, remain_gold=remain_gold).encode()
        await self.transport.send_event(event(2182, ack, correlation),
                                        note=f'guild money out ack (withdrawn={req.amount} remain={remain_gold})')

    async def on_2183(self, correlation, body):
        # eEGS_GUILD_LEVEL_UP_REQ (0x00790000.c:3250) -> 2184 eEGS_GUILD_LEVEL_UP_ACK (0x00753380).
        from darkblood.games.network.messages import GuildLevelUpAck, GuildLevelUpReq
        from darkblood.games.state import selected_character
        req = GuildLevelUpReq.decode(body)
        self.transport.record('guild-level-up-req', body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        new_level = 1
        if char:
            new_level = char.get('guild_level', 1) + 1
            char['guild_level'] = new_level
            self.store().save()
        ack = GuildLevelUpAck(result=0, new_level=new_level).encode()
        await self.transport.send_event(event(2184, ack, correlation),
                                        note=f'guild level up ack (new_level={new_level})')

    async def on_2185(self, correlation, body):
        # eEGS_GUILD_NOTICE_MODIFY_REQ (0x00790000.c:3278) -> 2186 eEGS_GUILD_NOTICE_MODIFY_ACK (0x0075A120).
        from darkblood.games.network.messages import GuildNoticeModifyAck, GuildNoticeModifyReq
        from darkblood.games.state import selected_character
        req = GuildNoticeModifyReq.decode(body)
        self.transport.record('guild-notice-modify-req', body, notice=req.notice)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            char['guild_notice'] = req.notice
            self.store().save()
        ack = GuildNoticeModifyAck(result=0).encode()
        await self.transport.send_event(event(2186, ack, correlation),
                                        note='guild notice modify ack')

    async def on_2188(self, correlation, body):
        # eEGS_GUILD_NOTICE_DELETE_REQ (0x00790000.c:3388) -> 2189 eEGS_GUILD_NOTICE_DELETE_ACK (0x0074B830).
        from darkblood.games.network.messages import GuildNoticeDeleteAck, GuildNoticeDeleteReq
        from darkblood.games.state import selected_character
        req = GuildNoticeDeleteReq.decode(body)
        self.transport.record('guild-notice-delete-req', body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            char.pop('guild_notice', None)
            self.store().save()
        ack = GuildNoticeDeleteAck(result=0).encode()
        await self.transport.send_event(event(2189, ack, correlation),
                                        note='guild notice delete ack')

    async def on_2214(self, correlation, body):
        # eEGS_GUILD_ALL_SKILL_INIT_REQ -> 2215 eEGS_GUILD_ALL_SKILL_INIT_ACK (0x00752D80).
        from darkblood.games.network.messages import GuildAllSkillInitAck, GuildAllSkillInitReq
        from darkblood.games.state import selected_character
        req = GuildAllSkillInitReq.decode(body)
        self.transport.record('guild-all-skill-init-req', body)
        char = None
        if 'id' in selected_character:
            char = self.store().get(self.account, selected_character['id'])
        if not char:
            chars = self.store().characters(self.account)
            char = chars[0] if chars else None
        if char:
            char['guild_skills'] = {}
            self.store().save()
        ack = GuildAllSkillInitAck(result=0, param=0).encode()
        await self.transport.send_event(event(2215, ack, correlation),
                                        note='guild all skill init ack')



