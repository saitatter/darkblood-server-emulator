"""Integration tests for lobby flow: server/channel lists, character management, selection."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games import session


class LobbyFlowTest(ServerTestCase):
    def test_lobby_and_selection(self):
        async def scenario(client):
            out = await lobby_flow(client)
            for opcode in (2403, 2002, 2022, 5029, 2009):
                self.assertIn(opcode, out)
                self.assertEqual(struct.unpack_from('<I', out[opcode])[0], 0)

            # Create character (class 1: Warrior)
            client.send_event(2012, create_request('LobbyWarrior', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            self.assertEqual(struct.unpack_from('<I', ack2013)[0], 0)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]

            # Select character
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<I', ack2007)[0], 0)

            # Character deletion
            client.send_event(2014, struct.pack('<q', char_id))
            _, ack2015 = await client.expect_event(2015)
            self.assertEqual(struct.unpack_from('<iqi', ack2015), (0, char_id, 0))

        self.run_async(self.with_server(scenario))

    def test_thief_creation_and_inventory(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('ThiefTest', char_class=4))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<I', ack2007)[0], 0)

            # Check that inventory items and bags were created for the thief
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIsNotNone(char)
            self.assertEqual(char['char_class'], 4)
            self.assertIn('items', char)
            self.assertIn('bags', char)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
