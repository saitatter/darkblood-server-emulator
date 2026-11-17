"""Two game connections play different characters at the same time (multibox)."""
import struct
import unittest

from tests.common import HeadlessClient, ServerTestCase, create_request, lobby_flow
from darkblood.core.serialization import jser
from darkblood.games import session


async def _enter(client, name):
    out = await lobby_flow(client)
    client.send_event(2012, create_request(name))
    _, created = await client.expect_event(2013)
    char_id = struct.unpack_from('<Q', created, 10)[0]
    client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
    await client.expect_event(2007)
    return char_id, out


def _welcome_account(body):
    uid = struct.unpack_from('<Q', body, 4)[0]
    length, offset = jser.read_varuint(body, 12)
    return uid, body[offset:offset + length].decode('utf-16le')


class TwoClientsTest(ServerTestCase):
    def test_selection_is_per_connection(self):
        async def scenario(first):
            second = HeadlessClient(port=first.port)
            try:
                a, _ = await _enter(first, 'Alpha')
                b, _ = await _enter(second, 'Bravo')  # selected last
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

    def test_each_client_logs_in_to_its_own_account(self):
        async def scenario(first):
            second = HeadlessClient(port=first.port, account='Player2')
            try:
                a, out_a = await _enter(first, 'Charlie')
                b, out_b = await _enter(second, 'Delta')
                self.assertEqual(_welcome_account(out_a[5020]), (1, 'OfflinePlayer'))
                uid, name = _welcome_account(out_b[5020])
                self.assertEqual(name, 'Player2')
                self.assertNotEqual(uid, 1)
                store = session.GameSession.store()
                self.assertIn(b, [c['id'] for c in store.characters('Player2')])
                self.assertNotIn(b, [c['id'] for c in store.characters('OfflinePlayer')])
                self.assertNotIn(a, [c['id'] for c in store.characters('Player2')])
            finally:
                await second.close()

        self.run_async(self.with_server(scenario))

    def test_client_without_ticket_gets_default_account(self):
        async def scenario(client):
            await client.connect()
            await client.expect_event(2)  # eE_ACCEPT_NOT; no 5386 answer
            _, body = await client.expect_event(5020)
            self.assertEqual(_welcome_account(body), (1, 'OfflinePlayer'))

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
