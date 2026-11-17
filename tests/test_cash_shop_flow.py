"""Steam cash shop offline: 2712 -> unsolicited 2037 with the items + 2714."""
import os
import struct
import unittest
from pathlib import Path

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games import session
from darkblood.games.game_data import client_dict

# Entry copied from the client's item_cash.lua (product 288).
PRODUCT_LUA = '\n'.join([
    'assert(DictCash:LoadProductList({', '  {', '    Best = 0,', '    Ggroup = 0,',
    '    ItemCount = 1,', '    ItemID = "IRanCashEtc232",', '    New = 0,', '    OnSell = 1,',
    '    Price = 2,', '    ProductID = 288,', '    Recommend = 22,', '    Sgroup = 4', '  }',
    '}), "DictCash:LoadProductList")', ''])


class CashShopFlowTest(ServerTestCase):
    def test_steam_init_buy_grants_items(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        path = dict_dir / 'item_cash.lua'
        path.write_text(PRODUCT_LUA, encoding='utf-8')
        client_dict.cash_products.cache_clear()
        self.addCleanup(client_dict.cash_products.cache_clear)
        self.addCleanup(path.unlink)
        self.assertEqual(client_dict.cash_products()[288], ('IRanCashEtc232', 1, 2.0))

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Buyer', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Live 2712 body: prefix, SteamID, vector<u32> {288}.
            client.send_event(2712, bytes.fromhex('ffffff7f0100000001001001108120010000'))
            _, items = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', items)[0], 0)
            self.assertEqual(items[4:6], b'\x10\x81')
            _, ack = await client.expect_event(2714)
            self.assertEqual(ack, struct.pack('<I', 0) + b'\x10\x80' + b'\x00\x01')

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIn('IRanCashEtc232', [i['code'] for i in char['items']])

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
