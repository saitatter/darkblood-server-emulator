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

            from darkblood.games.entities.items import Bag
            from darkblood.games.network.messages import SwitchBagAck, SwitchBagReq

            bag_slots = {b['bag_id']: b['w2a'] for b in char['bags']}
            client.send_event(2030, SwitchBagReq(from_index=0, to_index=slot).encode())
            _, swap_body = await client.expect_event(2031)
            swap = SwitchBagAck.decode(swap_body)
            self.assertEqual((swap.result, swap.from_index, swap.to_index), (0, 0, slot))
            self.assertEqual({b['bag_id']: b['w2a'] for b in char['bags']},
                             {**bag_slots, bag: slot, 38: 0})

            client.send_event(2030, SwitchBagReq(from_index=0, to_index=4).encode())
            await client.expect_event(2031)
            moved = next(b for b in char['bags'] if b['bag_id'] == 38)
            self.assertEqual(moved['w2a'], 4)
            from darkblood.games.network.messages import ChangeBagNameReq

            bag_name = 'Potions and gems'
            client.send_event(2032, ChangeBagNameReq(bag_uid=38, name=bag_name).encode())
            _, renamed = await client.expect_event(2033)
            self.assertEqual(struct.unpack_from('<i', renamed)[0], 0)
            self.assertEqual(moved['name'], bag_name)
            self.assertIn(bag_name.encode('utf-16le'), Bag(**moved).encode())
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, selected = await client.expect_event(2007)
            self.assertIn(Bag(**moved).encode(), selected)

            # Equipping a bag from a stack leaves the other bags in inventory.
            stacked = dict(code='Ibaga0004', uid=87, container=bag, slot=17, count=3)
            char['next_item_uid'] = 100
            char['items'].append(stacked)
            client.send_event(2026, struct.pack('<iq', 0x7fffffff, 87))
            _, opened = await client.expect_event(2027)
            self.assertEqual(struct.unpack_from('<Iq', opened), (0, 87))
            remainder = [item for item in char['items'] if item.get('code') == 'Ibaga0004']
            self.assertEqual([(item['count'], item['container'], item['slot']) for item in remainder],
                             [(2, bag, 17)])
            self.assertNotEqual(remainder[0]['uid'], 87)
            _, refresh = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', refresh)[0], 0)

            # A non-bag item is refused.
            client.send_event(2026, struct.pack('<iq', 0x7fffffff, 999))
            _, ack = await client.expect_event(2027)
            self.assertNotEqual(struct.unpack_from('<I', ack)[0], 0)

        self.run_async(self.with_server(scenario))


    def test_close_bag_keeps_it_equipped_until_another_bag_has_space(self):
        from darkblood.games.network import results
        from darkblood.games.network.messages import CloseBagReq
        from darkblood.player_management.characters import add_reward_items, free_cells

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('CloseBagHero'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)

            fillers = add_reward_items(char, [('Ihppa0001', 1)] * len(free_cells(char)))
            bag = dict(bag_id=38, code='Ibaga0004', b28=0, b29=5, w2a=1)
            char['bags'].append(bag)
            close = CloseBagReq(bag_id=bag['bag_id']).encode()
            client.send_event(2028, close)
            _, blocked = await client.expect_event(2029)
            self.assertEqual(blocked, struct.pack('<i', results.INVEN_FULL))
            self.assertIn(bag, char['bags'])
            self.assertFalse(any(item['uid'] == bag['bag_id'] for item in char['items']))

            freed = fillers[-1]
            char['items'].remove(freed)
            client.send_event(2028, close)
            _, closed = await client.expect_event(2029)
            self.assertEqual(struct.unpack_from('<i', closed)[0], 0)
            self.assertNotIn(bag, char['bags'])
            returned = next(item for item in char['items'] if item['uid'] == bag['bag_id'])
            self.assertEqual((returned['container'], returned['slot']), (freed['container'], freed['slot']))

        self.run_async(self.with_server(scenario))

    def test_unequip_waits_for_space_in_any_bag(self):
        from darkblood.games.network import results
        from darkblood.games.network.messages import EquipItemReq
        from darkblood.player_management.characters import add_reward_items, free_cells

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('UnequipHero'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)

            equipped = next(item for item in char['items'] if item.get('container') == 1)
            original_slot = equipped['slot']
            char['bags'].append(dict(bag_id=38, code='Ibaga0004', b28=0, b29=5, w2a=1))
            fillers = add_reward_items(char, [('Ihppa0001', 1)] * len(free_cells(char)))
            request = EquipItemReq(item_uid=equipped['uid'], equip_slot=-1).encode()
            client.send_event(2042, request)
            _, blocked = await client.expect_event(2043)
            self.assertEqual(struct.unpack_from('<i', blocked)[0], results.INVEN_FULL)
            self.assertEqual((equipped['container'], equipped['slot']), (1, original_slot))

            freed = fillers[-1]
            self.assertEqual(freed['container'], 38)
            char['items'].remove(freed)
            client.send_event(2042, request)
            _, moved = await client.expect_event(2043)
            self.assertEqual(struct.unpack_from('<i', moved)[0], 0)
            self.assertEqual((equipped['container'], equipped['slot']), (38, freed['slot']))

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
