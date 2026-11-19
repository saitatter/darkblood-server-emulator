"""Steam cash shop offline: 2712 -> unsolicited 2037 with the items + 2714."""
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games import session
from darkblood.games.game_data import cash_shop, client_dict


class CashShopFlowTest(ServerTestCase):
    def test_steam_init_buy_grants_items(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        path = root / 'cash_shop.tsv'
        cash_shop.load_catalog.cache_clear()
        self.addCleanup(cash_shop.load_catalog.cache_clear)
        with patch.object(cash_shop, 'CATALOG_PATH', path):
            self.assertEqual(cash_shop.load_catalog()[288], ('IRanCashEtc232', 1))
        cash_shop.load_catalog.cache_clear()

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Buyer', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Live 2712 body: prefix, SteamID, vector<u32> {288}.
            purchase = bytes.fromhex('ffffff7f0100000001001001108120010000')
            with patch.object(cash_shop, 'DEFAULT_CATALOG_PATH', root / 'missing.tsv'):
                client.send_event(2712, purchase)
                _, ack = await client.expect_event(2714)
                self.assertEqual(struct.unpack_from('<I', ack)[0], 24)

            path.write_text('product_id\titem_code\tquantity\n288\tIRanCashEtc232\t0\n', encoding='utf-8')
            client.send_event(2712, purchase)
            _, ack = await client.expect_event(2714)
            self.assertEqual(struct.unpack_from('<I', ack)[0], 24)

            path.write_text('product_id\titem_code\tquantity\n288\tIRanCashEtc232\t2\n', encoding='utf-8')
            client.send_event(2712, purchase[:-4] + struct.pack('<I', 99999))
            _, ack = await client.expect_event(2714)
            self.assertEqual(struct.unpack_from('<I', ack)[0], 442)

            with patch('darkblood.games.handlers.commerce.free_bag_slots', return_value=0):
                client.send_event(2712, purchase)
                _, ack = await client.expect_event(2714)
                self.assertEqual(struct.unpack_from('<I', ack)[0], 67)

            client.send_event(2712, purchase)
            _, items = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', items)[0], 0)
            self.assertEqual(items[4:6], b'\x10\x81')
            _, ack = await client.expect_event(2714)
            self.assertEqual(ack, struct.pack('<I', 0) + b'\x10\x80' + b'\x00\x01')

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIn(('IRanCashEtc232', 2), [(i['code'], i.get('count', 1)) for i in char['items']])

        with patch.object(cash_shop, 'CATALOG_PATH', path), \
             patch.dict(os.environ, DARKBLOOD_CLIENT_DATA=str(root)):
            self.run_async(self.with_server(scenario))

    def test_cash_package_opens_into_bag(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        path = dict_dir / 'item_cash.lua'
        # Shapes copied from the client's item_cash.lua (LoadItem / LoadPackage).
        path.write_text(chr(10).join([
            'assert(DictItem:LoadItem({', '  {', '    AdjValue = "PACKAGE9",', '    ItemID = "CPkgTest",',
            '    Type = 36,', '  }', '}), "DictItem:LoadItem")',
            'assert(DictItem:LoadPackage({', '  {', '    GroupID = "PACKAGE9",', '    ItemID = {',
            '      {', '        "Ihppa0000",', '        2,', '        0', '      },',
            '      {', '        "Imppa0000",', '        1,', '        0', '      }', '    }', '  }',
            '}), "DictItem:LoadPackage")', '']), encoding='utf-8')
        for fn in (client_dict.cash_items, client_dict.cash_packages):
            fn.cache_clear()
            self.addCleanup(fn.cache_clear)
        self.addCleanup(path.unlink)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Opener', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            bag = next(b['bag_id'] for b in char['bags'] if b['bag_id'] != 1)
            filler = [dict(code='Ihppa0000', uid=60 + s, container=bag, slot=s) for s in range(1, 5)]
            char['items'] = [dict(code='CPkgTest', uid=50, container=bag, slot=0)] + filler
            session.GameSession.store().save()

            # A full bag gets JERI_INVEN_05 (67, "Not enough space in inventory."),
            # not 1 (JERI_NO_EXIST_CHAR, "Unavailable character.").
            client.send_event(2038, struct.pack('<iqi', 0x7fffffff, 50, 1))
            _, ack = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 67)
            client.send_event(2038, struct.pack('<iqi', 0x7fffffff, 999, 1))
            _, ack = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 63)  # JERI_INVEN_01
            for item in filler:
                char['items'].remove(item)
            session.GameSession.store().save()

            # Live 2038 shape: prefix + i64 uid + i32 count.
            client.send_event(2038, struct.pack('<iqi', 0x7fffffff, 50, 1))
            _, ack = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
            _, items = await client.expect_event(2037)
            self.assertEqual(items[4:6], bytes.fromhex('1082'))
            codes = sorted(i['code'] for i in char['items'])
            self.assertEqual(codes, ['Ihppa0000', 'Imppa0000'])

        self.run_async(self.with_server(scenario))

    def test_monster_card_requests_get_empty_lists(self):
        async def scenario(client):
            await lobby_flow(client)
            for request, response, expected in ((2601, 2602, bytes.fromhex('10801780')),
                                                (2608, 2609, bytes.fromhex('1080')),
                                                (2617, 2618, bytes.fromhex('1080'))):
                client.send_event(request)
                _, ack = await client.expect_event(response)
                self.assertEqual(ack, struct.pack('<I', 0) + expected)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
