"""Town (square) play: tutorial, layers, NPCs, waypoints."""
import struct

from darkblood.core.serialization.jser import event
from darkblood.games.config import SQUARES, square_entry
from darkblood.games.entities.character import layer_net_id
from darkblood.games.entities.items import Item
from darkblood.games.network.messages import (
    BackToSquareAck,
    ClearTutorialAck,
    GTargetListAck,
    NpcFirstMeetAck,
)
from darkblood.games.state import selected_character


class SquareHandlers:
    """Town (square) play: tutorial, layers, NPCs, waypoints."""

    async def handle_clear_tutorial(self, correlation: int, body: bytes):
        """Opcode 2082 (eEGS_CLEAR_TUTORIAL_REQ) -> 2083 (eEGS_CLEAR_TUTORIAL_ACK).

        Client handler: 0x0077EEB0.
        Marks tutorial quest sequence as finished on character record, unlocking full
        town access, NPC interactions, and dungeon gates.

        Body: i32 prefix + bool. The quest talk SQ0882S01c1 calls
        On_Tutorial_Exit(true) and the skip button sends 0 (live: ffffff7f 00),
        so the bool is read as "completed". The rewards come from
        tutorialreward.lua (CompleteLoad / SkipLoad) and are granted once.
        """
        completed = len(body) > 4 and body[4] != 0
        char_id = selected_character.get('id', 1)
        char = self.store().get(self.account, char_id)
        items = []
        if char:
            if not char.get('tutorial_cleared'):
                from darkblood.games.game_data.client_dict import tutorial_rewards
                from darkblood.player_management.characters import add_reward_items
                rewards = tutorial_rewards()['complete' if completed else 'skip']
                items = [Item(owner=char.get('id', -1), **i) for i in add_reward_items(char, rewards)]
            char['tutorial_cleared'] = True
            self.store().save()
        ack = ClearTutorialAck(elements=items).encode()
        await self.transport.send_event(event(2083, ack, correlation),
                                        note='clear tutorial ack (completed=%d, %d items)' % (completed, len(items)))

    async def handle_clear_opening(self, correlation: int, body: bytes):
        """Opcode 2084 (eEGS_CLEAR_OPENING_NOT): Cinematic intro complete."""
        pass

    async def handle_tutorial_monster_dead(self, correlation: int, body: bytes):
        """Opcode 2353 (eEGS_TUTORIAL_MONSTER_DEAD_NOT): Notification only."""
        pass

    async def handle_npc_first_meet(self, correlation: int, body: bytes):
        """Opcode 2094 (eEGS_NPC_FIRST_MEET_REQ) -> 2095 (eEGS_NPC_FIRST_MEET_ACK).

        Client handler: 0x00752B60.
        Acknowledges dialogue greeting when a player interacts with an NPC for the first time.
        """
        npc_id = struct.unpack_from('<I', body, 4)[0] if len(body) >= 8 else 0
        ack = NpcFirstMeetAck(result=0, npc_id=npc_id).encode()
        await self.transport.send_event(event(2095, ack, correlation),
                                        note='npc first meet ack (npc %d)' % npc_id)

    async def handle_back_to_square(self, correlation: int, body: bytes):
        """Opcode 5045 (eERC_BACK_TO_SQUARE_REQ) -> 5046 (eERC_BACK_TO_SQUARE_ACK).

        Client handler: 0x007897F0.
        Transitions the player entity from a dungeon session back to the default town square.
        """
        ack = BackToSquareAck(square_uid=SQUARES[0]['square_id']).encode()
        await self.transport.send_event(event(5046, ack, correlation),
                                        note='back to square ack')

    async def handle_get_gtarget_list(self, correlation: int, body: bytes):
        """Opcode 5124 (eERC_GTARGET_LIST_REQ) -> 5125 (eERC_GTARGET_LIST_ACK).

        Client handler: 0x006F9AB9.
        Returns target tracking entities for current town layer.
        """
        await self.transport.send_event(event(5125, GTargetListAck().encode(), correlation),
                                        note='gtarget list ack')

    async def handle_join_layer(self, correlation: int, body: bytes):
        """Opcode 5030 (eERC_JOIN_LAYER_REQ) -> 5031 (eERC_JOIN_LAYER_ACK).

        Client handler: 0x00787A70.
        Moves client into an instanced town layer / sub-district.
        """
        layer_id = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else layer_net_id()
        ack = BackToSquareAck(square_uid=SQUARES[0]['square_id'], layer_net_id=layer_id).encode()
        await self.transport.send_event(event(5031, ack, correlation),
                                        note='join layer ack (%d)' % layer_id)

    async def handle_enter_maptool(self, correlation: int, body: bytes):
        """Opcode 2016 (eEGS_ENTER_MAPTOOL_REQ) -> 2017 (eEGS_ENTER_MAPTOOL_ACK).

        Client handler: 0x00757D20.
        Triggers scene transition.
        """
        await self.transport.send_event(event(2017, struct.pack('<I', 0), correlation),
                                        note='enter maptool ack')

    async def handle_waypoint_insert(self, correlation: int, body: bytes):
        """Opcode 2344 (eEGS_WAYPOINT_INSERT_REQ) -> 2345 (eEGS_WAYPOINT_INSERT_ACK).

        Client handler: 0x0064AE00.
        Registers visited portal waypoint in the world map.
        """
        layer = struct.unpack_from('<Q', body, 4)[0] if len(body) >= 12 else layer_net_id()
        ack = struct.pack('<IQ', 0, layer) + square_entry(**SQUARES[0])
        await self.transport.send_event(event(2345, ack, correlation),
                                        note='waypoint insert ack (%016x)' % layer)

    async def handle_leave_layer(self, correlation: int, body: bytes):
        """Opcode 5037 (eERC_LEAVE_LAYER_REQ) -> 5038 (eERC_LEAVE_LAYER_ACK).

        Sent by the in-game menu's "Select Character": OnBtn_SelectChar
        (0x00564490) opens MB_Square_To_SelChar, whose OnOK runs
        SquareToSelChar (0x006FB360). That sends 5037 (0x007ADA30), waits
        for 5038, then sends 2008 (0x00788DA0) and waits for 2009 before it
        switches to character select. Without 5038 the client timed out and
        dropped the connection (live, 2026-11-16 22:43).

        Client handler 0x007895C0 reads only the u32 result (0x00A1EA20(0));
        0 continues, any other value opens an error box. The player leaves
        the town, so it is removed from the world presence list.
        """
        if self.active_char_id:
            from darkblood.games.world import GameWorldManager
            GameWorldManager.get().unregister_player(self.active_char_id)
        await self.transport.send_event(event(5038, struct.pack('<I', 0), correlation),
                                        note='leave layer ack')

    # Opcode backward-compatibility aliases
    on_2082 = handle_clear_tutorial
    on_2084 = handle_clear_opening
    on_2353 = handle_tutorial_monster_dead
    on_2094 = handle_npc_first_meet
    on_5045 = handle_back_to_square
    on_5124 = handle_get_gtarget_list
    on_5030 = handle_join_layer
    on_5037 = handle_leave_layer
    on_2016 = handle_enter_maptool
    on_2344 = handle_waypoint_insert
