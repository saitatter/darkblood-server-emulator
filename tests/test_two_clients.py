"""Two game connections play different characters at the same time (multibox)."""
import struct
import unittest

from tests.common import HeadlessClient, ServerTestCase, create_request, lobby_flow
from darkblood.games import session


async def _enter(client, name):
    await lobby_flow(client)
    client.send_event(2012, create_request(name))
    _, created = await client.expect_event(2013)
    char_id = struct.unpack_from('<Q', created, 10)[0]
    client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
    await client.expect_event(2007)
    return char_id


class TwoClientsTest(ServerTestCase):
    def test_selection_is_per_connection(self):
        async def scenario(first):
            second = HeadlessClient(port=first.port)
            try:
                a = await _enter(first, 'Alpha')
                b = await _enter(second, 'Bravo')  # selected last
                self.assertNotEqual(a, b)

                # The first window acts after the second one selected.
                first.send_event(2044, bytes.fromhex('ffffff7f0100') + struct.pack('<iq', 0x77, -1))
                await first.expect_event(2045)
                store = session.GameSession.store()
                self.assertIn('1:0', store.get('OfflinePlayer', a).get('quickslots', {}))
                self.assertNotIn('1:0', store.get('OfflinePlayer', b).get('quickslots', {}))
            finally:
                await second.close()

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
