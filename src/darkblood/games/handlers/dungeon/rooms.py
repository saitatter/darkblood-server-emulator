"""Dungeon room creation, joining, leaving, host promotion, gate selection and map code."""
import struct
from dataclasses import dataclass, field

from darkblood.core.network.proudnet import relay_address
from darkblood.core.serialization.jser import WireError, event, read_varuint, strip_prefix
from darkblood.games.dispatcher import packet_handler
from darkblood.games.entities.character import Character
from darkblood.games.network import results
from darkblood.games.network.messages import (
    ChangeItemObtainAck,
    ChangeItemObtainReq,
    ChangeMapCodeAck,
    ChangeRoomInfoAck,
    ChangeRoomInfoReq,
    ChangeTeamAck,
    ChangeTeamReq,
    CreateRoomAck,
    CreateRoomReq,
    DungeonHistory,
    JoinRoomAck,
    JoinRoomReq,
    LeaveRoomAck,
    RoomInfo,
    RoomInfoListAck,
    RoomMember,
    RoomMemberJoinedNot,
    RoomMemberLeftNot,
    SelectDungeonAck,
)


@dataclass
class DungeonRoom:
    info: RoomInfo
    host: object
    members: dict = field(default_factory=dict)
    started: bool = False
    # Shared run state (reset at the host's 5013): monster kills already credited
    # ((monster id, instance) from 5063) and the floor drops all members see.
    dead: set = field(default_factory=set)
    floor_drops: dict = field(default_factory=dict)
    floor_gold: dict = field(default_factory=dict)
    next_drop_uid: int = 0
    # 5047 join requests waiting for the host: char id -> (session, correlation).
    join_requests: dict = field(default_factory=dict)
    loot_mode: int = 1  # 5088 mode: 1 = free for all (fresh page default), 0 = random looting (0x00584460)


class DungeonRoomHandlers:
    @packet_handler(2010)
    async def handle_get_room_info_list(self, correlation, body):
        # eEGS_GET_ROOMINFOLIST_REQ (sender 0x7AB140), written as
        # "nPage << bWait << nGateID << nMapID << sDiff" (live: page 0,
        # wait 0/1, the gate hash, -1, -1) -> 2011 with the open rooms.
        page, wait_only, gate, map_id, diff = 0, False, -1, -1, -1
        try:
            page, wait_only, gate, map_id, diff = struct.unpack_from('<i?iih', strip_prefix(body))
        except struct.error:
            pass
        rooms = []
        for room in self.transport.server.dungeon_rooms.values():
            info = room.info
            if info.name == '_singleplay' or not room.members:
                continue
            if wait_only and room.started:
                continue
            if gate != -1 and info.gate_id != gate:
                continue
            if map_id != -1 and info.map_id != map_id:
                continue
            rooms.append(self._room_info(room))
        # Page size of the client list is not recovered: everything on one page.
        # The last field is shown plus one (live: 1 displayed "1 / 2"), so it is
        # the last page index.
        ack = RoomInfoListAck(show_only_wait=wait_only, page=0, rooms=rooms, pages=0)
        await self.transport.send_event(event(2011, ack.encode(), correlation),
                                        note='room info list ack (%d rooms)' % len(rooms))


    @packet_handler(5060)
    async def handle_room_member_info(self, correlation, body):
        # eERC_ROOM_MEM_INFO_REQ (Find party row click) -> 5061. The client
        # waits for it before offering the join; member vectors not recovered.
        from darkblood.games.network.messages import RoomMemInfoAck, RoomMemInfoReq
        try:
            room_uid = RoomMemInfoReq.decode(body).room_uid
        except (WireError, struct.error):
            room_uid = -1
        room = self.transport.server.dungeon_rooms.get(room_uid)
        result = results.OK if room is not None and room.members else results.ROOM_NOT_EXISTS
        members = []
        if result == results.OK:
            for member, record in room.members.items():
                members.append(self._member_info(member, record))
        ack = RoomMemInfoAck(result=result, room_uid=room_uid, members=members)
        await self.transport.send_event(event(5061, ack.encode(), correlation),
                                        note='room member info ack (%d, result %d)' % (room_uid, result))


    def _member_info(self, session, record):
        from darkblood.games.network.messages import RoomMemberInfo
        from darkblood.games.world import square_uid
        return RoomMemberInfo(
            square_uid=square_uid(getattr(session, 'square_id', 1) or 1),
            char_uid=int(record.get('id', 0)),
            name=record.get('name', ''),
            char_class=int(record.get('char_class', 0)) & 0xFF,
            level=min(int(record.get('level', 1)), 0xFF))


    @packet_handler(ChangeRoomInfoReq)
    async def handle_change_room_info(self, correlation, body):
        # eERC_CHANGE_ROOMINFO_REQ (Party info OK) -> 5012. The request is a whole
        # jRoomInfo; the client locks input until the ack arrives (froze without it).
        try:
            req = ChangeRoomInfoReq.decode(body).room
        except (WireError, struct.error):
            await self.reply(ChangeRoomInfoAck(result=results.INVALID_STATE), correlation, note='change room info refused (bad request)')
            return
        room = self.room
        if room is None or room.host is not self.session:
            await self.reply(ChangeRoomInfoAck(result=results.INVALID_STATE), correlation, note='change room info refused (not host)')
            return
        info = room.info
        info.name = req.name
        if len(room.members) <= req.max_users <= 4:
            info.max_users = req.max_users
        # The host's client applies gate/map/diff itself before sending (0x0063BAC3);
        # keep them for the room list (2011) and later joiners (5004).
        info.gate_id, info.map_id, info.diff = req.gate_id, req.map_id, req.diff
        ack = ChangeRoomInfoAck(result=0, room=self._room_info(room)).encode()
        await self.transport.send_event(event(5012, ack, correlation),
                                        note='change room info ack (%s, max %d)' % (info.name, info.max_users))
        # 5012 on a member updates only the title and max users (0x0058432D);
        # no recovered message pushes gate/map/diff to members already in the room.
        await self._notify_room(room, [m for m in room.members if m is not self.session],
                                event(5012, ack), 'change room info (member sync)')


    @packet_handler(ChangeItemObtainReq)
    async def handle_change_item_obtain(self, correlation, body):
        # eERC_CHANGE_ITEM_OBTAIN_REQ (looting mode button) -> 5089 (i32 result, bool).
        # Echoing the mode alternates the two modes (see the 5089 schema notes).
        try:
            mode = ChangeItemObtainReq.decode(body).mode
        except (WireError, struct.error):
            return
        room = self.room
        if room is not None:
            if room.host is not self.session:
                return
            room.loot_mode = int(mode)
        ack = ChangeItemObtainAck(mode=mode).encode()
        await self.transport.send_event(event(5089, ack, correlation), note='change item obtain ack (mode=%d)' % mode)
        if room is not None:
            await self._notify_room(room, [m for m in room.members if m is not self.session],
                                    event(5089, ack), 'change item obtain (member sync)')


    @packet_handler(5047)
    async def handle_request_join_room(self, correlation, body):
        # eERC_REQUEST_JOIN_ROOM_REQ (View party info "Join"). The request goes
        # to the room host as 5048 (requester's member entry); the host's
        # confirmation popup continues the flow: its Accept sends 5049 for the
        # requester (AcceptJoinRoomREQ, 0x0063A6CD), which joins it directly.
        from darkblood.games.network.messages import RequestJoinRoomAck, RequestJoinRoomReq
        try:
            room_uid = RequestJoinRoomReq.decode(body).room_uid
        except (WireError, struct.error):
            return
        room = self.transport.server.dungeon_rooms.get(room_uid)
        char = self.current_char()
        if room is None or char is None or not room.members:
            self.transport.record('request-join-room-refused', body, room_uid=room_uid)
            return
        host = room.host
        room.join_requests[int(char['id'])] = (self.session, correlation)
        ack = RequestJoinRoomAck(room_uid=room_uid, requester=self._member_info(self.session, char))
        try:
            await host.transport.send_event(event(5048, ack.encode()),
                                            note='request join room (%s -> room %d)' % (char.get('name'), room_uid))
        except (ConnectionError, OSError):
            pass


    @packet_handler(CreateRoomReq)
    async def handle_create_room(self, correlation, body):
        # eERC_CREATE_ROOM_REQ (sender 0x0058B060) -> 5002 CREATE_ROOM_ACK.
        char = self.current_char()
        if char is None:
            await self.reply(CreateRoomAck(result=results.NO_EXIST_CHAR), correlation, note='create room refused (no character)')
            return
        try:
            req = CreateRoomReq.decode(body)
        except WireError:
            await self.reply(CreateRoomAck(result=results.INVALID_STATE), correlation, note='create room refused (invalid request)')
            return
        await self.leave_room()
        server = self.transport.server
        info = RoomInfo(room_id=next(server.room_ids), name=req.name, gate_id=req.gate_id, map_id=req.map_id,
                        diff=req.diff, max_users=req.max_users if 0 < req.max_users <= 4 else 4, cur_users=1,
                        host_uid=char['id'])
        self.room = DungeonRoom(info, self.session, {self.session: char})
        server.dungeon_rooms[info.room_id] = self.room
        ack = CreateRoomAck(room=info, relay=relay_address())
        await self.transport.send_event(event(5002, ack.encode(), correlation),
                                        note='create room ack (%s)' % req.name)


    @packet_handler(JoinRoomReq)
    async def handle_join_room(self, correlation, body):
        try:
            req = JoinRoomReq.decode(body)
        except WireError:
            room = None
        else:
            room = self.transport.server.dungeon_rooms.get(req.room_id)
        await self.join_room(room, correlation)


    async def join_room(self, room, correlation=0):
        """Join `room` and answer with 5004 (shared by 5003 and the 5054 invite accept)."""
        char = self.current_char()
        result = results.OK
        if char is None:
            result = results.NO_EXIST_CHAR
        elif room is None or room.info.name == '_singleplay':
            result = results.ROOM_NOT_EXISTS
        elif room is not self.room:
            if self.room is not None or any(record['id'] == char['id'] for record in room.members.values()):
                result = results.INVALID_STATE
            elif room.started:
                result = results.ALREADY_PLAY_GAME
            elif len(room.members) >= room.info.max_users:
                result = results.JOIN_FAIL_ROOM_FULL
        if result:
            await self.reply(JoinRoomAck(result=result), correlation, note='join room refused (%d)' % result)
            return

        is_new = self.room is not room
        peers = [member for member in room.members if member is not self.session]
        room.members[self.session] = char
        self.room = room
        roster = [RoomMember(Character.from_dict(record)) for record in room.members.values()]
        ack = JoinRoomAck(room=self._room_info(room), host_uid=room.info.host_uid, members=roster, relay=relay_address(),
                         free_item_obtain=room.loot_mode == 1)
        await self.transport.send_event(event(5004, ack.encode(), correlation), note='join room ack')
        if is_new and self.room is room:
            joined = RoomMemberJoinedNot(RoomMember(Character.from_dict(char)))
            await self._notify_room(room, peers, event(5035, joined.encode()), 'room member joined')


    async def _notify_room(self, room, peers, packet, note):
        for peer in peers:
            if peer.dungeon.room is room:
                try:
                    await peer.transport.send_event(packet, note=note)
                except (ConnectionError, OSError):
                    continue


    async def leave_room(self):
        room = self.room
        if room is None:
            return
        self.room = None
        char = room.members.pop(self.session)
        notice = event(5036, RoomMemberLeftNot(char['id']).encode())
        peers = list(room.members)
        if not peers:
            self.transport.server.dungeon_rooms.pop(room.info.room_id, None)
            return
        promoted_host_uid = None
        if self.session is room.host:
            new_host = peers[0]
            room.host = new_host
            promoted_host_uid = room.members[new_host]['id']
            room.info.host_uid = promoted_host_uid
        await self._notify_room(room, peers, notice, 'room member left')
        if promoted_host_uid is not None:
            # 5022 eERC_CHANGE_ROOMHOST_ACK (0x00599630): i32 result + i64 nChangeNewHostUID.
            # Promotes the remaining member so they can edit party settings / start runs.
            host_notice = event(5022, struct.pack('<Iq', 0, promoted_host_uid))
            await self._notify_room(room, peers, host_notice, f'change room host ({promoted_host_uid})')


    @packet_handler(5043)
    async def handle_select_dungeon(self, correlation, body):
        # eERC_SELECT_DUNGEON_REQ (sender 0x7AC1C0), observed body:
        # ffffff7f + J-wstring gate id ("Act1_G1") -> 5044.
        gate = ''
        try:
            length, offset = read_varuint(body, 4)
            gate = body[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        char = self.current_char() or {}
        ack = self._select_dungeon_ack(gate, char)
        await self.transport.send_event(event(5044, ack.encode(), correlation),
                                        note=f'select dungeon ack ({gate}, history {ack.dun_history}, '
                                             f'{len(ack.quest_ids)} active quests)')
        # The whole party enters the gate: entering it (0x006C7920) sends P2P 0x5F
        # and waits up to 15 s (0x005C6D40(2, 15000)) until every room member has
        # answered with its own 0x5F (0x009695F0 -> 0x005C4E40). Members only enter
        # through 5044, whose global handler 0x007702E0 changes the state itself;
        # without it the leader sat 10-15 s on a black screen (live 2026-11-21).
        room = self.room
        if room is not None and room.host is self.session and room.info.name != '_singleplay':
            for member, record in list(room.members.items()):
                if member is self.session:
                    continue
                notice = self._select_dungeon_ack(gate, record)
                try:
                    await member.transport.send_event(event(5044, notice.encode()),
                                                      note=f'select dungeon (party gate {gate})')
                except (ConnectionError, OSError):
                    pass


    def _select_dungeon_ack(self, gate, char):
        from darkblood.games.game_data.client_dict import gate_dungeons
        dungeons = set(gate_dungeons().get(gate, []))
        # Only cleared dungeons get an entry; the others default to Normal.
        dun_history = {dungeon: DungeonHistory(rec['map'], rec['diff'], 1)
                       for dungeon, rec in char.get('dungeon_history', {}).items() if dungeon in dungeons}
        quest_ids = []
        for quest_id in char.get('quests_active', {}):
            try:
                quest_ids.append(int(quest_id))
            except ValueError:
                continue
        return SelectDungeonAck(gate_id=gate, dun_history=dun_history,
                                quest_ids=sorted({q & 0xFFFFFFFF for q in quest_ids}))


    def _record_dungeon_clear(self, char, map_code):
        """Remember the highest cleared difficulty per dungeon (5044 history).

        34 quest maps (QuestLink) are copies of their dungeon's regular map at that
        Difficult (e.g. Act1_G1_A16 = Act1_G1_A10: same file, monsters and stats;
        only gold, PlayOrder and QuestLink differ). Such a clear counts as the
        regular map, which the history keeps: the gate auto-selects the history
        map (0x006D1120). The other quest maps have their own content (own file,
        or e.g. Act1_G1_A15 at level 35-37 although Difficult is 2) and do not
        advance the dungeon's difficulty.
        """
        from darkblood.games.game_data.client_dict import dungeon_map_copies, dungeon_maps
        map_code = dungeon_map_copies().get(map_code, map_code)
        info = dungeon_maps().get(map_code)
        if info is None or info[2]:
            return
        dungeon, diff, _ = info
        history = char.setdefault('dungeon_history', {})
        record = history.get(dungeon)
        if record is None or diff >= record['diff']:
            history[dungeon] = {'map': map_code, 'diff': diff}


    @packet_handler(5009)
    async def handle_change_map_code(self, correlation, body):
        # eERC_CHANGE_MAPCODE_REQ (sender 0x7AD680), observed body: ffffff7f
        # + J-wstring map code ("Act1_G1_A10") + bool -> 5010, consumed by
        # JAppStateDungeonGate vf20 -> 0x6D4A00 (only in app state 8).
        code, flag = '', False
        try:
            length, offset = read_varuint(body, 4)
            code = body[offset:offset + length].decode('utf-16le')
            flag = body[offset + length:offset + length + 1] == bytes([1])
        except (WireError, UnicodeDecodeError):
            pass
        self.map_code = code
        ack = ChangeMapCodeAck(map_code=code, flag=flag).encode()
        await self.transport.send_event(event(5010, ack, correlation),
                                        note='change mapcode ack (%s)' % code)
        room = self.room
        if room is not None and room.host is self.session and room.info.name != '_singleplay':
            # The members sit in the same gate (5044 above): show the host's choice.
            await self._notify_room(room, [m for m in room.members if m is not self.session],
                                    event(5010, ack), 'change mapcode (party gate %s)' % code)


    @staticmethod
    def _room_info(room):
        """jRoomInfo with the live member count and state.

        State 8 is a joinable waiting room: View party info enables Join only
        when +0x30 == 8 (0x0062E422). 1 and 2 show "PLAY" (live), anything else
        "FULL".
        """
        from dataclasses import replace
        state = 1 if room.started else (8 if len(room.members) < room.info.max_users else 0)
        return replace(room.info, cur_users=len(room.members), state=state)


    def _current_char(self):
        char = self.current_char()
        return char


    @packet_handler(5005)
    async def handle_leave_room(self, correlation, body):
        # eERC_LEAVE_ROOM_REQ (0x0058B240) -> 5006 eERC_LEAVE_ROOM_ACK (0x00598A00).
        # In town/gate this only leaves the party room. Inside a dungeon (eAS_GamePlay,
        # JAppStateGamePlay__OnBtn_GamePlayExit 0x006CE740), the client sends 5005
        # without 5045 and relies on 5046 (BackToSquareAck) to transition back to town,
        # plus 2085 (ChangeDungeonPenaltyNot) when abandoning before dungeon clear.
        was_in_dungeon = getattr(self, 'in_dungeon', False)
        was_cleared = getattr(self, 'dungeon_cleared', False)
        self.in_dungeon = False
        self.dungeon_cleared = False
        await self.leave_room()
        ack = LeaveRoomAck(result=0)
        await self.reply(ack, correlation, note='leave room ack')
        if was_in_dungeon:
            from darkblood.games.handlers.square import _wire_square_uid
            from darkblood.games.network.messages import BackToSquareAck, ChangeDungeonPenaltyNot
            back_ack = BackToSquareAck(
                square_uid=_wire_square_uid(self.session.square_id),
                layer_net_id=self.session.square._town_layer(),
                cur_ar=self.session.square._current_gold(),
            )
            await self.send_msg(back_ack, note='back to square ack (dungeon exit)')
            await self.session.square._sync_passive_stress()
            if not was_cleared:
                char = self.current_char()
                if char is not None:
                    from darkblood.games.progression import apply_dungeon_penalty
                    pen = apply_dungeon_penalty(char, penalty_type=0)
                    self.save_char()
                    await self.transport.send_event(
                        event(2085, pen.encode()),
                        note=f'change dungeon penalty not (leave count={pen.penalty_level}, elapsed={pen.duration}s)',
                    )


    @packet_handler(ChangeTeamReq)
    async def handle_change_team(self, correlation, body):
        # eERC_CHANGE_TEAM_REQ -> 5016 eERC_CHANGE_TEAM_ACK.
        req = ChangeTeamReq.decode(body)
        self.transport.record('change-team-req', body, team_id=req.team_id)
        ack = ChangeTeamAck(result=0, team_id=req.team_id)
        await self.reply(ack, correlation, note=f'change team ack (team={req.team_id})')


    @staticmethod
    async def _send_to(sessions, packet, note):
        for member in sessions:
            try:
                await member.transport.send_event(packet, note=note)
            except (ConnectionError, OSError):
                pass


    @packet_handler(5052)
    async def handle_again_select_dungeon(self, correlation, body):
        # eERC_AGAIN_SELECT_DUNGEON_REQ (0x007AC480) -> 5053 eERC_AGAIN_SELECT_DUNGEON_ACK (0x00770A80).
        from darkblood.games.network.messages.dungeon import AgainSelectDungeonAck, DungeonHistory
        char = self.current_char() or {}
        gate_id = getattr(self, 'gate_id', '') or 'Act1_G1'
        history = {}
        for dun_id, info in (char.get('dungeon_history') or {}).items():
            if isinstance(info, dict):
                history[dun_id] = DungeonHistory(
                    map_id=info.get('map_id', ''),
                    max_diff=int(info.get('max_diff', 0)) & 0xFF,
                    cleared=int(info.get('cleared', 1)) & 0xFF,
                )
        active_quests = sorted({int(q['id']) for q in char.get('quests', []) if 'id' in q})
        await self.reply(
            AgainSelectDungeonAck(result=0, history=history, min_citadel_history=[],
                                  gate_id=gate_id, active_quests=active_quests),
            correlation, note=f'again select dungeon ack (gate={gate_id}, history={len(history)})',
        )


    @packet_handler(5236)
    async def handle_training_join_room(self, correlation, body):
        # eERC_TRAINING_JOIN_ROOM_REQ (0x00798F80) -> 5237 eERC_TRAINING_JOIN_ROOM_ACK (0x0075AEC0).
        from darkblood.games.network.messages.dungeon import TrainingJoinRoomAck
        await self.reply(TrainingJoinRoomAck(result=0), correlation, note='training join room ack')


    @packet_handler(5238)
    async def handle_training_leave_room(self, correlation, body):
        # eERC_TRAINING_LEAVE_ROOM_REQ (0x007990D0) -> 5239 eERC_TRAINING_LEAVE_ROOM_ACK (0x0074B830).
        # 0x0074B830 only reads result and returns 1 without transitioning back to town;
        # follow with 5046 BackToSquareAck (like 5005 dungeon exit) to return to town.
        from darkblood.games.handlers.square import _wire_square_uid
        from darkblood.games.network.messages import BackToSquareAck
        from darkblood.games.network.messages.dungeon import TrainingLeaveRoomAck
        await self.reply(TrainingLeaveRoomAck(result=0), correlation, note='training leave room ack')
        back_ack = BackToSquareAck(
            square_uid=_wire_square_uid(self.session.square_id),
            layer_net_id=self.session.square._town_layer(),
            cur_ar=self.session.square._current_gold(),
        )
        await self.send_msg(back_ack, note='back to square ack (training exit)')

