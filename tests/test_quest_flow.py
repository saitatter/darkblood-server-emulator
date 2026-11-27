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
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            collected = dict(code='Iquea0310', uid=801, container=3, slot=0, count=2)
            char['items'].append(collected)
            from unittest.mock import patch

            objectives = {'Iquea0310': [(quest, 0, 1)]}
            with patch('darkblood.games.game_data.client_dict.quest_item_objectives', return_value=objectives):
                client.send_event(2076, req, compressed=True)
                _, retry = await client.expect_event(2077)
            self.assertEqual(struct.unpack_from('<I', retry)[0], 0)
            self.assertEqual(collected['count'], 2)
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
        # jAck +0x1E gold total: starting 0 + RewardGold 774; item vector holds Ibaga0004.
        self.assertEqual(struct.unpack_from('<q', ack, 4 + 0x1E)[0], 0 + 774)  # new character: 0 AR
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

            from darkblood.games.entities.items import DEPOT_CONTAINER

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            stored = dict(code='Iquea0310', uid=801, container=DEPOT_CONTAINER, slot=0, count=1)
            char['items'].insert(0, stored)
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
            self.assertEqual([it for it in char['items'] if it['code'] == 'Iquea0310'], [stored])

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

    def test_class_promotion_quest_promotes_character_and_sends_2283(self):
        """Completing a final class-promotion quest (e.g. QMA086 Born as Sorcerer) updates char_class,
        resets skills / refunds AP, and sends 2283 eEGS_PROMOTION_NOT."""
        from darkblood.games.entities.character import CharacterClass
        from darkblood.games.game_data.client_dict import char_level_stat, quest_promotion_class
        from darkblood.games.network.messages import PromotionNot

        # Verify table covers standard + jumping quests including Hunter/WHunter Trickster vs Shooter
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA052')), CharacterClass.BERSERKER)
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA056')), CharacterClass.BREAKER)
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA072')), CharacterClass.TRICKSTER)
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA076')), CharacterClass.SHOOTER)
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA082')), CharacterClass.MAGICIAN)
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA086')), CharacterClass.SORCERER)
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA112')), CharacterClass.WTRICKSTER)
        self.assertEqual(quest_promotion_class(hashing.jhash('QMA116')), CharacterClass.WSHOOTER)
        self.assertEqual(quest_promotion_class(hashing.jhash('Q1279S01e1')), CharacterClass.SORCERER)
        # Intermediate chain quests must NOT promote
        self.assertIsNone(quest_promotion_class(hashing.jhash('QMA077')))
        self.assertIsNone(quest_promotion_class(hashing.jhash('QMA084')))
        self.assertIsNone(quest_promotion_class(hashing.jhash('QMA085')))
        # Promoted classes still resolve base class level stats
        self.assertEqual(char_level_stat(CharacterClass.SORCERER, 20),
                         char_level_stat(CharacterClass.MAGE, 20))

        q_hash = hashing.jhash('QMA086') & 0xFFFFFFFF
        stamp = '2026-11-22'.encode('utf-16le')
        req_complete = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', q_hash, -1)

        async def scenario(client):
            await lobby_flow(client)
            # Create a Mage (class 3)
            client.send_event(2012, create_request('PromoMage', char_class=int(CharacterClass.MAGE)))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]

            # Set character to level 20 with some spent SP and learned skills
            store = session.GameSession.store()
            char = store.get('OfflinePlayer', char_id)
            char['level'] = 20
            char['sp'] = 12
            char['total_ap'] = 58
            char['skills'] = {'30': 3, '26': 2}
            char['locked_skills'] = [30]
            store.save_char('OfflinePlayer', char_id)

            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.expect_event(2410)

            # Complete QMA086 ("Born as Sorcerer")
            client.send_event(2076, req_complete, compressed=True)
            await client.expect_event(5086)  # EXP gain notification
            _, ack2077 = await client.expect_event(2077)
            self.assertEqual(struct.unpack_from('<I', ack2077[:4])[0], 0)

            _, not2283 = await client.expect_event(2283)
            res, new_cls, sp = struct.unpack_from('<IBi', not2283, 0)
            self.assertEqual(res, 0)
            self.assertEqual(new_cls, int(CharacterClass.SORCERER))
            self.assertEqual(sp, 58)
            self.assertEqual(not2283[9:], b'\x17\x80')  # empty map<u16, LearnedSkill>
            self.assertEqual(
                not2283,
                PromotionNot(result=0, new_class=int(CharacterClass.SORCERER), sp=58, skills={}).encode(),
            )

            # Verify persisted state
            updated = store.get('OfflinePlayer', char_id)
            self.assertEqual(updated['char_class'], int(CharacterClass.SORCERER))
            self.assertEqual(updated['sp'], 58)
            self.assertEqual(updated['skills'], {})
            self.assertEqual(updated['locked_skills'], [])
            self.assertIn(q_hash, updated.get('quests_done', []))

        self.run_async(self.with_server(scenario))

    def test_promotion_trial_grants_and_clears_temp_skills(self):
        """Starting a PromotionLv=1 trial quest (2073) with 2 chosen tempSkills
        grants both skills (2051) and returns QuestSpecialInfo(action_type=1)
        in 2074; abandoning (2078 -> 2079) removes them with action_type=3.
        """
        q_hash = hashing.jhash('QMA061') & 0xFFFFFFFF  # Paladin trial (class 0x11)
        s1_hash = hashing.jhash('san22401') & 0xFFFFFFFF  # NameIndex 224
        s2_hash = hashing.jhash('san29501') & 0xFFFFFFFF  # NameIndex 295
        stamp = '2015-02-23 15:42:11, '.encode('utf-16le')
        req_start = (
            jser.varuint(len(stamp)) + stamp
            + struct.pack('<IiHIII', q_hash, -1, 0x11, s1_hash, s2_hash, q_hash)
        )
        req_giveup = jser.varuint(len(stamp)) + stamp + struct.pack('<I', q_hash)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('TrialPaladin', char_class=1))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.expect_event(2410)

            client.send_event(2073, req_start, compressed=True)
            _, s1_ack = await client.expect_event(2051)
            _, s2_ack = await client.expect_event(2051)
            self.assertEqual(struct.unpack_from('<iHB', s1_ack, 0), (0, 224, 1))
            self.assertEqual(struct.unpack_from('<iHB', s2_ack, 0), (0, 295, 1))

            _, ack2074 = await client.expect_event(2074)
            # 2074: u32 result, u32 quest_id, i64 quest_uid, 18-byte QuestSpecialInfo
            res, r_qid, _ = struct.unpack_from('<IIq', ack2074, 0)
            self.assertEqual((res, r_qid), (0, q_hash))
            action, t_cls, idx1, idx2, tail_qid = struct.unpack_from('<iHiiI', ack2074, 16)
            self.assertEqual((action, t_cls, idx1, idx2, tail_qid), (1, 0x11, 224, 295, q_hash))

            store = session.GameSession.store()
            char = store.get('OfflinePlayer', char_id)
            self.assertEqual(char['skills'].get('224'), 1)
            self.assertEqual(char['skills'].get('295'), 1)

            # Relog (2006 -> 2007 SelectCharacterAck) restores QuestSpecialInfo(action_type=1)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            expected_qsi = struct.pack('<iHiiI', 1, 0x11, 224, 295, q_hash)
            self.assertIn(expected_qsi, ack2007)

            # Abandoning the trial quest removes temp skills and sends action_type=3
            client.send_event(2078, req_giveup, compressed=True)
            _, ack2079 = await client.expect_event(2079)
            # 2079: i32 result (4), vector<h32> quest_ids (2 + 4 = 6), QuestSpecialInfo at +10
            action3, t_cls3, r_idx1, r_idx2, r_tail = struct.unpack_from('<iHiiI', ack2079, 10)
            self.assertEqual((action3, t_cls3, r_idx1, r_idx2, r_tail), (3, 0x11, 224, 295, q_hash))

            char_after = store.get('OfflinePlayer', char_id)
            self.assertNotIn('224', char_after.get('skills', {}))
            self.assertNotIn('295', char_after.get('skills', {}))
            self.assertNotIn('temp_skills', char_after)

            # Relog after giveup no longer sends active temp skills in 2007
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007_after = await client.expect_event(2007)
            self.assertNotIn(expected_qsi, ack2007_after)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
