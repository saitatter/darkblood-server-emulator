"""Monster kill (5063) grants the template's EXP through 5086."""
import os
import struct
import unittest
from pathlib import Path

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.hashing import jhash
from darkblood.games import session
from darkblood.games.game_data import client_dict

# Fields copied from the client's monster.lua entry 1npi01n0.
MONSTER_LUA = '\n'.join([
    'assert(DictMonster:LoadMonster({', '  {', '    DropCnt = 1,', '    Exp = 9.9,',
    '    ID = "1npi01n0",', '    Lv = 1,', '  }', '}), "DictMonster:LoadMonster")', ''])


class MonsterExpTest(ServerTestCase):
    def test_monster_dead_grants_exp(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        path = dict_dir / 'monster.lua'
        path.write_text(MONSTER_LUA, encoding='utf-8')
        client_dict.monsters.cache_clear()
        self.addCleanup(client_dict.monsters.cache_clear)
        self.addCleanup(path.unlink)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Hunter', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Live 5063: prefix + u32 template hash + u32 instance.
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, jhash('1npi01n0') & 0xFFFFFFFF, 0x03000fa2))
            _, exp = await client.expect_event(5086)
            total, _, _, gained = struct.unpack_from('<iiii', exp)
            self.assertEqual(gained, 10)
            self.assertEqual(total, 10)
            self.assertEqual(len(exp), 4 + 32 + 1)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['exp'], total)
            char['exp'] = client_dict.char_level_stat(1, 1)['upexp'] - 10
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, jhash('1npi01n0'), 0x03000fa3))
            _, level_up = await client.expect_event(5087)
            self.assertEqual(level_up[0], 0x82)
            self.assertEqual(struct.unpack_from('<IIqBII?', level_up, 1), (3, 3, char_id, 2, 0, 3, True))
            _, exp = await client.expect_event(5086)
            self.assertEqual(struct.unpack_from('<iiii', exp), (0, 0, 0, 10))
            self.assertEqual(char['exp'], 0)

        self.run_async(self.with_server(scenario))

    def test_monster_drop_and_pick_up(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        (dict_dir / 'monster.lua').write_text(MONSTER_LUA, encoding='utf-8')
        # Shapes copied from itemlooting.lua; probability forced to 1.
        (dict_dir / 'itemlooting.lua').write_text('\n'.join([
            'assert(DictItemDrop:LoadLootingItem({', '  {', '    LootingID = "1N_Bag",',
            '    OneItemID = "Ibaga0004",', '    ItemGroup = {}', '  }', '}), "DictItemDrop:LoadLootingItem")',
            'assert(DictItemDrop:LoadMonLooting({', '  {', '    AdjustProbByMonHP = 0,', '    DungeonID = "Act1_G1_A1",',
            '    LootingID = "1N_Bag",', '    RotateCount = 1,', '    UsuallyProb = 1', '  }',
            '}), "DictItemDrop:LoadMonLooting")', '']), encoding='utf-8')
        for fn in (client_dict.monsters, client_dict.looting):
            fn.cache_clear()
            self.addCleanup(fn.cache_clear)
        self.addCleanup((dict_dir / 'monster.lua').unlink)
        self.addCleanup((dict_dir / 'itemlooting.lua').unlink)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Looter', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            # Map code as in the live 5009 (falls back to the _A1 table).
            code = 'Act1_G1_A10'.encode('utf-16le')
            client.send_event(5009, struct.pack('<i', 0x7fffffff) + bytes([0x80 | len(code)]) + code + b'\x00')
            await client.expect_event(5010)

            client.send_event(5063, struct.pack('<iII', 0x7fffffff, jhash('1npi01n0') & 0xFFFFFFFF, 77))
            _, drop = await client.expect_event(5064)
            self.assertEqual(struct.unpack_from('<I', drop)[0], 77)
            self.assertEqual(drop[4:6], bytes.fromhex('1081'))
            drop_uid, code_hash = struct.unpack_from('<II', drop, 6)
            self.assertEqual(code_hash, jhash('Ibaga0004') & 0xFFFFFFFF)

            client.send_event(5065, struct.pack('<iI', 0x7fffffff, drop_uid))
            _, result = await client.expect_event(5068)
            self.assertEqual(struct.unpack_from('<iq', result), (0, char_id))
            _, items = await client.expect_event(2037)
            self.assertEqual(items[4:6], bytes.fromhex('1081'))
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIn('Ibaga0004', [i['code'] for i in char['items']])

        self.run_async(self.with_server(scenario))

    def test_ar_drop_adds_gold(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        (dict_dir / 'monster.lua').write_text(MONSTER_LUA, encoding='utf-8')
        # Shapes copied from itemlooting.lua / item_moneysetting.lua; probability 1.
        (dict_dir / 'itemlooting.lua').write_text('\n'.join([
            'assert(DictItemDrop:LoadLootingItem({', '  {', '    LootingID = "1N_Ar",',
            '    OneItemID = "Gmara0007",', '    ItemGroup = {}', '  }', '}), "DictItemDrop:LoadLootingItem")',
            'assert(DictItemDrop:LoadMonLooting({', '  {', '    AdjustProbByMonHP = 0,', '    DungeonID = "Act1_G1_A1",',
            '    LootingID = "1N_Ar",', '    RotateCount = 1,', '    UsuallyProb = 1', '  }',
            '}), "DictItemDrop:LoadMonLooting")', '']), encoding='utf-8')
        (dict_dir / 'item_moneysetting.lua').write_text('\n'.join([
            'assert(DictItem:LoadMoneySetting({', '  {', '    GoldMax = 40.5,', '    GoldMin = 40.2,',
            '    ItemID = "Gmara0007",', '    Name = "Gmara0000_Ar"', '  }', '}), "DictItem:LoadMoneySetting")', '']),
            encoding='utf-8')
        for fn in (client_dict.monsters, client_dict.looting, client_dict.money_drops):
            fn.cache_clear()
            self.addCleanup(fn.cache_clear)
        for name in ('monster.lua', 'itemlooting.lua', 'item_moneysetting.lua'):
            self.addCleanup((dict_dir / name).unlink)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Miser', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char['gold'] = 100
            session.GameSession.store().save()
            code = 'Act1_G1_A10'.encode('utf-16le')
            client.send_event(5009, struct.pack('<i', 0x7fffffff) + bytes([0x80 | len(code)]) + code + b'\x00')
            await client.expect_event(5010)
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, jhash('1npi01n0') & 0xFFFFFFFF, 77))
            _, drop = await client.expect_event(5064)
            drop_uid = struct.unpack_from('<I', drop, 6)[0]
            # The floor label shows the rolled AR, the same amount 5114 awards.
            self.assertEqual(struct.unpack_from('<H', drop, 16)[0], 40)

            client.send_event(5065, struct.pack('<iI', 0x7fffffff, drop_uid))
            _, note = await client.expect_event(5114)
            self.assertEqual(struct.unpack_from('<iiiq', note), (0, 40, drop_uid, char_id))
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['gold'], 140)
            self.assertNotIn('Gmara0007', [i['code'] for i in char.get('items', [])])

        self.run_async(self.with_server(scenario))

    def test_dungeon_tables_resolves_map_id_to_dungeon_id(self):
        """MapIDs like Act1_G2_B10, Act2_G2_R10, and Act1_G1_A20 resolve via dungeon_maps to their DungeonID."""
        from darkblood.games import loot
        from darkblood.games.game_data import client_dict

        mon, _, _ = client_dict.looting()
        for map_id, dungeon_id in (
            ('Act1_G2_B10', 'Act1_G2_B1'),
            ('Act2_G2_B10', 'Act2_G2_B1'),
            ('Act2_G2_R10', 'Act2_G2_R1'),
            ('Act4_G2_B10', 'Act4_G2_B1'),
            ('Act1_G1_A20', 'Act1_G1_A2'),
        ):
            self.assertIn(dungeon_id, mon)
            self.assertEqual(loot.dungeon_tables(map_id), mon[dungeon_id])

if __name__ == '__main__':
    unittest.main()
