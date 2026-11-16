"""Reconnect with a character still loaded: 5028 without 2008 must get 5031."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from headless_client import HeadlessClient


class ReconnectResumeTest(ServerTestCase):
    def test_join_square_without_charlist_gets_join_layer(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Resumer'))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.close()

            # The shim's reconnect: new login, server/channel list, 5028, then
            # SelectChannel waits for 5031 without sending 2008.
            again = HeadlessClient(port=client.port)
            await again.connect()
            await again.expect_event(5020)
            again.send_event(5028, struct.pack('<iQ', 0x7fffffff, 1))
            await again.expect_event(5029)
            await again.expect_event(5134)
            _, ack5031 = await again.expect_event(5031)
            self.assertEqual(struct.unpack_from('<I', ack5031)[0], 0)
            await again.close()

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
