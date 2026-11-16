import struct

from darkblood.core.serialization.jser import WireError, event, read_varuint, varuint, wide_string
from darkblood.frontend.relay import RELAY_PORT
from darkblood.games.network.messages import (
    ActiveWarFlagReq,
    ChangeDungeonLayerNot,
    ChangeMapCodeAck,
    CreateRoomAck,
    DropItemNot,
    GuideBeginnerUpdateReq,
    MonsterDeadReq,
    RoomInfoListAck,
    SelectDungeonAck,
)
from darkblood.games.state import selected_character


class DungeonHandlers:
    """Rooms, dungeon gate, map code and game start."""

    async def on_2010(self, correlation, body):
        # eEGS_GET_ROOMINFOLIST_REQ (sender 0x7AB140) -> 2011: no open rooms.
        await self.transport.send_event(event(2011, RoomInfoListAck().encode(), correlation),
                                        note='room info list ack')

    async def on_5001(self, correlation, body):
        # eERC_CREATE_ROOM_REQ (writer 0x58B060): wstring name, i32, i32, i16,
        # i16 (observed: "_singleplay", -1, -1, -1, 1) -> 5002 CREATE_ROOM_ACK.
        name, a, b, c, d = '', -1, -1, -1, 1
        try:
            length, offset = read_varuint(body, 0)
            name = body[offset:offset + length].decode('utf-16le')
            a, b, c, d = struct.unpack_from('<iihh', body, offset + length)
        except (WireError, struct.error, UnicodeDecodeError):
            pass
        self.room_id = getattr(self, 'room_id', 0) + 1
        ack = CreateRoomAck(room_id=self.room_id, name=name, req_a=a, req_b=b, req_c=c, req_d=d,
                            host_uid=selected_character.get('id', 0),
                            relay_port=RELAY_PORT).encode()
        await self.transport.send_event(event(5002, ack, correlation),
                                        note='create room ack (%s)' % name)

    async def on_5043(self, correlation, body):
        # eERC_SELECT_DUNGEON_REQ (sender 0x7AC1C0), observed body:
        # ffffff7f + J-wstring gate id ("Act1_G1") -> 5044.
        gate = ''
        try:
            length, offset = read_varuint(body, 4)
            gate = body[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        ack = SelectDungeonAck(gate_id=gate).encode()
        await self.transport.send_event(event(5044, ack, correlation),
                                        note='select dungeon ack (%s)' % gate)

    async def on_5009(self, correlation, body):
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
        ack = ChangeMapCodeAck(map_code=code, flag=flag).encode()
        await self.transport.send_event(event(5010, ack, correlation),
                                        note='change mapcode ack (%s)' % code)

    async def on_5013(self, correlation, body):
        # eERC_START_GAME_REQ -> eERC_START_GAME_ACK (5014), handler 0x7880A0.
        # Success reader: u16, u32, J-wstring (0xB35AB0), three 0x17 maps,
        # then a 0x10 vector (0x78836B -> 0x4B94C0). Scalar/string type
        # codes are not wire tags; empty lengths use the terminal byte 0x80.
        # The J-wstring is the map code: 0x788539 resolves it with 0x98E630
        # and dereferences the result (+0x28), so an empty/unknown code
        # crashes. The request (sender observed live) is ffffff7f + J-wstring
        # map code ("Act1_G1_A10"); echo it. Other field meanings and nonempty
        # entries still need recovery.
        code = ''
        try:
            length, offset = read_varuint(body, 4)
            code = body[offset:offset + length].decode('utf-16le')
        except (WireError, UnicodeDecodeError):
            pass
        ack = (struct.pack('<IHI', 0, 0, 0) + wide_string(code)
               + (b'\x17' + varuint(0)) * 3 + b'\x10' + varuint(0))
        await self.transport.send_event(event(5014, ack, correlation),
                                        note='start game ack')

    async def on_5095(self, correlation, body):
        # eERC_CHANGE_DUNGEON_LAYER_NOT (sender 0x7900B0): ffffff7f + i64 layer_net_id.
        try:
            msg = ChangeDungeonLayerNot.decode(body)
            self.current_dungeon_layer = msg.layer_id
            self.current_dungeon_map_hash = msg.map_hash
            self.transport.record('dungeon-layer', body, layer_id=msg.layer_id, map_hash='0x%08x' % msg.map_hash)
        except (struct.error, ValueError):
            pass

    async def on_2422(self, correlation, body):
        # eEGS_ACTIVE_WARFLAG_REQ (sender 0x79C300): ffffff7f + u32 war_flag_id.
        try:
            msg = ActiveWarFlagReq.decode(body)
            self.active_war_flag = msg.war_flag_id
            self.transport.record('active-warflag', body, war_flag_id=msg.war_flag_id)
        except (struct.error, ValueError):
            pass

    async def on_2358(self, correlation, body):
        # eEGS_GUIDE_BEGINNER_UPDATE_REQ (sender 0x79A3B0): ffffff7f + vector<u32> guide_ids.
        try:
            msg = GuideBeginnerUpdateReq.decode(body)
            self.transport.record('guide-beginner-update', body, guide_ids=msg.guide_ids)
        except (struct.error, ValueError):
            pass

    async def on_5063(self, correlation, body):
        # eERC_MONSTER_DEAD_REQ (sender 0x78A690): ffffff7f + u32 monster_id + u32 param.
        try:
            msg = MonsterDeadReq.decode(body)
            self.transport.record('monster-dead', body, monster_id=msg.monster_id, param=msg.param)
        except (struct.error, ValueError):
            pass
