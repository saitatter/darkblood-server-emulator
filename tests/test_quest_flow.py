"""Tests for quest completion, client dictionary rewards, and active quest restoration."""
import os
from pathlib import Path
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

    def test_monster_dead_advances_quest_objective(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        quest_file = dict_dir / 'quest_act1.lua'
        quest_file.write_text('\n'.join([
            'assert(DictQuest:LoadMission({',
            '  {',
            '    MissionID = "QM14",',
            '    MissionType = "0",',
            '    TargetID = "1fpi03U0",',
            '    TargetValue = 1,',
            '  }',
            '}), "DictQuest:LoadMission")',
            'assert(DictQuest:LoadQuest({',
            '  {',
            '    ID = "Q0002S01",',
            '    MissionID = {"QM14"},',
            '  }',
            '}), "DictQuest:LoadQuest")',
            ''
        ]), encoding='utf-8')
        from darkblood.games.game_data import client_dict
        client_dict.quest_monster_objectives.cache_clear()
        self.addCleanup(client_dict.quest_monster_objectives.cache_clear)
        self.addCleanup(quest_file.unlink)

        quest = hashing.jhash('Q0002S01')
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest, -1)
        berserk_hog_hash = hashing.jhash('1fpi03U0') & 0xFFFFFFFF

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('HogHunter'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            # Accept Q0002S01
            client.send_event(2073, req, compressed=True)
            await client.expect_event(2074)

            # Kill Berserk Hog in dungeon (5063)
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, berserk_hog_hash, 1))
            _, not2075 = await client.expect_event(2075)
            self.assertEqual(not2075[:2], b'\x10\x81')
            q_id, obj_idx, count = struct.unpack_from('<iii', not2075, 2)
            q_signed = quest - (1 << 32) if quest >= 1 << 31 else quest
            self.assertEqual((q_id, obj_idx, count), (q_signed, 0, 1))

        self.run_async(self.with_server(scenario))

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

    def test_quest_giveup_and_fail(self):
        quest1 = hashing.jhash('Q0003S01')
        quest2 = hashing.jhash('Q0004S01')
        stamp = 'x'.encode('utf-16le')
        req1 = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest1, -1)
        req2 = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest2, -1)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('QuestQuitter'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Accept quest 1 and quest 2
            client.send_event(2073, req1, compressed=True)
            await client.expect_event(2074)
            client.send_event(2073, req2, compressed=True)
            await client.expect_event(2074)

            # Give up quest 1 (2078 -> 2079)
            client.send_event(2078, struct.pack('<I', quest1))
            _, ack2079 = await client.expect_event(2079)
            self.assertEqual(struct.unpack_from('<iI', ack2079[:8]), (0, quest1))

            # Fail quest 2 (2080 -> 2081)
            client.send_event(2080, struct.pack('<I', quest2))
            _, ack2081 = await client.expect_event(2081)
            self.assertEqual(struct.unpack_from('<iI', ack2081[:8]), (0, quest2))
            return char_id

        char_id = self.run_async(self.with_server(scenario))
        char = session.GameSession.store().get('OfflinePlayer', char_id)
        active = char.get('quests_active', {})
        self.assertNotIn(str(quest1), active)
        self.assertNotIn(str(quest2), active)


if __name__ == '__main__':
    unittest.main()
