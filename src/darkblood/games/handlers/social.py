import struct

from darkblood.core.serialization.jser import WireError, event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.network.messages import FriendListAck, GuildOrAttendanceAck, PostListAck


class SocialHandlers(BaseDomainService):
    """Mailbox, friends, block list and client notifications."""

    @packet_handler(2131)
    async def handle_friend_list(self, correlation, body):
        # eEGS_FRIEND_LIST_REQUEST_REQ -> eEGS_FRIEND_LIST_REQUEST_ACK (2132), handler 0x7712E0:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        char = self.current_char()
        friends = [self._friend_entry(uid) for uid in (char or {}).get('friends', [])]
        friends = [f for f in friends if f]
        ack = FriendListAck(friends={f.uid: f for f in friends}).encode()
        await self.transport.send_event(event(2132, ack, correlation),
                                        note='friend list ack (%d)' % len(friends))
        # Live, 2131 follows 2006 by ~2 s, right before the relay JoinGroup:
        # the earliest point where a town peer sent by 5027 is displayed.
        from darkblood.games.world import GameWorldManager
        await GameWorldManager.get().player_ready(self.session)

    def _friend_entry(self, uid):
        """FriendEntry for a character of any account, or None."""
        from darkblood.games.network.messages import FriendEntry
        from darkblood.games.world import GameWorldManager
        for _, char in self.store().all_characters():
            if char.get('id') == uid:
                return FriendEntry(uid=uid, name=char.get('name', ''), level=int(char.get('level', 1)),
                                   char_class=int(char.get('char_class', 0)),
                                   location=1 if uid in GameWorldManager.get().players else -1)
        return None

    @packet_handler(2569)
    async def handle_guild_or_attendance(self, correlation, body):
        # Opcode 2569 -> 2570 ACK, handler 0x772160:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        ack = GuildOrAttendanceAck().encode()
        await self.transport.send_event(event(2570, ack, correlation), note='opcode 2570 ack')

    @packet_handler(2352)
    async def handle_ip_address(self, correlation, body):
        # eEGS_IP_ADDRESS_NOT: client LAN/WAN IP notification only.
        pass

    @packet_handler(2203)
    async def handle_computer_stat(self, correlation, body):
        # eEGS_COMPUTER_STAT_NOT: client hardware report; notification only.
        pass

    @packet_handler(0)
    async def handle_keepalive(self, correlation, body):
        # Application-level keepalive heartbeat sent by client periodically.
        pass

    @packet_handler(2024)
    async def handle_get_invite_list(self, correlation, body):
        # eEGS_GET_INVITELIST_REQ (Find user) -> 2025 eEGS_GET_INVITELIST_ACK
        # (0x006A2E10): the other online players that match the search.
        from darkblood.games.network.messages import GetInviteListAck, GetInviteListReq, RoomMemberInfo
        from darkblood.games.world import SQUARE_UID_MASK, GameWorldManager, square_uid
        try:
            req = GetInviteListReq.decode(body)
        except (WireError, struct.error):
            await self.transport.send_event(event(2025, GetInviteListAck().encode(), correlation),
                                            note='invite list ack (bad request)')
            return
        square = req.square_uid & SQUARE_UID_MASK if req.square_uid >= 0 else None
        users = []
        for player in GameWorldManager.get().players.values():
            if player.char_id == self.char_id:
                continue
            record = player.char_data
            level = int(record.get('level', 1))
            char_class = int(record.get('char_class', 0)) & 0xFF
            if not req.low_level <= level <= req.high_level:
                continue
            if req.job < 7 and char_class != req.job:  # 7 = eCK_Max, taken as "any class"
                continue
            if square is not None and player.square_id != square:
                continue
            if req.layer_net_id != -1 and player.layer_id != req.layer_net_id:
                continue
            users.append(RoomMemberInfo(square_uid=square_uid(player.square_id), char_uid=player.char_id,
                                        name=record.get('name', ''), char_class=char_class, level=min(level, 0xFF)))
        # Page size not recovered: everything is sent as page 0.
        ack = GetInviteListAck(users=users).encode()
        await self.transport.send_event(event(2025, ack, correlation),
                                        note='invite list ack (%d users, lv %d-%d, job %d)'
                                             % (len(users), req.low_level, req.high_level, req.job))

    @packet_handler(2139)
    async def handle_friend_list_add(self, correlation, body):
        # eEGS_FRIEND_LIST_ADD_REQ (0x00790000.c:1595) -> 2140 eEGS_FRIEND_LIST_ADD_ACK (0x007591A0).
        from darkblood.games.network.messages import FriendListAddAck, FriendListAddReq
        req = FriendListAddReq.decode(body)
        self.transport.record('friend-add', body, name=req.char_name)
        char = self.current_char()
        target = next((c for _, c in self.store().all_characters()
                       if c.get('name', '').lower() == req.char_name.lower()), None)
        if not char or not target or target.get('id') == char.get('id'):
            await self.transport.send_event(event(2140, FriendListAddAck(result=0xCE).encode(), correlation),
                                            note=f'friend add fail ({req.char_name} not found)')
            return
        friends = char.setdefault('friends', [])
        if target['id'] not in friends:
            friends.append(target['id'])
            self.store().save()
        ack = FriendListAddAck(result=0, friend=self._friend_entry(target['id'])).encode()
        await self.transport.send_event(event(2140, ack, correlation), note=f'friend add ack ({req.char_name})')

    @packet_handler(2135)
    async def handle_friend_list_delete(self, correlation, body):
        # eEGS_FRIEND_LIST_DELETE_REQ (0x00790000.c:1824) -> 2136 eEGS_FRIEND_LIST_DELETE_ACK (0x00759560).
        from darkblood.games.network.messages import FriendListDeleteAck, FriendListDeleteReq
        req = FriendListDeleteReq.decode(body)
        self.transport.record('friend-delete', body, char_uid=req.char_uid)
        char = self.current_char()
        if char and req.char_uid in char.get('friends', []):
            char['friends'].remove(req.char_uid)
            self.store().save()
        ack = FriendListDeleteAck(result=0, char_uid=req.char_uid).encode()
        await self.transport.send_event(event(2136, ack, correlation), note=f'friend delete ack ({req.char_uid})')

    @packet_handler(2128)
    async def handle_use_speaker_item(self, correlation, body):
        # eEGS_USE_SPEAKER_ITEM_REQ (0x00790000.c:1992) -> 2129 eEGS_USE_SPEAKER_ITEM_ACK (0x0077F320).
        from darkblood.games.network.messages import UseSpeakerItemAck, UseSpeakerItemReq
        req = UseSpeakerItemReq.decode(body)
        self.transport.record('use-speaker-req', body, speaker=req.speaker_uid, msg=req.message)
        ack = UseSpeakerItemAck(result=0, speaker_uid=req.speaker_uid).encode()
        await self.transport.send_event(event(2129, ack, correlation),
                                        note=f'use speaker ack (speaker={req.speaker_uid} msg={req.message[:20]})')

    @packet_handler(2150)
    async def handle_guild_create(self, correlation, body):
        # eEGS_GUILD_CREATE_REQ -> 2151 eEGS_GUILD_CREATE_ACK (0x00793720).
        from darkblood.games.network.messages import GuildCreateAck, GuildCreateReq
        req = GuildCreateReq.decode(body)
        self.transport.record('guild-create-req', body, name=req.guild_name)
        char = self.current_char()
        if char is None:
            await self.transport.send_event(event(2151, GuildCreateAck(result=1).encode(), correlation),
                                            note='guild create fail (no character)')
            return
        char['guild_name'] = req.guild_name
        gold = char.get('gold', 100000)
        self.store().save()
        ack = GuildCreateAck(result=0, guild_uid=1001, guild_name=req.guild_name, remain_gold=gold).encode()
        await self.transport.send_event(event(2151, ack, correlation),
                                        note=f'guild create ack (name={req.guild_name})')

    @packet_handler(5121)
    async def handle_guild_create_proposal(self, correlation, body):
        # eERC_GUILD_CREATE_PROPOSAL_REQ (0x00790000.c:2514) -> 5122 eERC_GUILD_CREATE_PROPOSAL_ACK (0x00759750).
        from darkblood.games.network.messages import GuildCreateProposalAck, GuildCreateProposalReq
        req = GuildCreateProposalReq.decode(body)
        self.transport.record('guild-proposal-req', body, name=req.guild_name)
        ack = GuildCreateProposalAck(result=0).encode()
        await self.transport.send_event(event(5122, ack, correlation),
                                        note=f'guild create proposal ack (name={req.guild_name})')

    @packet_handler(2133)
    async def handle_friend_list_update(self, correlation, body):
        # eEGS_FRIEND_LIST_UPDATE_REQ (0x00790000.c:1735) -> 2134 eEGS_FRIEND_LIST_UPDATE_ACK (0x00752E80).
        from darkblood.games.network.messages import FriendListUpdateAck, FriendListUpdateReq
        req = FriendListUpdateReq.decode(body)
        self.transport.record('friend-update-req', body, char_uid=req.char_uid, comment=req.comment)
        ack = FriendListUpdateAck(result=0, char_uid=req.char_uid, comment=req.comment).encode()
        await self.transport.send_event(event(2134, ack, correlation),
                                        note=f'friend list update ack (uid={req.char_uid})')

    @packet_handler(2155)
    async def handle_guild_person_join(self, correlation, body):
        # eEGS_GUILD_PERSON_JOIN_REQ (0x00790000.c:2837) -> 2156 eEGS_GUILD_PERSON_JOIN_ACK (0x0075A220).
        from darkblood.games.network.messages import GuildPersonJoinAck, GuildPersonJoinReq
        req = GuildPersonJoinReq.decode(body)
        self.transport.record('guild-join-req', body, guild_uid=req.guild_uid)
        char = self.current_char()
        if char:
            char['guild_uid'] = req.guild_uid
            self.store().save()
        ack = GuildPersonJoinAck(result=0).encode()
        await self.transport.send_event(event(2156, ack, correlation),
                                        note=f'guild person join ack (guild={req.guild_uid})')

    @packet_handler(2160)
    async def handle_guild_invite(self, correlation, body):
        # eEGS_GUILD_INVITE_REQ -> 2161 eEGS_GUILD_INVITE_ACK (0x00759870).
        from darkblood.games.network.messages import GuildInviteAck, GuildInviteReq
        req = GuildInviteReq.decode(body)
        self.transport.record('guild-invite-req', body, target=req.char_name)
        ack = GuildInviteAck(result=0).encode()
        await self.transport.send_event(event(2161, ack, correlation),
                                        note=f'guild invite ack (target={req.char_name})')

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
            self.store().save()
        ack = GuildPersonLeaveAck(result=0).encode()
        await self.transport.send_event(event(2163, ack, correlation), note='guild person leave ack')

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
                char['u66'] = char['gold']
            guild_money = char.setdefault('guild_money', 0) + deposit
            char['guild_money'] = guild_money
            self.store().save()
        ack = GuildMoneyInAck(result=0, remain_gold=guild_money).encode()
        await self.transport.send_event(event(2180, ack, correlation),
                                        note=f'guild money in ack (deposited={req.amount} guild_money={guild_money})')

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
            char['u66'] = char['gold']
            guild_money = char['guild_money']
            self.store().save()
        ack = GuildMoneyOutAck(result=0, remain_gold=guild_money).encode()
        await self.transport.send_event(event(2182, ack, correlation),
                                        note=f'guild money out ack (withdrawn={req.amount} remain_guild_money={guild_money})')

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
            self.store().save()
        ack = GuildLevelUpAck(result=0, new_level=new_level).encode()
        await self.transport.send_event(event(2184, ack, correlation),
                                        note=f'guild level up ack (new_level={new_level})')

    @packet_handler(2185)
    async def handle_guild_notice_modify(self, correlation, body):
        # eEGS_GUILD_NOTICE_MODIFY_REQ (0x00790000.c:3278) -> 2186 eEGS_GUILD_NOTICE_MODIFY_ACK (0x0075A120).
        from darkblood.games.network.messages import GuildNoticeModifyAck, GuildNoticeModifyReq
        req = GuildNoticeModifyReq.decode(body)
        self.transport.record('guild-notice-modify-req', body, notice=req.notice)
        char = self.current_char()
        if char:
            char['guild_notice'] = req.notice
            self.store().save()
        ack = GuildNoticeModifyAck(result=0).encode()
        await self.transport.send_event(event(2186, ack, correlation),
                                        note='guild notice modify ack')

    @packet_handler(2188)
    async def handle_guild_notice_delete(self, correlation, body):
        # eEGS_GUILD_NOTICE_DELETE_REQ (0x00790000.c:3388) -> 2189 eEGS_GUILD_NOTICE_DELETE_ACK (0x0074B830).
        from darkblood.games.network.messages import GuildNoticeDeleteAck, GuildNoticeDeleteReq
        req = GuildNoticeDeleteReq.decode(body)
        self.transport.record('guild-notice-delete-req', body)
        char = self.current_char()
        if char:
            char.pop('guild_notice', None)
            self.store().save()
        ack = GuildNoticeDeleteAck(result=0).encode()
        await self.transport.send_event(event(2189, ack, correlation),
                                        note='guild notice delete ack')

    @packet_handler(2214)
    async def handle_guild_all_skill_init(self, correlation, body):
        # eEGS_GUILD_ALL_SKILL_INIT_REQ -> 2215 eEGS_GUILD_ALL_SKILL_INIT_ACK (0x00752D80).
        from darkblood.games.network.messages import GuildAllSkillInitAck, GuildAllSkillInitReq
        req = GuildAllSkillInitReq.decode(body)
        self.transport.record('guild-all-skill-init-req', body)
        char = self.current_char()
        if char:
            char['guild_skills'] = {}
            self.store().save()
        ack = GuildAllSkillInitAck(result=0, param=0).encode()
        await self.transport.send_event(event(2215, ack, correlation),
                                        note='guild all skill init ack')

    @packet_handler(5040)
    async def handle_chat(self, correlation, body):
        # eERC_CHAT_REQ (0x007AC5E0) -> 5041 eERC_CHAT_ACK (0x007AC890).
        from darkblood.games.network.messages import ChatAck, ChatReq
        from darkblood.games.progression import level_up_not
        from darkblood.games.progression import MAX_LEVEL, add_ap, advance_level
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
                previous = char.get('level', 1)
                gained = min(levels, max(0, MAX_LEVEL - previous))
                if gained:
                    level = previous + gained
                    advance_level(char, level, exp=0)
                    self.store().save()
                    await self.transport.send_event(event(5087, level_up_not(char).encode()),
                                                    note=f'gm levelup not (level={level})')
                system_reply = f'[GM] Leveled up by {gained}. Current level: {previous + gained}, SP: {char.get("sp", 0)}'
            elif cmd == '/sp' and len(parts) > 1 and char:
                try:
                    sp_amt = int(parts[1])
                    add_ap(char, sp_amt)
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
            elif cmd == '/bags' and char:
                from darkblood.player_management.characters import free_bag_slots, grant_test_bags
                changed = grant_test_bags(char)
                self.store().save()
                system_reply = (f'[GM] {changed} bag(s) set to 20 cells, {free_bag_slots(char)} free. '
                                'Select the character again to load them.')

        reply_msg = system_reply if system_reply else msg
        sender = 'System' if system_reply else char_name
        ack = ChatAck(result=0, channel=req.channel, sender=sender, target=req.target, message=reply_msg).encode()
        await self.transport.send_event(event(5041, ack, correlation), note=f'chat ack ({reply_msg})')
        if system_reply or not msg:
            return
        # Other players receive the line as an unsolicited 5041 (global handler
        # 0x007AC890). Channel 1 is normal chat (live), 2 a whisper (the handler
        # compares the target name); the party/guild/team values are not
        # recovered yet, so any other channel goes to the sender's party room.
        recipients = self._chat_recipients(req.channel, req.target)
        packet = event(5041, ack)
        for session in recipients:
            try:
                await session.transport.send_event(packet, note=f'chat from {char_name} (channel {req.channel})')
            except (ConnectionError, OSError):
                pass
        self.transport.record('chat-route', b'', channel=req.channel, target=req.target, recipients=len(recipients))

    def _chat_recipients(self, channel, target):
        """Sessions other than the sender that should see a chat line."""
        from darkblood.games.world import GameWorldManager
        world = GameWorldManager.get()
        me = self.session
        if channel == 2:
            wanted = (target or '').strip().lower()
            return [p.session for p in world.players.values()
                    if p.session is not me and p.char_data.get('name', '').lower() == wanted]
        room = me.dungeon.room
        in_party = room is not None and room.info.name != '_singleplay'
        if channel != 1 or (in_party and room.started):
            # Party channel, or normal chat inside a shared dungeon run.
            return [m for m in room.members if m is not me] if in_party else []
        player = world.get_player(me.active_char_id) if me.active_char_id else None
        square = player.square_id if player else me.square_id
        return [p.session for p in world.get_players_in_square(square) if p.session is not me]

    @packet_handler(2310)
    async def handle_char_nick_change(self, correlation, body):
        # eEGS_CHAR_NICK_CHANGE_REQ -> 2311 eEGS_CHAR_NICK_CHANGE_ACK (0x00780200).
        from darkblood.games.network.messages import CharNickChangeAck, CharNickChangeReq
        req = CharNickChangeReq.decode(body)
        new_name = req.new_name.strip()
        self.transport.record('char-nick-change-req', body, new_name=new_name)
        char = self.store().get(self.account, self.char_id) 
        if char and new_name:
            char['name'] = new_name
            self.store().save()
        ack = CharNickChangeAck(result=0, items=[], new_name=new_name).encode()
        await self.transport.send_event(event(2311, ack, correlation), note=f'char nick change ack ({new_name})')

    @packet_handler(2314)
    async def handle_guild_name_change(self, correlation, body):
        # eEGS_GUILD_NAME_CHANGE_REQ -> 2315 eEGS_GUILD_NAME_CHANGE_ACK (0x00780590).
        from darkblood.games.network.messages import GuildNameChangeAck, GuildNameChangeReq
        req = GuildNameChangeReq.decode(body)
        new_name = req.new_name.strip()
        self.transport.record('guild-name-change-req', body, new_name=new_name)
        ack = GuildNameChangeAck(result=0, items=[], new_name=new_name).encode()
        await self.transport.send_event(event(2315, ack, correlation), note=f'guild name change ack ({new_name})')

    @packet_handler(2319)
    async def handle_keyboard_set_custom_key(self, correlation, body):
        # eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ -> 2320 eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK (0x00753960).
        from darkblood.games.network.messages import KeyboardSetCustomKeyAck, KeyboardSetCustomKeyReq
        req = KeyboardSetCustomKeyReq.decode(body)
        self.transport.record('keyboard-set-custom-key-req', body)
        char = self.store().get(self.account, self.char_id) 
        if char:
            char['custom_keys'] = body.hex()
            self.store().save()
        ack = KeyboardSetCustomKeyAck(result=0, keys=req.keys_blob.decode('utf-16le', errors='ignore')).encode()
        await self.transport.send_event(event(2320, ack, correlation), note='keyboard set custom key ack')

    @packet_handler(5351)
    async def handle_request_teaching(self, correlation, body):
        # eERC_REQUEST_TEACHING_REQ -> 5352 eERC_REQUEST_TEACHING_ACK (0x0075C200).
        from darkblood.games.network.messages import RequestTeachingAck, RequestTeachingReq
        req = RequestTeachingReq.decode(body)
        self.transport.record('request-teaching-req', body, target_uid=req.target_uid)
        ack = RequestTeachingAck(result=0, target_uid=req.target_uid, target_name='Student').encode()
        await self.transport.send_event(event(5352, ack, correlation), note=f'request teaching ack (target={req.target_uid})')

    @packet_handler(5353)
    async def handle_accept_request_teaching(self, correlation, body):
        # eERC_ACCEPT_REQUEST_TEACHING_REQ -> 5354 eERC_ACCEPT_REQUEST_TEACHING_ACK (0x0075C430).
        from darkblood.games.network.messages import AcceptRequestTeachingAck, AcceptRequestTeachingReq
        req = AcceptRequestTeachingReq.decode(body)
        self.transport.record('accept-request-teaching-req', body, mentor_uid=req.mentor_uid)
        ack = AcceptRequestTeachingAck(result=0, accepted=True, mentor_uid=req.mentor_uid, mentor_name='Master').encode()
        await self.transport.send_event(event(5354, ack, correlation), note=f'accept request teaching ack (mentor={req.mentor_uid})')

    @packet_handler(2335)
    async def handle_title_change(self, correlation, body):
        # eEGS_TITLE_CHANGE_REQ -> 2336 eEGS_TITLE_CHANGE_ACK (0x007751C0).
        from darkblood.games.network.messages import TitleChangeAck, TitleChangeReq
        req = TitleChangeReq.decode(body)
        self.transport.record('title-change-req', body, title_id=req.title_id)
        ack = TitleChangeAck(result=0, title_id=req.title_id).encode()
        await self.transport.send_event(event(2336, ack, correlation), note=f'title change ack (title={req.title_id})')

    @packet_handler(2327)
    async def handle_achieve_get_list(self, correlation, body):
        # eEGS_ACHIEVE_GET_LIST_REQ -> 2328 eEGS_ACHIEVE_GET_LIST_ACK (0x0079D650).
        from darkblood.games import achievements
        from darkblood.games.network.messages import AchieveCompletion, AchieveEntry, AchieveGetListAck
        char = self.current_char() or {}
        entries = [AchieveEntry(h, t) for h, t in achievements.completed_entries(char)]
        ack = AchieveGetListAck(divisions=achievements.division_totals(char),
                                completed={e.achieve_hash: e for e in entries},
                                completions=[AchieveCompletion(e.achieve_hash) for e in entries]).encode()
        await self.transport.send_event(event(2328, ack, correlation),
                                        note=f'achieve get list ack ({len(entries)} completed)')

    @packet_handler(2444)
    async def handle_achieve_update(self, correlation, body):
        # eEGS_ACHIEVE_UPDATE_REQ (sender 0x007992D0): vector of u32 achievement
        # hashes completed client-side -> 2445 (u32 result, 0x0074B830), then 2330.
        from darkblood.games import achievements
        from darkblood.games.network.messages import AchieveCompleteNot, AchieveCompletion, AchieveEntry, AchieveUpdateReq
        self.transport.record('achieve-update', body)
        char = self.current_char()
        completed = []
        try:
            report = AchieveUpdateReq.decode(body)
        except (WireError, struct.error, IndexError):
            report = None
        if char is not None and report is not None:
            completed = achievements.apply_client_completions(char, report.hashes)
            self.store().save()
        await self.transport.send_event(event(2445, struct.pack('<I', 0), correlation),
                                        note='achieve update ack')
        if completed:
            entries = [AchieveEntry(h, t) for h, t in achievements.completed_entries(char, completed)]
            await self.transport.send_event(event(2330, AchieveCompleteNot(entries, [AchieveCompletion(e.achieve_hash) for e in entries]).encode()),
                                            note='achievements completed: %s' % ', '.join(completed))

    @packet_handler(2446)
    async def handle_achieve_div_update(self, correlation, body):
        # eEGS_ACHIEVE_DIV_UPDATE_REQ (per-run division amounts) -> 2447
        # (0x0074B830 reads only the u32 result), then 2330 for completions.
        from darkblood.games import achievements
        from darkblood.games.network.messages import AchieveCompleteNot, AchieveCompletion, AchieveDivUpdateReq, AchieveEntry
        self.transport.record('achieve-div-update', body)
        char = self.current_char()
        completed = []
        try:
            report = AchieveDivUpdateReq.decode(body)
        except (WireError, struct.error, IndexError):
            report = None
        if char is not None and report is not None:
            completed = achievements.apply_division_report(char, report.amounts)
            self.store().save()
        await self.transport.send_event(event(2447, struct.pack('<I', 0), correlation),
                                        note='achieve div update ack')
        if completed:
            entries = [AchieveEntry(h, t) for h, t in achievements.completed_entries(char, completed)]
            await self.transport.send_event(event(2330, AchieveCompleteNot(entries, [AchieveCompletion(e.achieve_hash) for e in entries]).encode()),
                                            note='achievements completed: %s' % ', '.join(completed))

    @packet_handler(5165)
    async def handle_arena_back_to_square(self, correlation, body):
        # eERC_ARENA_BACK_TO_SQUARE_REQ -> 5166 eERC_ARENA_BACK_TO_SQUARE_ACK (0x00758550).
        from darkblood.games.network.messages import ArenaBackToSquareAck
        ack = ArenaBackToSquareAck(result=0).encode()
        await self.transport.send_event(event(5166, ack, correlation), note='arena back to square ack')

    @packet_handler(5256)
    async def handle_second_pass_create(self, correlation, body):
        # eERC_SECOND_PASS_CREATE_REQ -> 5257 eERC_SECOND_PASS_CREATE_ACK (0x0075B020).
        from darkblood.games.network.messages import SecondPassCreateAck
        ack = SecondPassCreateAck(result=0).encode()
        await self.transport.send_event(event(5257, ack, correlation), note='second pass create ack')

    @packet_handler(5258)
    async def handle_second_pass_modify(self, correlation, body):
        # eERC_SECOND_PASS_MODIFY_REQ -> 5259 eERC_SECOND_PASS_MODIFY_ACK (0x0075B050).
        from darkblood.games.network.messages import SecondPassModifyAck
        ack = SecondPassModifyAck(result=0).encode()
        await self.transport.send_event(event(5259, ack, correlation), note='second pass modify ack')

    @packet_handler(5260)
    async def handle_second_pass_auth(self, correlation, body):
        # eERC_SECOND_PASS_AUTH_REQ -> 5261 eERC_SECOND_PASS_AUTH_ACK (0x0075B080).
        from darkblood.games.network.messages import SecondPassAuthAck
        ack = SecondPassAuthAck(result=0).encode()
        await self.transport.send_event(event(5261, ack, correlation), note='second pass auth ack')

    @packet_handler(6011)
    async def handle_request_char_info(self, correlation, body):
        # eERT_REQUEST_CHAR_INFO_REQ -> 6012 eERT_REQUEST_CHAR_INFO_ACK (0x00790FA0).
        from darkblood.games.network.messages import RequestCharInfoAck, RequestCharInfoReq
        req = RequestCharInfoReq.decode(body)
        self.transport.record('request-char-info-req', body, char_uid=req.char_uid)
        ack = RequestCharInfoAck(result=0).encode()
        await self.transport.send_event(event(6012, ack, correlation), note=f'request char info ack (char={req.char_uid})')

    @packet_handler(6028)
    async def handle_request_item_info(self, correlation, body):
        # eERT_REQUEST_ITEM_INFO_REQ -> 6029 eERT_REQUEST_ITEM_INFO_ACK (0x00766C20).
        from darkblood.games.network.messages import RequestItemInfoAck, RequestItemInfoReq
        req = RequestItemInfoReq.decode(body)
        self.transport.record('request-item-info-req', body, item_uid=req.item_uid)
        ack = RequestItemInfoAck(result=0, item_uid=req.item_uid).encode()
        await self.transport.send_event(event(6029, ack, correlation), note=f'request item info ack (item={req.item_uid})')

    @packet_handler(2164)
    async def handle_guild_person_grade_modify(self, correlation, body):
        # eEGS_GUILD_PERSON_GRADE_MODIFY_REQ -> 2165 eEGS_GUILD_PERSON_GRADE_MODIFY_ACK (0x00753170).
        from darkblood.games.network.messages import GuildPersonGradeModifyAck, GuildPersonGradeModifyReq
        req = GuildPersonGradeModifyReq.decode(body)
        member_uid = req.member_uids[0] if req.member_uids else 0
        self.transport.record('guild-person-grade-modify-req', body, member_uids=req.member_uids, new_grade=req.new_grade)
        ack = GuildPersonGradeModifyAck(result=0, member_uid=member_uid, new_grade=req.new_grade).encode()
        await self.transport.send_event(event(2165, ack, correlation), note=f'guild person grade modify ack (member={member_uid})')

    # =========================================================================
    # Party Subsystem Handlers (Opcodes 2100-2107, 5049-5056)
    # =========================================================================

    @packet_handler(2100)
    async def handle_legacy_party_invite(self, correlation, body):
        """Opcode 2100 (eEGS_PARTY_INVITE_REQ) -> 2101 (eEGS_PARTY_INVITE_ACK).

        Client handler: 0x00758700. Invites target player to co-op party.
        """
        from darkblood.games.network.messages.party import LegacyPartyInviteReq
        req = LegacyPartyInviteReq.decode(body)
        await self._invite_to_party(2101, correlation, req.target_uid, '')

    @packet_handler(5049)
    async def handle_party_invite(self, correlation, body):
        """Opcode 5049 (eERC_INVITE_REQ) -> 5050 (eERC_INVITE_ACK).

        Client handler: 0x00758700. Invites target player to co-op party.
        """
        from darkblood.games.network.messages.party import PartyInviteReq
        req = PartyInviteReq.decode(body)
        await self._invite_to_party(5050, correlation, req.target_uid, '')

    @packet_handler(5092)
    async def handle_party_invite_by_nick(self, correlation, body):
        """Opcode 5092 (eERC_INVITE_USE_NICK_REQ): party invite by nickname.

        The sender (0x007ABAA0) waits for no dedicated ack; the result goes
        out as 5050, like a 5049 invite.
        """
        from darkblood.games.network.messages.party import InviteUseNickReq
        try:
            req = InviteUseNickReq.decode(body)
        except (WireError, UnicodeDecodeError):
            self.transport.record('bad-invite-nick', body)
            return
        await self._invite_to_party(5050, correlation, 0, req.name)

    @staticmethod
    def _char_id(uid):
        """Character id inside a client UID.

        Peers are announced with the server key (31) in bits 54-58, so the
        client sends e.g. 0x07C0000000000001 for character 1. Live 2026-11-21:
        the unmasked lookup found no player, so no 5051 reached the invitee.
        """
        from darkblood.games.world import SQUARE_UID_MASK
        return int(uid) & SQUARE_UID_MASK if uid and uid > 0 else int(uid or 0)

    async def _invite_to_party(self, ack_opcode, correlation, target_id, target_name):
        """Shared invite path for 2100, 5049 and 5092 (target by id or name)."""
        target_id = self._char_id(target_id)
        from darkblood.games.network.messages.party import PartyInviteAck
        from darkblood.games.world import PartyManager
        char = self.current_char()
        char_id = char.get('id', 0) if char else self.session.active_char_id or 0
        char_name = char.get('name', 'Leader') if char else 'Leader'
        char_class = char.get('char_class', 0) if char else 0
        level = char.get('level', 1) if char else 1

        if not target_id and target_name:
            target = next((c for _, c in self.store().all_characters()
                           if c.get('name', '').lower() == target_name.lower()), None)
            if target:
                target_id = target.get('id', 0)

        room = self.session.dungeon.room
        pending = room.join_requests.pop(target_id, None) if room is not None else None
        if pending is not None and room.host is self.session:
            # Host accepted a 5047 join request (OnBtn_Party_Accept on the host
            # calls AcceptJoinRoomREQ = 5049): the requester joins at once and gets
            # 5004 for its pending 5047. A second invite/accept round never
            # completed live (the requester's Accept handler did not run).
            requester, request_correlation = pending
            await self.transport.send_event(event(ack_opcode, PartyInviteAck(result=0).encode(), correlation),
                                            note=f'party invite ack (join request of {target_id} accepted)')
            if requester.dungeon.room is None:
                await requester.dungeon.join_room(room, request_correlation)
            return
        res, _ = PartyManager.get().invite_player(char_id, target_id, char_name, char_class, level, session=self)
        ack = PartyInviteAck(result=res).encode()
        await self.transport.send_event(event(ack_opcode, ack, correlation),
                                        note=f'party invite ack (res={res} target={target_id})')
        if res == 0 and target_id:
            await self._send_party_invite_notice(char_id, char_name, target_id)

    async def _send_party_invite_notice(self, char_id, char_name, target_id):
        from darkblood.games.network.messages.party import PartyInviteNot
        from darkblood.games.world import GameWorldManager

        world = GameWorldManager.get()
        target = world.get_player(target_id)
        if not target or not target.session or not getattr(target.session, 'transport', None):
            return
        inviter = world.get_player(char_id)
        char = self.current_char() or {}
        notice = PartyInviteNot(inviter_uid=char_id, inviter_name=char_name,
                                inviter_square_uid=inviter.square_id if inviter else 1,
                                inviter_class=int(char.get('char_class', 0)) & 0xFF,
                                inviter_level=min(int(char.get('level', 1)), 0xFF))
        room = self.session.dungeon.room
        if room is not None and room.info.name != '_singleplay':
            # nInviteRoomUID: with a room UID > 0 Accept sends 5003 for this room.
            info = room.info
            notice.room_uid, notice.room_name = info.room_id, info.name
            notice.gate_id, notice.map_id, notice.diff = info.gate_id, info.map_id, info.diff
        await target.session.transport.send_event(event(5051, notice.encode()),
                                                  note=f'party invite not from {char_name}')

    @packet_handler(2102)
    async def handle_party_join(self, correlation, body):
        """Opcode 2102 (eEGS_PARTY_JOIN_REQ) -> 2103 (eEGS_PARTY_JOIN_ACK)."""
        from darkblood.games.network.messages.party import PartyAcceptInviteNot, PartyJoinAck, PartyJoinReq
        from darkblood.games.world import PartyManager
        req = PartyJoinReq.decode(body)
        char = self.current_char()
        char_id = char.get('id', 0) if char else self.session.active_char_id or 0
        char_name = char.get('name', 'Member') if char else 'Member'
        char_class = char.get('char_class', 0) if char else 0
        level = char.get('level', 1) if char else 1

        pm = PartyManager.get()
        host_id = self._char_id(req.host_uid)
        party = pm.get_party(req.party_id) if req.party_id else pm.get_player_party(host_id)
        if host_id and party and party.leader_id != host_id:
            party = None
        res, party = pm.accept_invite(char_id, party, char_name, char_class, level, session=self)
        party_id = party.party_id if party else 0
        ack = PartyJoinAck(result=res, party_id=party_id).encode()
        await self.transport.send_event(event(2103, ack, correlation),
                                        note=f'party join ack (res={res} party={party_id})')

        if res == 0 and party:
            notif = PartyAcceptInviteNot(party_id=party_id, member_uid=char_id, member_name=char_name).encode()
            await pm.broadcast_to_party(party_id, event(5056, notif), exclude_char_id=char_id, note='party accept invite not')

    @packet_handler(5054)
    async def handle_party_accept_invite(self, correlation, body):
        """Opcode 5054 (eERC_ACCEPT_INVITE_REQ) -> 5055 (eERC_ACCEPT_INVITE_ACK)."""
        from darkblood.games.network.messages.party import PartyAcceptInviteAck, PartyAcceptInviteNot, PartyAcceptInviteReq
        from darkblood.games.world import PartyManager
        req = PartyAcceptInviteReq.decode(body)
        char = self.current_char()
        char_id = char.get('id', 0) if char else self.session.active_char_id or 0
        char_name = char.get('name', 'Member') if char else 'Member'
        char_class = char.get('char_class', 0) if char else 0
        level = char.get('level', 1) if char else 1

        host_id = self._char_id(req.host_uid)
        from darkblood.games.world import GameWorldManager
        host = GameWorldManager.get().get_player(host_id)
        host_room = getattr(getattr(getattr(host, 'session', None), 'dungeon', None), 'room', None)
        if host_room is not None:
            # The client's party is the dungeon room (5004/5035 have handlers;
            # 5055/5056 do not): accepting joins the host's room.
            await self.session.dungeon.join_room(host_room, correlation)
            return
        pm = PartyManager.get()
        party = pm.get_player_party(host_id)
        if party and party.leader_id != host_id:
            party = None
        res, party = pm.accept_invite(char_id, party, char_name, char_class, level, session=self)
        party_id = party.party_id if party else 0
        ack = PartyAcceptInviteAck(result=res).encode()
        await self.transport.send_event(event(5055, ack, correlation),
                                        note=f'party accept invite ack (res={res} party={party_id})')

        if res == 0 and party:
            notif = PartyAcceptInviteNot(party_id=party_id, member_uid=char_id, member_name=char_name).encode()
            await pm.broadcast_to_party(party_id, event(5056, notif), exclude_char_id=char_id, note='party accept invite not')

    @packet_handler(2104)
    async def handle_party_leave(self, correlation, body):
        """Opcode 2104 (eEGS_PARTY_LEAVE_REQ) -> 2105 (eEGS_PARTY_LEAVE_ACK)."""
        from darkblood.games.network.messages.party import PartyLeaveAck, PartyLeaveReq
        from darkblood.games.world import PartyManager
        char = self.current_char()
        char_id = char.get('id', 0) if char else self.session.active_char_id or 0
        pm = PartyManager.get()
        res, rem_party = pm.leave_party(char_id)
        ack = PartyLeaveAck(result=res).encode()
        await self.transport.send_event(event(2105, ack, correlation), note=f'party leave ack (res={res})')

    @packet_handler(2106)
    async def handle_party_kick(self, correlation, body):
        """Opcode 2106 (eEGS_PARTY_KICK_REQ) -> 2107 (eEGS_PARTY_KICK_ACK)."""
        from darkblood.games.network.messages.party import PartyKickAck, PartyKickReq
        from darkblood.games.world import GameWorldManager, PartyManager
        req = PartyKickReq.decode(body)
        char = self.current_char()
        char_id = char.get('id', 0) if char else self.session.active_char_id or 0
        pm = PartyManager.get()
        res, party = pm.kick_player(char_id, req.target_uid)
        ack = PartyKickAck(result=res, target_uid=req.target_uid).encode()
        await self.transport.send_event(event(2107, ack, correlation),
                                        note=f'party kick ack (res={res} target={req.target_uid})')

        if res == 0:
            target_player = GameWorldManager.get().get_player(req.target_uid)
            if target_player and target_player.session and getattr(target_player.session, 'transport', None):
                from darkblood.games.network.messages.party import PartyLeaveAck
                await target_player.session.transport.send_event(
                    event(2105, PartyLeaveAck(result=0).encode()),
                    note=f'kicked from party {party.party_id if party else 0}'
                )






