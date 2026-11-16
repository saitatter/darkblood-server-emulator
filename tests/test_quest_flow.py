"""Tests for quest completion, client dictionary rewards, and active quest restoration."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core import hashing
from darkblood.core.serialization import jser
from darkblood.games import session


class QuestFlowTest(ServerTestCase):
    def test_quest_completion_persists(self):
        quest = hashing.jhash('Q0001S01')
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest, -1)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('QuestTester'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            # Accept quest 2073 -> 2074
            client.send_event(2073, req, compressed=True)
            _, ack2074 = await client.expect_event(2074)
            self.assertEqual(struct.unpack_from('<I', ack2074)[0], 0)
            # Complete quest 2076 -> 2077
            client.send_event(2076, req, compressed=True)
            _, ack2077 = await client.expect_event(2077)
            self.assertEqual(struct.unpack_from('<I', ack2077)[0], 0)
            return char_id

        char_id = self.run_async(self.with_server(scenario))
        char = session.GameSession.store().get('OfflinePlayer', char_id)
        self.assertIn(quest, char.get('quests_done', []))

    def test_quest_rewards_from_client_dict(self):
        import os
        from pathlib import Path
        from darkblood.games.game_data import client_dict
        base = Path(os.environ['DARKBLOOD_CLIENT_DATA'])
        dict_dir = base / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        (dict_dir / 'quest_act1.lua').write_text('\n'.join([
            'assert(DictQuest:LoadQuest({', '  {', '    ID = "Q0002S01",', '    RewardExp = 150,',
            '    RewardGP = 0,', '    RewardGold = 774,', '    RewardItemG = "LLQ0002S01r",', '  }',
            '}), "DictQuest:LoadQuest")', 'assert(DictQuest:LoadItemGroup({', '  {',
            '    GroupID = "LLQ0002S01r",', '    ItemUnit = {', '      {', '        "Ibaga0004",',
            '        0,', '        1', '      }', '    }', '  }', '}), "DictQuest:LoadItemGroup")', '']),
            encoding='utf-8')
        client_dict.quests.cache_clear()
        client_dict.item_groups.cache_clear()
        self.addCleanup(client_dict.quests.cache_clear)
        self.addCleanup(client_dict.item_groups.cache_clear)
        self.addCleanup((dict_dir / 'quest_act1.lua').unlink)

        quest = hashing.jhash('Q0002S01')
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest, -1)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RewardTester'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            client.send_event(2073, req, compressed=True)
            await client.expect_event(2074)
            client.send_event(2076, req, compressed=True)
            _, ack = await client.expect_event(2077)
            return char_id, ack

        char_id, ack = self.run_async(self.with_server(scenario))
        # jAck +0x1E gold total: default 21 + RewardGold 774; item vector holds Ibaga0004.
        self.assertEqual(struct.unpack_from('<q', ack, 4 + 0x1E)[0], 21 + 774)
        self.assertEqual(ack[4 + 0x26:4 + 0x28], b'\x10\x81')
        self.assertEqual(struct.unpack_from('<ii', ack, len(ack) - 8), (150, 0))  # EXP, GP
        char = session.GameSession.store().get('OfflinePlayer', char_id)
        self.assertEqual(char['level'], 2)
        self.assertEqual(char['u62'], 6)  # 13 + 150 exp - 157 req_exp = 6 remaining exp
        self.assertEqual(char['sp'], 3)
        self.assertIn('Ibaga0004', [i['code'] for i in char['items']])


    def test_active_quest_restored_in_select_ack(self):
        quest = hashing.jhash('Q0002S01')
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest, -1)
        entry = (b'\x0f' + struct.pack('<I', quest) + struct.pack('<qqI?', 1, 0, quest, True)
                 + jser.varuint(0))

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('ActiveTracker'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, first = await client.expect_event(2007)
            client.send_event(2073, req, compressed=True)
            await client.expect_event(2074)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, second = await client.expect_event(2007)
            return first, second

        first, second = self.run_async(self.with_server(scenario))
        self.assertNotIn(entry, first)
        # The 0xA3E450 map now carries one entry; everything else is unchanged.
        self.assertEqual(second.replace(b'\x17\x81' + entry, b'\x17\x80', 1), first)

    def test_char_level_stats_progression(self):
        from darkblood.games.game_data import client_dict
        warrior_lv1 = client_dict.char_level_stat(1, 1)
        self.assertGreater(warrior_lv1.get('upexp', 0), 0)
        self.assertGreater(warrior_lv1.get('hp', 0), 0)
        self.assertGreater(warrior_lv1.get('mp', 0), 0)

        # Higher level requires more EXP and grants higher HP
        warrior_lv10 = client_dict.char_level_stat(1, 10)
        self.assertGreater(warrior_lv10['upexp'], warrior_lv1['upexp'])
        self.assertGreater(warrior_lv10['hp'], warrior_lv1['hp'])


if __name__ == '__main__':
    unittest.main()
