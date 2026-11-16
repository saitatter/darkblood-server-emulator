"""Tests for item movement, usage, discarding, bag management, quickslots and skill learning."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games import session
from darkblood.games.state import selected_character


class InventoryFlowTest(ServerTestCase):
    def test_inventory_and_skill_operations(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('InvHero', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Populate items on character
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char['items'] = [
                dict(code='AbodT1N', uid=1, container=1, slot=0, count=10),
                dict(code='AbodT1N', uid=2, container=2, slot=1, count=5),
            ]
            selected_character['id'] = char_id
            session.GameSession.store().save()

            # 1. Drag item (2036 -> 2037)
            client.send_event(2036, struct.pack('<qqi', 1, 2, 0))
            _, ack2037 = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', ack2037)[0], 0)
            self.assertEqual(ack2037[4], 0x10)  # tag 0x10 vector

            # 2. Equip item (2042 -> 2043)
            client.send_event(2042, struct.pack('<qi', 1, 0))
            _, ack2043 = await client.expect_event(2043)
            self.assertEqual(struct.unpack_from('<i', ack2043)[0], 0)

            # 3. Use item (2038 -> 2039)
            client.send_event(2038, struct.pack('<qi', 1, 1))
            _, ack2039 = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039)[0], 0)

            # 4. Discard item (2040 -> 2041)
            client.send_event(2040, struct.pack('<qi', 2, 2))
            _, ack2041 = await client.expect_event(2041)
            self.assertEqual(struct.unpack_from('<iqi', ack2041), (0, 2, 2))

            # 5. Switch bag (2030 -> 2031)
            client.send_event(2030, struct.pack('<HH', 0, 1))
            _, ack2031 = await client.expect_event(2031)
            self.assertEqual(struct.unpack_from('<iHH', ack2031), (0, 0, 1))

            # 6. Close bag (2028: fire and forget)
            client.send_event(2028, struct.pack('<iq', 0x7fffffff, 2))

            # 7. Assign quickslot (2044 -> 2045)
            client.send_event(2044, struct.pack('<BBiq', 0, 1, 12345, 1))
            _, ack2045 = await client.expect_event(2045)
            self.assertEqual(struct.unpack_from('<iBBiq', ack2045), (0, 0, 1, 12345, 1))

            # 8. Switch quickslot (2046 -> 2047)
            client.send_event(2046, struct.pack('<BBB', 0, 0, 1))
            _, ack2047 = await client.expect_event(2047)
            self.assertEqual(struct.unpack_from('<iBBB', ack2047), (0, 0, 0, 1))

            # 9. Learn skill (2050 -> 2051)
            client.send_event(2050, struct.pack('<HB', 101, 2))
            _, ack2051 = await client.expect_event(2051)
            self.assertEqual(struct.unpack_from('<iHBiq', ack2051)[:3], (0, 101, 2))

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
