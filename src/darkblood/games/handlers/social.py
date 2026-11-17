import struct

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
        char = self.current_char()
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
        char = self.current_char()
        if char:
            char.pop('guild_uid', None)
            char.pop('guild_name', None)
            self.store().save()
        ack = GuildPersonLeaveAck(result=0).encode()
        await self.transport.send_event(event(2163, ack, correlation), note='guild person leave ack')

    async def on_2179(self, correlation, body):
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
                char['u66'] = char['gold']
            guild_money = char.setdefault('guild_money', 0) + deposit
            char['guild_money'] = guild_money
            self.store().save()
        ack = GuildMoneyInAck(result=0, remain_gold=guild_money).encode()
        await self.transport.send_event(event(2180, ack, correlation),
                                        note=f'guild money in ack (deposited={req.amount} guild_money={guild_money})')

    async def on_2181(self, correlation, body):
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
            char['u66'] = char['gold']
            guild_money = char['guild_money']
            self.store().save()
        ack = GuildMoneyOutAck(result=0, remain_gold=guild_money).encode()
        await self.transport.send_event(event(2182, ack, correlation),
                                        note=f'guild money out ack (withdrawn={req.amount} remain_guild_money={guild_money})')

    async def on_2183(self, correlation, body):
        # eEGS_GUILD_LEVEL_UP_REQ (0x00790000.c:3250) -> 2184 eEGS_GUILD_LEVEL_UP_ACK (0x00753380).
        from darkblood.games.network.messages import GuildLevelUpAck, GuildLevelUpReq
        from darkblood.games.state import selected_character
        req = GuildLevelUpReq.decode(body)
        self.transport.record('guild-level-up-req', body)
        char = self.current_char()
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
        char = self.current_char()
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
        char = self.current_char()
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
        char = self.current_char()
        if char:
            char['guild_skills'] = {}
            self.store().save()
        ack = GuildAllSkillInitAck(result=0, param=0).encode()
        await self.transport.send_event(event(2215, ack, correlation),
                                        note='guild all skill init ack')

    async def on_2221(self, correlation, body):
        # eEGS_POST_SEND_REQ (0x00795D70) -> 2222 eEGS_POST_SEND_ACK (0x00795F40).
        from darkblood.games.network.messages import PostSendAck, PostSendReq
        req = PostSendReq.decode(body)
        self.transport.record('post-send-req', body)
        ack = PostSendAck(result=0, items=[]).encode()
        await self.transport.send_event(event(2222, ack, correlation), note='post send ack')

    async def on_2223(self, correlation, body):
        # eEGS_POST_READ_REQ (0x007963C0) -> 2224 eEGS_POST_READ_ACK (0x0075A660).
        from darkblood.games.network.messages import PostReadAck, PostReadReq
        req = PostReadReq.decode(body)
        self.transport.record('post-read-req', body, mail_uid=req.mail_uid)
        ack = PostReadAck(result=0, mail_uid=req.mail_uid).encode()
        await self.transport.send_event(event(2224, ack, correlation), note=f'post read ack (uid={req.mail_uid})')

    async def on_2225(self, correlation, body):
        # eEGS_POST_GET_APPEND_ITEM_REQ (0x0079664C) -> 2226 eEGS_POST_GET_APPEND_ITEM_ACK (0x0077F8E0).
        from darkblood.games.network.messages import PostGetAppendItemAck, PostGetAppendItemReq
        from darkblood.games.state import selected_character
        req = PostGetAppendItemReq.decode(body)
        self.transport.record('post-get-append-item-req', body, mail_uid=req.mail_uid)
        char = self.current_char()
        char_gold = char.get('gold', 0) if char else 0
        ack = PostGetAppendItemAck(result=0, mail_uid=req.mail_uid, gold=char_gold, items=[]).encode()
        await self.transport.send_event(event(2226, ack, correlation),
                                        note=f'post get append item ack (uid={req.mail_uid})')

    async def on_2236(self, correlation, body):
        # eEGS_POST_DELETE_REQ (0x007964EC) -> 2237 eEGS_POST_DELETE_ACK (0x007715F0).
        from darkblood.games.network.messages import PostDeleteAck, PostDeleteReq
        req = PostDeleteReq.decode(body)
        self.transport.record('post-delete-req', body, mail_uids=req.mail_uids)
        ack = PostDeleteAck(result=0, mail_uids=req.mail_uids).encode()
        await self.transport.send_event(event(2237, ack, correlation),
                                        note=f'post delete ack (count={len(req.mail_uids)})')

    async def on_5040(self, correlation, body):
        # eERC_CHAT_REQ (0x007AC5E0) -> 5041 eERC_CHAT_ACK (0x007AC890).
        from darkblood.games.network.messages import ChatAck, ChatReq, LevelUpNot, ChangeExpNot
        from darkblood.games.state import selected_character
        req = ChatReq.decode(body)
        msg = req.message.strip()
        self.transport.record('chat-req', body, message=msg)

        char = self.current_char()

        char_name = char.get('name', 'Player') if char else 'Player'
        system_reply = None

        # In-Game GM Console Commands
        if msg.startswith('/'):
            parts = msg.split()
            cmd = parts[0].lower()
            if cmd == '/gold' and len(parts) > 1 and char:
                try:
                    amount = int(parts[1])
                    char['gold'] = char.get('gold', 0) + amount
                    char['u66'] = char['gold']
                    self.store().save()
                    system_reply = f'[GM] Added {amount} gold. Balance: {char["gold"]}'
                except ValueError:
                    system_reply = '[GM] Usage: /gold <amount>'
            elif cmd == '/levelup' and char:
                levels = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
                char['level'] = min(60, char.get('level', 1) + levels)
                char['sp'] = char.get('sp', 0) + (3 * levels)
                self.store().save()
                lvl_ack = LevelUpNot(
                    char_uid=char.get('id', 1),
                    new_level=char['level'],
                    max_hp=char.get('max_hp', 1000),
                    max_mp=char.get('max_mp', 500),
                    flag=True
                ).encode()
                await self.transport.send_event(event(5087, lvl_ack), note=f'gm levelup not (level={char["level"]})')
                system_reply = f'[GM] Leveled up by {levels}. Current level: {char["level"]}, SP: {char["sp"]}'
            elif cmd == '/sp' and len(parts) > 1 and char:
                try:
                    sp_amt = int(parts[1])
                    char['sp'] = char.get('sp', 0) + sp_amt
                    self.store().save()
                    system_reply = f'[GM] Added {sp_amt} SP. Total SP: {char["sp"]}'
                except ValueError:
                    system_reply = '[GM] Usage: /sp <amount>'
            elif cmd == '/item' and len(parts) > 1 and char:
                from darkblood.player_management.characters import add_reward_items
                icode = parts[1]
                icnt = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
                add_reward_items(char, [(icode, icnt)])
                self.store().save()
                system_reply = f'[GM] Granted {icnt}x {icode}'

        reply_msg = system_reply if system_reply else msg
        sender = 'System' if system_reply else char_name
        ack = ChatAck(result=0, channel=req.channel, sender=sender, message=reply_msg).encode()
        await self.transport.send_event(event(5041, ack, correlation), note=f'chat ack ({reply_msg})')

    async def on_2310(self, correlation, body):
        # eEGS_CHAR_NICK_CHANGE_REQ -> 2311 eEGS_CHAR_NICK_CHANGE_ACK (0x00780200).
        from darkblood.games.network.messages import CharNickChangeAck, CharNickChangeReq
        from darkblood.games.state import selected_character
        req = CharNickChangeReq.decode(body)
        new_name = req.new_name.strip()
        self.transport.record('char-nick-change-req', body, new_name=new_name)
        char = self.store().get(self.account, selected_character.get('id', 1)) if 'id' in selected_character else None
        if char and new_name:
            char['name'] = new_name
            self.store().save()
        ack = CharNickChangeAck(result=0, items=[], new_name=new_name).encode()
        await self.transport.send_event(event(2311, ack, correlation), note=f'char nick change ack ({new_name})')

    async def on_2314(self, correlation, body):
        # eEGS_GUILD_NAME_CHANGE_REQ -> 2315 eEGS_GUILD_NAME_CHANGE_ACK (0x00780590).
        from darkblood.games.network.messages import GuildNameChangeAck, GuildNameChangeReq
        req = GuildNameChangeReq.decode(body)
        new_name = req.new_name.strip()
        self.transport.record('guild-name-change-req', body, new_name=new_name)
        ack = GuildNameChangeAck(result=0, items=[], new_name=new_name).encode()
        await self.transport.send_event(event(2315, ack, correlation), note=f'guild name change ack ({new_name})')

    async def on_2319(self, correlation, body):
        # eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ -> 2320 eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK (0x00753960).
        from darkblood.games.network.messages import KeyboardSetCustomKeyAck, KeyboardSetCustomKeyReq
        from darkblood.games.state import selected_character
        req = KeyboardSetCustomKeyReq.decode(body)
        self.transport.record('keyboard-set-custom-key-req', body)
        char = self.store().get(self.account, selected_character.get('id', 1)) if 'id' in selected_character else None
        if char:
            char['custom_keys'] = body.hex()
            self.store().save()
        ack = KeyboardSetCustomKeyAck(result=0, keys_blob=req.keys_blob).encode()
        await self.transport.send_event(event(2320, ack, correlation), note='keyboard set custom key ack')

    async def on_5351(self, correlation, body):
        # eERC_REQUEST_TEACHING_REQ -> 5352 eERC_REQUEST_TEACHING_ACK (0x0075C200).
        from darkblood.games.network.messages import RequestTeachingAck, RequestTeachingReq
        req = RequestTeachingReq.decode(body)
        self.transport.record('request-teaching-req', body, target_uid=req.target_uid)
        ack = RequestTeachingAck(result=0, target_uid=req.target_uid, target_name='Student').encode()
        await self.transport.send_event(event(5352, ack, correlation), note=f'request teaching ack (target={req.target_uid})')

    async def on_5353(self, correlation, body):
        # eERC_ACCEPT_REQUEST_TEACHING_REQ -> 5354 eERC_ACCEPT_REQUEST_TEACHING_ACK (0x0075C430).
        from darkblood.games.network.messages import AcceptRequestTeachingAck, AcceptRequestTeachingReq
        req = AcceptRequestTeachingReq.decode(body)
        self.transport.record('accept-request-teaching-req', body, mentor_uid=req.mentor_uid)
        ack = AcceptRequestTeachingAck(result=0, accepted=True, mentor_uid=req.mentor_uid, mentor_name='Master').encode()
        await self.transport.send_event(event(5354, ack, correlation), note=f'accept request teaching ack (mentor={req.mentor_uid})')

    async def on_2335(self, correlation, body):
        # eEGS_TITLE_CHANGE_REQ -> 2336 eEGS_TITLE_CHANGE_ACK (0x007751C0).
        from darkblood.games.network.messages import TitleChangeAck, TitleChangeReq
        req = TitleChangeReq.decode(body)
        self.transport.record('title-change-req', body, title_id=req.title_id)
        ack = TitleChangeAck(result=0, title_id=req.title_id).encode()
        await self.transport.send_event(event(2336, ack, correlation), note=f'title change ack (title={req.title_id})')

    async def on_2327(self, correlation, body):
        # eEGS_ACHIEVE_GET_LIST_REQ -> 2328 eEGS_ACHIEVE_GET_LIST_ACK (0x0079D650).
        from darkblood.games.network.messages import AchieveGetListAck
        ack = AchieveGetListAck(result=0).encode()
        await self.transport.send_event(event(2328, ack, correlation), note='achieve get list ack')

    async def on_2446(self, correlation, body):
        # eEGS_ACHIEVE_DIV_UPDATE_REQ: tag 0x17 map of achievement progress
        # (live: 17 84 0f 0e000000 05000000 00000000 ...; entry layout not
        # recovered, recorded only) -> 2447 (0x0074B830 reads only the u32
        # result).
        self.transport.record('achieve-div-update', body)
        await self.transport.send_event(event(2447, struct.pack('<I', 0), correlation),
                                        note='achieve div update ack')

    async def on_5165(self, correlation, body):
        # eERC_ARENA_BACK_TO_SQUARE_REQ -> 5166 eERC_ARENA_BACK_TO_SQUARE_ACK (0x00758550).
        from darkblood.games.network.messages import ArenaBackToSquareAck
        ack = ArenaBackToSquareAck(result=0).encode()
        await self.transport.send_event(event(5166, ack, correlation), note='arena back to square ack')

    async def on_5256(self, correlation, body):
        # eERC_SECOND_PASS_CREATE_REQ -> 5257 eERC_SECOND_PASS_CREATE_ACK (0x0075B020).
        from darkblood.games.network.messages import SecondPassCreateAck
        ack = SecondPassCreateAck(result=0).encode()
        await self.transport.send_event(event(5257, ack, correlation), note='second pass create ack')

    async def on_5258(self, correlation, body):
        # eERC_SECOND_PASS_MODIFY_REQ -> 5259 eERC_SECOND_PASS_MODIFY_ACK (0x0075B050).
        from darkblood.games.network.messages import SecondPassModifyAck
        ack = SecondPassModifyAck(result=0).encode()
        await self.transport.send_event(event(5259, ack, correlation), note='second pass modify ack')

    async def on_5260(self, correlation, body):
        # eERC_SECOND_PASS_AUTH_REQ -> 5261 eERC_SECOND_PASS_AUTH_ACK (0x0075B080).
        from darkblood.games.network.messages import SecondPassAuthAck
        ack = SecondPassAuthAck(result=0).encode()
        await self.transport.send_event(event(5261, ack, correlation), note='second pass auth ack')

    async def on_6011(self, correlation, body):
        # eERT_REQUEST_CHAR_INFO_REQ -> 6012 eERT_REQUEST_CHAR_INFO_ACK (0x00790FA0).
        from darkblood.games.network.messages import RequestCharInfoAck, RequestCharInfoReq
        req = RequestCharInfoReq.decode(body)
        self.transport.record('request-char-info-req', body, char_uid=req.char_uid)
        ack = RequestCharInfoAck(result=0).encode()
        await self.transport.send_event(event(6012, ack, correlation), note=f'request char info ack (char={req.char_uid})')

    async def on_6028(self, correlation, body):
        # eERT_REQUEST_ITEM_INFO_REQ -> 6029 eERT_REQUEST_ITEM_INFO_ACK (0x00766C20).
        from darkblood.games.network.messages import RequestItemInfoAck, RequestItemInfoReq
        req = RequestItemInfoReq.decode(body)
        self.transport.record('request-item-info-req', body, item_uid=req.item_uid)
        ack = RequestItemInfoAck(result=0, item_uid=req.item_uid).encode()
        await self.transport.send_event(event(6029, ack, correlation), note=f'request item info ack (item={req.item_uid})')

    async def on_2164(self, correlation, body):
        # eEGS_GUILD_PERSON_GRADE_MODIFY_REQ -> 2165 eEGS_GUILD_PERSON_GRADE_MODIFY_ACK (0x00753170).
        from darkblood.games.network.messages import GuildPersonGradeModifyAck, GuildPersonGradeModifyReq
        req = GuildPersonGradeModifyReq.decode(body)
        self.transport.record('guild-person-grade-modify-req', body, member_uid=req.member_uid, new_grade=req.new_grade)
        ack = GuildPersonGradeModifyAck(result=0, member_uid=req.member_uid, new_grade=req.new_grade).encode()
        await self.transport.send_event(event(2165, ack, correlation), note=f'guild person grade modify ack (member={req.member_uid})')

    async def on_2234(self, correlation, body):
        # eEGS_POST_RETURN_REQ -> 2235 eEGS_POST_RETURN_ACK (0x00771470).
        from darkblood.games.network.messages import PostReturnAck, PostReturnReq
        req = PostReturnReq.decode(body)
        self.transport.record('post-return-req', body, mail_id=req.mail_id)
        ack = PostReturnAck(result=0).encode()
        await self.transport.send_event(event(2235, ack, correlation), note=f'post return ack (mail={req.mail_id})')





