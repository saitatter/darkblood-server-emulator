"""In-game "Select Character": 5037 -> 5038, then 2008 -> 2009 (SquareToSelChar 0x006FB360)."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games.world import GameWorldManager


class SelectCharFromWorldTest(ServerTestCase):
    def test_leave_layer_then_char_list(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Returner', char_class=5))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            self.assertIsNotNone(GameWorldManager.get().get_player(char_id))

            # Live 5037 body is empty.
            client.send_event(5037, b'')
            _, ack5038 = await client.expect_event(5038)
            self.assertEqual(ack5038, struct.pack('<I', 0))
            self.assertIsNone(GameWorldManager.get().get_player(char_id))

            client.send_event(2008, b'')
            _, ack2009 = await client.expect_event(2009)
            self.assertEqual(struct.unpack_from('<I', ack2009)[0], 0)
            self.assertIn('Returner'.encode('utf-16le'), ack2009)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
