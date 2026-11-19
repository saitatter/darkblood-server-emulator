"""GM /bags gives every UI bag slot a 20-cell bag (testing aid)."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games import session
from darkblood.player_management.characters import (
    EQUIP_CONTAINER, ensure_inventory, free_bag_slots, grant_test_bags)


class GrantTestBagsTest(unittest.TestCase):
    def test_enlarges_starting_bag_and_fills_free_slots(self):
        char = {'char_class': 1, 'items': []}
        ensure_inventory(char)
        self.assertEqual(free_bag_slots(char), 5)

        self.assertEqual(grant_test_bags(char), 5)
        bags = [b for b in char['bags'] if b['bag_id'] != EQUIP_CONTAINER]
        self.assertEqual(sorted(b['w2a'] for b in bags), [0, 1, 2, 3, 4])
        self.assertTrue(all(b['b29'] == 20 and b['code'] == 'Ibaga0003' for b in bags))
        ids = [b['bag_id'] for b in char['bags']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(2, ids)  # container 2 is dropped by the client
        self.assertEqual(free_bag_slots(char), 100)
        self.assertEqual(grant_test_bags(char), 0)


class GmBagsFlowTest(ServerTestCase):
    def test_gm_bags_command_is_sent_in_next_selection(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('GmBagTester'))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            client.send_event(5040, b'\x00' + '/bags'.encode('utf-16le'))
            _, ack = await client.expect_event(5041)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(free_bag_slots(char), 100 - len(
                [i for i in char['items'] if i['container'] != EQUIP_CONTAINER]))

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
