"""Integration tests for lobby flow: server/channel lists, character management, selection."""
import struct
import time
import unittest

from darkblood.games.entities.character import Character
from darkblood.games.entities.items import Item

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
            client.send_event(2012, create_request('LobbyWarrior', char_class=1), correlation=42)
            correlation, ack2013 = await client.expect_event(2013)
            self.assertEqual(correlation, 42)
            self.assertEqual(struct.unpack_from('<I', ack2013)[0], 0)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]

            # The new model receives its worn items without requesting a list.
            correlation, preview = await client.expect_event(2009)
            self.assertEqual(correlation, 42)
            store = session.GameSession.store()
            worn = [i for i in store.get('OfflinePlayer', char_id)['items'] if i['container'] == 1]
            self.assertTrue(worn)
            for item in worn:
                self.assertIn(Item(owner=char_id, **item).encode(), preview)

            # Select character
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<I', ack2007)[0], 0)

            # Character deletion
            # Deletion is pending: the record stays until the delay ends.
            client.send_event(2014, struct.pack('<iq', 0x7fffffff, char_id))
            _, ack2015 = await client.expect_event(2015)
            result, uid, done_at = struct.unpack_from('<iqi', ack2015)
            self.assertEqual((result, uid), (0, char_id))
            # Seconds left (duration formatter 0x0074F1D0), two days.
            self.assertTrue(2 * 86400 - 5 <= done_at <= 2 * 86400)
            self.assertGreater(store.get('OfflinePlayer', char_id)['delete_time'], time.time())
            entry = Character.from_dict(store.get('OfflinePlayer', char_id))
            self.assertTrue(entry.b5d)
            self.assertTrue(2 * 86400 - 5 <= entry.u5e <= 2 * 86400)

            # Cancel Delete (2246 -> 2247) clears it.
            client.send_event(2246, struct.pack('<iq', 0x7fffffff, char_id))
            _, ack2247 = await client.expect_event(2247)
            self.assertEqual(struct.unpack_from('<iq', ack2247), (0, char_id))
            self.assertNotIn('delete_time', store.get('OfflinePlayer', char_id))

            # 2009 carries the worn items for the character-select models,
            # owned by their character (0x00538DF0).
            client.send_event(2008, b'')
            _, ack2009 = await client.expect_event(2009)
            worn = [i for i in store.get('OfflinePlayer', char_id)['items'] if i['container'] == 1]
            self.assertTrue(worn)
            for item in worn:
                self.assertIn(Item(owner=char_id, **item).encode(), ack2009)

            # An expired deletion is purged when the list is requested.
            store.get('OfflinePlayer', char_id)['delete_time'] = int(time.time()) - 1
            store.save()
            client.send_event(2008, b'')
            await client.expect_event(2009)
            self.assertIsNone(store.get('OfflinePlayer', char_id))

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


class ServerListCountTest(ServerTestCase):
    def test_server_list_shows_character_count(self):
        """2403 u16 after the name is the character count (0x0062E760; 0 -> 'None')."""
        async def scenario(client):
            await lobby_flow(client)
            for name in ('CountA', 'CountB'):
                client.send_event(2012, create_request(name, char_class=5))
                await client.expect_event(2013)
            client.send_event(2402, b'')
            _, ack = await client.expect_event(2403)
            name = 'Offline'.encode('utf-16le')
            count = struct.unpack_from('<H', ack, ack.index(name) + len(name))[0]
            store = session.GameSession.store()
            self.assertEqual(count, len(store.characters('OfflinePlayer')))
            self.assertGreaterEqual(count, 2)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
