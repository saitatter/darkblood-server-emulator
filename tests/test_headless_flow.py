"""End-to-end server tests driven by the headless client (no game window).

    python -m unittest discover -s tests -v
"""
import asyncio
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory()
os.environ['DARKBLOOD_DATA'] = TMP.name  # must be set before characters is imported
os.environ['DARKBLOOD_CLIENT_DATA'] = TMP.name  # no private game tables in tests
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

from darkblood.frontend.server import BootstrapServer  # noqa: E402
from darkblood.core import hashing  # noqa: E402
from darkblood.core.serialization import jser  # noqa: E402
from darkblood.frontend import relay  # noqa: E402
from darkblood.games import session  # noqa: E402
from darkblood.games.entities import character as entities  # noqa: E402
from darkblood.games.network import messages  # noqa: E402
from headless_client import HeadlessClient, lobby_flow  # noqa: E402


def wide(text):
    raw = text.encode('utf-16le')
    return jser.varuint(len(raw)) + raw


def create_request(name, char_class=1):
    # Observed 2012 layout: i32, u8 class, wstr, u32 face, u32 hair, 5 x u8, u8.
    return (struct.pack('<iB', 0x7fffffff, char_class) + wide(name)
            + struct.pack('<II', 1, 1) + bytes([50] * 5) + b'\x00')


class SquareEntryTest(unittest.TestCase):
    def test_jhash_matches_client_djb2(self):
        # 0x00B3AD70: h = 5381; h = h * 33 + (signed byte) over UTF-16LE bytes.
        self.assertEqual(hashing.jhash(''), 5381)
        self.assertEqual(hashing.jhash('A'), ((5381 * 33 + 0x41) * 33) & 0xffffffff)
        self.assertEqual(hashing.jhash('Act1'), 0x5F98AFAE)

    def test_store_records_start_with_item_hash(self):
        ack = messages.StoreInfoAck(npc_id=1, items=[('Ihppa0001', -1)]).encode()
        self.assertEqual(ack[8:10], b'\x10\x81')
        self.assertEqual(struct.unpack_from('<Ii', ack, 10), (hashing.jhash('Ihppa0001'), -1))
        self.assertEqual(len(ack), 10 + 32 + 2)

    def test_details_carry_layer_and_tutorial_flag(self):
        # Details +0x5F (u64 nJoinLayerNetID) is immediately followed by the
        # +0x9C tutorial flag; 0x0095A150 copies them to player +0xF0 / +0x80.
        for cleared in (False, True):
            details = entities.Character(tutorial_cleared=cleared).encode_world_details()
            needle = struct.pack('<Q?', entities.layer_net_id(), cleared)
            self.assertEqual(details.count(needle), 1, cleared)

    def test_dungeon_messages_and_item_drop(self):
        from darkblood.games.network.messages import (
            ChangeDungeonLayerNot, ActiveWarFlagReq, GuideBeginnerUpdateReq,
            MonsterDeadReq, ItemDropEntry, DropItemNot
        )
        layer_net_id = (hashing.jhash('Act1_G1_A10') << 32) | 4
        raw_5095 = struct.pack('<iq', 0x7fffffff, layer_net_id)
        msg_5095 = ChangeDungeonLayerNot.decode(raw_5095)
        self.assertEqual(msg_5095.layer_id, 4)
        self.assertEqual(msg_5095.map_hash, hashing.jhash('Act1_G1_A10'))

        msg_2422 = ActiveWarFlagReq.decode(struct.pack('<iI', 0x7fffffff, 31))
        self.assertEqual(msg_2422.war_flag_id, 31)

        raw_2358 = struct.pack('<i', 0x7fffffff) + b'\x10' + jser.varuint(2) + struct.pack('<II', 101, 102)
        msg_2358 = GuideBeginnerUpdateReq.decode(raw_2358)
        self.assertEqual(msg_2358.guide_ids, [101, 102])

        msg_5063 = MonsterDeadReq.decode(struct.pack('<iII', 0x7fffffff, 42, 1))
        self.assertEqual((msg_5063.monster_id, msg_5063.param), (42, 1))

        drop = ItemDropEntry(drop_uid=1, item_id=hashing.jhash('Ihppa0024'), count=1, x=100.0, y=-2000.0, z=0.0)
        not_5064 = DropItemNot(source_id=42, drops=[drop])
        encoded = not_5064.encode()
        self.assertTrue(encoded.startswith(struct.pack('<I', 42) + b'\x10'))
        self.assertEqual(len(drop.encode()), 1 + 12 + 1 + 14)


class HeadlessFlowTest(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(asyncio.wait_for(coro, 30))

    async def with_server(self, scenario, role='game'):
        server = BootstrapServer(port=0, role=role,
                                 log_path=Path(TMP.name) / 'wire.jsonl',
                                 key_path=Path(TMP.name) / 'rsa.key')
        await server.start()
        port = server.server.sockets[0].getsockname()[1]
        client = HeadlessClient(port=port)
        try:
            return await scenario(client)
        finally:
            await client.close()
            server.server.close()
            await server.server.wait_closed()

    def test_lobby_and_selection(self):
        async def scenario(client):
            out = await lobby_flow(client)
            client.send_event(2012, create_request('Headless'))
            _, created = await client.expect_event(2013)
            self.assertEqual(struct.unpack_from('<I', created)[0], 0)
            char_id = struct.unpack_from('<Q', created, 10)[0]  # u32 result (4B) + varuint+sliders (6B) -> u64 id
            self.assertEqual(created[18], 1)  # level
            self.assertEqual(created[19], 1)  # knight
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, out[2007] = await client.expect_event(2007)
            return out

        out = self.run_async(self.with_server(scenario))
        for opcode in (2403, 2002, 2022, 5029, 2009, 2007):
            self.assertEqual(struct.unpack_from('<I', out[opcode])[0], 0, opcode)
        # 5134: 6 raw bytes, IPv4 network order + u16 LE port (verified live).
        self.assertEqual(out[5134], bytes([127, 0, 0, 1]) + struct.pack('<H', relay.RELAY_PORT))

    def test_town_and_tutorial_opcodes(self):
        async def scenario(client):
            await client.connect()
            # Friend list 2131 -> 2132
            client.send_event(2131)
            _, ack2132 = await client.expect_event(2132)
            self.assertEqual(struct.unpack_from('<I', ack2132)[0], 0)

            # Opcode 2569 -> 2570
            client.send_event(2569)
            _, ack2570 = await client.expect_event(2570)
            self.assertEqual(struct.unpack_from('<I', ack2570)[0], 0)

            # Clear tutorial 2082 -> 2083 (triggers Scene 9)
            client.send_event(2082, struct.pack('<iB', 0x7fffffff, 0))
            _, ack2083 = await client.expect_event(2083)
            self.assertEqual(struct.unpack_from('<I', ack2083)[0], 0)

            # Tutorial quest start 2346 -> 2347
            client.send_event(2346)
            _, ack2347 = await client.expect_event(2347)
            self.assertEqual(struct.unpack_from('<I', ack2347)[0], 0)

            # Taming monster insert 2348 -> 2349
            client.send_event(2348)
            _, ack2349 = await client.expect_event(2349)
            self.assertEqual(struct.unpack_from('<I', ack2349)[0], 0)

            # Taming monster delete 2350 -> 2351
            client.send_event(2350)
            _, ack2351 = await client.expect_event(2351)
            self.assertEqual(struct.unpack_from('<I', ack2351)[0], 0)

            # Roulette info 2390 -> 2391
            client.send_event(2390)
            _, ack2391 = await client.expect_event(2391)
            self.assertEqual(struct.unpack_from('<I', ack2391)[0], 0)
            self.assertEqual(len(ack2391), 25)

            # Back to square 5045 -> 5046 (handler 0x7897F0)
            client.send_event(5045, struct.pack('<i', 0x7fffffff))
            _, ack5046 = await client.expect_event(5046)
            result, square_uid, layer = struct.unpack_from('<IQQ', ack5046)
            self.assertEqual((result, square_uid), (0, 1))
            self.assertEqual(layer >> 32, hashing.jhash('Act1'))
            self.assertEqual(ack5046[20:22], b'\x10\x80')  # tag + varuint 0: empty vecTargetState
            self.assertEqual(len(ack5046), 22 + 1 + 8)

            # Join layer 5030 -> 5031: observed request i32, u64 layer, u8
            layer = hashing.jhash('Act1') << 32
            client.send_event(5030, struct.pack('<iQB', 0x7fffffff, layer, 0))
            _, ack5031 = await client.expect_event(5031)
            self.assertEqual(struct.unpack_from('<IQQ', ack5031), (0, 1, layer))
            self.assertEqual(ack5031[20:22], b'\x10\x80')  # vector tag, not u8 0

            # Town requests (schemas from tools/extract_schemas.py)
            client.send_event(5124)
            _, ack5125 = await client.expect_event(5125)
            self.assertEqual(ack5125, struct.pack('<I', 0) + b'\x10\x80')
            client.send_event(2065, struct.pack('<iI', 0x7fffffff, 0xbf1dbbc6))
            _, ack2066 = await client.expect_event(2066)
            self.assertEqual(ack2066, struct.pack('<Ii', 0, -0x40e2443a) + b'\x10\x80\x10\x80')
            # Quest start 2073 (compressed like the client) -> 2074
            stamp = '2015-02-23 15:42:11, '.encode('utf-16le')
            req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', hashing.jhash('Q0001S01'), -1)
            client.send_event(2073, req, compressed=True)
            _, ack2074 = await client.expect_event(2074)
            result, qid, quid = struct.unpack_from('<Iiq', ack2074)
            self.assertEqual((result, qid & 0xffffffff, quid), (0, hashing.jhash('Q0001S01'), 1))
            self.assertEqual(len(ack2074), 16 + 18 + 2)
            client.send_event(2076, req, compressed=True)
            _, ack2077 = await client.expect_event(2077)
            self.assertEqual(struct.unpack_from('<Ii', ack2077)[1] & 0xffffffff, hashing.jhash('Q0001S01'))
            self.assertEqual(len(ack2077), 12 + 18 + 12 + 2 + 2 + 8)
            client.send_event(2119, bytes.fromhex('ffffff7f01001080'))  # observed live
            _, ack2120 = await client.expect_event(2120)
            self.assertEqual(ack2120, struct.pack('<I', 0) + bytes.fromhex('01001080'))
            # Dungeon entry: room list 2010 -> 2011, create room 5001 -> 5002
            client.send_event(2010, bytes.fromhex('ffffff7f00000000012543f6f0ffffffffffff'))
            _, ack2011 = await client.expect_event(2011)
            self.assertEqual(len(ack2011), 4 + 1 + 4 + 2 + 4)
            client.send_event(5001, bytes.fromhex(
                '965f00730069006e0067006c00650070006c0061007900ffffffffffffffffffff0100'))
            _, ack5002 = await client.expect_event(5002)
            self.assertEqual(struct.unpack_from('<Iq', ack5002), (0, 1))
            self.assertEqual(ack5002[-6:], bytes([127, 0, 0, 1]) + struct.pack('<H', relay.RELAY_PORT))
            # 5043 SELECT_DUNGEON (observed live after 5002) -> 5044 echoes the gate id.
            client.send_event(5043, bytes.fromhex('ffffff7f8e41006300740031005f0047003100'))
            _, ack5044 = await client.expect_event(5044)
            self.assertEqual(ack5044, bytes.fromhex('00000000 1780 1380 8e')
                             + 'Act1_G1'.encode('utf-16le') + bytes.fromhex('1380'))
            # 5009 CHANGE_MAPCODE (observed live on the gate map) -> 5010.
            client.send_event(5009, bytes.fromhex(
                'ffffff7f9641006300740031005f00470031005f0041003100300000'))
            _, ack5010 = await client.expect_event(5010)
            self.assertEqual(ack5010, bytes.fromhex('00000000 96')
                             + 'Act1_G1_A10'.encode('utf-16le') + bytes([0]))
            # 5014 success reader 0x7880A0: u16, u32, untagged J-wstring,
            # three maps, then a mandatory vector (0x78836B).
            client.send_event(5013, bytes.fromhex(
                'ffffff7f9641006300740031005f00470031005f00410031003000'))  # observed live
            _, ack5014 = await client.expect_event(5014)
            self.assertEqual(ack5014, bytes.fromhex('00000000 0000 00000000 96')
                             + 'Act1_G1_A10'.encode('utf-16le')
                             + bytes.fromhex('1780 1780 1780 1080'))

            # Dungeon notifications / requests observed after 5014:
            # 5095: eERC_CHANGE_DUNGEON_LAYER_NOT (layer 4, jhash('Act1_G1_A10'))
            client.send_event(5095, bytes.fromhex('ffffff7f0400000046cdad32'))
            # 2422: eEGS_ACTIVE_WARFLAG_REQ (warflag 31)
            client.send_event(2422, bytes.fromhex('ffffff7f1f000000'))
            # 2358: eEGS_GUIDE_BEGINNER_UPDATE_REQ
            client.send_event(2358, bytes.fromhex('ffffff7f108101000000'))
            # 5063: eERC_MONSTER_DEAD_REQ (monster id 100, overkill 0)
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, 100, 0))

            # 2406: eEGS_CHAR_VERIFY_STAT_REQ -> 2407
            client.send_event(2406, bytes.fromhex('ffffff7f0000000010801080621ac3412811ea41b802414088b60e400ad7233cffffffff'))
            _, ack2407 = await client.expect_event(2407)
            self.assertEqual(struct.unpack_from('<i', ack2407)[0], 0)

            # 5093: eERC_GAMEPLAY_DIE_CHAR_REQ -> 5094
            client.send_event(5093, struct.pack('<q?iii', 0, True, 50, 0, 500))
            _, ack5094 = await client.expect_event(5094)
            res, from_uid, to_uid, bDie, dmg, hp, max_hp, die_cnt, coins = struct.unpack_from('<iqq?iiiHH', ack5094)
            self.assertEqual((res, bDie, hp, max_hp, coins), (0, True, 0, 500, 5))

            # 2448: eEGS_DAILY_REBIRTH_COIN_USE_REQ -> 2449
            client.send_event(2448, bytes.fromhex('ffffff7f00'))
            _, ack2449 = await client.expect_event(2449)
            res, daily_cnt, pcbang = struct.unpack_from('<iHI', ack2449)
            self.assertEqual((res, daily_cnt, pcbang), (0, 1, 5))

            # 2028: eEGS_CLOSE_BAG_REQ
            client.send_event(2028, struct.pack('<iq', 0x7fffffff, 2))

            # Ensure character has an item to drag
            from darkblood.games.state import selected_character
            chars = session.GameSession.store().characters('OfflinePlayer')
            if chars:
                char = chars[0]
                char['items'] = [dict(code='AbodT1N', uid=1, container=1, slot=0)]
                selected_character['id'] = char['id']
                session.GameSession.store().save()

            # 2036: eEGS_DRAG_ITEM_REQ -> 2037
            client.send_event(2036, struct.pack('<qqi', 1, 2, 0))
            _, ack2037 = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', ack2037)[0], 0)
            self.assertEqual(ack2037[4], 0x10)  # tag 0x10 vector

            # 5090: eERC_CHOICE_REWARD_PARTYRANK_REQ -> 5091
            client.send_event(5090, struct.pack('<ii', 0x7fffffff, 0))
            _, ack5091 = await client.expect_event(5091)
            self.assertEqual(struct.unpack_from('<iq', ack5091)[:2], (0, char['id']))

            # 2044: eEGS_ASSIGN_QUICKSLOT_REQ -> 2045
            client.send_event(2044, struct.pack('<BBiq', 0, 1, 12345, 1))
            _, ack2045 = await client.expect_event(2045)
            self.assertEqual(struct.unpack_from('<iBBiq', ack2045), (0, 0, 1, 12345, 1))

            # 2042: eEGS_EQUIP_ITEM_REQ -> 2043
            client.send_event(2042, struct.pack('<qi', 1, 0))
            _, ack2043 = await client.expect_event(2043)
            self.assertEqual(struct.unpack_from('<i', ack2043)[0], 0)

            # 2038: eEGS_USE_ITEM_REQ -> 2039
            client.send_event(2038, struct.pack('<qi', 1, 1))
            _, ack2039 = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039)[0], 0)


            client.send_event(2344, bytes.fromhex('ffffff7f00000000aeaf985f'))  # observed live
            _, ack2345 = await client.expect_event(2345)
            self.assertEqual(struct.unpack_from('<IQQ', ack2345), (0, hashing.jhash('Act1') << 32, 1))
            client.send_event(2369)
            _, ack2370 = await client.expect_event(2370)
            self.assertEqual(ack2370, b'\x00' * 16)

            # NPC first meet 2094 -> 2095
            client.send_event(2094, struct.pack('<iI', 0x7fffffff, 0xeaec51bd))
            _, ack2095 = await client.expect_event(2095)
            self.assertEqual(struct.unpack_from('<II', ack2095), (0, 0xeaec51bd))

        self.run_async(self.with_server(scenario))

    def test_quest_completion_persists(self):
        quest = hashing.jhash('Q0001S01')
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest, -1)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Quester'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, first = await client.expect_event(2410)
            client.send_event(2073, req, compressed=True)
            await client.expect_event(2074)
            client.send_event(2076, req, compressed=True)
            await client.expect_event(2077)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, second = await client.expect_event(2410)
            return first, second

        first, second = self.run_async(self.with_server(scenario))
        self.assertEqual(first, b'\x13\x80\x00')  # empty set, bWeekly false
        self.assertEqual(second, b'\x13\x81' + struct.pack('<I', quest) + b'\x00')

    def test_quest_rewards_from_client_dict(self):
        from darkblood.games.game_data import client_dict
        # Minimal fixture in the unluac layout of Data/Dict/quest_act1.lua.
        dict_dir = Path(TMP.name) / 'lua_src' / 'data' / 'dict'
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
            client.send_event(2012, create_request('Rewarded'))
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
        self.assertEqual(char['u62'], 13 + 150)
        self.assertIn('Ibaga0004', [i['code'] for i in char['items']])

    def test_active_quest_restored_in_select_ack(self):
        quest = hashing.jhash('Q0002S01')
        stamp = 'x'.encode('utf-16le')
        req = jser.varuint(len(stamp)) + stamp + struct.pack('<Ii', quest, -1)
        entry = (b'\x0f' + struct.pack('<I', quest) + struct.pack('<qqI?', 1, 0, quest, True)
                 + jser.varuint(0))

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Active'))
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

    def test_thief_creation_and_selection(self):
        async def scenario(client):
            out = await lobby_flow(client)
            # Create Thief (char_class = 4)
            client.send_event(2012, create_request('ThiefTester', char_class=4))
            _, created = await client.expect_event(2013)
            self.assertEqual(struct.unpack_from('<I', created)[0], 0)
            # Layout: u32 result (4B), varuint+sliders (6B), u64 id (8B), u8 level (1B), u8 char_class (1B)
            self.assertEqual(created[18], 1)  # level must be 1
            self.assertEqual(created[19], 4)  # class must be Thief (4)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            # Select the Thief character
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<I', ack2007)[0], 0)
            return ack2007

        ack = self.run_async(self.with_server(scenario))
        self.assertIsNotNone(ack)

    def test_relay_handshake_without_welcome(self):
        async def scenario(client):
            await client.connect()
            client.send_event(2131)
            try:
                payload = await asyncio.wait_for(client.expect(0x02), 0.5)
            except asyncio.TimeoutError:
                payload = None
            return payload

        self.assertIsNone(self.run_async(self.with_server(scenario, role='relay')))


if __name__ == '__main__':
    unittest.main()
