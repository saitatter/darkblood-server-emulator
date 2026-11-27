"""Tests for multi-client GameWorldManager presence and Opcode 5096 spawning."""
import asyncio
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games.entities.character import layer_net_id
from darkblood.games.world import GameWorldManager
from headless_client import HeadlessClient


class WorldFlowTest(ServerTestCase):
    def test_town_peers_wait_until_the_client_is_ready(self):
        async def select(client, name):
            await lobby_flow(client)
            client.send_event(2012, create_request(name))
            _, created = await client.expect_event(2013)
            uid = struct.unpack_from('<q', created, 10)[0]
            client.send_event(2006, struct.pack('<iq', 0x7fffffff, uid))
            await client.expect_event(2007)
            return uid

        async def scenario(first):
            second = HeadlessClient(port=first.port)
            try:
                a = await select(first, 'ReadyFirst')
                first.send_event(2131, struct.pack('<i', 0x7fffffff))
                await first.expect_event(2132)
                b = await select(second, 'ReadySecond')
                # Live: a 5027 sent while the client is still entering town is never shown.
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(first.expect_event(5027), timeout=0.2)
                second.send_event(2131, struct.pack('<i', 0x7fffffff))
                await second.expect_event(2132)
                for client, uid in ((first, b), (second, a)):
                    _, joined = await client.expect_event(5027)
                    self.assertEqual(struct.unpack_from('<q', joined, 2)[0], uid)
                    await client.expect_event(5096)
            finally:
                await second.close()

        self.run_async(self.with_server(scenario))

    def test_town_layer_is_remembered_for_back_to_square_and_select(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('LayerKeeper'))
            _, created = await client.expect_event(2013)
            uid = struct.unpack_from('<q', created, 10)[0]
            client.send_event(2006, struct.pack('<iq', 0x7fffffff, uid))
            _, details = await client.expect_event(2007)
            # New characters start on layer 0 (the old local default 1 always
            # spawned players on the same start point).
            self.assertIn(struct.pack('<Q', layer_net_id(layer=0)), details)

            layer = layer_net_id(layer=5)
            client.send_event(5030, struct.pack('<iQ?', 0x7fffffff, layer, False))
            await client.expect_event(5031)
            client.send_event(5045, struct.pack('<i', 0x7fffffff))
            _, back = await client.expect_event(5046)
            self.assertEqual(struct.unpack_from('<IQQ', back)[2], layer)

            client.send_event(2006, struct.pack('<iq', 0x7fffffff, uid))
            _, details = await client.expect_event(2007)
            self.assertIn(struct.pack('<Q', layer), details)

        self.run_async(self.with_server(scenario))

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
            # The town has loaded (5124): peers already there are sent now.
            client.send_event(5124, struct.pack('<i', 0x7fffffff))
            await client.expect_event(5125)
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
                self.assertEqual(struct.unpack_from('<IQQ', ack), (0, (0x1F << 54) | 2, new_layer))  # keyed square UID
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
                    _, details = await client.expect_event(5096)
                    # The peer's details carry the layer both are now on.
                    self.assertIn(struct.pack('<Q', new_layer), details)

                second.send_event(5028, struct.pack('<iQ', 0x7fffffff, 1))
                await second.expect_event(5029)
                _, departure = await first.expect_event(5039)
                self.assertEqual(departure, struct.pack('<Iq', 0, b))

                first.send_event(5037)
                await first.expect_event(5038)
                first.send_event(5028, struct.pack('<iQ', 0x7fffffff, 1))
                await first.expect_event(5029)
                first.send_event(2008)
                await first.expect_event(2009)
                self.assertIsNone(GameWorldManager.get().get_player(a))
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(second.expect_event(5027), timeout=0.1)
            finally:
                await second.close()

        self.run_async(self.with_server(scenario))

    def test_multi_client_town_presence_and_mutual_spawns(self):
        async def scenario(client1):
            world = GameWorldManager._instance = GameWorldManager()

            # 1. Client 1 logs in, creates character "Warrior1", and selects it
            await lobby_flow(client1)
            client1.send_event(2012, create_request('Warrior1', char_class=1))
            _, created1 = await client1.expect_event(2013)
            char_id1 = struct.unpack_from('<Q', created1, 10)[0]
            client1.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id1))
            await client1.expect_event(2007)
            await client1.expect_event(2410)
            # The town has loaded (5124): peers already there are sent now.
            client1.send_event(5124, struct.pack('<i', 0x7fffffff))
            await client1.expect_event(5125)

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
                # The town has loaded (5124): peers already there are sent now.
                client2.send_event(5124, struct.pack('<i', 0x7fffffff))
                await client2.expect_event(5125)

                # Client 2 should receive Opcode 5027 (JOIN_LAYER_NOT) and 5096 (UPDATE_CHAR_INFO_NOT) for existing Client 1
                _, layer_not_c2 = await client2.expect_event(5027)
                self.assertIn('Warrior1'.encode('utf-16le'), layer_not_c2)
                self.assertEqual(struct.unpack_from('<Q', layer_not_c2, len(layer_not_c2) - 10)[0] >> 54, 0x1F)  # own JUser key is 31 (live)
                _, spawn_for_c2 = await client2.expect_event(5096)
                self.assertIn('Warrior1'.encode('utf-16le'), spawn_for_c2)

                # Client 1 should receive Opcode 5027 (JOIN_LAYER_NOT) and 5096 (UPDATE_CHAR_INFO_NOT) for newcomer Client 2
                _, layer_not_c1 = await client1.expect_event(5027)
                self.assertIn('Mage2'.encode('utf-16le'), layer_not_c1)
                self.assertEqual(struct.unpack_from('<Q', layer_not_c1, len(layer_not_c1) - 10)[0] >> 54, 0x1F)
                _, spawn_for_c1 = await client1.expect_event(5096)
                self.assertIn('Mage2'.encode('utf-16le'), spawn_for_c1)

                # Verify both are registered in the square
                players = world.get_players_in_square(1)
                self.assertEqual(len(players), 2)
                await client2.close()
                _, departure = await client1.expect_event(5039)
                self.assertEqual(departure, struct.pack('<Iq', 0, char_id2))
            finally:
                await client2.close()

            # Clean up
            world.unregister_player(char_id1)
            world.unregister_player(char_id2)

        self.run_async(self.with_server(scenario))

    def test_waypoint_insert_cost_deduction_and_relog_persistence(self):
        async def scenario(client):
            from darkblood.core.hashing import jhash
            from darkblood.games.game_data.world import portal_cost
            from darkblood.games.network.messages.lobby import BackToSquareAck
            from darkblood.games.network.messages.quests import WaypointInsertAck

            await lobby_flow(client)
            client.send_event(2012, create_request('WpTester'))
            _, created = await client.expect_event(2013)
            uid = struct.unpack_from('<q', created, 10)[0]
            client.send_event(2006, struct.pack('<iq', 0x7fffffff, uid))
            await client.expect_event(2007)
            await client.expect_event(2410)
            client.send_event(5124)
            await client.expect_event(5125)

            # Give the character enough AR to cover waypoint teleport cost.
            from darkblood.games.world import GameWorldManager
            char = GameWorldManager.get().get_player(uid).char_data
            char['gold'] = 5000

            wp0 = layer_net_id('Act1', 0)  # act1_01: @LayerName_2, (1536, -1792)
            wp4 = layer_net_id('Act1', 4)  # act1_02: @LayerName_10, (2688, -1408)

            client.send_event(2344, struct.pack('<iQ', 0x7fffffff, wp0))
            _, ack0_raw = await client.expect_event(2345)
            ack0 = WaypointInsertAck.decode(ack0_raw)
            self.assertEqual(ack0.result, 0)
            self.assertEqual(ack0.waypoint.layer_net_id, wp0)
            self.assertEqual(ack0.waypoint.name, '@LayerName_2')
            self.assertEqual(ack0.waypoint.waypoint_id, jhash('act1_01') & 0xFFFFFFFF)
            self.assertEqual((ack0.waypoint.x, ack0.waypoint.y), (1536, -1792))

            client.send_event(2344, struct.pack('<iQ', 0x7fffffff, wp4))
            _, ack4_raw = await client.expect_event(2345)
            ack4 = WaypointInsertAck.decode(ack4_raw)
            self.assertEqual(ack4.waypoint.name, '@LayerName_10')
            self.assertEqual(ack4.waypoint.waypoint_id, jhash('act1_02') & 0xFFFFFFFF)
            self.assertEqual((ack4.waypoint.x, ack4.waypoint.y), (2688, -1408))

            # Teleport from Act1 layer 0 -> Act1 layer 4 with use_waypoint=True
            expected_cost = portal_cost('act1_01', 'act1_02', char.get('level', 1))
            from darkblood.games.network import results

            self.assertGreater(expected_cost, 0)
            char['gold'] = expected_cost - 1
            client.send_event(5030, struct.pack('<iQ?', 0x7fffffff, wp4, True))
            _, refusal = await client.expect_event(5031)
            refused = BackToSquareAck.decode(refusal)
            self.assertEqual(refused.result, results.NOT_ENOUGH_AR)
            self.assertEqual(refused.layer_net_id, wp0)
            self.assertEqual(char.get('join_layer_net_id', wp0), wp0)
            self.assertEqual(char['gold'], expected_cost - 1)

            char['gold'] = 5000
            client.send_event(5030, struct.pack('<iQ?', 0x7fffffff, wp4, True))
            _, tp_raw = await client.expect_event(5031)
            tp = BackToSquareAck.decode(tp_raw)
            self.assertTrue(tp.use_waypoint)
            self.assertEqual(tp.layer_net_id, wp4)
            self.assertEqual(tp.cur_ar, 5000 - expected_cost)

            # Relog (2006 -> 2007) includes saved waypoints in SelectCharacterAck
            client.send_event(2006, struct.pack('<iq', 0x7fffffff, uid))
            _, sel_raw = await client.expect_event(2007)
            self.assertIn('@LayerName_2'.encode('utf-16-le'), sel_raw)
            self.assertIn('@LayerName_10'.encode('utf-16-le'), sel_raw)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
