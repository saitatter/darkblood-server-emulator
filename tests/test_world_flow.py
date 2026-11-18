"""Tests for multi-client GameWorldManager presence and Opcode 5096 spawning."""
import asyncio
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games.entities.character import layer_net_id
from darkblood.games.world import GameWorldManager
from headless_client import HeadlessClient


class WorldFlowTest(ServerTestCase):
    def test_layer_change_updates_peer_visibility_on_selected_channel(self):
        async def enter(client, name):
            await lobby_flow(client)
            client.send_event(5028, struct.pack('<iQ', 0x7fffffff, 2))
            await client.expect_event(5029)
            client.send_event(2012, create_request(name))
            _, created = await client.expect_event(2013)
            uid = struct.unpack_from('<q', created, 10)[0]
            client.send_event(2006, struct.pack('<iq', 0x7fffffff, uid))
            await client.expect_event(2007)
            await client.expect_event(2410)
            return uid

        async def scenario(first):
            second = HeadlessClient(port=first.port)
            try:
                a = await enter(first, 'LayerWalkerA')
                b = await enter(second, 'LayerWalkerB')
                for client, uid in ((first, b), (second, a)):
                    _, joined = await client.expect_event(5027)
                    self.assertEqual(struct.unpack_from('<q', joined, 2)[0], uid)
                    await client.expect_event(5096)

                new_layer = layer_net_id(layer=5)
                req = struct.pack('<iQ?', 0x7fffffff, new_layer, False)
                second.send_event(5030, req)
                _, ack = await second.expect_event(5031)
                self.assertEqual(struct.unpack_from('<IQQ', ack), (0, 2, new_layer))
                _, leave = await first.expect_event(5039)
                self.assertEqual(leave, struct.pack('<Iq', 0, b))

                # Rejoin from the old layer. Nothing in the new layer should see it.
                first.send_event(5030, struct.pack('<iQ?', 0x7fffffff, layer_net_id(), False))
                await first.expect_event(5031)
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(second.expect_event(5027), timeout=0.1)

                first.send_event(5030, req)
                await first.expect_event(5031)
                for client, uid in ((first, b), (second, a)):
                    _, joined = await client.expect_event(5027)
                    self.assertEqual(struct.unpack_from('<q', joined, 2)[0], uid)
                    await client.expect_event(5096)
            finally:
                await second.close()

        self.run_async(self.with_server(scenario))

    def test_multi_client_town_presence_and_mutual_spawns(self):
        async def scenario(client1):
            world = GameWorldManager.get()
            world.players.clear()
            world.squares.clear()

            # 1. Client 1 logs in, creates character "Warrior1", and selects it
            await lobby_flow(client1)
            client1.send_event(2012, create_request('Warrior1', char_class=1))
            _, created1 = await client1.expect_event(2013)
            char_id1 = struct.unpack_from('<Q', created1, 10)[0]
            client1.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id1))
            await client1.expect_event(2007)
            await client1.expect_event(2410)

            # Verify Client 1 is registered in GameWorldManager
            p1 = world.get_player(char_id1)
            self.assertIsNotNone(p1)
            self.assertEqual(p1.char_id, char_id1)

            # 2. Spawn a second client on the same server instance
            port = client1.port
            client2 = HeadlessClient(port=port)
            try:
                await lobby_flow(client2)
                client2.send_event(2012, create_request('Mage2', char_class=6))
                _, created2 = await client2.expect_event(2013)
                char_id2 = struct.unpack_from('<Q', created2, 10)[0]
                client2.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id2))
                await client2.expect_event(2007)
                await client2.expect_event(2410)

                # Client 2 should receive Opcode 5027 (JOIN_LAYER_NOT) and 5096 (UPDATE_CHAR_INFO_NOT) for existing Client 1
                _, layer_not_c2 = await client2.expect_event(5027)
                self.assertIn('Warrior1'.encode('utf-16le'), layer_not_c2)
                _, spawn_for_c2 = await client2.expect_event(5096)
                self.assertIn('Warrior1'.encode('utf-16le'), spawn_for_c2)

                # Client 1 should receive Opcode 5027 (JOIN_LAYER_NOT) and 5096 (UPDATE_CHAR_INFO_NOT) for newcomer Client 2
                _, layer_not_c1 = await client1.expect_event(5027)
                self.assertIn('Mage2'.encode('utf-16le'), layer_not_c1)
                _, spawn_for_c1 = await client1.expect_event(5096)
                self.assertIn('Mage2'.encode('utf-16le'), spawn_for_c1)

                # Verify both are registered in the square
                players = world.get_players_in_square(1)
                self.assertEqual(len(players), 2)
            finally:
                await client2.close()

            # Clean up
            world.unregister_player(char_id1)
            world.unregister_player(char_id2)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
