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

            # 10. Change bag property (2048 -> 2049)
            client.send_event(2048, struct.pack('<qB', 2, 3))
            _, ack2049 = await client.expect_event(2049)
            self.assertEqual(struct.unpack_from('<iqB', ack2049), (0, 2, 3))

            # 11. Modify skill speech (2053 -> 2054)
            shout = 'Die!'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2053, struct.pack('<H', 101) + struct.pack(f'<{len(shout)}s', shout))
            _, ack2054 = await client.expect_event(2054)
            self.assertEqual(struct.unpack_from('<iH', ack2054), (0, 101))

            # 12. Delete skill speech (2055 -> 2056)
            client.send_event(2055, struct.pack('<H', 101))
            _, ack2056 = await client.expect_event(2056)
            self.assertEqual(struct.unpack_from('<iH', ack2056), (0, 101))

            # 13. Store buy item (2067 -> 2068)
            client.send_event(2067, struct.pack('<iiH', 1, 99999, 1))
            _, ack2068 = await client.expect_event(2068)
            self.assertEqual(struct.unpack_from('<i', ack2068)[0], 0)

            # 14. Store sell item (2069 -> 2070)
            client.send_event(2069, struct.pack('<iqi', 1, 1, 1))
            _, ack2070 = await client.expect_event(2070)
            self.assertEqual(struct.unpack_from('<i', ack2070)[0], 0)

            # 15. Store repurchase item (2071 -> 2072)
            client.send_event(2071, struct.pack('<q', 1))
            _, ack2072 = await client.expect_event(2072)
            self.assertEqual(struct.unpack_from('<i', ack2072)[0], 0)

            # 16. Change bag name (2032 -> 2033)
            bname = 'Storage'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2032, struct.pack('<q', 2) + bname)
            _, ack2033 = await client.expect_event(2033)
            self.assertEqual(struct.unpack_from('<iq', ack2033), (0, 2))

            # 17. Update skill locked (2117 -> 2118)
            client.send_event(2117, struct.pack('<h?', 101, True))
            _, ack2118 = await client.expect_event(2118)
            self.assertEqual(struct.unpack_from('<ih?', ack2118), (0, 101, True))

            # 18. Durability repair (2145 -> 2146)
            client.send_event(2145, b'\x17\x80')
            _, ack2146 = await client.expect_event(2146)
            self.assertEqual(struct.unpack_from('<i', ack2146)[0], 0)

            # 19. Item upgrade (2115 -> 2116)
            client.send_event(2115, struct.pack('<qqq', 1, 2, 0))
            _, ack2116 = await client.expect_event(2116)
            self.assertNotEqual(struct.unpack_from('<i', ack2116)[0], 0)

            # 20. Buy life water (2086 -> 2087)
            client.send_event(2086, struct.pack('<?', True))
            _, ack2087 = await client.expect_event(2087)
            self.assertEqual(struct.unpack_from('<i?', ack2087), (0, True))

            # 21. Contract update (2121 -> 2122)
            client.send_event(2121, struct.pack('<i', 10))
            _, ack2122 = await client.expect_event(2122)
            self.assertEqual(struct.unpack_from('<ii', ack2122), (0, 10))

            # 22. Durability change (2143 -> 2144)
            client.send_event(2143, b'\x17\x80')
            _, ack2144 = await client.expect_event(2144)
            self.assertEqual(struct.unpack_from('<i', ack2144)[0], 0)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
