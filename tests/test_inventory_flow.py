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

            # 3. Use item (2038 -> 2039)
            client.send_event(2038, struct.pack('<qi', 1, 1))
            _, ack2039 = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<i', ack2039)[0], 0)

            # 4. Discard item (2040 -> 2041)
            client.send_event(2040, struct.pack('<qi', 2, 2))
            _, ack2041 = await client.expect_event(2041)
            self.assertEqual(struct.unpack_from('<iqi', ack2041), (0, 2, 2))

            # 5. Switch bag (2030 -> 2031)
            client.send_event(2030, struct.pack('<HH', 0, 1))
            _, ack2031 = await client.expect_event(2031)
            self.assertEqual(struct.unpack_from('<iHH', ack2031), (0, 0, 1))

            # 6. Close bag (2028: fire and forget)
            client.send_event(2028, struct.pack('<iq', 0x7fffffff, 2))

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
            client.send_event(2067, struct.pack('<iiH', 1, 99999, 1))
            _, ack2068 = await client.expect_event(2068)
            self.assertEqual(struct.unpack_from('<i', ack2068)[0], 0)

            # 14. Store sell item (2069 -> 2070)
            client.send_event(2069, bytes.fromhex('ffffff7f6d03416f') + struct.pack('<qH', 1, 1))
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
            client.send_event(2254, struct.pack('<qqq', 1, 2, 0))
            _, ack2255 = await client.expect_event(2255)
            self.assertEqual(struct.unpack_from('<i', ack2255)[0], 0)

            # 32. Magic enchant erase option (2256 -> 2257)
            client.send_event(2256, struct.pack('<q', 1))
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
            client.send_event(2364, struct.pack('<q', 10))
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
            client.send_event(2228, DepotSaveArReq(gold=10000).encode())
            _, ack2229 = await client.expect_event(2229)
            self.assertEqual(struct.unpack_from('<i', ack2229[:4])[0], 0)

            # 43. Depot load AR (2230 -> 2231)
            client.send_event(2230, DepotLoadArReq(gold=5000).encode())
            _, ack2231 = await client.expect_event(2231)
            self.assertEqual(struct.unpack_from('<i', ack2231[:4])[0], 0)

            # 44. Depot share expire time get (2242 -> 2243)
            client.send_event(2242, b'')
            _, ack2243 = await client.expect_event(2243)
            self.assertEqual(struct.unpack_from('<i', ack2243)[0], 0)

            # 45. Depot slot extend (2461 -> 2462)
            client.send_event(2461, struct.pack('<qh', 1, 5))
            _, ack2462 = await client.expect_event(2462)
            self.assertEqual(struct.unpack_from('<ihq', ack2462[:14]), (0, 5, 0))

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
            self.assertEqual(char['skills'], {'5': 2, '254': 1})

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
