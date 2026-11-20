"""Counter achievements: 2446 division reports, 2330 completion and the 2328 list."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.hashing import jhash
from darkblood.games import session


def division_report(amounts):
    """Live 2446 layout: tag 0x17 map of 0x0F, u32 division, i64 amount."""
    body = b'\x17' + bytes([0x80 | len(amounts)])
    for division, amount in amounts.items():
        body += b'\x0f' + struct.pack('<Iq', division, amount)
    return body


class AchievementFlowTest(ServerTestCase):
    def test_division_reports_complete_counter_achievements(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Achiever'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)

            # Empty list: two empty maps, the bool, and an empty vector.
            client.send_event(2327, b'')
            _, ack = await client.expect_event(2328)
            self.assertEqual(ack, struct.pack('<i', 0) + bytes.fromhex('1780178000') + bytes.fromhex('1080'))

            # Division 25 (OSACHV25Lv1, goal 500, accumulated): two runs.
            client.send_event(2446, division_report({25: 300, 24: 87}))
            _, ack2447 = await client.expect_event(2447)
            self.assertEqual(ack2447, struct.pack('<I', 0))
            self.assertNotIn('OSACHV25Lv1', char['achievements'])

            client.send_event(2446, division_report({25: 250}))
            await client.expect_event(2447)
            _, done = await client.expect_event(2330)
            self.assertEqual(done[:2], b'\x10\x81')
            achieve_hash, flag, extra, stamp = struct.unpack_from('<I?iq', done, 2)
            self.assertEqual((achieve_hash, flag), (jhash('OSACHV25Lv1') & 0xFFFFFFFF, True))
            # Second vector: the 13-byte block 0x0079D240 announces by name.
            self.assertEqual(done[2 + 17:2 + 17 + 6], b'\x10\x81' + struct.pack('<I', achieve_hash))
            self.assertEqual(len(done), 2 + 17 + 2 + 13)
            self.assertEqual(char['achieve_divisions'], {'25': 550, '24': 87})

            # The list now carries the totals and the completed entry.
            client.send_event(2327, b'')
            _, ack = await client.expect_event(2328)
            self.assertIn(b'\x0f' + struct.pack('<Iq', 25, 550), ack)
            self.assertIn(b'\x0f' + struct.pack('<I', achieve_hash) + struct.pack('<I', achieve_hash), ack)
            self.assertTrue(ack.endswith(b'\x10\x81' + struct.pack('<I', achieve_hash) + b'\x00' * 9))

            # 2444: the client reports a hidden achievement it completed itself;
            # unknown ids are ignored.
            hidden = jhash('HACHV10001Lv1') & 0xFFFFFFFF
            client.send_event(2444, b'\x10\x82' + struct.pack('<II', hidden, 0x12345678))
            _, ack2445 = await client.expect_event(2445)
            self.assertEqual(ack2445, struct.pack('<I', 0))
            _, done = await client.expect_event(2330)
            self.assertEqual(done[:2], b'\x10\x81')
            self.assertEqual(struct.unpack_from('<I', done, 2)[0], hidden)
            self.assertIn('HACHV10001Lv1', char['achievements'])

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
