"""Tutorial: quest start (2346 -> 2347 + 2074) and exit rewards (2082 -> 2083)."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core import hashing
from darkblood.games import session
from darkblood.games.game_data.client_dict import tutorial_rewards


# Live 2346 body: J-wstring "2015-02-23 15:42:11, " + u32 jhash('Q0882S01').
TUTORIAL_QUEST_START = bytes.fromhex(
    'aa32003000310035002d00300032002d00320033002000310035003a00340032003a00310031002c0020007c8ec534')


class TutorialFlowTest(ServerTestCase):
    def test_tutorial_quest_start_and_exit(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Pupil', char_class=5))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            quest = hashing.jhash('Q0882S01') & 0xFFFFFFFF
            client.send_event(2346, TUTORIAL_QUEST_START)
            _, ack2347 = await client.expect_event(2347)
            self.assertEqual(struct.unpack_from('<I', ack2347)[0], 0)
            _, ack2074 = await client.expect_event(2074)
            result, qid, uid = struct.unpack_from('<IIq', ack2074)
            self.assertEqual((result, qid, uid), (0, quest, 1))
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIn(str(quest), char['quests_active'])
            self.assertEqual(char['quests_active'][str(quest)]['counters'], [0, 0])

            # Monster kills: opcode 2353 eEGS_TUTORIAL_MONSTER_DEAD_NOT
            # Kill Wild Hog (16npi4, 0x1b371aa7) -> Objective 0
            client.send_event(2353, struct.pack('<iI', 0x7FFFFFFF, 0x1b371aa7))
            _, not2075 = await client.expect_event(2075)
            # Tag 0x10, varuint(1) (0x81), then 12 raw bytes <iii (no 0x1e byte)
            self.assertEqual(not2075[0:2], b'\x10\x81')
            self.assertEqual(len(not2075), 14)
            q_up, obj_idx, count = struct.unpack_from('<iii', not2075, 2)
            self.assertEqual((q_up, obj_idx, count), (quest, 0, 1))

            # Kill second Wild Hog -> Objective 0 count 2 (completed)
            client.send_event(2353, struct.pack('<iI', 0x7FFFFFFF, 0x1b371aa7))
            _, not2075 = await client.expect_event(2075)
            q_up, obj_idx, count = struct.unpack_from('<iii', not2075, 2)
            self.assertEqual((q_up, obj_idx, count), (quest, 0, 2))

            # Kill Black Hog (17bpi9, 0x0c2bb1e1) -> Objective 1
            client.send_event(2353, struct.pack('<iI', 0x7FFFFFFF, 0x0c2bb1e1))
            _, not2075 = await client.expect_event(2075)
            q_up, obj_idx, count = struct.unpack_from('<iii', not2075, 2)
            self.assertEqual((q_up, obj_idx, count), (quest, 1, 1))

            # Kill second Black Hog -> Objective 1 count 2 (completed)
            client.send_event(2353, struct.pack('<iI', 0x7FFFFFFF, 0x0c2bb1e1))
            _, not2075 = await client.expect_event(2075)
            q_up, obj_idx, count = struct.unpack_from('<iii', not2075, 2)
            self.assertEqual((q_up, obj_idx, count), (quest, 1, 2))

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['quests_active'][str(quest)]['counters'], [2, 2])

            # Complete quest Q0882S01 via opcode 2076
            from darkblood.core.serialization.jser import wide_string
            client.send_event(2076, wide_string('') + struct.pack('<Ii', quest, -1))
            _, ack2077 = await client.expect_event(2077)
            self.assertEqual(struct.unpack_from('<I', ack2077)[0], 0)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertNotIn(str(quest), char.get('quests_active', {}))
            self.assertIn(quest, char.get('quests_done', []))

            # On_Tutorial_Exit(true): completion rewards, granted once.
            client.send_event(2082, bytes.fromhex('ffffff7f01'))
            _, ack2083 = await client.expect_event(2083)
            self.assertEqual(struct.unpack_from('<I', ack2083)[0], 0)
            self.assertEqual(ack2083[4], 0x10)
            expected = len(tutorial_rewards()['complete'])
            self.assertEqual(ack2083[5], 0x80 | expected)
            self.assertTrue(char['tutorial_cleared'])

            client.send_event(2082, bytes.fromhex('ffffff7f01'))
            _, again = await client.expect_event(2083)
            self.assertEqual(again[4:6], b'\x10\x80')

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
