"""Equip a bag item: 2026 eEGS_OPEN_BAG_REQ -> 2027 eEGS_OPEN_BAG_ACK."""
import os
import struct
import unittest
from pathlib import Path

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.hashing import jhash
from darkblood.games import session
from darkblood.games.game_data import client_dict

# Entry shape copied from the client's item_disposable.lua (Ibaga0004).
BAG_LUA = '\n'.join([
    'assert(DictItem:LoadItem({', '  {', '    BagSize = 5,', '    BuyPrice = 50,',
    '    ItemID = "Ibaga0004",', '    SellPrice = 10', '  }', '}), "DictItem:LoadItem")', ''])


class BagFlowTest(ServerTestCase):
    def test_open_bag_equips_bag_item(self):
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        path = dict_dir / 'item_disposable.lua'
        path.write_text(BAG_LUA, encoding='utf-8')
        client_dict.item_int_fields.cache_clear()
        self.addCleanup(client_dict.item_int_fields.cache_clear)
        self.addCleanup(path.unlink)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Bagger', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            used = {b.get('w2a') for b in char['bags']}
            bag = next(b['bag_id'] for b in char['bags'] if b['bag_id'] != 1)
            char['items'].append(dict(code='Ibaga0004', uid=38, container=bag, slot=17))
            session.GameSession.store().save()

            # Live body: prefix + i64 bag item uid.
            client.send_event(2026, bytes.fromhex('ffffff7f2600000000000000'))
            _, ack = await client.expect_event(2027)
            result, bag_id, code = struct.unpack_from('<IqI', ack)
            self.assertEqual((result, bag_id, code), (0, 38, jhash('Ibaga0004')))
            # empty J-wstring, u8 page, u8 capacity, u16 UI slot
            page, size, slot = struct.unpack_from('<BBH', ack, 17)
            self.assertEqual((page, size), (0, 5))
            self.assertNotIn(slot, used)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertNotIn(38, [i['uid'] for i in char['items']])
            self.assertIn(38, [b['bag_id'] for b in char['bags']])

            # A non-bag item is refused.
            client.send_event(2026, struct.pack('<iq', 0x7fffffff, 999))
            _, ack = await client.expect_event(2027)
            self.assertNotEqual(struct.unpack_from('<I', ack)[0], 0)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
