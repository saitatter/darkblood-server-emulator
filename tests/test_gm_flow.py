"""Tests for native GM console cheats (eEGS_CHEAT_* / eERC_CHEAT_*) and gm_mode auth level."""
from __future__ import annotations

import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow, wide
from darkblood.core import options
from darkblood.core.hashing import jhash
from darkblood.games.game_data import client_dict
from darkblood.games.network import messages


def _welcome_auth_level(body: bytes, account: str = 'OfflinePlayer') -> int:
    # 5020 layout: <IQ (12B) + wide(account) + <II???Q -> auth_level is second u32
    offset = 12 + len(wide(account)) + 4
    return struct.unpack_from('<I', body, offset)[0]


class GmFlowTest(ServerTestCase):
    def test_gm_mode_sets_welcome_auth_level(self):
        async def scenario(client):
            out = await lobby_flow(client)
            self.assertEqual(_welcome_auth_level(out[5020]), 1)

        self.run_async(self.with_server(scenario))

    def test_gm_mode_disabled_clears_welcome_auth_level(self):
        orig_get = options.get

        def patched_get(key, *args, **kwargs):
            if key == 'gm_mode':
                return False
            return orig_get(key, *args, **kwargs)

        async def scenario(client):
            out = await lobby_flow(client)
            self.assertEqual(_welcome_auth_level(out[5020]), 0)

        options.get = patched_get
        try:
            self.run_async(self.with_server(scenario))
        finally:
            options.get = orig_get

    def test_gm_console_cheat_opcodes(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('GameMaster'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # 2057 -> 2058 + 5087 (lv)
            client.send_event(2057, messages.CheatLevelUpReq(target_level=20).encode())
            _, ack2058 = await client.expect_event(2058)
            self.assertEqual(struct.unpack_from('<I', ack2058, 0)[0], 0)
            await client.expect_event(5087)

            # 2059 -> 2060 (itemdrop)
            client.send_event(2059, messages.CheatItemDropReq(item_id=12345).encode())
            _, ack2060 = await client.expect_event(2060)
            self.assertEqual(messages.CheatItemDropAck.decode(ack2060).result, 0)

            # 2061 -> 2062 (allskill)
            client.send_event(2061, messages.CheatLearnAllSkillReq().encode())
            _, ack2062 = await client.expect_event(2062)
            self.assertEqual(messages.CheatLearnAllSkillAck.decode(ack2062).result, 0)

            # 2063 -> 2064 (skill)
            client.send_event(2063, messages.CheatLearnSkillReq(skill_id=101, skill_level=5).encode())
            _, ack2064 = await client.expect_event(2064)
            self.assertEqual(messages.CheatLearnSkillAck.decode(ack2064).result, 0)

            # 2088 -> 2089 (generic GM cheat router)
            cheat_data = messages.CheatPleaseData(
                char_uid=char_id, cheat_index=3, str_arg1='hello', int_arg1=77
            )
            client.send_event(2088, messages.CheatPleaseReq(cheat=cheat_data).encode())
            _, ack2089 = await client.expect_event(2089)
            parsed2089 = messages.CheatPleaseAck.decode(ack2089)
            self.assertEqual(parsed2089.result, 0)
            self.assertEqual(parsed2089.cheat.cheat_index, 3)
            self.assertEqual(parsed2089.cheat.str_arg1, 'hello')
            self.assertEqual(parsed2089.cheat.int_arg1, 77)

            # 2099 -> 2074 (queststart), 2093 -> 2077 (questclear), 2096 -> 2097 (questreset)
            client.send_event(2099, messages.CheatQuestStartReq(quest_id=9001).encode())
            _, ack2074 = await client.expect_event(2074)
            self.assertEqual(struct.unpack_from('<I', ack2074, 0)[0], 0)

            client.send_event(2093, messages.CheatQuestCompleteReq(quest_id=9001).encode())
            _, ack2077 = await client.expect_event(2077)
            self.assertEqual(struct.unpack_from('<I', ack2077, 0)[0], 0)

            client.send_event(2096, messages.CheatQuestResetReq().encode())
            _, ack2097 = await client.expect_event(2097)
            self.assertEqual(messages.CheatQuestResetAck.decode(ack2097).result, 0)

            # 2101 -> 2102 + 2286 (coin)
            client.send_event(2101, messages.CheatInsertCoinReq(coins=10).encode())
            _, ack2102 = await client.expect_event(2102)
            res2102, total_coins = struct.unpack_from('<Ih', ack2102, 0)
            self.assertEqual(res2102, 0)
            self.assertGreaterEqual(total_coins, 10)
            await client.expect_event(2286)

            # 2103 -> 2104 (ar)
            client.send_event(2103, messages.CheatInsertArReq(amount=50000).encode())
            _, ack2104 = await client.expect_event(2104)
            res2104, cur_ar = struct.unpack_from('<Iq', ack2104, 0)
            self.assertEqual(res2104, 0)
            self.assertGreaterEqual(cur_ar, 50000)

            # 2105 -> 2106 (ap)
            client.send_event(2105, messages.CheatInsertApReq(amount=250).encode())
            _, ack2106 = await client.expect_event(2106)
            self.assertEqual(struct.unpack_from('<I', ack2106, 0)[0], 0)

            # 2137 -> 2138 (itemcall) with a real item from client_dict
            sample_code = next(iter(client_dict.item_int_fields().keys()))
            client.send_event(2137, messages.CheatItemCallReq(item_id=jhash(sample_code), count=1).encode())
            _, ack2138 = await client.expect_event(2138)
            self.assertEqual(struct.unpack_from('<I', ack2138, 0)[0], 0)

            # 2107 -> 2108 (clearbag)
            client.send_event(2107, messages.CheatDeleteAllInvenItemReq().encode())
            _, ack2108 = await client.expect_event(2108)
            self.assertEqual(struct.unpack_from('<I', ack2108, 0)[0], 0)

            # 2123 -> 2116 (forceupgrade)
            client.send_event(2123, messages.CheatItemUpgradeReq(upg_item_uid=0).encode())
            _, ack2116 = await client.expect_event(2116)
            self.assertEqual(struct.unpack_from('<I', ack2116, 0)[0], 0)

            # 2124 -> 2125 (promotion)
            client.send_event(2124, messages.CheatPromotionReq(target_job=2).encode())
            _, ack2125 = await client.expect_event(2125)
            parsed2125 = messages.CheatPromotionAck.decode(ack2125)
            self.assertEqual(parsed2125.result, 0)
            self.assertEqual(parsed2125.job, 2)

            # 2130 -> 2023 (stress)
            client.send_event(2130, messages.CheatChangeStressReq(stress=100, stress_pcb=50, stress_week=200).encode())
            _, not2023 = await client.expect_event(2023)
            self.assertEqual(messages.StressChangedNot.decode(not2023).stress, 100)

            # 2141 -> 2142 (quality)
            client.send_event(2141, messages.CheatChangeItemQualityReq(item_uid=0, quality=3).encode())
            _, ack2142 = await client.expect_event(2142)
            self.assertEqual(struct.unpack_from('<I', ack2142, 0)[0], 0)

            # Extended guild / pet / card / explore / broker cheats
            pairs = [
                (2170, messages.CheatGuildFalloutFinishReq(), 2171),
                (2194, messages.CheatGuildDismissalFinishReq(), 2195),
                (2197, messages.CheatGuildAddPointReq(points=100), 2198),
                (2199, messages.CheatGuildLevelReq(level=5), 2200),
                (2212, messages.CheatGuildAllSkillInitReq(), 2213),
                (2232, messages.CheatDepotSizeIncreaseReq(), 2233),
                (2238, messages.CheatProficiencyChangeReq(prof_type=1, value=50.0), 2239),
                (2488, messages.CheatPetSatietyReq(satiety=100, is_cash_food=False), 2489),
                (2490, messages.CheatPetEvolutionReq(pet_id=10, param=0), 2491),
                (2624, messages.CheatMonsterCardClearReq(), 2625),
                (2660, messages.CheatExploreCompleteReq(char_uid=char_id), 2661),
                (2687, messages.CheatGuildBrokerExitReq(), 2688),
                (2689, messages.CheatGuildBrokerRewardReq(), 2690),
                (2691, messages.CheatChangeValidGuildCountReq(count=1), 2692),
                (5262, messages.CheatSecondPassDeleteReq(), 5263),
            ]
            for req_op, req_msg, ack_op in pairs:
                client.send_event(req_op, req_msg.encode())
                _, ack_body = await client.expect_event(ack_op)
                self.assertEqual(struct.unpack_from('<I', ack_body, 0)[0], 0, f'op {req_op}->{ack_op}')

            # Fire-and-forget cheat notifications/requests
            client.send_event(2512, messages.CheatTitleGetAllReq().encode())
            client.send_event(2514, messages.CheatTitleChangeReq(title_id=1).encode())
            client.send_event(2522, messages.CheatAchieveCompleteReq(achieve_id=1).encode())
            client.send_event(2627, messages.CheatIndulgenceTimeChangeReq(time_val=3600).encode())
            client.send_event(5129, messages.CheatSummonRequestNot(target_nick='Hero', pos_x=1.0, pos_y=2.0).encode())
            client.send_event(5252, messages.CheatForceItemDropNot(item_id=1234).encode())
            # Verify connection is still alive after fire-and-forget cheats
            client.send_event(2096, messages.CheatQuestResetReq().encode())
            _, ack2097_2 = await client.expect_event(2097)
            self.assertEqual(messages.CheatQuestResetAck.decode(ack2097_2).result, 0)

        self.run_async(self.with_server(scenario))

    def test_rune_slate_unlock_and_itemcall_issue26(self):
        from darkblood.games.entities.character import Character

        # Lv 60 character encodes bActiveMark=True, sBaseCnt=5, sBonusCnt=0 in world details.
        details60 = Character.from_dict({'level': 60}).encode_world_details()
        self.assertEqual(struct.unpack_from('<?HH', details60, len(details60) - 16), (True, 5, 0))

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RuneTester'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # %lv 30 unlocks Rune Slate (2621 MarkTabActiveNot + 2620 MarkItemActiveNot)
            client.send_event(2057, messages.CheatLevelUpReq(target_level=30).encode())
            _, ack2058 = await client.expect_event(2058)
            self.assertEqual(struct.unpack_from('<I', ack2058, 0)[0], 0)
            await client.expect_event(5087)
            _, not2621 = await client.expect_event(2621)
            self.assertTrue(messages.MarkTabActiveNot.decode(not2621).active_mark)
            _, not2620 = await client.expect_event(2620)
            parsed2620 = messages.MarkItemActiveNot.decode(not2620)
            self.assertEqual((parsed2620.base_count, parsed2620.bonus_count), (3, 0))

            # %itemcall resolves Agreement of Rune (IAMk1R190) and rune items (MMrk103)
            client.send_event(2137, messages.CheatItemCallReq(item_id=jhash('IAMk1R190'), count=1).encode())
            _, ack_agr = await client.expect_event(2138)
            self.assertEqual(struct.unpack_from('<I', ack_agr, 0)[0], 0)
            agr_uid, agr_hash = struct.unpack_from('<qI', ack_agr, len(ack_agr) - 22)
            self.assertEqual(agr_hash, jhash('IAMk1R190'))
            self.assertGreater(agr_uid, 0)

            client.send_event(2137, messages.CheatItemCallReq(item_id=jhash('MMrk103'), count=1).encode())
            _, ack_rune = await client.expect_event(2138)
            self.assertEqual(struct.unpack_from('<I', ack_rune, 0)[0], 0)
            _, rune_hash = struct.unpack_from('<qI', ack_rune, len(ack_rune) - 22)
            self.assertEqual(rune_hash, jhash('MMrk103'))

            # Using Agreement of Rune (2038 -> 2039) increments bonus slots and notifies 2621 + 2620
            client.send_event(2038, messages.UseItemReq(item_uid=agr_uid, use_count=1).encode())
            _, ack2039 = await client.expect_event(2039)
            self.assertEqual(struct.unpack_from('<I', ack2039, 0)[0], 0)
            _, not2621_2 = await client.expect_event(2621)
            self.assertTrue(messages.MarkTabActiveNot.decode(not2621_2).active_mark)
            _, not2620_2 = await client.expect_event(2620)
            parsed2620_2 = messages.MarkItemActiveNot.decode(not2620_2)
            self.assertEqual((parsed2620_2.base_count, parsed2620_2.bonus_count), (3, 1))

            # Re-selecting character encodes persisted mark_active=True, base=3, bonus=1
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertIn(struct.pack('<?HH', True, 3, 1), ack2007)

        self.run_async(self.with_server(scenario))

    def test_gm_bridge_shares_level_up_rune_slate_unlock(self):
        from darkblood.games.gm_bridge import execute_gm_command

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('BridgeTester'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            res = await execute_gm_command('lv 30', char_id=char_id)
            self.assertTrue(res['ok'], res)
            await client.expect_event(2058)
            await client.expect_event(5087)
            _, not2621 = await client.expect_event(2621)
            self.assertTrue(messages.MarkTabActiveNot.decode(not2621).active_mark)
            _, not2620 = await client.expect_event(2620)
            parsed2620 = messages.MarkItemActiveNot.decode(not2620)
            self.assertEqual((parsed2620.base_count, parsed2620.bonus_count), (3, 0))

        self.run_async(self.with_server(scenario))

    def test_item_upgrade_and_quality_survive_char_list_and_relog(self):
        """Items modified with 'upgrade' or 'quality' (GM commands) must serialize cleanly on 2008/2009 and 2006/2007."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Upgrader', char_class=0))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]

            from darkblood.games import session
            store = session.GameSession.store()
            char = store.get('OfflinePlayer', char_id)
            worn = next(it for it in char['items'] if it.get('container') == 1)
            worn['upgrade'] = 10
            worn['quality'] = 3
            store.save_char('OfflinePlayer', char_id)

            client.send_event(2008, b'')
            _, ack2009 = await client.expect_event(2009)
            self.assertEqual(struct.unpack_from('<I', ack2009, 0)[0], 0)

            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<I', ack2007, 0)[0], 0)

            # 2216 PlayOptionUpdateReq persists the 24-byte GameOption block (incl. HideHelmet byte 23) across relog
            opt_bytes = bytes.fromhex('010101010100010100000101010101b6f3fd3eb6f3fd3e01')
            client.send_event(2216, struct.pack('<q', char_id) + opt_bytes)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007_opt = await client.expect_event(2007)
            self.assertIn(opt_bytes, ack2007_opt)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
