"""Arena: Arena channels (2304/2305) and room management (2306/2307, 5145-5154)."""
from __future__ import annotations


from darkblood.games.network import results
from darkblood.games.network.messages import (
    ArenaCreateRoomAck,
    ArenaCreateRoomReq,
    ArenaGetInviteListAck,
    ArenaGetInviteListReq,
    ArenaGetRoomListAck,
    ArenaGetRoomListReq,
    ArenaJoinRoomAck,
    ArenaJoinRoomReq,
    ArenaLeaveRoomAck,
    ArenaLeaveRoomReq,
    ArenaSquare,
    ArenaSquareListAck,
    ArenaSquareListReq,
)
from darkblood.games.dispatcher import packet_handler
from darkblood.core.network.proudnet import relay_address


class ArenaRoomHandlers:
    # Arena Channels / Square (Opcodes 2304 / 2305)

    @packet_handler(ArenaSquareListReq)
    async def handle_arena_square_list(self, correlation: int, body: bytes):
        """Opcode 2304 -> 2305 / 2447.

        Client handler: 0x004B7E80 -> 0x004B67F0.
        Returns the list of arena channels / square lobbies.
        """
        req = ArenaSquareListReq.decode(body)
        self.transport.record('arena-squarelist-req', body, server_key=req.server_key)
        squares = [
            ArenaSquare(square_id=101, name='Colosseum Channel 1', load=45),
            ArenaSquare(square_id=102, name='Gladiator Channel 2', load=20),
        ]
        ack = ArenaSquareListAck(result=0, squares=squares)
        await self.reply(ack, correlation, note='arena square list ack')

    # Arena Room Management (Opcodes 2306 / 2307, 5145-5154)

    @packet_handler(ArenaGetRoomListReq)
    async def handle_arena_get_room_list(self, correlation: int, body: bytes):
        """Opcode 2306 -> 2307 / 2449.

        Client handler: 0x004C6080 -> 0x004B96D0.
        Returns list of open arena match rooms.
        """
        req = ArenaGetRoomListReq.decode(body)
        self.transport.record('arena-get-roomlist-req', body, page=req.page)
        rooms = list(self.arena.rooms.values())
        ack = ArenaGetRoomListAck(result=0, flag=True, room_count=len(rooms), rooms=rooms)
        await self.reply(ack, correlation, note='arena get room list ack')

    @packet_handler(ArenaCreateRoomReq)
    async def handle_arena_create_room(self, correlation: int, body: bytes):
        """Opcode 5153 (eERC_ARENA_CREATE_ROOM_REQ) -> 5154 (eERC_ARENA_CREATE_ROOM_ACK).

        Client handler: 0x004C6080 -> 0x004BCCE0.
        Creates an arena PvP match room.
        """
        req = ArenaCreateRoomReq.decode(body)
        char_uid, char_name, char_class, char_level = self._get_active_char_info()
        room = req.room
        while room.room_id <= 0 or room.room_id in self.arena.rooms:
            room.room_id = next(self.arena.room_ids)
        if not room.room_name:
            room.room_name = f"{char_name}'s Colosseum"
        room.host_uid = char_uid
        room.team_id = self._current_arena_team_id or 1
        self.arena.room_members[room.room_id] = [{
            'uid': char_uid,
            'name': char_name,
            'class': char_class,
            'level': char_level,
        }]
        self.arena.rooms[room.room_id] = room
        self._current_arena_room_id = room.room_id

        self.transport.record('arena-create-room-req', body, room_id=room.room_id, name=room.room_name)
        ack = ArenaCreateRoomAck(result=0, room=room)
        await self.reply(ack, correlation, note=f'arena create room ack (id={room.room_id}, name={room.room_name})')

    @packet_handler(ArenaJoinRoomReq)
    async def handle_arena_join_room(self, correlation: int, body: bytes):
        """Opcode 5145 (eERC_ARENA_JOIN_ROOM_REQ) -> 5146 (eERC_ARENA_JOIN_ROOM_ACK).

        Client handler: 0x004C6080 -> 0x004C5380.
        Joins an existing arena PvP match room.
        """
        req = ArenaJoinRoomReq.decode(body)
        char_uid, char_name, char_class, char_level = self._get_active_char_info()
        room = self.arena.rooms.get(req.room_id)
        if not room:
            await self.reply(ArenaJoinRoomAck(result=results.ROOM_NOT_EXISTS), correlation,
                             note=f'arena join room refused (room={req.room_id} no longer exists)')
            return

        member_entry = {'uid': char_uid, 'name': char_name, 'class': char_class, 'level': char_level}
        members = self.arena.room_members.setdefault(room.room_id, [])
        if not any(m.get('uid') == char_uid for m in members):
            members.append(member_entry)
        self._current_arena_room_id = room.room_id

        self.transport.record('arena-join-room-req', body, room_id=req.room_id)
        ack = ArenaJoinRoomAck(result=0, room=room, host_uid=room.host_uid, relay=relay_address())
        await self.reply(ack, correlation, note=f'arena join room ack (room={room.room_id})')

    @packet_handler(ArenaLeaveRoomReq)
    async def handle_arena_leave_room(self, correlation: int, body: bytes):
        """Opcode 5148 (eERC_ARENA_LEAVE_ROOM_REQ) -> 5149 (eERC_ARENA_LEAVE_ROOM_ACK).

        Client handler: 0x004BB5B0.
        Leaves current match room and updates player count.
        """
        char_uid, _, _, _ = self._get_active_char_info()
        curr_room_id = self._current_arena_room_id
        if curr_room_id and curr_room_id in self.arena.rooms:
            room = self.arena.rooms[curr_room_id]
            members = [m for m in self.arena.room_members.get(curr_room_id, [])
                       if m.get('uid') != char_uid]
            self.arena.room_members[curr_room_id] = members
            if not members:
                self.arena.rooms.pop(curr_room_id, None)
                self.arena.room_members.pop(curr_room_id, None)
            elif room.host_uid == char_uid:
                room.host_uid = members[0]['uid']
            self._current_arena_room_id = None

        self.transport.record('arena-leave-room-req', body)
        ack = ArenaLeaveRoomAck(result=0)
        await self.reply(ack, correlation, note='arena leave room ack')

    @packet_handler(ArenaGetInviteListReq)
    async def handle_arena_get_invite_list(self, correlation: int, body: bytes):
        """Opcode 2308 (eEGS_ARENA_GET_INVITELIST_REQ) -> 2309 (eEGS_ARENA_GET_INVITELIST_ACK).

        Client handler: 0x004C5200 -> 0x004B4680.
        Returns pending arena match invitations.
        """
        ack = ArenaGetInviteListAck(result=0)
        await self.reply(ack, correlation, note='arena get invite list ack')
