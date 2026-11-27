"""Friends, block list, character/item inspection, achievements and system notices."""
import struct

from darkblood.games.network import results
from darkblood.core.serialization.jser import WireError, event
from darkblood.games.dispatcher import packet_handler
from darkblood.games.network.messages import (
    AchieveCompleteNot,
    AchieveCompletion,
    AchieveDivUpdateAck,
    AchieveDivUpdateReq,
    AchieveEntry,
    AchieveGetListAck,
    AchieveUpdateAck,
    AchieveUpdateReq,
    ArenaBackToSquareAck,
    BanishUserAck,
    BanishUserReq,
    CharNickChangeAck,
    CharNickChangeReq,
    FriendBlockEntry,
    FriendBlockListAddAck,
    FriendBlockListAddReq,
    FriendBlockListDeleteAck,
    FriendBlockListDeleteReq,
    FriendBlockListRequestAck,
    FriendBlockListUpdateAck,
    FriendBlockListUpdateReq,
    FriendEntry,
    FriendListAck,
    FriendListAddAck,
    FriendListAddReq,
    FriendListDeleteAck,
    FriendListDeleteReq,
    FriendListUpdateAck,
    FriendListUpdateReq,
    GetInviteListAck,
    GetInviteListReq,
    GuildSkillEntry,
    KeyboardSetCustomKeyAck,
    KeyboardSetCustomKeyReq,
    RequestCharInfoAck,
    RequestCharInfoByNickReq,
    RequestCharInfoReq,
    RequestItemInfoAck,
    RequestItemInfoReq,
    RoomMemberInfo,
    SecondPassAuthAck,
    SecondPassCreateAck,
    SecondPassModifyAck,
    TitleChangeAck,
    TitleChangeReq,
    WatchEventSeenAck,
)
from darkblood.games.handlers.arena.league import league_arena_info
from darkblood.games.world import GameWorldManager, SQUARE_UID_MASK, square_uid
from darkblood.games import achievements
from darkblood.games.entities.character import Character
from darkblood.games.entities.items import EQUIPPED, Item
from darkblood.games.handlers.skills import learned_skill_map


class FriendsHandlers:
    @packet_handler(2131)
    async def handle_friend_list(self, correlation, body):
        # eEGS_FRIEND_LIST_REQUEST_REQ -> eEGS_FRIEND_LIST_REQUEST_ACK (2132), handler 0x7712E0:
        # u32 result (0), tag 0x17 map (0x76AE20). Empty map is b'\x17\x00'.
        char = self.current_char()
        friends = [self._friend_entry(uid) for uid in (char or {}).get('friends', [])]
        friends = [f for f in friends if f]
        ack = FriendListAck(friends={f.uid: f for f in friends})
        await self.reply(ack, correlation, note='friend list ack (%d)' % len(friends))
        # Live, 2131 follows 2006 by ~2 s, right before the relay JoinGroup:
        # the earliest point where a town peer sent by 5027 is displayed.
        await GameWorldManager.get().player_ready(self.session)


    def _friend_entry(self, uid):
        """FriendEntry for a character of any account, or None."""
        world = GameWorldManager.get()
        owner = self.current_char() or {}
        memo = (owner.get('friend_memos') or {}).get(str(uid), '')
        _, char = self.store().get_by_id(uid)
        if char is not None:
            player = world.players.get(uid)
            online = player is not None
            return FriendEntry(
                uid=uid,
                name=char.get('name', ''),
                level=int(char.get('level', 1)),
                char_class=int(char.get('char_class', 0)),
                location=player.square_id if online else -1,
                memo=memo,
                is_online=online,
            )
        return None


    @packet_handler(2569)
    async def handle_friend_block_list_request(self, correlation, body):
        # eEGS_FRIEND_BLOCK_LIST_REQUEST_REQ -> 2570 (0x00772160, mapFriendBlockList).
        char = self.current_char() or {}
        block_list = {}
        for uid_key, memo in char.get('blocked_friends', {}).items():
            uid = int(uid_key)
            other = self.find_char(uid) or {}
            block_list[uid] = FriendEntry(uid=uid, name=other.get('name', ''),
                                          char_class=int(other.get('char_class', 0)) & 0xFF,
                                          level=min(int(other.get('level', 1)), 0xFF), memo=memo or '',
                                          is_online=False)
        await self.reply(FriendBlockListRequestAck(block_list=block_list), correlation,
                         note=f'friend block list ack ({len(block_list)})')


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
        try:
            req = GetInviteListReq.decode(body)
        except (WireError, struct.error):
            await self.reply(GetInviteListAck(), correlation, note='invite list ack (bad request)')
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
            if req.job < 7 and (char_class & 0x0F) != req.job:  # 7 = eCK_Max, taken as "any class"
                continue
            if square is not None and player.square_id != square:
                continue
            if req.layer_net_id != -1 and player.layer_id != req.layer_net_id:
                continue
            users.append(RoomMemberInfo(square_uid=square_uid(player.square_id), char_uid=player.char_id,
                                        name=record.get('name', ''), char_class=char_class,
                                        stress=int(record.get('stress', 0)), level=min(level, 0xFF)))
        # Page size not recovered: everything is sent as page 0.
        ack = GetInviteListAck(users=users)
        await self.reply(ack, correlation, note='invite list ack (%d users, lv %d-%d, job %d)'
                                             % (len(users), req.low_level, req.high_level, req.job))


    @packet_handler(2139)
    async def handle_friend_list_add(self, correlation, body):
        # eEGS_FRIEND_LIST_ADD_REQ (0x00790000.c:1595) -> 2140 eEGS_FRIEND_LIST_ADD_ACK (0x007591A0).
        req = FriendListAddReq.decode(body)
        self.transport.record('friend-add', body, name=req.char_name)
        char = self.current_char()
        _, target = self.store().get_by_name(req.char_name)
        if not char or not target or target.get('id') == char.get('id'):
            await self.reply(FriendListAddAck(result=0xCE), correlation, note=f'friend add fail ({req.char_name} not found)')
            return
        friends = char.setdefault('friends', [])
        if target['id'] not in friends:
            friends.append(target['id'])
            self.save_char()
        ack = FriendListAddAck(result=0, friend=self._friend_entry(target['id']))
        await self.reply(ack, correlation, note=f'friend add ack ({req.char_name})')


    @packet_handler(2135)
    async def handle_friend_list_delete(self, correlation, body):
        # eEGS_FRIEND_LIST_DELETE_REQ (0x00790000.c:1824) -> 2136 eEGS_FRIEND_LIST_DELETE_ACK (0x00759560).
        req = FriendListDeleteReq.decode(body)
        self.transport.record('friend-delete', body, char_uid=req.char_uid)
        char = self.current_char()
        if char and req.char_uid in char.get('friends', []):
            char['friends'].remove(req.char_uid)
            char.get('friend_memos', {}).pop(str(req.char_uid), None)
            self.save_char()
        ack = FriendListDeleteAck(result=0, char_uid=req.char_uid)
        await self.reply(ack, correlation, note=f'friend delete ack ({req.char_uid})')


    @packet_handler(2133)
    async def handle_friend_list_update(self, correlation, body):
        # eEGS_FRIEND_LIST_UPDATE_REQ (0x00790000.c:1735) -> 2134 eEGS_FRIEND_LIST_UPDATE_ACK (0x00752E80).
        req = FriendListUpdateReq.decode(body)
        self.transport.record('friend-update-req', body, char_uid=req.char_uid, comment=req.comment)
        char = self.current_char()
        if char is not None:
            char.setdefault('friend_memos', {})[str(req.char_uid)] = req.comment
            self.save_char()
        ack = FriendListUpdateAck(result=0, char_uid=req.char_uid, comment=req.comment)
        await self.reply(ack, correlation, note=f'friend list update ack (uid={req.char_uid})')


    @packet_handler(2310)
    async def handle_char_nick_change(self, correlation, body):
        # eEGS_CHAR_NICK_CHANGE_REQ -> 2311 eEGS_CHAR_NICK_CHANGE_ACK (0x00780200).
        req = CharNickChangeReq.decode(body)
        new_name = req.new_name.strip()
        self.transport.record('char-nick-change-req', body, new_name=new_name)
        char = self.current_char()
        if not char or not new_name:
            result = results.NICK_INVALID if char else results.NO_EXIST_CHAR
            await self.reply(CharNickChangeAck(result=result), correlation, note='char nick change refused')
            return
        if not self.store().rename_character(self.account, char, new_name):
            await self.reply(CharNickChangeAck(result=results.NICK_ALREADY_EXISTS), correlation,
                             note='char nick change refused (name already taken)')
            return
        ack = CharNickChangeAck(result=0, items=[], new_name=new_name)
        await self.reply(ack, correlation, note=f'char nick change ack ({new_name})')


    @packet_handler(2319)
    async def handle_keyboard_set_custom_key(self, correlation, body):
        # eEGS_KEYBOARD_SET_CUSTOM_KEY_REQ (0x0045FC10) -> 2320 eEGS_KEYBOARD_SET_CUSTOM_KEY_ACK (0x00753960).
        req = KeyboardSetCustomKeyReq.decode(body)
        self.transport.record('keyboard-set-custom-key-req', body, keys=req.keys)
        char = self.store().get(self.account, self.char_id)
        if char is not None:
            char['custom_keys'] = req.keys
            self.save_char()
        ack = KeyboardSetCustomKeyAck(result=0, keys=req.keys)
        await self.reply(ack, correlation, note='keyboard set custom key ack')


    @packet_handler(2335)
    async def handle_title_change(self, correlation, body):
        # eEGS_TITLE_CHANGE_REQ -> 2336 eEGS_TITLE_CHANGE_ACK (0x007751C0).
        req = TitleChangeReq.decode(body)
        self.transport.record('title-change-req', body, title_id=req.title_id)
        ack = TitleChangeAck(result=0, title_id=req.title_id)
        await self.reply(ack, correlation, note=f'title change ack (title={req.title_id})')


    @packet_handler(2327)
    async def handle_achieve_get_list(self, correlation, body):
        # eEGS_ACHIEVE_GET_LIST_REQ -> 2328 eEGS_ACHIEVE_GET_LIST_ACK (0x0079D650).
        char = self.current_char() or {}
        divisions, completed = achievements.total_info(char)
        ack = AchieveGetListAck(divisions=divisions, completed=completed,
                                completions=[AchieveCompletion(h) for h in completed])
        await self.reply(ack, correlation, note=f'achieve get list ack ({len(completed)} completed)')


    @packet_handler(2444)
    async def handle_achieve_update(self, correlation, body):
        # eEGS_ACHIEVE_UPDATE_REQ (sender 0x007992D0): vector of u32 achievement
        # hashes completed client-side -> 2445 (u32 result, 0x0074B830), then 2330.
        self.transport.record('achieve-update', body)
        char = self.current_char()
        completed = []
        try:
            report = AchieveUpdateReq.decode(body)
        except (WireError, struct.error, IndexError):
            report = None
        if char is not None and report is not None:
            completed = achievements.apply_client_completions(char, report.hashes)
            self.save_char()
        await self.reply(AchieveUpdateAck(), correlation,
                         note='achieve update ack')
        if completed:
            entries = [AchieveEntry(h, t) for h, t in achievements.completed_entries(char, completed)]
            await self.send_msg(AchieveCompleteNot(entries, [AchieveCompletion(e.achieve_hash) for e in entries]), note='achievements completed: %s' % ', '.join(completed))


    @packet_handler(2446)
    async def handle_achieve_div_update(self, correlation, body):
        # eEGS_ACHIEVE_DIV_UPDATE_REQ (per-run division amounts) -> 2447
        # (0x0074B830 reads only the u32 result), then 2330 for completions.
        self.transport.record('achieve-div-update', body)
        char = self.current_char()
        completed = []
        try:
            report = AchieveDivUpdateReq.decode(body)
        except (WireError, struct.error, IndexError):
            report = None
        if char is not None and report is not None:
            completed = achievements.apply_division_report(char, report.amounts)
            self.save_char()
        await self.reply(AchieveDivUpdateAck(), correlation,
                         note='achieve div update ack')
        if completed:
            entries = [AchieveEntry(h, t) for h, t in achievements.completed_entries(char, completed)]
            await self.send_msg(AchieveCompleteNot(entries, [AchieveCompletion(e.achieve_hash) for e in entries]), note='achievements completed: %s' % ', '.join(completed))


    @packet_handler(5165)
    async def handle_arena_back_to_square(self, correlation, body):
        # eERC_ARENA_BACK_TO_SQUARE_REQ -> 5166 eERC_ARENA_BACK_TO_SQUARE_ACK (0x00758550).
        ack = ArenaBackToSquareAck(result=0)
        await self.reply(ack, correlation, note='arena back to square ack')


    @packet_handler(5256)
    async def handle_second_pass_create(self, correlation, body):
        # eERC_SECOND_PASS_CREATE_REQ -> 5257 eERC_SECOND_PASS_CREATE_ACK (0x0075B020).
        ack = SecondPassCreateAck(result=0)
        await self.reply(ack, correlation, note='second pass create ack')


    @packet_handler(5258)
    async def handle_second_pass_modify(self, correlation, body):
        # eERC_SECOND_PASS_MODIFY_REQ -> 5259 eERC_SECOND_PASS_MODIFY_ACK (0x0075B050).
        ack = SecondPassModifyAck(result=0)
        await self.reply(ack, correlation, note='second pass modify ack')


    @packet_handler(5260)
    async def handle_second_pass_auth(self, correlation, body):
        # eERC_SECOND_PASS_AUTH_REQ -> 5261 eERC_SECOND_PASS_AUTH_ACK (0x0075B080).
        ack = SecondPassAuthAck(result=0)
        await self.reply(ack, correlation, note='second pass auth ack')


    def _build_char_info_ack(self, target, is_other=True):
        if target is None:
            return RequestCharInfoAck(result=0xCE)
        equipped = [Item(owner=target['id'], **item) for item in target.get('items', [])
                    if item.get('container') == EQUIPPED]
        passive_skills = list(learned_skill_map(
            target.get('skills', {}),
            target.get('skill_speeches', {}),
            target.get('locked_skills', []),
            target.get('skill_show_cooltime', []),
        ).values())
        guild_skills = [
            GuildSkillEntry(
                skill_id=int(gs.get('skill_id', 0xFFFF)),
                skill_level=int(gs.get('skill_level', 0)),
                is_used=bool(gs.get('is_used', False)),
                remain_time=int(gs.get('remain_time', 0)),
                cool_time=int(gs.get('cool_time', 0)),
                param=int(gs.get('param', 0)),
            )
            for gs in target.get('guild_skills', [])
        ]
        league_arena = league_arena_info(target)
        raw_prof = list(target.get('proficiencies', []))
        proficiencies = [float(raw_prof[i]) if i < len(raw_prof) else 0.0 for i in range(10)]
        return RequestCharInfoAck(
            result=0,
            is_other=bool(is_other),
            character=Character.from_dict(target),
            items=equipped,
            passive_skills=passive_skills,
            guild_skills=guild_skills,
            league_arena=league_arena,
            proficiencies=proficiencies,
        )


    @packet_handler(6011)
    async def handle_request_char_info(self, correlation, body):
        # eERT_REQUEST_CHAR_INFO_REQ -> 6012 eERT_REQUEST_CHAR_INFO_ACK (0x00790FA0).
        req = RequestCharInfoReq.decode(body)
        self.transport.record('request-char-info-req', body, char_uid=req.char_uid)
        target_id = self.char_id_from_uid(req.char_uid)
        _, target = self.store().get_by_id(target_id)
        ack = self._build_char_info_ack(target, is_other=req.is_other).encode()
        await self.transport.send_event(event(6012, ack, correlation), note=f'request char info ack (char={req.char_uid})')


    @packet_handler(6028)
    async def handle_request_item_info(self, correlation, body):
        # eERT_REQUEST_ITEM_INFO_REQ -> 6029 eERT_REQUEST_ITEM_INFO_ACK (0x00766C20).
        req = RequestItemInfoReq.decode(body)
        target_id = self.char_id_from_uid(req.target_char_uid)
        target = self.find_char(req.target_char_uid)
        # nItemInfoID is matched against the target's item UIDs (assumption: low 32 bits).
        record = next((i for i in (target or {}).get('items', [])
                       if int(i.get('uid', 0)) & 0xFFFFFFFF == req.item_info_id), None)
        if record is None:
            ack = RequestItemInfoAck(result=results.INVEN_ITEM_NOT_FOUND)
        else:
            ack = RequestItemInfoAck(result=0, char_uid=req.target_char_uid,
                                     item=Item(owner=target.get('id', -1), **record))
        await self.reply(ack, correlation,
                         note=f'request item info ack (char={target_id}, item={req.item_info_id}, result={ack.result})')


    @packet_handler(2565)
    async def handle_friend_block_list_add(self, correlation, body):
        # eEGS_FRIEND_BLOCK_LIST_ADD_REQ (0x007A2930) -> 2566 eEGS_FRIEND_BLOCK_LIST_ADD_ACK (0x0075B640).
        req = FriendBlockListAddReq.decode(body)
        self.transport.record('friend-block-add', body, name=req.char_name)
        char = self.current_char()
        _, target = self.store().get_by_name(req.char_name)
        if not char or not target or target.get('id') == char.get('id'):
            await self.reply(FriendBlockListAddAck(result=0xCF), correlation,
                             note=f'friend block add fail ({req.char_name} not found)')
            return
        blocked = char.setdefault('blocked_friends', {})
        uid_key = str(target['id'])
        if uid_key not in blocked:
            blocked[uid_key] = ''
            self.save_char()
        entry = FriendBlockEntry(
            uid=target['id'],
            name=target.get('name', ''),
            char_class=int(target.get('char_class', 0)) & 0xFF,
            level=min(int(target.get('level', 1)), 0xFF),
            memo=blocked.get(uid_key, ''),
        )
        await self.reply(FriendBlockListAddAck(result=0, block=entry), correlation,
                         note=f'friend block add ack ({req.char_name})')


    @packet_handler(2567)
    async def handle_friend_block_list_delete(self, correlation, body):
        # eEGS_FRIEND_BLOCK_LIST_DELETE_REQ (0x007A2C70) -> 2568 eEGS_FRIEND_BLOCK_LIST_DELETE_ACK (0x0075B9B0).
        req = FriendBlockListDeleteReq.decode(body)
        self.transport.record('friend-block-delete', body, char_uid=req.char_uid)
        char = self.current_char()
        if char and str(req.char_uid) in char.get('blocked_friends', {}):
            del char['blocked_friends'][str(req.char_uid)]
            self.save_char()
        await self.reply(FriendBlockListDeleteAck(result=0, char_uid=req.char_uid), correlation,
                         note=f'friend block delete ack ({req.char_uid})')


    @packet_handler(2571)
    async def handle_friend_block_list_update(self, correlation, body):
        # eEGS_FRIEND_BLOCK_LIST_UPDATE_REQ (0x007A2F20) -> 2572 eEGS_FRIEND_BLOCK_LIST_UPDATE_ACK (0x00753C80).
        req = FriendBlockListUpdateReq.decode(body)
        self.transport.record('friend-block-update', body, char_uid=req.char_uid, memo=req.memo)
        char = self.current_char()
        if char is not None:
            char.setdefault('blocked_friends', {})[str(req.char_uid)] = req.memo
            self.save_char()
        await self.reply(FriendBlockListUpdateAck(result=0, char_uid=req.char_uid, memo=req.memo), correlation,
                         note=f'friend block update ack ({req.char_uid})')


    @packet_handler(2693)
    async def handle_watch_event_seen(self, correlation, body):
        # eEGS_WATCH_EVENTSEEN_REQ -> 2694 eEGS_WATCH_EVENTSEEN_ACK (0x00655800).
        self.transport.record('watch-event-seen-req', body)
        await self.reply(WatchEventSeenAck(result=0), correlation, note='watch event seen ack')


    @packet_handler(5007)
    async def handle_banish_user(self, correlation, body):
        # eERC_BANISH_USER_REQ (0x005975D0) -> 5008 eERC_BANISH_USER_ACK (0x005999A0).
        req = BanishUserReq.decode(body)
        target_id = self.char_id_from_uid(req.target_uid)
        self.transport.record('banish-user-req', body, target_uid=target_id)
        room = getattr(getattr(self.session, 'dungeon', None), 'room', None)
        if room is None or room.host is not self.session:
            await self.reply(BanishUserAck(result=results.INVALID_STATE), correlation, note='banish user fail (not host)')
            return
        kicked = next((m for m in list(room.members) if m.active_char_id == target_id and m is not self.session), None)
        if kicked is None:
            await self.reply(BanishUserAck(result=results.INVALID_STATE), correlation, note=f'banish user fail ({target_id} not in room)')
            return
        recipients = list(room.members)
        room.members.remove(kicked)
        kicked.dungeon.room = None
        ack_msg = BanishUserAck(result=0, leave_user_uid=target_id)
        ack_bytes = ack_msg.encode()
        await self.transport.send_event(event(5008, ack_bytes, correlation),
                                        note=f'banish user ack (kicked={target_id})')
        unsolicited = event(5008, ack_bytes)
        for member in recipients:
            if member is self.session or not getattr(member, 'transport', None):
                continue
            try:
                await member.transport.send_event(unsolicited, note=f'banish user broadcast (kicked={target_id})')
            except (ConnectionError, OSError):
                pass


    @packet_handler(6018)
    async def handle_request_char_info_by_nick(self, correlation, body):
        # eERT_REQUEST_CHAR_INFO_BY_NICK_REQ (0x00790E10) -> 6012 eERT_REQUEST_CHAR_INFO_ACK (0x00790FA0).
        req = RequestCharInfoByNickReq.decode(body)
        self.transport.record('request-char-info-by-nick', body, target_nick=req.target_nick)
        _, target = self.store().get_by_name(req.target_nick)
        ack = self._build_char_info_ack(target, is_other=True)
        await self.reply(ack, correlation,
                         note=f'request char info by nick ack ({req.target_nick}, res={ack.result})')

