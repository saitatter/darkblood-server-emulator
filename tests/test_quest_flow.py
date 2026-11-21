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

    def test_quest_start_hands_over_offer_items(self):
        from darkblood.games.game_data import client_dict
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        # Shapes copied from quest_act1.lua (Q0008S01 / LLQ0008S01o).
        (dict_dir / 'quest_act1.lua').write_text('\n'.join([
            'assert(DictQuest:LoadQuest({', '  {', '    ID = "Q0008S01",', '    OfferItemG = "LLQ0008S01o",',
            '    RewardExp = 300,', '  }', '}), "DictQuest:LoadQuest")', 'assert(DictQuest:LoadItemGroup({', '  {',
            '    GroupID = "LLQ0008S01o",', '    ItemUnit = {', '      {', '        "Iquea0310",',
            '        0,', '        1', '      }', '    }', '  }', '}), "DictQuest:LoadItemGroup")', '']),
            encoding='utf-8')
        for fn in (client_dict.quests, client_dict.item_groups):
            fn.cache_clear()
            self.addCleanup(fn.cache_clear)
        self.addCleanup((dict_dir / 'quest_act1.lua').unlink)
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', hashing.jhash('Q0008S01'), -1)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Courier'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            client.send_event(2073, req, compressed=True)
            await client.expect_event(2074)
            _, items = await client.expect_event(2037)
            self.assertEqual(items[4:6], b'\x10\x81')
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual([i['code'] for i in char['items']].count('Iquea0310'), 1)
            # Accepting again (already active) hands nothing over.
            client.send_event(2073, req, compressed=True)
            await client.expect_event(2074)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual([i['code'] for i in char['items']].count('Iquea0310'), 1)

        self.run_async(self.with_server(scenario))

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
            _, level_up = await client.expect_event(5087)
            _, exp = await client.expect_event(5086)
            self.assertEqual(struct.unpack_from('<IIqBII?', level_up, 1), (3, 3, char_id, 2, 6, 3, True))
            self.assertEqual(struct.unpack_from('<iiii', exp), (6, 0, 0, 150))
            _, ack = await client.expect_event(2077)
            return char_id, ack

        char_id, ack = self.run_async(self.with_server(scenario))
        # jAck +0x1E gold total: default 21 + RewardGold 774; item vector holds Ibaga0004.
        self.assertEqual(struct.unpack_from('<q', ack, 4 + 0x1E)[0], 21 + 774)
        self.assertEqual(ack[4 + 0x26:4 + 0x28], b'\x10\x81')
        self.assertEqual(struct.unpack_from('<ii', ack, len(ack) - 8), (150, 0))  # EXP, GP
        char = session.GameSession.store().get('OfflinePlayer', char_id)
        self.assertEqual(char['level'], 2)
        self.assertEqual(char['exp'], 6)  # 150 reward XP - 144 required XP
        self.assertEqual(char['sp'], 3)
        self.assertIn('Ibaga0004', [i['code'] for i in char['items']])


    def test_active_quest_restored_in_select_ack(self):
        quest = hashing.jhash('Q0002S01')
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest, -1)
        from darkblood.games.game_data import client_dict
        counts = client_dict.quest_mission_counts().get(quest, 0)
        entry = (b'\x0f' + struct.pack('<I', quest) + struct.pack('<qqI?', 1, 0, quest, True)
                 + jser.varuint(counts) + (struct.pack('<I', 0) * counts))

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
        warrior_lv1 = client_dict.char_level_stat(0, 1)
        self.assertGreater(warrior_lv1.get('upexp', 0), 0)
        self.assertGreater(warrior_lv1.get('hp', 0), 0)
        self.assertGreater(warrior_lv1.get('mp', 0), 0)

        # Higher level requires more EXP and grants higher HP
        warrior_lv10 = client_dict.char_level_stat(0, 10)
        self.assertGreater(warrior_lv10['upexp'], warrior_lv1['upexp'])
        self.assertGreater(warrior_lv10['hp'], warrior_lv1['hp'])

    def test_quest_giveup_and_fail(self):
        quest1 = hashing.jhash('Q0003S01')
        quest2 = hashing.jhash('Q0004S01')
        stamp = '2015-02-23 15:42:11, '.encode('utf-16le')
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
            client.send_event(2078, jser.varuint(len(stamp)) + stamp + struct.pack('<I', quest1), compressed=True)
            _, ack2079 = await client.expect_event(2079)
            self.assertEqual(struct.unpack_from('<i', ack2079[:4])[0], 0)
            self.assertEqual(ack2079[4:6], b'\x10\x81')
            self.assertEqual(struct.unpack_from('<I', ack2079, 6)[0], quest1)

            # Fail quest 2 (2080 -> 2081)
            client.send_event(2080, jser.varuint(len(stamp)) + stamp + struct.pack('<I', quest2), compressed=True)
            _, ack2081 = await client.expect_event(2081)
            self.assertEqual(struct.unpack_from('<i', ack2081[:4])[0], 0)
            self.assertEqual(ack2081[4:6], b'\x10\x81')
            self.assertEqual(struct.unpack_from('<I', ack2081, 6)[0], quest2)
            return char_id

        char_id = self.run_async(self.with_server(scenario))
        char = session.GameSession.store().get('OfflinePlayer', char_id)
        active = char.get('quests_active', {})
        self.assertNotIn(str(quest1), active)
        self.assertNotIn(str(quest2), active)

    def test_quest_item_objective_tracked_and_completed(self):
        from darkblood.games.game_data import client_dict
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        (dict_dir / 'quest_act1.lua').write_text('\n'.join([
            'assert(DictQuest:LoadQuest({',
            '  {',
            '    ID = "Q0008S01",',
            '    MissionID = {"QM807", "QM815"},',
            '    OfferItemG = "LLQ0008S01o",',
            '    RewardExp = 100,',
            '    RewardGold = 50,',
            '  }',
            '}), "DictQuest:LoadQuest")',
            'assert(DictQuest:LoadItemGroup({',
            '  {',
            '    GroupID = "LLQ0008S01o",',
            '    ItemUnit = {',
            '      {',
            '        "Iquea0310",',
            '        0,',
            '        1',
            '      }',
            '    }',
            '  }',
            '}), "DictQuest:LoadItemGroup")',
            'assert(DictQuest:LoadMission({',
            '  {',
            '    MissionID = "QM807",',
            '    MissionType = "5",',
            '    TargetValue = 1',
            '  },',
            '  {',
            '    MissionID = "QM815",',
            '    MissionType = "1",',
            '    TargetID = "Iquea0310",',
            '    TargetValue = 1',
            '  }',
            '}), "DictQuest:LoadMission")',
            ''
        ]), encoding='utf-8')
        for fn in (client_dict.quests, client_dict.item_groups, client_dict.quest_item_objectives,
                   client_dict.quest_mission_counts, client_dict.quest_mission_objectives):
            fn.cache_clear()
            self.addCleanup(fn.cache_clear)
        self.addCleanup((dict_dir / 'quest_act1.lua').unlink)

        q_hash = hashing.jhash('Q0008S01') & 0xFFFFFFFF
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', q_hash, -1)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('GuardBuddy'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Start quest: hands over Iquea0310 (2037) and immediately updates QM815 (2075)
            client.send_event(2073, req, compressed=True)
            await client.expect_event(2074)
            await client.expect_event(2037)
            _, not2075 = await client.expect_event(2075)
            # 2075: b'\x10' + varuint(1) + signed_qid, obj_idx (1), count (1)
            q_signed = q_hash - (1 << 32) if q_hash >= 1 << 31 else q_hash
            self.assertEqual(struct.unpack_from('<iii', not2075, 2), (q_signed, 1, 1))

            # Talk to NPC Lloyd: sends 2113 for QM807 -> updates objective 0
            mission_str = 'QM807'.encode('utf-16le')
            body_2113 = struct.pack('<i', 0x7fffffff) + jser.varuint(len(mission_str)) + mission_str
            client.send_event(2113, body_2113)
            _, not2075_talk = await client.expect_event(2075)
            self.assertEqual(struct.unpack_from('<iii', not2075_talk, 2), (q_signed, 0, 1))
            await client.expect_event(2114)

            # Both objectives complete: turn in quest (2076 -> 2077)
            client.send_event(2076, req, compressed=True)
            await client.expect_event(5086)  # EXP gain notification
            _, ack2077 = await client.expect_event(2077)
            self.assertEqual(struct.unpack_from('<I', ack2077[:4])[0], 0)

            # Verify character store: quest is done and consumed offer item is gone
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIn(q_hash, char.get('quests_done', []))
            self.assertNotIn('Iquea0310', [it['code'] for it in char.get('items', [])])

        self.run_async(self.with_server(scenario))

    def test_quest_dungeon_clear_objectives_advance_on_finish_game(self):
        """5017 FinishGame clear advances both mission_type 3 (exact map) and mission_type 2 (dungeon id)."""
        q_map_hash = hashing.jhash('Q0019S01') & 0xFFFFFFFF  # QM23: type 3 -> Act1_G1_A34
        # Also pick a type-2 quest targeting dungeon Act1_G1_A3 (e.g. QM44/QM24)
        from darkblood.games.game_data.client_dict import quest_dungeon_objectives
        by_dungeon, _ = quest_dungeon_objectives()
        q_dun_hash, q_dun_idx, _ = by_dungeon['Act1_G1_A3'][0]

        stamp = 'x'.encode('utf-16le')
        req_map = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', q_map_hash, -1)
        req_dun = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', q_dun_hash, -1)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('HaramRunner'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.expect_event(2410)

            # Accept both quests
            client.send_event(2073, req_map, compressed=True)
            await client.expect_event(2074)
            client.send_event(2073, req_dun, compressed=True)
            await client.expect_event(2074)

            # Enter and clear Act1_G1_A34 (dungeon Act1_G1_A3)
            from darkblood.games.network.messages import StartGameReq
            client.send_event(5013, StartGameReq(map_code='Act1_G1_A34').encode())
            await client.expect_event(5014)
            client.send_event(5017, b'\x01')

            updates = {}
            for _ in range(2):
                _, body2075 = await client.expect_event(2075)
                qid, idx, cnt = struct.unpack_from('<iii', body2075, 2)
                updates[(qid & 0xFFFFFFFF, idx)] = cnt
            await client.expect_event(5018)

            self.assertEqual(updates.get((q_map_hash, 0)), 1)
            self.assertEqual(updates.get((q_dun_hash, q_dun_idx)), 1)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['quests_active'][str(q_map_hash)]['counters'][0], 1)
            self.assertEqual(char['quests_active'][str(q_dun_hash)]['counters'][q_dun_idx], 1)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
