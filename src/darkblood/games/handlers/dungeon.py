import struct
import time
from dataclasses import dataclass, field

from darkblood.core.hashing import jhash
from darkblood.core.serialization.jser import WireError, event, read_varuint, strip_prefix
from darkblood.frontend.relay import relay_address
from darkblood.games.entities.character import Character
from darkblood.games.network.messages import (
    ActiveWarFlagReq,
    ChangeDungeonLayerNot,
    ChangeItemObtainAck,
    ChangeItemObtainReq,
    ChangeRoomInfoAck,
    ChangeRoomInfoReq,
    ChangeMapCodeAck,
    ChangeTeamAck,
    ChangeTeamReq,
    ChoiceRewardPartyRankAck,
    ChoiceRewardPartyRankReq,
    CreateRoomAck,
    CreateRoomReq,
    DailyRebirthCoinUseAck,
    DailyRebirthCoinUseReq,
    DropItemNot,
    GameplayDieCharAck,
    GameplayDieCharReq,
    GuideBeginnerUpdateReq,
    JoinRoomAck,
    JoinRoomReq,
    LeaveRoomAck,
    MonsterDeadReq,
    PartyAcceptInviteAck,
    PartyAcceptInviteReq,
    PartyInviteAck,
    PartyInviteReq,
    RebirthCoinChangeNot,
    RoomInfo,
    RoomInfoListAck,
    RoomMember,
    RoomMemberJoinedNot,
    RoomMemberLeftNot,
    DungeonHistory,
    SelectDungeonAck,
    StartGameAck,
    StartGameReq,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.games.handlers.base import BaseDomainService
from darkblood.games.network import results

# The daily-claim sender refuses when owned or received coins reach 3.
DAILY_REBIRTH_COINS = 3


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


class DungeonHandlers(BaseDomainService):
    """Rooms, dungeon gate, map code and game start."""

    def __init__(self, session):
        super().__init__(session)
        self.room = None

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
            await self.transport.send_event(event(5012, ChangeRoomInfoAck(result=results.INVALID_STATE).encode(),
                                                  correlation), note='change room info refused (bad request)')
            return
        room = self.room
        if room is None or room.host is not self.session:
            await self.transport.send_event(event(5012, ChangeRoomInfoAck(result=results.INVALID_STATE).encode(),
                                                  correlation), note='change room info refused (not host)')
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
            await self.transport.send_event(event(5002, CreateRoomAck(result=results.NO_EXIST_CHAR).encode(), correlation),
                                            note='create room refused (no character)')
            return
        try:
            req = CreateRoomReq.decode(body)
        except WireError:
            await self.transport.send_event(event(5002, CreateRoomAck(result=results.INVALID_STATE).encode(), correlation),
                                            note='create room refused (invalid request)')
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
            await self.transport.send_event(event(5004, JoinRoomAck(result=result).encode(), correlation),
                                            note='join room refused (%d)' % result)
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

    @packet_handler(StartGameReq)
    async def handle_start_game(self, correlation, body):
        try:
            request = StartGameReq.decode(body)
            if not request.map_code or '\x00' in request.map_code:
                raise WireError('Missing or invalid dungeon map code')
        except (WireError, UnicodeDecodeError):
            # The success path assumes the map code resolves to a client property.
            ack = StartGameAck(result=1)
        else:
            ack = StartGameAck(map_code=request.map_code)
            self.map_code = request.map_code
            self._reset_dungeon_stats()
            if self.room is not None and self.room.host is self.session:
                self.room.started = True
                self.room.dead.clear()
                self.room.floor_drops.clear()
                self.room.floor_gold.clear()
        await self.transport.send_event(event(5014, ack.encode(), correlation),
                                        note='start game ack')
        if ack.result == 0:
            await self._consume_session_stress(self.session)
        room = self.room
        if ack.result == 0 and room is not None and room.host is self.session and room.info.name != '_singleplay':
            # Shared dungeon, step 1: the members sit in the same gate (5044 at the
            # host's 5043), whose dispatcher handles 5014 (0x007880A0). Start them on
            # the host's map so all clients load it and meet in its relay group.
            for member in list(room.members):
                if member is self.session or member.dungeon.room is not room:
                    continue
                member.dungeon.map_code = request.map_code
                member.dungeon._reset_dungeon_stats()
                try:
                    await member.transport.send_event(event(5014, ack.encode()),
                                                      note='start game (party, %s)' % request.map_code)
                    await self._consume_session_stress(member)
                except (ConnectionError, OSError):
                    pass

    def _reset_dungeon_stats(self):
        self.dungeon_kill_count = 0
        self.dungeon_score = 0
        self.dungeon_exp = 0
        self.visited_dungeon_layers = set()

    async def _consume_session_stress(self, session, amount=None):
        from darkblood.games.progression import STRESS_PER_DUNGEON_ROOM, consume_stress, stress_changed_not
        char = session.dungeon.current_char()
        if char is None:
            return
        pts = STRESS_PER_DUNGEON_ROOM if amount is None else amount
        if consume_stress(char, pts):
            session.dungeon.save_char()
            await session.transport.send_event(
                event(2023, stress_changed_not(char).encode()),
                note=f"stress changed not ({char['stress']})",
            )

    @packet_handler(ChangeDungeonLayerNot)
    async def handle_change_dungeon_layer(self, correlation, body):
        # eERC_CHANGE_DUNGEON_LAYER_NOT (sender 0x7900B0): ffffff7f + i64 layer_net_id.
        try:
            msg = ChangeDungeonLayerNot.decode(body)
            # layer_net_id = (jhash(map_code) << 32) | layer_id
            layer_id, map_hash = msg.layer_net_id & 0xFFFFFFFF, (msg.layer_net_id >> 32) & 0xFFFFFFFF
            self.current_dungeon_layer = layer_id
            self.current_dungeon_map_hash = map_hash
            self.transport.record('dungeon-layer', body, layer_id=layer_id, map_hash='0x%08x' % map_hash)
            visited = getattr(self, 'visited_dungeon_layers', None)
            if visited is None:
                visited = set()
                self.visited_dungeon_layers = visited
            if layer_id not in visited:
                visited.add(layer_id)
                # First layer of a run was already charged on 5013 StartGame; charge subsequent rooms.
                if len(visited) > 1:
                    await self._consume_session_stress(self.session)
        except (struct.error, ValueError):
            pass

    @packet_handler(2509)
    async def handle_monster_layer_move(self, correlation, body):
        # eEGS_MONSTER_LAYER_MOVE_NOT: notification without an ACK opcode
        # (2510 is PET_NICK_CHANGE_REQ). Live: ffffff7f 13270006 + two
        # (u32 layer, u32 hash) pairs, e.g. 2 -> 5 in 0x32ADCD46. Recorded only.
        self.transport.record('monster-layer-move', body)

    @packet_handler(ActiveWarFlagReq)
    async def handle_active_war_flag(self, correlation, body):
        # eEGS_ACTIVE_WARFLAG_REQ (sender 0x79C300): ffffff7f + u32 war_flag_id.
        try:
            msg = ActiveWarFlagReq.decode(body)
            self.active_war_flag = msg.war_flag_id
            self.transport.record('active-warflag', body, war_flag_id=msg.war_flag_id)
        except (struct.error, ValueError):
            pass

    @packet_handler(2204)
    async def handle_frame_stat(self, correlation, body):
        # eEGS_FRAME_STAT_NOT: client frame-rate telemetry sent after dungeon
        # results (live: ffffff7f 3a f9010000, the u32 varies per run). The
        # opcode has no ACK; recorded only so it no longer shows as unhandled.
        self.transport.record('frame-stat', body)

    @packet_handler(GuideBeginnerUpdateReq)
    async def handle_guide_beginner_update(self, correlation, body):
        # eEGS_GUIDE_BEGINNER_UPDATE_REQ (sender 0x79A3B0): ffffff7f + vector<u32> guide_ids.
        try:
            msg = GuideBeginnerUpdateReq.decode(body)
            self.transport.record('guide-beginner-update', body, guide_ids=msg.guide_ids)
        except (struct.error, ValueError):
            pass

    def _shared_run(self):
        """The party room this session plays a dungeon in with others, or None.

        The host's client runs the monsters: only it sends 5063 and 5017 (live
        2026-11-21), so kills, drops and the result are shared through the room.
        """
        room = self.room
        if room is None or not room.started or room.info.name == '_singleplay':
            return None
        return room

    def _run_members(self):
        """(session, character) of every member in this session's dungeon run."""
        room = self._shared_run()
        if room is None:
            char = self._current_char()
            return [(self.session, char)] if char is not None else []
        code = getattr(self, 'map_code', '')
        out = []
        for member, record in room.members.items():
            if member.dungeon.room is room and getattr(member.dungeon, 'map_code', '') == code:
                char = member.current_char()
                if char is not None:
                    out.append((member, char))
        return out

    def _loot_holder(self):
        """Where the floor drops live: the shared room, or this session alone."""
        room = self._shared_run()
        if room is not None:
            return room
        if not hasattr(self, 'floor_drops'):
            self.floor_drops, self.floor_gold, self.next_drop_uid = {}, {}, 0
        return self

    @packet_handler(MonsterDeadReq)
    async def handle_monster_dead(self, correlation, body):
        # eERC_MONSTER_DEAD_REQ (sender 0x78A690): ffffff7f + u32 monster_id + u32 param.
        try:
            msg = MonsterDeadReq.decode(body)
        except (struct.error, ValueError):
            return
        self.transport.record('monster-dead', body, monster_id=msg.monster_id, param=msg.param)
        room = self._shared_run()
        if room is not None:
            key = (msg.monster_id, msg.param)
            if key in room.dead:
                return  # already credited from another member's report
            room.dead.add(key)
        from darkblood.games.game_data.client_dict import monsters
        info = monsters().get(msg.monster_id)
        exp = round(info['exp']) if info else 0
        mon_target = info['id'] if info else msg.monster_id
        members = self._run_members()
        # Every member of the run gets the kill's EXP, score and quest progress.
        for member, char in members:
            run = member.dungeon
            run.dungeon_kill_count = getattr(run, 'dungeon_kill_count', 0) + 1
            if info:
                run.dungeon_score = getattr(run, 'dungeon_score', 0) + max(1, exp) * 10
            if exp > 0:
                run.dungeon_exp = getattr(run, 'dungeon_exp', 0) + exp
                await member.quests.grant_exp(char, exp)
            await run._update_quest_monsters(mon_target, char)
        if members:
            self.store().save()
        char = self._current_char()
        if char is not None and info:
            await self._drop_loot(msg.param, info, char)

    async def _update_quest_monsters(self, mon_code, char):
        """Advance kill counters for active quests targeting mon_code."""
        from darkblood.games.game_data.client_dict import quest_monster_objectives
        from darkblood.games.network.messages import QuestObjective, QuestUpdateNot
        objectives = quest_monster_objectives().get(mon_code, [])
        if not objectives:
            return
        active = char.get('quests_active', {})
        for q_hash, obj_idx, target_count in objectives:
            q_key = str(q_hash)
            if q_key in active:
                q_record = active[q_key]
                counters = q_record.setdefault('counters', [])
                while len(counters) <= obj_idx:
                    counters.append(0)
                if counters[obj_idx] < target_count:
                    counters[obj_idx] += 1
                    self.store().save()
                    update = QuestUpdateNot(updates=[QuestObjective(q_hash, obj_idx, counters[obj_idx])]).encode()
                    await self.transport.send_event(
                        event(2075, update),
                        note=f'quest update not ({q_key} obj={obj_idx} count={counters[obj_idx]}/{target_count})'
                    )

    @packet_handler(5017)
    async def handle_finish_game(self, correlation, body):
        # eERC_FINISH_GAME_REQ (sender 0x007AD380) -> 5018 eERC_FINISH_GAME_ACK (handler 0x007ADB60).
        from darkblood.games.network.messages import FinishGameAck, FinishGameReq, SingleReward
        req = FinishGameReq.decode(body)
        self.transport.record('finish-game-req', body, is_clear=req.is_clear)
        map_code = getattr(self, 'map_code', '')
        room = self._shared_run()
        # Only the host's client sends 5017 in a party run (live 2026-11-21): its
        # result goes to every member. A member's own 5017 stays a solo result.
        if room is not None and room.host is self.session:
            members = self._run_members()
        else:
            char = self._current_char()
            members = [(self.session, char)] if char is not None else []
        # Optional 5017 trailing maps: map<i64,i32> scores, map<i64,i32> rank_points.
        # Headless tests may send a bare 1-byte body; parse defensively.
        rank_points = {}
        if req.tail:
            from darkblood.core.serialization.jser import JSerBufferReader
            try:
                r = JSerBufferReader(req.tail)
                r.read_tagged_map(JSerBufferReader.read_i64, JSerBufferReader.read_i32)  # per-player combat score
                rank_points = r.read_tagged_map(JSerBufferReader.read_i64, JSerBufferReader.read_i32)  # per-player rank percentage (0..100+)
            except (WireError, struct.error, IndexError):
                rank_points = {}

        # Client rank enum (0x007101F0 / 0x00720000:530 Lua_OnChecked_5):
        # 0=D, 1=C, 2=B, 3=A, 4=S, 5=SS, 6=SSS.
        kill_count = getattr(self, 'dungeon_kill_count', 0)
        score = getattr(self, 'dungeon_score', 0)
        if score >= 50000 or kill_count >= 25:
            fallback_rank = 6
        elif score >= 30000 or kill_count >= 20:
            fallback_rank = 5
        elif score >= 15000 or kill_count >= 15:
            fallback_rank = 4
        elif score >= 8000 or kill_count >= 10:
            fallback_rank = 3
        elif score >= 3000 or kill_count >= 5:
            fallback_rank = 2
        elif score >= 1000 or kill_count >= 2:
            fallback_rank = 1
        else:
            fallback_rank = 0

        def _points_to_rank(pts: int) -> int:
            if pts >= 98:
                return 6
            if pts >= 90:
                return 5
            if pts >= 80:
                return 4
            if pts >= 65:
                return 3
            if pts >= 50:
                return 2
            if pts >= 30:
                return 1
            return 0

        # The player's UID is the character id (2007 details +0x1C, copied to
        # player +0x10 by 0x0095A150). Characters have no 'char_uid' key, so
        # mapSingleReward used to go out empty and the result screen froze.
        rewards = {}
        member_ranks = []
        for member, char in members:
            if req.is_clear:
                member.dungeon._record_dungeon_clear(char, map_code)
            # EXP was already granted per kill (5063 -> 5086), so the result
            # screen only reports it. No extra boxes are offered.
            uid = int(char.get('id', 0))
            gained = getattr(member.dungeon, 'dungeon_exp', 0)
            user_rank = _points_to_rank(rank_points[uid]) if uid in rank_points else fallback_rank
            member_ranks.append(user_rank)
            rewards[uid] = SingleReward(total=gained, exp=gained, rank=user_rank)
        if members and req.is_clear:
            self.store().save()

        # Party rank uses the exact same 0..6 (D..SSS) scale as SingleReward.rank.
        # In solo runs this guarantees party_rank == user_rank (never off-by-one).
        party_rank = round(sum(member_ranks) / len(member_ranks)) if member_ranks else fallback_rank
        box_grade = min(4, max(1, (party_rank + 1) // 2))

        ack = FinishGameAck(
            result=0,
            is_clear=req.is_clear,
            map_code=map_code,
            rewards={uid: reward for uid, reward in rewards.items() if uid},
            rank_first=party_rank,
            rank_final=party_rank,
            box_grade=box_grade,
            extra_box_cost=0,
        ).encode()
        await self.transport.send_event(event(5018, ack, correlation),
                                        note=f'finish game ack ({map_code} clear={req.is_clear} rank={party_rank})')
        await self._send_to([member for member, _ in members if member is not self.session], event(5018, ack),
                            f'finish game (party, {map_code} rank={party_rank})')

    async def _drop_loot(self, source_id, monster, char):
        """Roll itemlooting.lua drops for a kill and announce them with 5064.

        source_id is the 5063 instance id: 0x0078A870 looks the monster up by
        it (0x00859C60) and spawns the drops there. In a party run the drops
        are rolled once, kept in the room and shown to every member; the first
        to pick one up gets it (free for all; random looting is not applied yet).
        """
        from darkblood.games import loot
        from darkblood.games.network.messages import DropItemNot, ItemDropEntry
        codes = loot.roll_drops(getattr(self, 'map_code', ''), monster, int(char.get('char_class', 0)))
        if not codes:
            return
        import random
        from darkblood.games.game_data.client_dict import money_drops
        holder = self._loot_holder()
        entries = []
        for code in codes:
            holder.next_drop_uid += 1
            uid = holder.next_drop_uid
            holder.floor_drops[uid] = code
            count = 1
            money = money_drops().get(code)
            if money:
                # Roll the AR now so the floor label (count, passed to
                # 0x004C8CA0 as the amount) matches what 5114 awards.
                low = int(money[0])
                count = min(0xFFFF, random.randint(low, max(low, int(money[1]))))
                holder.floor_gold[uid] = count
            entries.append(ItemDropEntry(drop_uid=uid, item_id=jhash(code), count=count))
        packet = event(5064, DropItemNot(source_id=source_id, drops=entries).encode())
        for member, _ in self._run_members():
            try:
                await member.transport.send_event(packet, note='drop item not (%s: %s)' % (monster['id'], ', '.join(codes)))
            except (ConnectionError, OSError):
                pass

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

    @packet_handler(GameplayDieCharReq)
    async def handle_gameplay_die_char(self, correlation, body):
        # eERC_GAMEPLAY_DIE_CHAR_REQ (writer 0x0078EDF0) -> 5094 (0x0078F090).
        # bDie = 1: echo the client's own UID so the handler opens the revive
        # window (page 0x6B). bDie = 0: revive; spend one rebirth coin and
        # report the remaining count in the trailing u16.
        req = GameplayDieCharReq.decode(body)
        char = self._current_char()
        # Echo the client's own UID unchanged (0x00946570; live: 0, because
        # details +0x1C is 0). Substituting the character id (1) made the
        # death page 0x0055BEF0 look up an unknown user through 0x00966470,
        # get NULL and read [0x10] (live crash at 0x0055BF71, 2026-11-17).
        char_uid = req.char_uid

        coins = 0
        if char is not None:
            coins = int(char.get('rebirth_coins', 3))
            if not req.bDie and coins > 0:
                coins -= 1
                char['rebirth_coins'] = coins
                self.store().save()
        self.die_count = getattr(self, 'die_count', 0) + (1 if req.bDie else 0)

        # On revive (bDie = False), other_uid must match the reviving player UID (0x0055C354)
        # to execute the revival routine (0x00548D80).
        reviver_uid = char_uid if not req.bDie else 0
        # nLayerID/nX/nY place the revived unit (0x0055BEF0). Echo the position
        # the client reported; these fields were once sent as HP values, which
        # revived the player far from where they died.
        ack = GameplayDieCharAck(
            result=0,
            char_uid=char_uid,
            other_uid=reviver_uid,
            bDie=req.bDie,
            layer_id=req.layer_id,
            x=req.x,
            y=req.y,
            party_rebirth_limit=self.die_count,  # previous value kept; meaning not recovered
            rebirth_coin=coins,
        ).encode()
        await self.transport.send_event(event(5094, ack, correlation),
                                        note='gameplay die char ack (die=%d uid=%d coins=%d)' % (req.bDie, char_uid, coins))
        if not req.bDie:
            await self.transport.send_event(event(2286, RebirthCoinChangeNot(result=0, coins=coins).encode()),
                                            note='rebirth coin change not (%d)' % coins)

    @packet_handler(DailyRebirthCoinUseReq)
    async def handle_daily_rebirth_coin_use(self, correlation, body):
        # eEGS_DAILY_REBIRTH_COIN_USE_REQ -> 2449 (0x0079DC70) + 2286 (0x007983B0).
        # Daily claim of free rebirth coins: top the owned coins up to 3, count
        # them as received today, then announce the new total with 2286.
        req = DailyRebirthCoinUseReq.decode(body)
        char = self._current_char()
        if char is None:
            await self.transport.send_event(event(2449, struct.pack('<I', 1), correlation),
                                            note='daily rebirth coin fail (no char)')
            return
        today = time.strftime('%Y-%m-%d')
        if char.get('daily_rebirth_day') != today:
            char['daily_rebirth_day'] = today
            char['daily_rebirth_recv'] = 0
        coins = int(char.get('rebirth_coins', 3))
        received = int(char.get('daily_rebirth_recv', 0))
        granted = max(0, min(DAILY_REBIRTH_COINS - coins, DAILY_REBIRTH_COINS - received))
        coins += granted
        received += granted
        char['rebirth_coins'] = coins
        char['daily_rebirth_recv'] = received
        self.store().save()
        ack = DailyRebirthCoinUseAck(result=0, daily_recv_cnt=received, pcbang_coin_remain=0).encode()
        await self.transport.send_event(event(2449, ack, correlation),
                                        note='daily rebirth coin use ack (pcbang=%d +%d)' % (req.coin_type, granted))
        await self.transport.send_event(event(2286, RebirthCoinChangeNot(result=0, coins=coins).encode()),
                                        note='rebirth coin change not (%d)' % coins)

    @packet_handler(5005)
    async def handle_leave_room(self, correlation, body):
        # eERC_LEAVE_ROOM_REQ (0x0058B240) -> 5006 eERC_LEAVE_ROOM_ACK (0x00598A00).
        # Acknowledges leaving game room before eERC_BACK_TO_SQUARE_REQ (5045).
        await self.leave_room()
        ack = LeaveRoomAck(result=0).encode()
        await self.transport.send_event(event(5006, ack, correlation), note='leave room ack')

    @packet_handler(ChoiceRewardPartyRankReq)
    async def handle_choice_reward_party_rank(self, correlation, body):
        # eERC_CHOICE_REWARD_PARTYRANK_REQ (0x00780000.c:9280) -> 5091 eERC_CHOICE_REWARD_PARTYRANK_ACK (0x0078D660).
        req = ChoiceRewardPartyRankReq.decode(body)
        char = self._current_char()
        char_id = self.char_id
        reward_code = 'Ihppa0001'
        item_id = jhash(reward_code) & 0xFFFFFFFF
        from darkblood.games.entities.items import UPDATE_OWNER, Item
        from darkblood.player_management.characters import add_reward_items
        stored_items = []
        if char:
            stored_items = add_reward_items(char, [(reward_code, 1)])
            self.store().save()
        reward_item = [Item(owner=UPDATE_OWNER, **i) for i in stored_items] if stored_items else []
        gold = char.get('gold', char.get('u66', 0)) if char else 0
        ack = ChoiceRewardPartyRankAck(
            result=0,
            char_uid=char_id,
            item_id=item_id,
            count=1,
            box_type=0,
            box_cost=0,
            items=reward_item,
            gold=gold,
        ).encode()
        await self.transport.send_event(event(5091, ack, correlation),
                                        note=f'choice reward partyrank ack (card={req.card_index} item={reward_code})')

    @packet_handler(ChangeTeamReq)
    async def handle_change_team(self, correlation, body):
        # eERC_CHANGE_TEAM_REQ -> 5016 eERC_CHANGE_TEAM_ACK.
        req = ChangeTeamReq.decode(body)
        self.transport.record('change-team-req', body, team_id=req.team_id)
        ack = ChangeTeamAck(result=0, team_id=req.team_id).encode()
        await self.transport.send_event(event(5016, ack, correlation), note=f'change team ack (team={req.team_id})')

    @packet_handler(5065)
    async def handle_pick_up_item(self, correlation, body):
        # eERC_PICK_UP_ITEM_REQ (prefix + u32 drop uid). 5066 has no client
        # handler; 5068 (global 0x0078AD80) removes the drop and prints the
        # message, and an unsolicited 2037 puts the item into the bag.
        from darkblood.games.entities.items import UPDATE_OWNER, Item
        from darkblood.games.network.messages import DragItemAck, ItemDropEntry, PickUpItemReq, PickUpItemResultAck
        from darkblood.player_management.characters import add_reward_items, free_bag_slots, slots_needed
        req = PickUpItemReq.decode(body)
        holder = self._loot_holder()
        drops = holder.floor_drops
        code = drops.get(req.drop_uid)
        char = self._current_char()
        self.transport.record('pick-up-item-req', body, drop_uid=req.drop_uid, code=code or '')
        if not code or char is None:
            return
        run = self._run_members()
        room = self._shared_run()
        is_random = room is not None and room.loot_mode == 0 and bool(run)
        from darkblood.games.game_data.client_dict import money_drops
        money = money_drops().get(code)
        if money:
            # AR drop: 5114 eERC_GET_DROP_AR_NOT (0x00792700) removes the drop
            # (0x0086AFF0) and plays the picker's pickup before it checks the
            # result; only result 0 adds the amount to the *local* player +0x70.
            # The other members get the same notice with a nonzero result.
            import random
            if is_random:
                winner, char = random.choice(run)
            else:
                winner = self.session
            others = [member for member, _ in run if member is not winner]
            from darkblood.games.network.messages import GetDropArNot
            del drops[req.drop_uid]
            amount = holder.floor_gold.pop(req.drop_uid, None)
            if amount is None:
                amount = random.randint(int(money[0]), max(int(money[0]), int(money[1])))
            char['gold'] = char.get('gold', 0) + amount
            char['u66'] = char['gold']
            self.store().save()
            ack = GetDropArNot(result=0, gold=amount, drop_id=req.drop_uid, picker_uid=char['id']).encode()
            await winner.transport.send_event(event(5114, ack),
                                              note='picked AR (%s: +%d, total %d)' % (code, amount, char['gold']))
            seen = GetDropArNot(result=1, gold=amount, drop_id=req.drop_uid, picker_uid=char['id']).encode()
            await self._send_to(others, event(5114, seen), 'AR picked by %s' % char.get('name'))
            return
        needed = slots_needed([(code, 1)])
        if is_random:
            # Random looting: choose randomly among members who have free bag space,
            # so one member's full bag does not block the whole party from looting.
            import random
            eligible = [(m, c) for m, c in run
                        if free_bag_slots(c) is None or free_bag_slots(c) >= needed]
            if not eligible:
                await self.transport.send_event(
                    event(5068, PickUpItemResultAck(result=results.INVEN_FULL, picker_uid=char['id']).encode()),
                    note='pick up item refused (all party bags full, drop %d)' % req.drop_uid)
                return
            winner, char = random.choice(eligible)
        else:
            winner = self.session
            free = free_bag_slots(char)
            if free is not None and needed > free:
                await self.transport.send_event(
                    event(5068, PickUpItemResultAck(result=results.INVEN_FULL, picker_uid=char['id']).encode()),
                    note='pick up item refused (bag full, drop %d)' % req.drop_uid)
                return
        others = [member for member, _ in run if member is not winner]
        del drops[req.drop_uid]
        stored = add_reward_items(char, [(code, 1)])
        self.store().save()
        entry = ItemDropEntry(drop_uid=req.drop_uid, item_id=jhash(code))
        result = event(5068, PickUpItemResultAck(result=0, picker_uid=char['id'], drop=entry).encode())
        await winner.transport.send_event(result, note='pick up item result (drop %d: %s)' % (req.drop_uid, code))
        # The bag update (2037) goes to the winner only; 5068 removes the drop for all.
        await self._send_to(others, result, 'item picked by %s' % char.get('name'))
        await winner.transport.send_event(event(2037, DragItemAck(result=0, items=[Item(owner=UPDATE_OWNER, **i) for i in stored]).encode()),
                                        note='picked item into bag (%s)' % code)
        await winner.quests.check_quest_item_objectives(char)

    @staticmethod
    async def _send_to(sessions, packet, note):
        for member in sessions:
            try:
                await member.transport.send_event(packet, note=note)
            except (ConnectionError, OSError):
                pass

    @packet_handler(5363)
    async def handle_gold_goblin_attack(self, correlation, body):
        # eERC_GOLDGOBLIEN_ATTACK_REQ -> 5364 eERC_GOLDGOBLIEN_ATTACK_ACK (0x00784A10).
        from darkblood.games.network.messages import GoldGoblinAttackAck, GoldGoblinAttackReq
        req = GoldGoblinAttackReq.decode(body)
        self.transport.record('gold-goblin-attack-req', body, goblin_id=req.goblin_id, damage=req.damage)
        ack = GoldGoblinAttackAck(result=0).encode()
        await self.transport.send_event(event(5364, ack, correlation), note=f'gold goblin attack ack (goblin={req.goblin_id})')

    @packet_handler(5365)
    async def handle_gold_goblin_dead(self, correlation, body):
        # eERC_GOLDGOBLIEN_DEAD_REQ -> 5366 eERC_GOLDGOBLIEN_DEAD_ACK (0x00784CA0).
        from darkblood.games.network.messages import GoldGoblinDeadAck, GoldGoblinDeadReq
        req = GoldGoblinDeadReq.decode(body)
        self.transport.record('gold-goblin-dead-req', body, goblin_id=req.goblin_id)
        ack = GoldGoblinDeadAck(result=0, goblin_id=req.goblin_id, items=[]).encode()
        await self.transport.send_event(event(5366, ack, correlation), note=f'gold goblin dead ack (goblin={req.goblin_id})')

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
        from darkblood.games.network.messages.dungeon import TrainingLeaveRoomAck
        await self.reply(TrainingLeaveRoomAck(result=0), correlation, note='training leave room ack')

    @packet_handler(5240)
    async def handle_monster_regen(self, correlation, body):
        # eERC_MONSTER_REGEN_REQ (0x00799150) -> 5241 eERC_MONSTER_REGEN_ACK (0x0074B830).
        from darkblood.games.network.messages.dungeon import MonsterRegenAck, MonsterRegenReq
        req = MonsterRegenReq.decode(body)
        self.transport.record('monster-regen-req', body, mob_id=req.regen_mob_id, slot_id=req.slot_id)
        await self.reply(MonsterRegenAck(result=0), correlation,
                         note=f'monster regen ack (mob={req.regen_mob_id} slot={req.slot_id})')

    @packet_handler(5342)
    async def handle_treasure_find(self, correlation, body):
        # eERC_TREASURE_FIND_REQ (0x007A4580) -> 5343 eERC_TREASURE_FIND_ACK (0x00782A80).
        from darkblood.games.network.messages.dungeon import TreasureFindAck, TreasureFindReq
        req = TreasureFindReq.decode(body)
        self.transport.record('treasure-find-req', body, treasure_id=req.treasure_id)
        await self.reply(TreasureFindAck(result=0, items=[], success=True), correlation,
                         note=f'treasure find ack (id={req.treasure_id})')

    # =========================================================================
    # Cronos (Attendance), Explore & Clear Rank Handlers
    # =========================================================================

    @packet_handler(2289)
    async def handle_cronos_reward(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosRewardAck, CronosRewardReq
        req = CronosRewardReq.decode(body)
        await self.reply(CronosRewardAck(result=0, items=[], index=req.index, reward_select=req.reward_select),
                         correlation, note=f'cronos reward ack (idx={req.index})')

    @packet_handler(2292)
    async def handle_cronos_info(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosInfoAck
        await self.reply(CronosInfoAck(result=0), correlation, note='cronos info ack')

    @packet_handler(2294)
    async def handle_cronos_date(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosDateAck
        await self.reply(CronosDateAck(result=0), correlation, note='cronos date ack')

    @packet_handler(2296)
    async def handle_cronos_today_time(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosTodayTimeAck
        await self.reply(CronosTodayTimeAck(result=0, today_login_second=60), correlation,
                         note='cronos today time ack')

    @packet_handler(2299)
    async def handle_cronos_stamp(self, correlation, body):
        from darkblood.games.network.messages.dungeon import CronosStampAck
        await self.reply(CronosStampAck(result=0, items=[], item_id=0), correlation, note='cronos stamp ack')

    @packet_handler(2651)
    async def handle_explore_start(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreStartAck, ExploreStartReq
        req = ExploreStartReq.decode(body)
        await self.reply(
            ExploreStartAck(result=0, explore_char_uid=req.char_uid, explore_time=req.explore_time, items=[], stress=0),
            correlation, note=f'explore start ack (char={req.char_uid})',
        )

    @packet_handler(2653)
    async def handle_explore_cancel(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreCancelAck, ExploreCancelReq
        req = ExploreCancelReq.decode(body)
        await self.reply(ExploreCancelAck(result=0, explore_char_uid=req.explore_char_uid), correlation,
                         note=f'explore cancel ack (char={req.explore_char_uid})')

    @packet_handler(2656)
    async def handle_explore_get_reward(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreGetRewardAck, ExploreGetRewardReq
        req = ExploreGetRewardReq.decode(body)
        await self.reply(ExploreGetRewardAck(result=0, reward_uid=req.reward_uid, items=[]), correlation,
                         note=f'explore get reward ack (uid={req.reward_uid})')

    @packet_handler(2662)
    async def handle_explore_cancel_by_user_uid(self, correlation, body):
        from darkblood.games.network.messages.dungeon import ExploreCancelByUserUidAck, ExploreCancelByUserUidReq
        req = ExploreCancelByUserUidReq.decode(body)
        await self.reply(ExploreCancelByUserUidAck(result=0, explore_char_uid=req.explore_char_uid), correlation,
                         note=f'explore cancel by uid ack (char={req.explore_char_uid})')

    @packet_handler(2539)
    async def handle_clear_rank_history_info(self, correlation, body):
        import time
        from darkblood.games.network.messages.dungeon import (
            ClearRankHistoryInfoAck, ClearRankHistoryInfoReq, DungeonClearRankInfo,
        )
        req = ClearRankHistoryInfoReq.decode(body)
        await self.reply(
            ClearRankHistoryInfoAck(result=0, start_time=int(time.time()), cur_page=req.page,
                                    map_id=req.map_id, rank_infos=[], my_rank_info=DungeonClearRankInfo()),
            correlation, note=f'clear rank history ack (map={req.map_id} page={req.page})',
        )

    @packet_handler(5228)
    async def handle_clear_rank_info(self, correlation, body):
        from darkblood.games.network.messages.dungeon import (
            ClearRankInfoAck, ClearRankInfoReq, DungeonClearRankInfo,
        )
        req = ClearRankInfoReq.decode(body)
        await self.reply(
            ClearRankInfoAck(result=0, cur_page=req.page, map_id=req.map_id,
                             rank_infos=[], my_rank_info=DungeonClearRankInfo()),
            correlation, note=f'clear rank info ack (map={req.map_id} page={req.page})',
        )


