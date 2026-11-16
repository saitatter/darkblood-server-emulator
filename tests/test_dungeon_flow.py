"""Tests for dungeon gameplay: layer transition, combat events, deaths, and rank reward choices."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core import hashing
from darkblood.games import session
from darkblood.games.state import selected_character


class DungeonFlowTest(ServerTestCase):
    def test_dungeon_and_combat_lifecycle(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('DungeonSlayer', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            selected_character['id'] = char_id

            # 1. Map transition / Gate (2344 -> 2345)
            client.send_event(2344, bytes.fromhex('ffffff7f00000000aeaf985f'))
            _, ack2345 = await client.expect_event(2345)
            self.assertEqual(struct.unpack_from('<IQQ', ack2345), (0, hashing.jhash('Act1') << 32, 1))

            # 2. Gate selection (2369 -> 2370)
            client.send_event(2369)
            _, ack2370 = await client.expect_event(2370)
            self.assertEqual(ack2370, b'\x00' * 16)

            # 3. Dungeon layer change (5095)
            layer_net_id = (hashing.jhash('Act1_G1_A10') << 32) | 4
            client.send_event(5095, struct.pack('<iq', 0x7fffffff, layer_net_id))

            # 4. War flag (2422)
            client.send_event(2422, struct.pack('<iI', 0x7fffffff, 31))

            # 5. Beginner guide update (2358)
            client.send_event(2358, struct.pack('<i', 0x7fffffff) + b'\x10\x80')

            # 6. Monster dead (5063)
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, 100, 0))

            # 7. Char stat verify (2406 -> 2407)
            client.send_event(2406, bytes.fromhex('ffffff7f0000000010801080621ac3412811ea41b802414088b60e400ad7233cffffffff'))
            _, ack2407 = await client.expect_event(2407)
            self.assertEqual(struct.unpack_from('<i', ack2407)[0], 0)

            # 8. Gameplay death (5093 -> 5094): live body is uid 0, die 1, 3 x u32.
            client.send_event(5093, bytes.fromhex('000000000000000001000000000000000000000000'))
            _, ack5094 = await client.expect_event(5094)
            res, uid, other, bDie, a, b, c, cnt = struct.unpack_from('<Iqq?IIIH', ack5094)
            self.assertEqual((res, uid, other, bDie), (0, 0, 0, True))
            self.assertEqual(len(ack5094), 35)  # no coin u16 when bDie is set

            # 8b. Revive (bDie = 0) spends one coin; trailing u16 = coins left.
            client.send_event(5093, struct.pack('<q?III', 0, False, 0, 0, 0))
            _, ack5094 = await client.expect_event(5094)
            self.assertEqual(struct.unpack_from('<?', ack5094, 20)[0], False)
            self.assertEqual(struct.unpack_from('<H', ack5094, 35)[0], 2)

            # 9. Daily rebirth coin claim (2448 -> 2449 + 2286): tops coins up to 3.
            client.send_event(2448, bytes.fromhex('ffffff7f00'))
            _, ack2449 = await client.expect_event(2449)
            self.assertEqual(struct.unpack_from('<IHI', ack2449), (0, 1, 0))
            _, not2286 = await client.expect_event(2286)
            self.assertEqual(struct.unpack_from('<IH', not2286), (0, 3))

            # 10. Choice reward party rank (5090 -> 5091)
            client.send_event(5090, struct.pack('<ii', 0x7fffffff, 0))
            _, ack5091 = await client.expect_event(5091)
            self.assertEqual(struct.unpack_from('<iq', ack5091)[:2], (0, char['id']))

            # 11. Back to square (5045 -> 5046)
            client.send_event(5045, struct.pack('<i', 0x7fffffff))
            _, ack5046 = await client.expect_event(5046)
            self.assertEqual(struct.unpack_from('<i', ack5046)[0], 0)

            # 12. Party invite (5049 -> 5050)
            client.send_event(5049, struct.pack('<q', 12345))
            _, ack5050 = await client.expect_event(5050)
            self.assertEqual(struct.unpack_from('<i', ack5050)[0], 0)

            # 13. Party accept invite (5054 -> 5055)
            client.send_event(5054, struct.pack('<q', 12345))
            _, ack5055 = await client.expect_event(5055)
            self.assertEqual(struct.unpack_from('<i', ack5055)[0], 0)

            # 14. Change team (5015 -> 5016)
            client.send_event(5015, struct.pack('<i', 1))
            _, ack5016 = await client.expect_event(5016)
            self.assertEqual(struct.unpack_from('<ii', ack5016), (0, 1))

            # 15. Pick up item (5065 -> 5066 & 5068)
            client.send_event(5065, struct.pack('<q', 8888))
            _, ack5066 = await client.expect_event(5066)
            self.assertEqual(struct.unpack_from('<i', ack5066)[0], 0)
            _, ack5068 = await client.expect_event(5068)
            self.assertEqual(struct.unpack_from('<i', ack5068)[0], 0)

            # 16. Gold goblin attack (5363 -> 5364)
            client.send_event(5363, struct.pack('<ii', 1, 100))
            _, ack5364 = await client.expect_event(5364)
            self.assertEqual(struct.unpack_from('<i', ack5364)[0], 0)

            # 17. Gold goblin dead (5365 -> 5366)
            client.send_event(5365, struct.pack('<i', 1))
            _, ack5366 = await client.expect_event(5366)
            self.assertEqual(struct.unpack_from('<i', ack5366)[0], 0)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
