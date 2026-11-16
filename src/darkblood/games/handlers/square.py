import struct

from darkblood.core.serialization.jser import event
from darkblood.games.config import SQUARES, square_entry
from darkblood.games.entities.character import layer_net_id
from darkblood.games.network.messages import BackToSquareAck, ClearTutorialAck, GTargetListAck, NpcFirstMeetAck
from darkblood.games.state import selected_character


class SquareHandlers:
    """Town (square) play: tutorial, layers, NPCs, waypoints."""

    async def on_2082(self, correlation, body):
        # eEGS_CLEAR_TUTORIAL_REQ -> eEGS_CLEAR_TUTORIAL_ACK (2083), handler 0x77EEB0:
        # u32 result (0), tag 0x10 vector (0x4B9210). Empty vector is b'\x10\x00'.
        # Persist tutorial completion in character storage so tutorial is skipped.
        char_id = selected_character.get('id', 1)
        char = self.store().get(self.account, char_id)
        if char:
            char['tutorial_cleared'] = True
            self.store().save()
        ack = ClearTutorialAck().encode()
        await self.transport.send_event(event(2083, ack, correlation), note='clear tutorial ack')

    async def on_2084(self, correlation, body):
        # eEGS_CLEAR_OPENING_NOT: client notification that opening cinematic/sequence has ended.
        pass

    async def on_2353(self, correlation, body):
        # eEGS_TUTORIAL_MONSTER_DEAD_NOT, sender 0x799E60: notification only.
        pass

    async def on_2094(self, correlation, body):
        # eEGS_NPC_FIRST_MEET_REQ -> eEGS_NPC_FIRST_MEET_ACK (2095), handler 0x752B60:
        # body: i32 dummy (0x7FFFFFFF), u32 npc_id.
        # ack: u32 result (0), u32 npc_id.
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        ack = NpcFirstMeetAck(result=0, npc_id=npc_id).encode()
        await self.transport.send_event(event(2095, ack, correlation),
                                        note='npc first meet ack (npc %d)' % npc_id)

    async def on_5045(self, correlation, body):
        # eERC_BACK_TO_SQUARE_REQ -> eERC_BACK_TO_SQUARE_ACK (5046), handler 0x7897F0.
        # Request body layout not recovered; the reply schema is in BackToSquareAck.
        ack = BackToSquareAck(square_uid=SQUARES[0]['square_id']).encode()
        await self.transport.send_event(event(5046, ack, correlation),
                                        note='back to square ack')

    async def on_5124(self, correlation, body):
        # eERC_GTARGET_LIST_REQ (empty, fire-and-forget from SquarePlay 0x6F9AB9)
        # -> eERC_GTARGET_LIST_ACK 5125: u32 result + empty 0x10 vector.
        await self.transport.send_event(event(5125, GTargetListAck().encode(), correlation),
                                        note='gtarget list ack')

    async def on_5030(self, correlation, body):
        # eERC_JOIN_LAYER_REQ (i32, u64 nJoinLayerNetID, u8) -> eERC_JOIN_LAYER_ACK
        # (5031), handler 0x787A70. Read order (tools/extract_schemas.py) matches
        # 5046: u32 result, u64, u64, tag 0x10 vector {i32,bool,bool}, bool, u64.
        # The former `u8 0` after the two u64 failed the 0x10 tag check, so the
        # client kept resending 5030 (observed live: layer jhash('Act1') << 32).
        layer_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else layer_net_id()
        ack = BackToSquareAck(square_uid=SQUARES[0]['square_id'], layer_net_id=layer_id).encode()
        await self.transport.send_event(event(5031, ack, correlation),
                                        note='join layer ack (%d)' % layer_id)

    async def on_2016(self, correlation, body):
        # eEGS_ENTER_MAPTOOL_REQ -> eEGS_ENTER_MAPTOOL_ACK (2017), handler 0x757D20:
        # u32 result (0 -> triggers scene transition 5 via 0x6DBFD0)
        await self.transport.send_event(event(2017, struct.pack('<I', 0), correlation),
                                        note='enter maptool ack')

    async def on_2344(self, correlation, body):
        # eEGS_WAYPOINT_INSERT_REQ (observed: i32, u64 nLayerNetID) ->
        # eEGS_WAYPOINT_INSERT_ACK 2345 (JAppPageSquarePortal 0x64B9D0 -> 0x64AE00):
        # u32 result, u64 nLayerNetID, implicit jData = square entry 0xA49700
        # (same reader as the 2022 channel list).
        layer = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else layer_net_id()
        ack = struct.pack('<IQ', 0, layer) + square_entry(**SQUARES[0])
        await self.transport.send_event(event(2345, ack, correlation),
                                        note='waypoint insert ack (%016x)' % layer)
