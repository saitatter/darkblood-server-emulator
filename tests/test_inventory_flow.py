"""Tests for item movement, usage, discarding, bag management, quickslots and skill learning."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.games import session
from darkblood.games.network.messages import (
    DeleteTradeItemReq, DepotLoadArReq, DepotSaveArReq, InsertTradeItemReq, ModifySkillSpeechReq,
    UseLearnSkillItemReq,
)


class InventoryFlowTest(ServerTestCase):
    def test_drag_onto_same_material_merges_stacks(self):
        from darkblood.games.entities.items import UPDATE_OWNER, Item

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Stacker', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            bag = next(b['bag_id'] for b in char['bags'] if b['bag_id'] != 1)
            char['items'] = [
                dict(code='IMnr20N', uid=30, container=bag, slot=1),
                dict(code='IMnr20N', uid=31, container=bag, slot=0),
                dict(code='IRid1Cash46', uid=40, container=bag, slot=2, count=8),
                dict(code='IRid1Cash46', uid=41, container=bag, slot=3, count=5),
                dict(code='IbagU160', uid=50, container=bag, slot=4),
            ]
            session.GameSession.store().save()

            # Ore onto ore (stack 1000): one stack of 2, the source cell is cleared.
            client.send_event(2036, struct.pack('<qqi', 31, bag, 1))
            _, ack = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
            ore = next(i for i in char['items'] if i['uid'] == 30)
            self.assertEqual((ore['slot'], ore['count']), (1, 2))
            self.assertFalse(any(i['uid'] == 31 for i in char['items']))
            self.assertIn(Item(owner=UPDATE_OWNER, **ore).encode(), ack)
            self.assertIn(Item(owner=UPDATE_OWNER, uid=0, code='', container=bag, slot=0, count=0).encode(), ack)

            # Stack limit 10: 5 onto 8 fills it to 10 and leaves 3 in place.
            client.send_event(2036, struct.pack('<qqi', 41, bag, 2))
            _, ack = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
            counts = {i['uid']: (i['slot'], i.get('count', 1)) for i in char['items']}
            self.assertEqual((counts[40], counts[41]), ((2, 10), (3, 3)))

            # A full stack, or a different code, still swaps.
            client.send_event(2036, struct.pack('<qqi', 41, bag, 2))
            await client.expect_event(2037)
            counts = {i['uid']: (i['slot'], i.get('count', 1)) for i in char['items']}
            self.assertEqual((counts[40], counts[41]), ((3, 10), (2, 3)))

        self.run_async(self.with_server(scenario))

    def test_shared_depot_ar_saves_both_balances_in_one_transaction(self):
        from unittest.mock import patch

        async def scenario(client):
            await lobby_flow(client)
            ids = []
            for name in ('DepotHolder', 'DepotVisitor'):
                client.send_event(2012, create_request(name))
                _, created = await client.expect_event(2013)
                ids.append(struct.unpack_from('<Q', created, 10)[0])
            holder_id, visitor_id = ids
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, visitor_id))
            await client.expect_event(2007)

            store = session.GameSession.store()
            visitor = store.get('OfflinePlayer', visitor_id)
            holder = store.get('OfflinePlayer', holder_id)
            visitor['gold'] = 1000
            accounts = [('OfflinePlayer', visitor_id), ('OfflinePlayer', holder_id)]
            with patch.object(store, 'save_chars', wraps=store.save_chars) as save_chars:
                client.send_event(2228, DepotSaveArReq(depot_uid=holder_id, gold=400).encode())
                _, deposit = await client.expect_event(2229)
                self.assertEqual(struct.unpack_from('<qqq', deposit, 7), (holder_id, 400, 600))
                save_chars.assert_called_once_with(accounts)
                save_chars.reset_mock()

                client.send_event(2230, DepotLoadArReq(depot_uid=holder_id, gold=100).encode())
                _, withdrawal = await client.expect_event(2231)
                self.assertEqual(struct.unpack_from('<qqq', withdrawal, 7), (holder_id, 300, 700))
                save_chars.assert_called_once_with(accounts)
            self.assertEqual((visitor['gold'], holder['depot_gold']), (700, 300))

        self.run_async(self.with_server(scenario))

    def test_inventory_and_skill_operations(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('InvHero', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Populate items on character
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char['items'] = [
                dict(code='AbodT1N', uid=1, container=1, slot=0, count=10),
                dict(code='AbodT1N', uid=2, container=3, slot=1, count=5),
            ]
            char['sp'] = 7
            char['gold'] = 500
            session.GameSession.store().save()

            # 1. Drag item (2036 -> 2037)
            client.send_event(2036, struct.pack('<qqi', 1, 3, 0))
            _, ack2037 = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', ack2037)[0], 0)
            self.assertEqual(ack2037[4], 0x10)  # tag 0x10 vector

            # 2. Equip item (2042 -> 2043)
            client.send_event(2042, struct.pack('<iqi', 0x7FFFFFFF, 1, -1))  # live form: prefix + uid + slot
            _, ack2043 = await client.expect_event(2043)
            self.assertEqual(struct.unpack_from('<i', ack2043)[0], 0)

            # 2b. Unequip item via right click (2042 -> 2043)
            client.send_event(2042, struct.pack('<iqi', 0x7FFFFFFF, 1, -1))  # live form: prefix + uid + slot
            _, ack2043_unequip = await client.expect_event(2043)
            self.assertEqual(struct.unpack_from('<i', ack2043_unequip)[0], 0)
            self.assertEqual(char['items'][0]['container'], 3)

            from darkblood.games.network.messages import AssignQuickslotReq

            client.send_event(2044, AssignQuickslotReq(slot_type=0, slot_num=5, ref_id=101, ref_uid=-1).encode())
            await client.expect_event(2045)
            self.assertIn('0:5', char['quickslots'])
            client.send_event(2044, AssignQuickslotReq(slot_type=0, slot_num=5, ref_id=-1, ref_uid=-1).encode())
            _, cleared = await client.expect_event(2045)
            self.assertEqual(struct.unpack_from('<i', cleared)[0], 0)
            self.assertNotIn('0:5', char['quickslots'])

            # 3. Use item (2038 -> 2039)
            client.send_event(2038, struct.pack('<iqi', 0x7fffffff, 1, 1))
            _, ack2039 = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039)[0], 0)

            # 4. Discard item (2040 -> 2041)
            client.send_event(2040, struct.pack('<iqi', 0x7fffffff, 2, 2))
            _, ack2041 = await client.expect_event(2041)
            self.assertEqual(struct.unpack_from('<iqi', ack2041), (0, 2, 2))

            # 5. Switch bag (2030 -> 2031)
            client.send_event(2030, struct.pack('<HH', 0, 1))
            _, ack2031 = await client.expect_event(2031)
            self.assertEqual(struct.unpack_from('<iHH', ack2031), (0, 0, 1))

            # 6. Close bag (2028 -> 2029)
            client.send_event(2028, struct.pack('<iq', 0x7fffffff, 2))
            await client.expect_event(2029)

            # 7. Assign quickslot (2044 -> 2045)
            # Live body: prefix + type 1, slot 1, ref 0x19a, ref_uid -1.
            client.send_event(2044, bytes.fromhex('ffffff7f01019a010000ffffffffffffffff'))
            _, ack2045 = await client.expect_event(2045)
            self.assertEqual(struct.unpack_from('<iBBiq', ack2045), (0, 1, 1, 0x19a, -1))
            # Item bar slot 1 must not overwrite skill bar slot 1.
            client.send_event(2044, bytes.fromhex('ffffff7f0001') + struct.pack('<iq', 0x1234, 2))
            await client.expect_event(2045)
            # Both come back on the next selection (2007 vector 0x4B2C30).
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            for entry in ((1, 1, 0x19a, -1), (0, 1, 0x1234, 2)):
                self.assertIn(struct.pack('<BBiq?qH', *entry, False, 0, 0xFFFF), ack2007)

            # 8. Switch quickslot (2046 -> 2047), live form: prefix + type 1,
            # from 1, to 2. The skill in slot 1 moves to slot 2.
            client.send_event(2046, bytes.fromhex('ffffff7f010102'))
            _, ack2047 = await client.expect_event(2047)
            self.assertEqual(struct.unpack_from('<iBBB', ack2047), (0, 1, 1, 2))
            slots = session.GameSession.store().get('OfflinePlayer', char_id)['quickslots']
            self.assertEqual((slots['1:2']['slot'], slots['1:2']['ref_id']), (2, 0x19a))
            self.assertNotIn('1:1', slots)
            self.assertIn('0:1', slots)  # the item bar is untouched

            # 9. Learn skill (2050 -> 2051)
            client.send_event(2050, struct.pack('<HB', 101, 2))
            _, ack2051 = await client.expect_event(2051)
            self.assertEqual(struct.unpack_from('<iHBiq', ack2051)[:3], (0, 101, 2))

            # 9b. Learn skill list (2697 -> 2698)
            req_2697 = bytes.fromhex('ffffff7f10830f0500010ffb00010f230001')
            client.send_event(2697, req_2697)
            _, ack2698 = await client.expect_event(2698)
            self.assertEqual(struct.unpack_from('<i', ack2698[:4])[0], 0)
            self.assertEqual(ack2698[4], 0x17)  # map tag
            sp, gold = struct.unpack_from('<iq', ack2698[-12:])
            # Learning skill 101 to lv 2 (step 9) costs 2 SP; skills 5, 251, 35 at lv 1 are free (0 SP).
            self.assertEqual((sp, gold), (5, 500))

            # 9c. Bare (no 0x7FFFFFFF prefix, as after zlib decompression) multi-step 2697 batch (Issue #15 item 1)
            char['sp'] = 50
            session.GameSession.store().save_char('OfflinePlayer', char_id)
            bare_2697 = bytes.fromhex(
                '108a0fff00040fff00050fff00060f0001020f0001030f0001040f0001050f2900020f2900030f290004'
            )
            client.send_event(2697, bare_2697)
            _, ack2698_bare = await client.expect_event(2698)
            self.assertEqual(struct.unpack_from('<i', ack2698_bare[:4])[0], 0)
            self.assertEqual(char['skills']['255'], 6)
            self.assertEqual(char['skills']['256'], 5)
            self.assertEqual(char['skills']['41'], 4)

            # 10. Change bag property (2048 -> 2049)
            client.send_event(2048, struct.pack('<qB', 2, 3))
            _, ack2049 = await client.expect_event(2049)
            self.assertEqual(struct.unpack_from('<iqB', ack2049), (0, 2, 3))

            # 11. Modify skill speech (2053 -> 2054)
            client.send_event(2053, ModifySkillSpeechReq(skill_index=101, speech='Die!').encode())
            _, ack2054 = await client.expect_event(2054)
            self.assertEqual(struct.unpack_from('<iH', ack2054), (0, 101))

            # 12. Delete skill speech (2055 -> 2056)
            client.send_event(2055, struct.pack('<H', 101))
            _, ack2056 = await client.expect_event(2056)
            self.assertEqual(struct.unpack_from('<iH', ack2056), (0, 101))

            # 13. Store buy item (2067 -> 2068)
            from darkblood.core.hashing import jhash
            from darkblood.games.network.messages import BuyItemAck
            client.send_event(2067, struct.pack('<iiH', 1, jhash('Ihppa0001') & 0x7FFFFFFF, 1))
            _, ack2068 = await client.expect_event(2068)
            self.assertEqual(struct.unpack_from('<i', ack2068)[0], 0)
            # Verify store_record item_hash, npc_id, and trailing nItemID/sItemNum (0 crashes client 0x0077E2F0)
            rec_hash = struct.unpack_from('<I', ack2068, 4)[0]
            npc_id = struct.unpack_from('<I', ack2068, 36)[0]
            self.assertEqual(npc_id, 1)
            self.assertEqual(rec_hash, jhash('Ihppa0001') & 0xFFFFFFFF)
            # Trailing 18 bytes: h32 item_id, u16 item_num, i64 pvp_point, i32 league_point
            buy_item_id, buy_item_num = struct.unpack_from('<IH', ack2068, len(ack2068) - 18)
            self.assertEqual(buy_item_id, jhash('Ihppa0001') & 0xFFFFFFFF)
            self.assertEqual(buy_item_num, 1)

            # 14. Store sell item (2069 -> 2070)
            client.send_event(2069, bytes.fromhex('ffffff7f6d03416f') + struct.pack('<qH', 1, 10))
            _, ack2070 = await client.expect_event(2070)
            self.assertEqual(struct.unpack_from('<i', ack2070)[0], 0)

            # 15. Store repurchase item (2071 -> 2072)
            client.send_event(2071, struct.pack('<q', 1))
            _, ack2072 = await client.expect_event(2072)
            self.assertEqual(struct.unpack_from('<i', ack2072)[0], 0)

            # 16. Change bag name (2032 -> 2033)
            bname = 'Storage'.encode('utf-16le') + b'\x00\x00'
            client.send_event(2032, struct.pack('<q', 2) + bname)
            _, ack2033 = await client.expect_event(2033)
            self.assertEqual(struct.unpack_from('<iq', ack2033), (0, 2))

            # 17. Update skill locked (2117 -> 2118)
            client.send_event(2117, struct.pack('<h?', 101, True))
            _, ack2118 = await client.expect_event(2118)
            self.assertEqual(struct.unpack_from('<ih?', ack2118), (0, 101, True))

            # 18. Durability repair (2145 -> 2146)
            client.send_event(2145, b'\x17\x80')
            _, ack2146 = await client.expect_event(2146)
            self.assertEqual(struct.unpack_from('<i', ack2146)[0], 0)

            # 19. Item upgrade (2115 -> 2116)
            client.send_event(2115, struct.pack('<qqq', 1, 2, 0))
            _, ack2116 = await client.expect_event(2116)
            self.assertNotEqual(struct.unpack_from('<i', ack2116)[0], 0)

            # 20. Buy life water (2086 -> 2087)
            client.send_event(2086, struct.pack('<?', True))
            _, ack2087 = await client.expect_event(2087)
            self.assertEqual(struct.unpack_from('<i?', ack2087), (0, True))

            # 21. Contract update (2121 -> 2122)
            client.send_event(2121, struct.pack('<i', 10))
            _, ack2122 = await client.expect_event(2122)
            self.assertEqual(struct.unpack_from('<ii', ack2122), (0, 10))

            # 22. Durability change (2143 -> 2144)
            client.send_event(2143, b'\x17\x80')
            _, ack2144 = await client.expect_event(2144)
            self.assertEqual(struct.unpack_from('<i', ack2144)[0], 0)

            # 23. Request trade (5069 -> 5070)
            client.send_event(5069, struct.pack('<q', 777))
            _, ack5070 = await client.expect_event(5070)
            self.assertEqual(struct.unpack_from('<iq', ack5070[:12]), (0, 777))

            # 24. Accept request trade (5071 -> 5072)
            client.send_event(5071, struct.pack('<q', 777))
            _, ack5072 = await client.expect_event(5072)
            self.assertEqual(struct.unpack_from('<iq', ack5072[:12]), (0, 777))

            # 25. Insert trade item (5075 -> 5076)
            client.send_event(5075, InsertTradeItemReq(item_uid=1, slot=0).encode())
            _, ack5076 = await client.expect_event(5076)
            self.assertEqual(struct.unpack_from('<i', ack5076)[0], 0)

            # 26. Delete trade item (5077 -> 5078)
            client.send_event(5077, DeleteTradeItemReq(item_uid=1).encode())
            _, ack5078 = await client.expect_event(5078)
            self.assertEqual(struct.unpack_from('<i', ack5078)[0], 0)

            # 27. Update trade gold (5079 -> 5080)
            client.send_event(5079, struct.pack('<q', 2500))
            _, ack5080 = await client.expect_event(5080)
            self.assertEqual(struct.unpack_from('<i', ack5080)[0], 0)

            # 28. Accept trade (5081 -> 5082)
            client.send_event(5081, b'')
            _, ack5082 = await client.expect_event(5082)
            self.assertEqual(struct.unpack_from('<i', ack5082)[0], 0)

            # 29. Finally accept trade (5083 -> 5084)
            client.send_event(5083, b'')
            _, ack5084 = await client.expect_event(5084)
            self.assertEqual(struct.unpack_from('<i', ack5084)[0], 0)

            # 30. Cancel trade (5073 -> 5074)
            client.send_event(5073, b'')
            _, ack5074 = await client.expect_event(5074)
            self.assertEqual(struct.unpack_from('<i', ack5074)[0], 0)

            # 31. Magic enchant (2254 -> 2255)
            client.send_event(2254, struct.pack('<qq', 1, 2))
            _, ack2255 = await client.expect_event(2255)
            self.assertEqual(struct.unpack_from('<i', ack2255)[0], 0)

            # 32. Magic enchant erase option (2256 -> 2257)
            client.send_event(2256, struct.pack('<qi', 1, 0))
            _, ack2257 = await client.expect_event(2257)
            self.assertEqual(struct.unpack_from('<i', ack2257)[0], 0)

            # 33. Magic enchant expend slot (2258 -> 2259)
            client.send_event(2258, struct.pack('<qq', 1, 2))
            _, ack2259 = await client.expect_event(2259)
            self.assertEqual(struct.unpack_from('<i', ack2259)[0], 0)

            # 34. Random item upgrade (2284 -> 2285)
            client.send_event(2284, struct.pack('<qq', 1, 2))
            _, ack2285 = await client.expect_event(2285)
            self.assertEqual(struct.unpack_from('<i', ack2285)[0], 0)

            # 35. Fix item upgrade (2672 -> 2673)
            client.send_event(2672, struct.pack('<qq', 1, 2))
            _, ack2673 = await client.expect_event(2673)
            self.assertEqual(struct.unpack_from('<i', ack2673)[0], 0)

            # 36. Item spirit change (2338 -> 2339)
            client.send_event(2338, struct.pack('<qq', 1, 2))
            _, ack2339 = await client.expect_event(2339)
            self.assertEqual(struct.unpack_from('<i', ack2339)[0], 0)

            # 37. Avatar zam insert (2362 -> 2363)
            client.send_event(2362, struct.pack('<qq', 10, 20))
            _, ack2363 = await client.expect_event(2363)
            self.assertEqual(struct.unpack_from('<i', ack2363[:4])[0], 0)

            # 38. Avatar zam erase (2364 -> 2365)
            client.send_event(2364, struct.pack('<qi', 10, 0))
            _, ack2365 = await client.expect_event(2365)
            self.assertEqual(struct.unpack_from('<i', ack2365[:4])[0], 0)

            # 39. Use arena sp item (2709 -> 2710)
            client.send_event(2709, struct.pack('<q', 30))
            _, ack2710 = await client.expect_event(2710)
            self.assertEqual(struct.unpack_from('<i', ack2710[:4])[0], 0)

            # 40. Divide item (2250 -> 2251)
            client.send_event(2250, struct.pack('<qqih', 1, 0, 5, 2))
            _, ack2251 = await client.expect_event(2251)
            self.assertEqual(struct.unpack_from('<i', ack2251[:4])[0], 0)

            # 41. Use learn skill item (2111 -> 2112)
            client.send_event(2111, UseLearnSkillItemReq(item_uid=1, skill_id=105).encode())
            _, ack2112 = await client.expect_event(2112)
            self.assertEqual(struct.unpack_from('<i', ack2112[:4])[0], 0)

            # 42. Depot save AR (2228 -> 2229)
            from darkblood.games.session import GameSession
            from darkblood.games.entities.items import DEPOT_CONTAINER
            char_for_depot = GameSession.store().get('OfflinePlayer', char_id)
            char_for_depot['gold'] = 25000
            char_for_depot['depot_gold'] = 0
            client.send_event(2228, DepotSaveArReq(depot_uid=char_id, gold=10000).encode())
            _, ack2229 = await client.expect_event(2229)
            self.assertEqual(struct.unpack_from('<i', ack2229[:4])[0], 0)
            # mapCurDepotAr (tag 0x17, count 1, 0x0f, i64 char_id, i64 10000) + i64 remaining player gold (15000)
            self.assertEqual(ack2229[4:7], b'\x17\x81\x0f')
            self.assertEqual(struct.unpack_from('<qqq', ack2229, 7), (char_id, 10000, 15000))

            # 43. Depot load AR (2230 -> 2231)
            client.send_event(2230, DepotLoadArReq(depot_uid=char_id, gold=4000).encode())
            _, ack2231 = await client.expect_event(2231)
            self.assertEqual(struct.unpack_from('<i', ack2231[:4])[0], 0)
            self.assertEqual(ack2231[4:7], b'\x17\x81\x0f')
            self.assertEqual(struct.unpack_from('<qqq', ack2231, 7), (char_id, 6000, 19000))

            # 43b. Drag item from bag into depot (to_container = char_id) and back to bag
            bag_item = next(i for i in char_for_depot['items'] if i.get('container') == 3)
            bag_item_uid = bag_item['uid']
            client.send_event(2036, struct.pack('<qqi', bag_item_uid, char_id, 0))
            _, ack2037_in = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', ack2037_in[:4])[0], 0)
            self.assertEqual(bag_item['container'], DEPOT_CONTAINER)
            self.assertEqual(bag_item['slot'], 0)

            client.send_event(2036, struct.pack('<qqi', bag_item_uid, 3, 2))
            _, ack2037_out = await client.expect_event(2037)
            self.assertEqual(struct.unpack_from('<i', ack2037_out[:4])[0], 0)
            self.assertEqual(bag_item['container'], 3)
            self.assertEqual(bag_item['slot'], 2)

            # 44. Depot share expire time get (2242 -> 2243)
            client.send_event(2242, b'')
            _, ack2243 = await client.expect_event(2243)
            self.assertEqual(struct.unpack_from('<i', ack2243)[0], 0)

            # 45. Depot slot extend (2461 -> 2462)
            client.send_event(2461, struct.pack('<qh', 1, 0))
            _, ack2462 = await client.expect_event(2462)
            self.assertEqual(struct.unpack_from('<ihq', ack2462[:14]), (0, 0, 30 * 86400))

            from darkblood.games.progression import refresh_depot_timers

            renter = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertIn('depot_extend_expires', renter)
            expires_at = renter['depot_extend_expires'][0]
            self.assertTrue(refresh_depot_timers(renter, now=expires_at - 60))
            self.assertEqual(renter['depot_extend_remain'][0], 60)
            self.assertTrue(refresh_depot_timers(renter, now=expires_at))
            self.assertEqual(renter['depot_extend_remain'][0], 0)

            # 46. Durability loss (2143 -> 2144), AR repair (2145 -> 2146), and repair-by-item (2154 -> 2146)
            from darkblood.games.network.messages import (
                DurabilityChangeAck, DurabilityChangeReq, DurabilityRepairAck,
                DurabilityRepairByItemReq, DurabilityRepairReq,
            )
            from darkblood.games.session import GameSession
            char = GameSession.store().get('OfflinePlayer', char_id)
            char['gold'] = 5000
            target_item = {'uid': 777, 'code': 'Abodk0002', 'container': 1, 'slot': 2, 'durability': 20.0}
            char.setdefault('items', []).append(target_item)
            item_uid = 777
            # Prefixed 2143 lowering durability to 5.0 (not broken)
            client.send_event(2143, DurabilityChangeReq(durabilities={item_uid: 5.0}).encode())
            _, ack2144 = await client.expect_event(2144)
            parsed2144 = DurabilityChangeAck.decode(ack2144)
            self.assertEqual((parsed2144.result, parsed2144.changed_item_uids), (0, []))
            self.assertAlmostEqual(target_item['durability'], 5.0, places=3)
            # Bare 2143 (without 0x7FFFFFFF prefix) breaking durability to 0.0 -> reported in changed_item_uids
            client.send_event(2143, DurabilityChangeReq(durabilities={item_uid: 0.0}).encode()[4:])
            _, ack2144_broken = await client.expect_event(2144)
            parsed2144_broken = DurabilityChangeAck.decode(ack2144_broken)
            self.assertEqual((parsed2144_broken.result, parsed2144_broken.changed_item_uids), (0, [item_uid]))
            self.assertAlmostEqual(target_item['durability'], 0.0, places=3)
            # Refusing a repair should report the currency problem and leave durability alone.
            from darkblood.games.network import results

            char['gold'] = 0
            client.send_event(2145, DurabilityRepairReq(repair_items={item_uid: 0.0}).encode())
            _, refused_repair = await client.expect_event(2146)
            self.assertEqual(refused_repair, struct.pack('<i', results.NOT_ENOUGH_AR))
            self.assertEqual((char['gold'], target_item['durability']), (0, 0.0))
            char['gold'] = 5000

            # 2145 repair with AR -> restores integer max durability and deducts exact RepairPrice * missing
            from darkblood.games.game_data.client_dict import item_field, item_max_durability
            client.send_event(2145, DurabilityRepairReq(repair_items={item_uid: 0.0}).encode())
            _, ack2146 = await client.expect_event(2146)
            parsed2146 = DurabilityRepairAck.decode(ack2146)
            self.assertEqual(parsed2146.result, 0)
            self.assertIn(item_uid, parsed2146.repaired_items)
            expected_max = float(int(item_max_durability('Abodk0002') or 100))
            expected_cost = int(expected_max) * int(item_field('Abodk0002', 'RepairPrice', 0) or 0)
            self.assertEqual(parsed2146.repaired_items[item_uid], expected_max)
            self.assertEqual(target_item['durability'], expected_max)
            self.assertEqual(parsed2146.remain_gold, 5000 - expected_cost)
            # Fractional Lua Durability (e.g. Aglok0001 = 19.2, RepairPrice = 5) must truncate to 19.0
            # (matching client short +0xBE) so client never displays 20/19, and charge (19 - ceil(15.2)) * 5 = 15 AR.
            glove_uid = 778
            glove_item = {'uid': glove_uid, 'code': 'Aglok0001', 'container': 1, 'slot': 3, 'durability': 15.2}
            char['items'].append(glove_item)
            gold_pre_glove = char['gold']
            client.send_event(2145, DurabilityRepairReq(repair_items={glove_uid: 15.2}).encode())
            _, ack2146_glove = await client.expect_event(2146)
            parsed_glove = DurabilityRepairAck.decode(ack2146_glove)
            self.assertEqual(parsed_glove.result, 0)
            self.assertEqual(parsed_glove.repaired_items[glove_uid], 19.0)
            self.assertEqual(glove_item['durability'], 19.0)
            self.assertEqual(parsed_glove.remain_gold, gold_pre_glove - (19 - 16) * 5)
            # 2154 repair by item -> restores durability without deducting AR
            target_item['durability'] = 1.0
            gold_before = char['gold']
            client.send_event(2154, DurabilityRepairByItemReq(repair_items={item_uid: 1.0}, repair_item_uid=999999).encode())
            _, refused_kit = await client.expect_event(2146)
            self.assertEqual(DurabilityRepairAck.decode(refused_kit).result, results.INVEN_ITEM_NOT_FOUND)
            self.assertEqual(target_item['durability'], 1.0)
            self.assertEqual(char['gold'], gold_before)

            kit = dict(uid=779, code='IDur1R338', container=3, slot=0, count=1)
            char['items'].append(kit)
            client.send_event(2154, DurabilityRepairByItemReq(repair_items={item_uid: 1.0}, repair_item_uid=779).encode())
            _, ack2146_kit = await client.expect_event(2146)
            parsed2146_kit = DurabilityRepairAck.decode(ack2146_kit)
            self.assertEqual((parsed2146_kit.result, parsed2146_kit.remain_gold), (0, gold_before))
            self.assertGreater(target_item['durability'], 1.0)
            self.assertNotIn(kit, char['items'])

            # 47. Extended skills sweep: 2152 show cooltime, 2302/2303 readjust quality,
            #     2384/2385 init proficiency, 2579/2580 dual skill switch, plus 2577/2578/2280 encodings.
            from darkblood.games.network.messages import (
                DualSkillActiveNot, DualSkillChangeIndexReq, DualSkillExpireNot,
                InitProficiencyReq, InitSkillNot, ReadjustQualityReq, SkillUpdateShowCoolTimeReq,
            )
            client.send_event(2152, SkillUpdateShowCoolTimeReq(skill_index=101, show_cooltime=True).encode())
            client.send_event(2302, ReadjustQualityReq(target_item_uid=item_uid, material_item_uid=999999).encode())
            _, ack2303 = await client.expect_event(2303)
            self.assertEqual(struct.unpack_from('<i', ack2303[:4])[0], 0)
            self.assertIn(101, char.get('skill_show_cooltime', []))

            client.send_event(2384, InitProficiencyReq(item_uid=999999, pf_index=2).encode())
            _, ack2385 = await client.expect_event(2385)
            self.assertEqual(struct.unpack_from('<iq', ack2385[:12]), (0, 999999))

            # Switch to Dual Skill page 1, then back to page 0 (preserving page 0 skills)
            char['skills'] = {'101': 2}
            char['sp'] = 15
            client.send_event(2579, DualSkillChangeIndexReq(dual_skill_index=1).encode())
            _, ack2580_1 = await client.expect_event(2580)
            self.assertEqual(struct.unpack_from('<i', ack2580_1[:4])[0], 0)
            self.assertEqual(char['dual_skill_index'], 1)
            self.assertEqual(char['skills'], {})

            client.send_event(2579, DualSkillChangeIndexReq(dual_skill_index=0).encode())
            _, ack2580_0 = await client.expect_event(2580)
            self.assertEqual(struct.unpack_from('<i', ack2580_0[:4])[0], 0)
            self.assertEqual(char['dual_skill_index'], 0)
            self.assertEqual(char['skills'], {'101': 2})
            self.assertEqual(char['sp'], 15)

            # Verify wire notifications 2577, 2578, 2280 encode cleanly
            self.assertEqual(DualSkillExpireNot(cur_dual_skill_index=0).encode(), b'\x00\x00')
            self.assertEqual(len(DualSkillActiveNot(extend_time=86400, add_day=30, cur_dual_skill_index=1, item_id=1).encode()), 16)
            self.assertEqual(struct.unpack_from('<ii', InitSkillNot(result=0, sp=20, skills={}).encode(), 0), (0, 20))

            # Use Dual Skill Activation Order (IDSk1Cash269, 30 days) -> 2039 + 2578 DualSkillActiveNot
            ds_uid = max((i.get('uid', 0) for i in char.get('items', [])), default=0) + 1
            char.setdefault('items', []).append({
                'uid': ds_uid, 'code': 'IDSk1Cash269', 'container': 1, 'slot': 19, 'count': 1,
            })
            client.send_event(2038, struct.pack('<iqI', 0x7fffffff, ds_uid, 1))
            _, ack2039_ds = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039_ds, 0)[0], 0)
            _, not2578 = await client.expect_event(2578)
            ds_not = DualSkillActiveNot.decode(not2578)
            self.assertEqual(ds_not.add_day, 30)
            self.assertEqual(ds_not.extend_time, 30 * 86400)
            self.assertEqual(ds_not.cur_dual_skill_index, 0)
            self.assertGreater(char.get('dual_skill_expire', 0), 0)

            # 48. Extended quests sweep: 2098 alimi tracker, 2090/2091 discard, 2126/2127 tag,
            #     2177/2178 act kairo, 2496/2497 making kairo, 2728/2729 npc seal, 5382/5383 quest item drop.
            from darkblood.games.network.messages import (
                ActKairoReq, GetQuestTagReq, NpcMakingKairoReq, NpcSealItemReq,
                QuestAlimiChangeNot, QuestDiscardReq, QuestItemDropReq,
            )
            char.setdefault('quests_active', {})['123456'] = {'uid': 9, 'tracked': True, 'counters': []}
            client.send_event(2098, QuestAlimiChangeNot(quest_id=123456, tracked=False).encode())
            client.send_event(2126, GetQuestTagReq().encode())
            _, ack2127 = await client.expect_event(2127)
            self.assertEqual(struct.unpack_from('<i', ack2127[:4])[0], 0)
            self.assertFalse(char['quests_active']['123456']['tracked'])

            client.send_event(2090, QuestDiscardReq(timestamp='2026-11-21', quest_id=123456).encode())
            _, ack2091 = await client.expect_event(2091)
            self.assertEqual(struct.unpack_from('<i', ack2091[:4])[0], 0)
            self.assertNotIn('123456', char['quests_active'])

            client.send_event(2177, ActKairoReq(kairo_id='KairoTest', param=-1).encode())
            _, ack2178 = await client.expect_event(2178)
            self.assertEqual(struct.unpack_from('<i', ack2178[:4])[0], 0)

            client.send_event(2496, NpcMakingKairoReq(kairo_id='MakingTest').encode())
            _, ack2497 = await client.expect_event(2497)
            self.assertEqual(struct.unpack_from('<i', ack2497[:4])[0], 0)

            client.send_event(2728, NpcSealItemReq(item_uid=item_uid).encode())
            _, ack2729 = await client.expect_event(2729)
            self.assertEqual(struct.unpack_from('<i', ack2729[:4])[0], 0)

            client.send_event(5382, QuestItemDropReq(mission_id=0x11223344, layer_id=1, pos_x=10.0, pos_y=20.0, jump=True).encode())
            _, ack5383 = await client.expect_event(5383)
            self.assertEqual(struct.unpack_from('<iIi', ack5383[:12]), (0, 0x11223344, 1))

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()


class SkillCostTest(ServerTestCase):
    def test_learning_charges_skill_points(self):
        import os
        from pathlib import Path
        from darkblood.games.game_data import client_dict
        dict_dir = Path(os.environ['DARKBLOOD_CLIENT_DATA']) / 'lua_src' / 'data' / 'dict'
        dict_dir.mkdir(parents=True, exist_ok=True)
        path = dict_dir / 'skill.lua'
        # Entry shape copied from the client's skill.lua (NameIndex as "005" or 254).
        entries = [('"005"', 1, 0), ('"005"', 2, 2), ('254', 1, 1)]
        path.write_text('assert(DictSkill:LoadSkill({\n' + ''.join(
            '  {\n    DemandAr = 0,\n    DemandPoint = %d,\n    Lv = %d,\n    NameIndex = %s,\n  },\n'
            % (sp, lv, idx) for idx, lv, sp in entries) + '}), "DictSkill:LoadSkill")\n', encoding='utf-8')
        client_dict.skill_costs.cache_clear()
        self.addCleanup(client_dict.skill_costs.cache_clear)
        self.addCleanup(path.unlink)
        self.assertEqual(client_dict.skill_learn_cost(5, 0, 2), (2, 0))

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Learner', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char['sp'] = 3
            session.GameSession.store().save()

            # skill 5 -> level 2 (0 + 2 SP) and skill 254 -> level 1 (1 SP)
            body = bytes.fromhex('ffffff7f') + b'\x10\x82' + b'\x0f' + struct.pack('<HB', 5, 2) \
                + b'\x0f' + struct.pack('<HB', 254, 1)
            client.send_event(2697, body)
            _, ack = await client.expect_event(2698)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 0)
            self.assertEqual(struct.unpack_from('<i', ack, len(ack) - 12)[0], 0)

            # A level the skill already has costs nothing, even with 0 SP left.
            client.send_event(2050, struct.pack('<HB', 5, 2))
            _, ack = await client.expect_event(2051)
            self.assertEqual(struct.unpack_from('<i', ack)[0], 0)  # already level 2: free
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            self.assertEqual(char['sp'], 0)
            self.assertEqual(char['skills'].get('5'), 2)
            self.assertEqual(char['skills'].get('254'), 1)
            self.assertEqual(
                {k: v for k, v in char['skills'].items() if int(k) < 9000},
                {'5': 2, '254': 1},
            )

            # SP reaches the client at login (details u32 array +0x51).
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertIn(b'\x82' + struct.pack('<II', 0, 0), ack2007)

        self.run_async(self.with_server(scenario))

    def test_use_dyeing_item_replies_and_consumes_the_dye(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('DyeHero', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char['items'].append(dict(code='IdyeS1Cash4', uid=40, container=3, slot=17))
            session.GameSession.store().save()

            # Live 2210 body for a skin dye (target -1, color 0xFF945A4C).
            client.send_event(2210, bytes.fromhex('2800000000000000ffffffffffffffff0000ffffffff4c5a94ff00'))
            _, ack2211 = await client.expect_event(2211)
            self.assertEqual(struct.unpack_from('<iHiI', ack2211), (0, 0, -1, 0xFF945A4C))
            self.assertEqual(ack2211[14:16], b'\x10\x81')  # one item update: the emptied dye slot
            self.assertFalse(any(i['uid'] == 40 for i in char['items']))
            self.assertEqual(char['skin_dye'], [0, -1, 0xFF945A4C])
            # The skin dye comes back on the next selection (details +0x71).
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertIn(struct.pack('<HiI', 0, 0, 0) + struct.pack('<HiI', 0, -1, 0xFF945A4C), ack2007)

            # Unknown dye item -> JERI_INVEN_01 (63).
            client.send_event(2210, bytes.fromhex('2800000000000000ffffffffffffffff0000ffffffff4c5a94ff00'))
            _, ack2211 = await client.expect_event(2211)
            self.assertEqual(struct.unpack_from('<i', ack2211)[0], 63)

        self.run_async(self.with_server(scenario))

    def test_extended_inventory_opcodes_and_recovered_fields(self):
        from darkblood.games.network.messages import (
            AddedItemNotice, AvatarChangerReq, AvatarMergeReq, AvatarZamMergeReq,
            AvatarZamSeparateReq, BagChangeSellEnableAck, DecreaseUsageLimitNot,
            DurabilityChangeAck, DurabilityRepairAck, InventoryUpdatedNot,
            ItemClassSmeltingReq, ItemDecomposeReq, ItemDropEntry,
            MarkItemActiveNot, MarkOptionChangeReq, MarkTabActiveNot,
            NotEnoughInvenSpaceNot, RandomOptionChangeReq, RareAvatarChangeLookReq,
            SealItemReq, UseItemLeaguePointAddReq, UseSelectedSkillChangeItemReq,
        )

        # Verify recovered wire encodings for notices and formerly unmapped fields.
        drop = ItemDropEntry(drop_uid=10, item_id=0x11223344, quality=2, count=3, owner_uids=[1, 2])
        self.assertIn(struct.pack('<IIHH', 10, 0x11223344, 2, 3), drop.encode())
        self.assertEqual(DurabilityRepairAck(result=0, repaired_items={5: 80.0}, remain_gold=99).encode()[:6],
                         struct.pack('<iB', 0, 0x17) + b'\x81')
        self.assertEqual(DurabilityChangeAck(result=0, changed_item_uids=[5, 6]).encode(),
                         struct.pack('<iBBqq', 0, 0x10, 0x82, 5, 6))
        self.assertIn(struct.pack('<IHH', 0xAABBCCDD, 1, 4),
                      InventoryUpdatedNot(added_notices=[AddedItemNotice(item_id=0xAABBCCDD, quality=1, count=4)]).encode())
        self.assertEqual(NotEnoughInvenSpaceNot(item_ids=[0x1234]).encode(), struct.pack('<BBI', 0x10, 0x81, 0x1234))
        self.assertEqual(BagChangeSellEnableAck(result=0, bag_uid=7, enabled=True).encode(), struct.pack('<iq?', 0, 7, True))
        self.assertEqual(MarkItemActiveNot(base_count=3, bonus_count=1).encode(), struct.pack('<HH', 3, 1))
        self.assertEqual(MarkTabActiveNot(active_mark=True).encode(), struct.pack('<?', True))
        self.assertEqual(DecreaseUsageLimitNot(group_id=0x55, usage_count=2).encode(), struct.pack('<IH', 0x55, 2))

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('ExtInv', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char['items'] = [
                dict(code='AbodT1N', uid=10, container=3, slot=0, count=1),
                dict(code='AbodT1N', uid=11, container=3, slot=1, count=1),
                dict(code='Ihppa0000', uid=12, container=3, slot=2, count=2),
            ]
            char['bags'].append(dict(bag_id=50, code='Ibaga0004', b28=0, b29=8, w2a=1))
            char['gold'] = 1234
            session.GameSession.store().save()

            # 2028 -> 2029 CloseBagAck (empty bag removed & returned to inventory)
            client.send_event(2028, struct.pack('<iq', 0x7fffffff, 50))
            _, ack2029 = await client.expect_event(2029)
            self.assertEqual(struct.unpack_from('<i', ack2029)[0], 0)
            self.assertFalse(any(b['bag_id'] == 50 for b in char['bags']))

            # 2147 -> 2148 SealItem
            client.send_event(2147, SealItemReq(item_uid=10).encode())
            _, ack2148 = await client.expect_event(2148)
            self.assertEqual(struct.unpack_from('<i', ack2148)[0], 0)

            # 2154 -> 2146 DurabilityRepairByItem
            client.send_event(2154, b'\x17\x80' + struct.pack('<q', 10))
            _, ack2146 = await client.expect_event(2146)
            self.assertEqual(struct.unpack_from('<i', ack2146)[0], 0)

            # 2408 -> 2409 AvatarZamMerge
            client.send_event(2408, AvatarZamMergeReq(zam1_uid=10, zam2_uid=11, catalyst_uid=12).encode())
            _, ack2409 = await client.expect_event(2409)
            self.assertEqual(struct.unpack_from('<i', ack2409)[0], 0)

            # 2428 -> 2429 UseSelectedSkillChangeItem
            client.send_event(2428, UseSelectedSkillChangeItemReq(item_uid=10, skill_index=5, skill_level=1).encode())
            _, ack2429 = await client.expect_event(2429)
            self.assertEqual(struct.unpack_from('<i', ack2429)[0], 0)

            # 2432 -> 2433 AvatarMerge
            client.send_event(2432, AvatarMergeReq(merge_item_uid=12, avatar1_uid=10, avatar2_uid=11, merge_option=0).encode())
            _, ack2433 = await client.expect_event(2433)
            self.assertEqual(struct.unpack_from('<i', ack2433)[0], 0)

            # 2543 -> 2544 AvatarChanger
            client.send_event(2543, AvatarChangerReq(changer_item_uid=12, target_avatar_uid=10, material_uid=11).encode())
            _, ack2544 = await client.expect_event(2544)
            self.assertEqual(struct.unpack_from('<i', ack2544)[0], 0)

            # 2545 -> 2546 ItemDecompose (removes item 11)
            client.send_event(2545, ItemDecomposeReq(item_uid=11).encode())
            _, ack2546 = await client.expect_event(2546)
            self.assertEqual(struct.unpack_from('<i', ack2546)[0], 0)
            self.assertFalse(any(i['uid'] == 11 for i in char['items']))

            # 2547 -> 2548 RandomOptionChange
            client.send_event(2547, RandomOptionChangeReq(item_uid=10).encode())
            _, ack2548 = await client.expect_event(2548)
            self.assertEqual(struct.unpack_from('<iq', ack2548), (0, 10))

            # 2573 -> 2574 UseItemLeaguePointAdd (consumes 1 of item 12)
            client.send_event(2573, UseItemLeaguePointAddReq(item_uid=12).encode())
            _, ack2574 = await client.expect_event(2574)
            self.assertEqual(struct.unpack_from('<i', ack2574)[0], 0)
            self.assertEqual(struct.unpack_from('<i', ack2574[-4:])[0], 100)

            # 2583 -> 2584 RareAvatarChangeLook
            client.send_event(2583, RareAvatarChangeLookReq(target_avatar_uid=10, look_item_uid=12).encode())
            _, ack2584 = await client.expect_event(2584)
            self.assertEqual(struct.unpack_from('<iq', ack2584), (0, 10))

            # 2597 -> 2598 AvatarZamSeparate
            client.send_event(2597, AvatarZamSeparateReq(target_item_uid=10, zam_id=1, use_item_id=2).encode())
            _, ack2598 = await client.expect_event(2598)
            self.assertEqual(struct.unpack_from('<i', ack2598)[0], 0)

            # 2629 -> 2630 ItemClassSmelting
            client.send_event(2629, ItemClassSmeltingReq(use_item_uid=10, get_item_id=0x1234).encode())
            _, ack2630 = await client.expect_event(2630)
            self.assertEqual(struct.unpack_from('<i', ack2630)[0], 0)

            # 2701 -> 2702 MarkOptionChange
            client.send_event(2701, MarkOptionChangeReq(target_item_uid=10, catalyst_item_uid=12).encode())
            _, ack2702 = await client.expect_event(2702)
            self.assertEqual(struct.unpack_from('<iq', ack2702), (0, 10))

        self.run_async(self.with_server(scenario))

    def test_sell_item_populates_repurchase_item_and_zero_count_tombstone(self):
        """2069 -> 2070 clears bag slot with empty cell, sets repurchase_price, and 2071 -> 2072 charges AR."""
        from darkblood.games.entities.items import Item, UPDATE_OWNER
        from darkblood.games.game_data.client_dict import item_field
        from darkblood.games.network.messages import RepurchaseItemAck, RepurchaseItemReq, SellItemAck, SellItemReq

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('ShopSeller'))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            weapon = dict(next(item for item in char['items'] if item['container'] == 1 and item['slot'] == 0))
            char['items'] = [
                dict(code='Ihppa0000', uid=77, container=3, slot=0, count=2),
            ]
            char['gold'] = 100
            session.GameSession.store().save_char('OfflinePlayer', char_id)
            sell_price = item_field('Ihppa0000', 'SellPrice', 0)

            # Partial sell (1 of 2) -> reduced count in items, repurchase_price == sell_price
            client.send_event(2069, SellItemReq(npc_id=1, item_uid=77, count=1).encode())
            _, body1 = await client.expect_event(2070)
            self.assertEqual(struct.unpack_from('<i', body1, 0)[0], 0)
            self.assertEqual(char['gold'], 100 + sell_price)
            self.assertEqual(char['items'][0]['count'], 1)

            # Final sell (last 1 -> empty cell clears bag slot, repurchase_price == sell_price)
            client.send_event(2069, SellItemReq(npc_id=1, item_uid=77, count=1).encode())
            _, body2 = await client.expect_event(2070)
            self.assertEqual(struct.unpack_from('<i', body2, 0)[0], 0)
            self.assertEqual(char['gold'], 100 + 2 * sell_price)
            self.assertEqual(len(char['items']), 0)
            # Verify empty cell (uid -1, code -1) is encoded in items[0] and repurchase_price is non-zero
            empty_cell = Item(code='', uid=-1, owner=UPDATE_OWNER, container=3, slot=0, count=0).encode()
            self.assertIn(empty_cell, body2)

            # Reopening the shop lists both sales in 2066 vecRePur (RepurchaseItem 0x00A1ECA0):
            # the last field is a two-entry vector (tag 0x10, count 2).
            client.send_event(2065, struct.pack('<iI', 0x7fffffff, 1))
            _, body2066 = await client.expect_event(2066)
            self.assertIn(bytes.fromhex('1082'), body2066)
            self.assertIn(struct.pack('<i', sell_price), body2066)

            # Repurchase the sold item (2071 -> 2072): charges sell_price AR and restores item to bag
            client.send_event(2071, RepurchaseItemReq(item_uid=77).encode())
            _, body2072 = await client.expect_event(2072)
            res2072, rep_uid = struct.unpack_from('<iq', body2072, 0)
            self.assertEqual(res2072, 0)
            self.assertEqual(rep_uid, 77)
            self.assertEqual(char['gold'], 100 + sell_price)
            self.assertEqual(len(char['items']), 1)
            self.assertEqual(char['items'][0]['code'], 'Ihppa0000')

            weapon.update(container=3, slot=1, durability=25.0, upgrade=7, quality=3)
            char['items'].append(weapon)
            client.send_event(2069, SellItemReq(npc_id=1, item_uid=weapon['uid'], count=1).encode())
            _, sale = await client.expect_event(2070)
            self.assertEqual(struct.unpack_from('<i', sale)[0], 0)
            client.send_event(2071, RepurchaseItemReq(item_uid=weapon['uid']).encode())
            _, buyback = await client.expect_event(2072)
            self.assertEqual(struct.unpack_from('<i', buyback)[0], 0)
            restored = next(item for item in char['items'] if item['code'] == weapon['code'])
            for field in ('durability', 'upgrade', 'quality'):
                self.assertEqual(restored.get(field), weapon[field], field)
            self.assertIn(Item(owner=UPDATE_OWNER, **restored).encode(), buyback)

        self.run_async(self.with_server(scenario))

    def test_repurchase_list_stays_with_the_selected_character(self):
        from darkblood.games.entities.items import Item
        from darkblood.games.network.messages import SellItemReq

        async def scenario(client):
            await lobby_flow(client)
            char_ids = []
            for name in ('SaleOwner', 'SaleSibling'):
                client.send_event(2012, create_request(name))
                _, created = await client.expect_event(2013)
                char_ids.append(struct.unpack_from('<Q', created, 10)[0])

            first, second = char_ids
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, first))
            await client.expect_event(2007)
            item = dict(code='Ihppa0000', uid=5000, count=1, container=3, slot=0)
            char = session.GameSession.store().get('OfflinePlayer', first)
            char['items'].append(item)
            client.send_event(2069, SellItemReq(npc_id=1, item_uid=5000, count=1).encode())
            await client.expect_event(2070)

            wire_item = Item(owner=0, **item).encode()
            for char_id, visible in ((first, True), (second, False), (first, True)):
                client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
                await client.expect_event(2007)
                client.send_event(2065, struct.pack('<iI', 0x7fffffff, 1))
                _, shop = await client.expect_event(2066)
                self.assertEqual(wire_item in shop, visible)

        self.run_async(self.with_server(scenario))

    def test_delete_item_refreshes_quickslots_and_clears_uid_bound_slot(self):
        """2040 -> 2041 sends an empty 2037 to refresh UI 7 (Quickslot) and clears UID-bound quickslots on full delete."""
        from darkblood.core.hashing import jhash

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('DelQsHero', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            char['items'] = [
                dict(code='Ihppa0000', uid=101, container=3, slot=0, count=5),
                dict(code='AbodT1N', uid=102, container=3, slot=1, count=1),
            ]
            session.GameSession.store().save_char('OfflinePlayer', char_id)

            # Bind stackable potion (ref_uid = -1) to slot 0 and unique armor (ref_uid = 102) to slot 1.
            potion_hash = jhash('Ihppa0000') & 0x7FFFFFFF
            armor_hash = jhash('AbodT1N') & 0x7FFFFFFF
            client.send_event(2044, struct.pack('<iBBiq', 0x7fffffff, 0, 0, potion_hash, -1))
            await client.expect_event(2045)
            client.send_event(2044, struct.pack('<iBBiq', 0x7fffffff, 0, 1, armor_hash, 102))
            await client.expect_event(2045)

            # Partial delete of potion stack: 2041 followed by empty 2037 UI refresh; quickslot stays bound.
            client.send_event(2040, struct.pack('<iqi', 0x7fffffff, 101, 2))
            _, ack2041 = await client.expect_event(2041)
            self.assertEqual(struct.unpack_from('<iqi', ack2041), (0, 101, 2))
            _, refresh2037 = await client.expect_event(2037)
            self.assertEqual(refresh2037, b'\x00\x00\x00\x00\x10\x80')
            self.assertIn('0:0', char['quickslots'])

            # Full delete of UID-bound armor: 2041 -> 2045 clear (-1, -1) -> empty 2037 refresh.
            client.send_event(2040, struct.pack('<iqi', 0x7fffffff, 102, 1))
            _, ack2041_full = await client.expect_event(2041)
            self.assertEqual(struct.unpack_from('<iqi', ack2041_full), (0, 102, 1))
            _, clear2045 = await client.expect_event(2045)
            self.assertEqual(struct.unpack_from('<iBBiq', clear2045), (0, 0, 1, -1, -1))
            _, refresh2037_full = await client.expect_event(2037)
            self.assertEqual(refresh2037_full, b'\x00\x00\x00\x00\x10\x80')
            self.assertNotIn('0:1', char['quickslots'])
            self.assertIn('0:0', char['quickslots'])

        self.run_async(self.with_server(scenario))

    def test_life_skills_base_supply_learning_relog_and_reset(self):
        """BaseSupply life skills (9005/9006/9009), 2-chosen-proficiency cap, 2007 persistence, and 2384 reset."""
        from darkblood.core.serialization.jser import varuint
        from darkblood.games.network.messages import DualSkillChangeIndexReq, InitProficiencyReq, LearnSkillReq

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('LifeHero', char_class=0))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            for sid in ('9005', '9006', '9009'):
                self.assertEqual(char['skills'].get(sid), 1)
            # 2007 carries 10-float proficiencies array at offset 5 (after u32 result + empty array 0x80)
            self.assertEqual(ack2007[:5], b'\x00\x00\x00\x00\x80')
            self.assertEqual(ack2007[5:6], varuint(10))
            self.assertEqual(struct.unpack_from('<10f', ack2007, 6), (0.0,) * 10)

            from unittest.mock import patch

            with patch('darkblood.games.handlers.skills.skill_learn_cost', return_value=(25, 0)):
                client.send_event(2050, LearnSkillReq(skill_index=9007, level=1).encode())
                _, refused = await client.expect_event(2051)
                self.assertNotEqual(struct.unpack_from('<i', refused)[0], 0)
            self.assertEqual(char.get('learned_proficiencies', []), [])
            self.assertNotIn('9007', char['skills'])

            # gathering.lua: Mining/Gathering level 1 need character level 20 (DemandLv).
            client.send_event(2050, LearnSkillReq(skill_index=9007, level=1).encode())
            _, too_low = await client.expect_event(2051)
            self.assertNotEqual(struct.unpack_from('<i', too_low)[0], 0)
            self.assertNotIn('9007', char['skills'])
            char['level'] = 20

            # Learn Mining (9007 -> prof 0) and Gathering (9008 -> prof 1)
            for sid in (9007, 9008):
                client.send_event(2050, LearnSkillReq(skill_index=sid, level=1).encode())
                _, ack2051 = await client.expect_event(2051)
                self.assertEqual(struct.unpack_from('<i', ack2051, 0)[0], 0)
            self.assertEqual(char['learned_proficiencies'], [0, 1])

            # 3rd chosen proficiency (9000 Weapon Making -> prof 2) must be rejected (client max 2)
            client.send_event(2050, LearnSkillReq(skill_index=9000, level=1).encode())
            _, ack2051_fail = await client.expect_event(2051)
            self.assertNotEqual(struct.unpack_from('<i', ack2051_fail, 0)[0], 0)
            self.assertNotIn('9000', char['skills'])

            # Update proficiency floats and relog -> 2007 encodes updated floats and learned_proficiencies=[0, 1]
            char['proficiencies'] = [12.5, 34.0] + [0.0] * 8
            session.GameSession.store().save_char('OfflinePlayer', char_id)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007_relog = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<10f', ack2007_relog, 6)[:2], (12.5, 34.0))
            # Encoded vector<u32> [0, 1] = 0x10 + varuint(2) + u32(0) + u32(1)
            self.assertIn(b'\x10' + varuint(2) + struct.pack('<II', 0, 1), ack2007_relog)

            client.send_event(2579, DualSkillChangeIndexReq(dual_skill_index=1).encode())
            await client.expect_event(2580)
            self.assertEqual(char['skills']['9007'], 1)

            # Reset Mining (pf_index=0) via 2384 -> clears prof 0, removes 9007, frees a slot for 9000
            client.send_event(2384, InitProficiencyReq(item_uid=999999, pf_index=0).encode())
            _, ack2385 = await client.expect_event(2385)
            self.assertEqual(struct.unpack_from('<i', ack2385, 0)[0], 0)
            self.assertEqual(char['learned_proficiencies'], [1])
            self.assertEqual(char['proficiencies'][0], 0.0)
            self.assertNotIn('9007', char['skills'])

            client.send_event(2579, DualSkillChangeIndexReq(dual_skill_index=0).encode())
            await client.expect_event(2580)
            self.assertNotIn('9007', char['skills'])
            self.assertEqual(char['skills']['9008'], 1)

            client.send_event(2050, LearnSkillReq(skill_index=9000, level=1).encode())
            _, ack2051_ok = await client.expect_event(2051)
            self.assertEqual(struct.unpack_from('<i', ack2051_ok, 0)[0], 0)
            self.assertEqual(char['learned_proficiencies'], [1, 2])

            # Recipe learning respects DemandAr from making.lua (e.g. 10032 Wmake33 = 64,300 AR)
            char['gold'] = 1000
            session.GameSession.store().save_char('OfflinePlayer', char_id)
            client.send_event(2050, LearnSkillReq(skill_index=10032, level=1).encode())
            _, ack2051_poor = await client.expect_event(2051)
            self.assertNotEqual(struct.unpack_from('<i', ack2051_poor, 0)[0], 0)
            self.assertNotIn('10032', char['skills'])
            self.assertEqual(char['gold'], 1000)

            char['gold'] = 100000
            session.GameSession.store().save_char('OfflinePlayer', char_id)
            client.send_event(2050, LearnSkillReq(skill_index=10032, level=1).encode())
            _, ack2051_recipe = await client.expect_event(2051)
            res, sidx, lv, rem_sp, rem_gold = struct.unpack_from('<iHBiq', ack2051_recipe, 0)
            self.assertEqual((res, sidx, lv, rem_gold), (0, 10032, 1, 100000 - 64300))
            self.assertEqual(char['gold'], 100000 - 64300)
            self.assertEqual(char['skills'].get('10032'), 1)

        self.run_async(self.with_server(scenario))
