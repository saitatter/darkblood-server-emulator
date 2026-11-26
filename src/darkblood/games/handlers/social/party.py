"""Party invites, joins, kicks and teaching/guide/summon handlers."""
from darkblood.core.serialization.jser import WireError, event
from darkblood.games.dispatcher import packet_handler


class PartyHandlers:
    @packet_handler(5351)
    async def handle_request_teaching(self, correlation, body):
        # eERC_REQUEST_TEACHING_REQ -> 5352 eERC_REQUEST_TEACHING_ACK (0x0075C200).
        from darkblood.games.network.messages import RequestTeachingAck, RequestTeachingReq
        req = RequestTeachingReq.decode(body)
        self.transport.record('request-teaching-req', body, target_uid=req.target_uid)
        target = self.find_char(req.target_uid) or {}
        ack = RequestTeachingAck(result=0, target_uid=req.target_uid, target_name=target.get('name', ''),
                                 level=min(int(target.get('level', 1)), 0xFF), job=int(target.get('char_class', 0)) & 0xFF)
        await self.reply(ack, correlation, note=f'request teaching ack (target={req.target_uid})')


    @packet_handler(5353)
    async def handle_accept_request_teaching(self, correlation, body):
        # eERC_ACCEPT_REQUEST_TEACHING_REQ -> 5354 eERC_ACCEPT_REQUEST_TEACHING_ACK (0x0075C430).
        from darkblood.games.network.messages import AcceptRequestTeachingAck, AcceptRequestTeachingReq
        req = AcceptRequestTeachingReq.decode(body)
        self.transport.record('accept-request-teaching-req', body, mentor_uid=req.mentor_uid)
        ack = AcceptRequestTeachingAck(result=0, accepted=True, mentor_uid=req.mentor_uid, mentor_name='Master')
        await self.reply(ack, correlation, note=f'accept request teaching ack (mentor={req.mentor_uid})')


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




    async def _invite_to_party(self, ack_opcode, correlation, target_id, target_name):
        """Shared invite path for 2100, 5049 and 5092 (target by id or name)."""
        target_id = self.char_id_from_uid(target_id)
        from darkblood.games.network.messages.party import PartyInviteAck
        from darkblood.games.world import PartyManager
        char = self.current_char()
        char_id = char.get('id', 0) if char else self.session.active_char_id or 0
        char_name = char.get('name', 'Leader') if char else 'Leader'
        char_class = char.get('char_class', 0) if char else 0
        level = char.get('level', 1) if char else 1

        if not target_id and target_name:
            _, target = self.store().get_by_name(target_name)
            if target:
                target_id = target.get('id', 0)

        room = self.session.dungeon.room
        pending = room.join_requests.pop(target_id, None) if room is not None else None
        if pending is not None and room.host is self.session:
            # Host accepted a 5047 join request (OnBtn_Party_Accept on the host
            # calls AcceptJoinRoomREQ = 5049): the requester joins at once and gets
            # 5004 for its pending 5047. Do not send 5050 on success: handler
            # 0x00758700 unconditionally prints FUN_00ab29c0(result) as an error
            # ("This is an unknown message" for result=0).
            requester, request_correlation = pending
            if requester.dungeon.room is None:
                await requester.dungeon.join_room(room, request_correlation)
            return
        res, _ = PartyManager.get().invite_player(char_id, target_id, char_name, char_class, level, session=self)
        # 5050 handler (0x00758700) has no result==0 guard and prints any result
        # via FUN_00ab29c0(result) in red chat ("This is an unknown message" for 0).
        # Send 5050 only on failure; legacy 2101 still replies unconditionally.
        if ack_opcode != 5050 or res != 0:
            ack = PartyInviteAck(result=res).encode()
            await self.transport.send_event(event(ack_opcode, ack, correlation),
                                            note=f'party invite ack (res={res} target={target_id})')
        if res == 0 and target_id:
            await self._send_party_invite_notice(char_id, char_name, target_id)


    async def _send_party_invite_notice(self, char_id, char_name, target_id):
        from darkblood.games.network.messages.party import PartyInviteNot
        from darkblood.games.world import GameWorldManager, square_uid

        world = GameWorldManager.get()
        target = world.get_player(target_id)
        if not target or not target.session or not getattr(target.session, 'transport', None):
            return
        inviter = world.get_player(char_id)
        char = self.current_char() or {}
        notice = PartyInviteNot(inviter_uid=char_id, inviter_name=char_name,
                                inviter_square_uid=square_uid(inviter.square_id if inviter else 1),
                                inviter_class=int(char.get('char_class', 0)) & 0xFF,
                                inviter_stress=int(char.get('stress', 0)),
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
        host_id = self.char_id_from_uid(req.host_uid)
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

        host_id = self.char_id_from_uid(req.host_uid)
        from darkblood.games.world import GameWorldManager
        host = GameWorldManager.get().get_player(host_id)
        host_room = getattr(getattr(getattr(host, 'session', None), 'dungeon', None), 'room', None)
        if host_room is not None and self.session.dungeon.room is not host_room:
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
        ack = PartyAcceptInviteAck(result=res)
        await self.reply(ack, correlation, note=f'party accept invite ack (res={res} party={party_id})')

        if res == 0 and party:
            notif = PartyAcceptInviteNot(party_id=party_id, member_uid=char_id, member_name=char_name).encode()
            await pm.broadcast_to_party(party_id, event(5056, notif), exclude_char_id=char_id, note='party accept invite not')
            # Real client has no handlers for 5055/5056; its party IS a DungeonRoom.
            # If the host had no room yet, create one on the host (5002) and join it (5004 + 5035).
            if host and host.session and getattr(host.session, 'dungeon', None) and host.session.dungeon.room is None:
                from darkblood.games.handlers.dungeon import DungeonRoom, relay_address
                from darkblood.games.network.messages.dungeon import CreateRoomAck, RoomInfo
                server = host.session.transport.server
                host_char = host.session.dungeon.current_char() or host.char_data
                info = RoomInfo(room_id=next(server.room_ids), name=f"{host_char.get('name', 'Party')}'s Party",
                                gate_id=-1, map_id=-1, diff=-1, max_users=4, cur_users=1, host_uid=host_id)
                new_room = DungeonRoom(info, host.session, {host.session: host_char})
                host.session.dungeon.room = new_room
                server.dungeon_rooms[info.room_id] = new_room
                await host.session.transport.send_event(
                    event(5002, CreateRoomAck(room=info, relay=relay_address()).encode()),
                    note='create party room ack (auto on 5054)',
                )
                await self.session.dungeon.join_room(new_room, correlation)


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


    @packet_handler(2356)
    async def handle_guide_waitlist_update(self, correlation, body):
        # eEGS_GUIDE_WAITLIST_UPDATE_REQ (0x0079A260) -> 2357 eEGS_GUIDE_WAITLIST_UPDATE_ACK.
        from darkblood.games.network.messages.party import GuideWaitlistUpdateAck, GuideWaitlistUpdateReq
        req = GuideWaitlistUpdateReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['guide_waitlist'] = list(req.guide_ids)
            self.save_char()
        await self.reply(GuideWaitlistUpdateAck(result=0), correlation,
                         note=f'guide waitlist update ack ({len(req.guide_ids)})')


    @packet_handler(2360)
    async def handle_guide_donelist_update(self, correlation, body):
        # eEGS_GUIDE_DONELIST_UPDATE_REQ (0x0079A110) -> 2361 eEGS_GUIDE_DONELIST_UPDATE_ACK.
        from darkblood.games.network.messages.party import GuideDonelistUpdateAck, GuideDonelistUpdateReq
        req = GuideDonelistUpdateReq.decode(body)
        char = self.current_char()
        if char is not None:
            char['guide_donelist'] = list(req.guide_ids)
            self.save_char()
        await self.reply(GuideDonelistUpdateAck(result=0), correlation,
                         note=f'guide donelist update ack ({len(req.guide_ids)})')


    @packet_handler(2648)
    async def handle_teaching_stress_reward(self, correlation, body):
        # eEGS_TEACHING_STRESS_REWARD_REQ (0x007A60E0) -> 2649 eEGS_TEACHING_STRESS_REWARD_ACK (0x0075C7B0).
        from darkblood.games.network.messages.party import TeachingStressRewardAck, TeachingStressRewardReq
        req = TeachingStressRewardReq.decode(body)
        self.transport.record('teaching-stress-reward-req', body, reward_idx=req.reward_idx)
        await self.reply(TeachingStressRewardAck(result=0), correlation,
                         note=f'teaching stress reward ack (idx={req.reward_idx})')


    @packet_handler(2658)
    async def handle_teaching_graduation_reward(self, correlation, body):
        # eEGS_TEACHING_GRADUATION_REWARD_REQ (0x007A6180) -> 2659 eEGS_TEACHING_GRADUATION_REWARD_ACK (0x0075C8E0).
        from darkblood.games.network.messages.party import TeachingGraduationRewardAck, TeachingGraduationRewardReq
        req = TeachingGraduationRewardReq.decode(body)
        self.transport.record('teaching-graduation-reward-req', body, reward_idx=req.reward_idx)
        await self.reply(TeachingGraduationRewardAck(result=0), correlation,
                         note=f'teaching graduation reward ack (idx={req.reward_idx})')


    @packet_handler(5130)
    async def handle_summon_acknowledge(self, correlation, body):
        # eERC_SUMMON_ACKNOWLEDGE_REQ (0x004D31D0) -> 5131 eERC_SUMMON_ACKNOWLEDGE_ACK.
        from darkblood.games.network.messages.party import SummonAcknowledgeAck, SummonAcknowledgeReq
        req = SummonAcknowledgeReq.decode(body)
        self.transport.record('summon-acknowledge-req', body, accept=req.accept)
        await self.reply(SummonAcknowledgeAck(result=0), correlation,
                         note=f'summon acknowledge ack (accept={req.accept})')


    @packet_handler(5356)
    async def handle_teaching_summon_accept(self, correlation, body):
        # eERC_TEACHING_SUMMON_ACCEPT_REQ (0x007A6490) -> 5357 eERC_TEACHING_SUMMON_ACCEPT_ACK (0x0077B780).
        from darkblood.games.network.messages.party import TeachingSummonAcceptAck, TeachingSummonAcceptReq
        req = TeachingSummonAcceptReq.decode(body)
        char = self.current_char()
        nick = char.get('name', '') if char else ''
        await self.reply(TeachingSummonAcceptAck(result=0, answer=req.accept, nick=nick), correlation,
                         note=f'teaching summon accept ack (accept={req.accept})')


    @packet_handler(6030)
    async def handle_teaching_delete(self, correlation, body):
        # eERT_TEACHING_DELETE_REQ (0x007A5CB0) -> 6031 eERT_TEACHING_DELETE_ACK (0x007A5D60).
        from darkblood.games.network.messages.party import TeachingDeleteAck, TeachingDeleteReq
        req = TeachingDeleteReq.decode(body)
        target_id = self.char_id_from_uid(req.target_uid)
        _, target = self.store().get_by_id(target_id)
        nick = target.get('name', '') if target else ''
        await self.reply(TeachingDeleteAck(result=0, nick=nick, is_request=False), correlation,
                         note=f'teaching delete ack (target={target_id})')


    @packet_handler(6032)
    async def handle_teaching_summon_request(self, correlation, body):
        # eERT_TEACHING_SUMMON_REQUEST_REQ (0x007A6240) -> 6033 eERT_TEACHING_SUMMON_REQUEST_ACK (0x0075CA40).
        from darkblood.games.entities.character import layer_net_id
        from darkblood.games.network.messages.party import TeachingSummonRequestAck, TeachingSummonRequestReq
        from darkblood.games.world import GameWorldManager
        req = TeachingSummonRequestReq.decode(body)
        char = self.current_char()
        my_name = char.get('name', '') if char else ''
        world = GameWorldManager.get()
        me = world.get_player(self.char_id)
        cur_layer = me.layer_id if me else layer_net_id()
        channel = getattr(self.session, 'channel_id', 1) or 1
        target = next((p for p in world.players.values()
                       if p.char_data.get('name', '').lower() == req.target_nick.lower()), None)
        if not target:
            await self.reply(TeachingSummonRequestAck(result=0xCE), correlation,
                             note=f'teaching summon fail ({req.target_nick} offline)')
            return
        ack = TeachingSummonRequestAck(
            result=0, nick=my_name, pos_x=req.pos_x, pos_y=req.pos_y,
            layer_net_id=cur_layer, channel=channel,
        )
        if target.session and getattr(target.session, 'transport', None):
            await target.session.transport.send_event(event(6033, ack.encode()),
                                                      note=f'teaching summon forward to {req.target_nick}')
        await self.reply(ack, correlation, note=f'teaching summon request ack ({req.target_nick})')

