"""Tests for dungeon gameplay: layer transition, combat events, deaths, and rank reward choices."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow, wide
from darkblood.core import hashing
from darkblood.games import session
from darkblood.games.network import results
from darkblood.games.network.messages import (
    FinishGameAck,
    PartyAcceptInviteReq,
    PartyInviteReq,
    SelectDungeonAck,
)


class DungeonFlowTest(ServerTestCase):
    def test_start_game_replies_with_map_or_result_only(self):
        async def scenario(client):
            await lobby_flow(client)
            prefix = struct.pack('<I', 0x7fffffff)
            map_code = wide('Act1_G1_A10')
            for payload in (prefix + wide(''), prefix + map_code[:-2], prefix + b'\x81A'):
                client.send_event(5013, payload, correlation=42)
                correlation, error = await client.expect_event(5014)
                self.assertEqual(correlation, 42)
                self.assertEqual(error, bytes.fromhex('01000000'))

            client.send_event(5013, prefix + map_code, correlation=43)
            correlation, success = await client.expect_event(5014)
            self.assertEqual(correlation, 43)
            self.assertEqual(success, b'\x00' * 10 + map_code + bytes.fromhex('1780178017801080'))

        self.run_async(self.with_server(scenario))

    def test_dungeon_and_combat_lifecycle(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('DungeonSlayer', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            char = session.GameSession.store().get('OfflinePlayer', char_id)

            # 1. Map transition / Waypoint insert (2344 -> 2345)
            client.send_event(2344, bytes.fromhex('ffffff7f00000000aeaf985f'))
            _, ack2345 = await client.expect_event(2345)
            act1_layer = hashing.jhash('Act1') << 32
            self.assertEqual(struct.unpack_from('<IQQ', ack2345), (0, act1_layer, act1_layer))

            # 2. Gate selection (2369 -> 2370)
            client.send_event(2369)
            _, ack2370 = await client.expect_event(2370)
            self.assertEqual(ack2370, b'\x00' * 16)

            # 3. Dungeon layer change (5095)
            layer_net_id = (hashing.jhash('Act1_G1_A10') << 32) | 4
            client.send_event(5095, struct.pack('<iq', 0x7fffffff, layer_net_id))

            # 4. War flag (2422)
            client.send_event(2422, struct.pack('<iI', 0x7fffffff, 31))

            # 5. Beginner guide update (2358)
            client.send_event(2358, struct.pack('<i', 0x7fffffff) + b'\x10\x80')

            # 6. Monster dead (5063)
            client.send_event(5063, struct.pack('<iII', 0x7fffffff, 100, 0))

            # 7. Char stat verify (2406 -> 2407)
            client.send_event(2406, bytes.fromhex('ffffff7f0000000010801080621ac3412811ea41b802414088b60e400ad7233cffffffff'))
            _, ack2407 = await client.expect_event(2407)
            self.assertEqual(struct.unpack_from('<i', ack2407)[0], 0)

            # 8. Gameplay death (5093 -> 5094): live body is uid 0, die 1, nLayerID, nX, nY.
            client.send_event(5093, bytes.fromhex('000000000000000001000000000000000000000000'))
            _, ack5094 = await client.expect_event(5094)
            res, uid, other, bDie, a, b, c, cnt = struct.unpack_from('<Iqq?IIIH', ack5094)
            self.assertEqual((res, uid, other, bDie), (0, 0, 0, True))  # client's own UID echoed (0 live)
            self.assertEqual(len(ack5094), 35)  # no coin u16 when bDie is set

            # 8b. Revive (bDie = 0) with 0x7FFFFFFF prefix spends one coin; trailing u16 = coins left.
            # Body: uid, bDie, nLayerID, (int)x, (int)y; the ack must echo the position.
            client.send_event(5093, struct.pack('<i', 0x7fffffff) + struct.pack('<q?iii', 0, False, 3, 1520, -264))
            _, ack5094 = await client.expect_event(5094)
            res, uid, other, bDie, layer, x, y = struct.unpack_from('<Iqq?iii', ack5094)
            self.assertEqual((res, uid, other, bDie), (0, 0, 0, False))
            self.assertEqual((layer, x, y), (3, 1520, -264))
            self.assertEqual(struct.unpack_from('<?', ack5094, 20)[0], False)
            self.assertEqual(struct.unpack_from('<H', ack5094, 35)[0], 2)
            _, not2286_revive = await client.expect_event(2286)
            self.assertEqual(struct.unpack_from('<IH', not2286_revive), (0, 2))

            # 9. Daily rebirth coin claim (2448 -> 2449 + 2286): tops coins up to 3.
            client.send_event(2448, bytes.fromhex('ffffff7f00'))
            _, ack2449 = await client.expect_event(2449)
            self.assertEqual(struct.unpack_from('<IHI', ack2449), (0, 1, 0))
            _, not2286 = await client.expect_event(2286)
            self.assertEqual(struct.unpack_from('<IH', not2286), (0, 3))

            # 10. A reward card is unavailable before a clear.
            client.send_event(5090, struct.pack('<ii', 0x7fffffff, 0))
            _, ack5091 = await client.expect_event(5091)
            self.assertEqual(ack5091, struct.pack('<i', results.INVALID_STATE))

            # 10b. Leave room outside dungeon (5005 -> 5006 only, no 5046)
            client.send_event(5005, b'')
            _, ack5006 = await client.expect_event(5006)
            self.assertEqual(struct.unpack_from('<i', ack5006)[0], 0)

            # 10c. Mid-dungeon abandon before clear (5013 -> 5014, then 5005 -> 5006 + 5046 + 2085 penalty)
            from darkblood.games.network.messages import ChangeDungeonPenaltyNot, StartGameReq
            client.send_event(5013, StartGameReq(map_code='Act1_G1_A10').encode())
            _, ack5014_ab = await client.expect_event(5014)
            self.assertEqual(struct.unpack_from('<i', ack5014_ab)[0], 0)
            await client.expect_event(2023)  # stress consumed on dungeon entry
            client.send_event(5005, b'')
            _, ack5006_ab = await client.expect_event(5006)
            self.assertEqual(struct.unpack_from('<i', ack5006_ab)[0], 0)
            _, ack5046_ab = await client.expect_event(5046)
            self.assertEqual(struct.unpack_from('<i', ack5046_ab)[0], 0)
            _, not2085 = await client.expect_event(2085)
            pen = ChangeDungeonPenaltyNot.decode(not2085)
            self.assertEqual((pen.in_dungeon, pen.is_penalty, pen.penalty_level, pen.penalty_id, pen.duration),
                             (True, False, 1, 0, 0))

            # 10d. BuyLifeWater (2086 -> 2087 + 2085 clear) deducts exact LoadLifeWater AR and clears penalty
            from darkblood.games.network.messages import BuyLifeWaterAck, BuyLifeWaterReq
            from darkblood.games.progression import life_water_cost
            char['gold'] = 10000
            char['u66'] = 10000
            expected_lw_cost = life_water_cost(char, penalty_type=0)
            self.assertGreater(expected_lw_cost, 0)
            client.send_event(2086, BuyLifeWaterReq(flag=False).encode())
            _, ack2087 = await client.expect_event(2087)
            lw_ack = BuyLifeWaterAck.decode(ack2087)
            self.assertEqual((lw_ack.result, lw_ack.flag, lw_ack.remain_currency),
                             (0, False, 10000 - expected_lw_cost))
            _, not2085_clear = await client.expect_event(2085)
            pen_clear = ChangeDungeonPenaltyNot.decode(not2085_clear)
            self.assertEqual((pen_clear.in_dungeon, pen_clear.is_penalty, pen_clear.penalty_level,
                              pen_clear.penalty_id, pen_clear.duration),
                             (False, False, 0, -1, -1))

            # 11. Back to square (5045 -> 5046)
            client.send_event(5045, struct.pack('<i', 0x7fffffff))
            _, ack5046 = await client.expect_event(5046)
            self.assertEqual(struct.unpack_from('<i', ack5046)[0], 0)

            # 12. Party invite to self is rejected with 5050 (error-only ack;
            # success sends no 5050 because 0x00758700 prints result=0 as an error).
            client.send_event(5049, PartyInviteReq(target_uid=char_id).encode())
            _, ack5050 = await client.expect_event(5050)
            self.assertNotEqual(struct.unpack_from('<i', ack5050)[0], 0)

            # 13. Accepting without an invitation is rejected (5054 -> 5055).
            client.send_event(5054, PartyAcceptInviteReq(host_uid=12345).encode())
            _, ack5055 = await client.expect_event(5055)
            self.assertNotEqual(struct.unpack_from('<i', ack5055)[0], 0)

            # 14. Change team (5015 -> 5016)
            client.send_event(5015, struct.pack('<i', 1))
            _, ack5016 = await client.expect_event(5016)
            self.assertEqual(struct.unpack_from('<ii', ack5016), (0, 1))

            # 15. Pick up item: covered by tests/test_monster_exp.py (drop + pick-up).

            # 16. Gold goblin attack (5363 -> 5364)
            client.send_event(5363, struct.pack('<ii', 1, 100))
            _, ack5364 = await client.expect_event(5364)
            self.assertEqual(struct.unpack_from('<i', ack5364)[0], 0)

            # 17. Gold goblin dead (5365 -> 5366)
            client.send_event(5365, struct.pack('<i', 1))
            _, ack5366 = await client.expect_event(5366)
            self.assertEqual(struct.unpack_from('<i', ack5366)[0], 0)

            # 18. Finish game (5017 -> 5018)
            client.send_event(5017, b'\x01')
            _, ack5018 = await client.expect_event(5018)
            res, is_clear = struct.unpack_from('<I?', ack5018, 0)
            self.assertEqual((res, is_clear), (0, True))
            self.assertTrue(ack5018.endswith(b'\x10\x80'))
            # mapSingleReward must hold the player's own entry (uid = char id).
            entry = ack5018.index(b'\x17\x81\x0f' + struct.pack('<q', char_id)) + 11
            stats = struct.unpack_from('<10i', ack5018, entry)
            # Extra-box count (+0x20) drives a UI loop on the result screen; it
            # must not carry combat numbers (that froze and crashed the client).
            self.assertEqual(stats[8], 0)
            self.assertEqual(stats[1], stats[4])  # total == EXP reported

        self.run_async(self.with_server(scenario))

    def test_select_dungeon_history_and_active_quests(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('GateQuester', char_class=1))
            _, ack2013 = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', ack2013, 10)[0]
            store = session.GameSession.store()
            char = store.get('OfflinePlayer', char_id)
            quest_id = hashing.jhash('Q0002S01')  # QuestLink of Act1_G1_A16
            char['quests_active'] = {str(quest_id): {'uid': 1, 'tracked': True, 'counters': [0]}}
            store.save()
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            prefix = struct.pack('<i', 0x7fffffff)

            # A new character has no history: every dungeon defaults to Normal.
            client.send_event(5043, prefix + wide('Act1_G1'))
            _, ack5044 = await client.expect_event(5044)
            self.assertEqual(ack5044[4:6], b'\x17\x80')
            self.assertTrue(ack5044.endswith(b'\x13\x81' + struct.pack('<I', quest_id)))

            # Clearing Hard (A11) records ucDiff 1 with the cleared flag.
            client.send_event(5013, prefix + wide('Act1_G1_A11'))
            await client.expect_event(5014)
            client.send_event(5017, b'\x01')
            await client.expect_event(5018)
            self.assertEqual(char['dungeon_history'], {'Act1_G1_A1': {'map': 'Act1_G1_A11', 'diff': 1}})

            # Clearing Normal afterwards keeps the highest difficulty, and so does
            # the Normal quest variant (A16 = A1 at Difficult 0).
            for code in ('Act1_G1_A10', 'Act1_G1_A16'):
                client.send_event(5013, prefix + wide(code))
                await client.expect_event(5014)
                client.send_event(5017, b'\x01')
                await client.expect_event(5018)
            self.assertEqual(char['dungeon_history']['Act1_G1_A1']['diff'], 1)

            # A15 has its own content (Act1_G1_A1_Q2.map, level 35-37) although it is
            # marked Difficult 2: it does not clear Master.
            client.send_event(5013, prefix + wide('Act1_G1_A15'))
            await client.expect_event(5014)
            client.send_event(5017, b'\x01')
            await client.expect_event(5018)
            self.assertEqual(char['dungeon_history']['Act1_G1_A1'], {'map': 'Act1_G1_A11', 'diff': 1})

            # Act2_G1_A14 is a copy of Act2_G1_A11 (Hard): its clear counts as A11.
            client.send_event(5013, prefix + wide('Act2_G1_A14'))
            await client.expect_event(5014)
            client.send_event(5017, b'\x01')
            await client.expect_event(5018)
            self.assertEqual(char['dungeon_history']['Act2_G1_A1'], {'map': 'Act2_G1_A11', 'diff': 1})

            client.send_event(5043, prefix + wide('Act1_G1'))
            _, ack5044 = await client.expect_event(5044)
            self.assertIn(b'\x17\x81\x0f' + wide('Act1_G1_A1') + wide('Act1_G1_A11') + b'\x01\x01', ack5044)

        self.run_async(self.with_server(scenario))

    def test_second_gate_reports_exp_and_only_unlocks_on_clear(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('SecondGate', char_class=1))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            prefix = struct.pack('<I', 0x7fffffff)
            client.send_event(2006, prefix + struct.pack('<Q', char_id))
            await client.expect_event(2007)

            async def select_gate():
                client.send_event(5043, prefix + wide('Act1_G2'))
                _, body = await client.expect_event(5044)
                ack = SelectDungeonAck.decode(body)
                self.assertEqual((ack.result, ack.gate_id), (0, 'Act1_G2'))
                return ack.dun_history

            self.assertEqual(await select_gate(), {})
            runs = (
                # Map, victory, monster instance, result EXP, cleared map and difficulty.
                ('Act1_G2_B10', True, 101, 10, 'Act1_G2_B10', 0),
                ('Act1_G2_B11', False, 102, 0, 'Act1_G2_B10', 0),
                ('Act1_G2_B11', True, None, 0, 'Act1_G2_B11', 1),
            )
            for code, victory, monster_instance, exp, cleared_map, diff in runs:
                with self.subTest(map=code, victory=victory):
                    client.send_event(5013, prefix + wide(code))
                    _, started = await client.expect_event(5014)
                    self.assertEqual(started, b'\x00' * 10 + wide(code) + bytes.fromhex('1780178017801080'))

                    if monster_instance is not None:
                        kill = struct.pack('<II', hashing.jhash('1npi01n0'), monster_instance)
                        client.send_event(5063, prefix + kill)
                        _, gained = await client.expect_event(5086)
                        self.assertEqual(struct.unpack_from('<i', gained, 12)[0], 10)

                    client.send_event(5017, bytes([victory]))
                    _, finished = await client.expect_event(5018)
                    result = FinishGameAck.decode(finished)
                    self.assertEqual((result.result, result.map_code, result.is_clear), (0, code, victory))
                    if victory:
                        self.assertEqual(set(result.rewards), {char_id})
                        reward = result.rewards[char_id]
                        self.assertEqual((reward.exp, reward.total, reward.extra_box_count), (exp, exp, 0))
                    else:
                        self.assertEqual(result.rewards, {})

                    history = await select_gate()
                    self.assertEqual(set(history), {'Act1_G2_B1'})
                    entry = history['Act1_G2_B1']
                    self.assertEqual((entry.map_id, entry.max_diff, entry.cleared), (cleared_map, diff, 1))

        self.run_async(self.with_server(scenario))

    def test_extended_lobby_dungeon_and_arena_opcodes(self):
        """Test newly recovered Lobby, Dungeon (again/training/treasure), and Arena (GBB) opcodes."""
        from darkblood.games.network.messages.lobby import (
            CharNickChangeByIntegrateAck, CharNickChangeByIntegrateReq,
            CharSlotExtendReq, EventDeleteCharacterAck, EventDeleteCharacterReq,
            ImpliedJoinLayerReq,
        )
        from darkblood.games.network.messages.dungeon import (
            AgainSelectDungeonAck, AgainSelectDungeonReq,
            MonsterRegenAck, MonsterRegenReq,
            TrainingJoinRoomAck, TrainingJoinRoomReq,
            TrainingLeaveRoomAck, TrainingLeaveRoomReq,
            TreasureFindReq,
        )
        from darkblood.games.network.messages.arena import (
            GbbChallengeAck, GbbChallengeReq, GbbGiveupAck, GbbGiveupReq,
            MinigameGbbStartAck, MinigameGbbStartReq,
        )

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RunnerOne'))
            _, c1 = await client.expect_event(2013)
            char1_id = struct.unpack_from('<Q', c1, 10)[0]

            client.send_event(2012, create_request('TempDel'))
            _, c2 = await client.expect_event(2013)
            char2_id = struct.unpack_from('<Q', c2, 10)[0]

            # Lobby: nick change by integrate (2323), event delete (2404), char slot extend (2441)
            client.send_event(2323, CharNickChangeByIntegrateReq(char_uid=char1_id, old_nick='RunnerOne', new_nick='RunnerNew').encode())
            _, r = await client.expect_event(2324)
            ack = CharNickChangeByIntegrateAck.decode(r)
            self.assertEqual((ack.result, ack.char_uid, ack.new_nick), (0, char1_id, 'RunnerNew'))

            client.send_event(2404, EventDeleteCharacterReq(char_uid=char2_id).encode())
            _, r = await client.expect_event(2405)
            ack = EventDeleteCharacterAck.decode(r)
            self.assertEqual((ack.result, ack.delete_char_uid), (0, char2_id))

            # Instant Delete (2244 -> 2245) removes character immediately (even when pending delete)
            from darkblood.games.network.messages.lobby import (
                CheatSystemDeleteCharacterAck, CheatSystemDeleteCharacterReq,
            )
            client.send_event(2012, create_request('InstantDel'))
            _, c3 = await client.expect_event(2013)
            char3_id = struct.unpack_from('<Q', c3, 10)[0]
            client.send_event(2014, struct.pack('<iq', 0x7fffffff, char3_id))
            await client.expect_event(2015)
            client.send_event(2244, CheatSystemDeleteCharacterReq(char_uid=char3_id).encode())
            _, r = await client.expect_event(2245)
            ack2245 = CheatSystemDeleteCharacterAck.decode(r)
            self.assertEqual((ack2245.result, ack2245.char_uid), (0, char3_id))
            # Second instant delete on same UID fails cleanly (result=1)
            client.send_event(2244, CheatSystemDeleteCharacterReq(char_uid=char3_id).encode())
            _, r_fail = await client.expect_event(2245)
            self.assertEqual(struct.unpack_from('<I', r_fail)[0], 1)

            client.send_event(2441, CharSlotExtendReq(item_uid=900).encode())
            _, r = await client.expect_event(2442)
            self.assertEqual(struct.unpack_from('<IB', r), (0, 14))

            # Select char and enter town
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char1_id))
            await client.expect_event(2007)

            # Implied join layer (5128 -> 5031)
            client.send_event(5128, ImpliedJoinLayerReq(layer_net_id=(0x20846A << 32) | 1, flag=True).encode())
            _, r = await client.expect_event(5031)
            self.assertEqual(struct.unpack_from('<I', r)[0], 0)

            # Dungeon: again select (5052 -> 5053), training room (5236/5238/5240), treasure (5342)
            client.send_event(5052, AgainSelectDungeonReq().encode())
            _, r = await client.expect_event(5053)
            self.assertEqual(AgainSelectDungeonAck.decode(r).result, 0)

            client.send_event(5236, TrainingJoinRoomReq().encode())
            _, r = await client.expect_event(5237)
            self.assertEqual(TrainingJoinRoomAck.decode(r).result, 0)

            client.send_event(5240, MonsterRegenReq(regen_mob_id=101, slot_id=0).encode())
            _, r = await client.expect_event(5241)
            self.assertEqual(MonsterRegenAck.decode(r).result, 0)

            client.send_event(5238, TrainingLeaveRoomReq().encode())
            _, r = await client.expect_event(5239)
            self.assertEqual(TrainingLeaveRoomAck.decode(r).result, 0)
            _, r5046 = await client.expect_event(5046)
            self.assertEqual(struct.unpack_from('<I', r5046)[0], 0)

            client.send_event(5342, TreasureFindReq(treasure_id=7).encode())
            _, r = await client.expect_event(5343)
            self.assertEqual(struct.unpack_from('<I', r)[0], 0)

            # Arena GBB Minigame (2715-2720)
            client.send_event(2715, MinigameGbbStartReq().encode())
            _, r = await client.expect_event(2716)
            self.assertEqual(MinigameGbbStartAck.decode(r).result, 0)

            client.send_event(2717, GbbChallengeReq(choice=1).encode())
            _, r = await client.expect_event(2718)
            ack = GbbChallengeAck.decode(r)
            self.assertEqual(ack.result, 0)
            self.assertIn(ack.outcome, (0, 1, 2))

            client.send_event(2719, GbbGiveupReq().encode())
            _, r = await client.expect_event(2720)
            self.assertEqual(GbbGiveupAck.decode(r).result, 0)

        self.run_async(self.with_server(scenario))

    def test_stress_consumption_and_recovery(self):
        """Verify dungeon stress consumption (5013 + 5095), passive recovery, and daily reset."""
        from darkblood.games.network.messages.dungeon import StartGameReq
        from darkblood.games.network.messages.system import StressChangedNot
        from darkblood.games.progression import MAX_STRESS, consume_stress, refresh_stress

        # Unit checks: consumption, clamping, passive 1/min recovery, and daily reset.
        char = {'id': 1, 'stress': 0}
        t0 = 1_700_000_000.0
        self.assertTrue(consume_stress(char, 2, now=t0))
        self.assertEqual(char['stress'], 2)
        self.assertEqual(char['today_cronos_stress'], 2)
        self.assertTrue(consume_stress(char, 500, now=t0))
        self.assertEqual(char['stress'], MAX_STRESS)
        self.assertTrue(refresh_stress(char, now=t0 + 185.0))  # 3 full minutes -> -3 stress
        self.assertEqual(char['stress'], MAX_STRESS - 3)
        self.assertTrue(refresh_stress(char, now=t0 + 90_000.0))  # next day -> reset to 0
        self.assertEqual(char['stress'], 0)
        self.assertEqual(char['today_cronos_stress'], 0)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('StressHero', char_class=1))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.expect_event(2410)

            # 5013 StartGame consumes initial room stress (+2 -> 2023 StressChangedNot)
            client.send_event(5013, StartGameReq(map_code='Act1_G1_A10').encode())
            await client.expect_event(5014)
            _, n1 = await client.expect_event(2023)
            self.assertEqual(StressChangedNot.decode(n1).stress, 2)

            # First 5095 (initial layer 1) does not double-charge; second layer (2) charges +2 -> 4
            map_hash = hashing.jhash('Act1_G1_A10')
            client.send_event(5095, struct.pack('<iq', 0x7fffffff, (map_hash << 32) | 1))
            client.send_event(5095, struct.pack('<iq', 0x7fffffff, (map_hash << 32) | 2))
            _, n2 = await client.expect_event(2023)
            self.assertEqual(StressChangedNot.decode(n2).stress, 4)

        self.run_async(self.with_server(scenario))

    def test_penalty_timers_relogin_and_db_reload(self):
        """Verify penalty recovery steps (40/90/210/450/600s), DB reload reconciliation, and 2006 login restore."""
        import time
        from darkblood.games.network.messages import ChangeDungeonPenaltyNot
        from darkblood.games.progression import (
            apply_dungeon_penalty,
            refresh_dungeon_penalty,
        )
        from darkblood.games.session import GameSession

        t0 = 1_700_000_000.0
        c = {'id': 1, 'level': 5}
        p0 = apply_dungeon_penalty(c, penalty_type=0, now=t0)
        self.assertEqual((p0.in_dungeon, p0.penalty_level, p0.penalty_id, p0.duration), (True, 1, 0, 0))
        # Step 1 at 45s
        changed, p1 = refresh_dungeon_penalty(c, penalty_type=0, now=t0 + 45)
        self.assertTrue(changed)
        self.assertEqual((p1.in_dungeon, p1.penalty_level, p1.penalty_id, p1.duration), (False, 1, 1, 45))
        # No change at 50s (still step 1)
        changed, p_same = refresh_dungeon_penalty(c, penalty_type=0, now=t0 + 50)
        self.assertFalse(changed)
        self.assertIsNone(p_same)
        # Step 4 at 460s
        changed, p4 = refresh_dungeon_penalty(c, penalty_type=0, now=t0 + 460)
        self.assertTrue(changed)
        self.assertEqual((p4.penalty_id, p4.duration), (4, 460))
        # Expired at 605s -> cleared with duration=-1
        changed, p_end = refresh_dungeon_penalty(c, penalty_type=0, now=t0 + 605)
        self.assertTrue(changed)
        self.assertEqual((p_end.penalty_level, p_end.penalty_id, p_end.duration), (0, -1, -1))
        self.assertEqual(c['leave_penalty_count'], 0)

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('PenHero', char_class=1))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            # Seed a persisted penalty started 100s ago (step 2) before login, simulating server restart
            char = GameSession.store().get('OfflinePlayer', char_id)
            apply_dungeon_penalty(char, penalty_type=0, now=time.time() - 100)
            GameSession.store().save()
            GameSession.store().refresh_all_timers()
            self.assertEqual(char['leave_penalty_step'], 2)

            # On 2006 SelectCharacter, client receives 2007, 2410, and silent 2085 restore (in_dungeon=False)
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.expect_event(2410)
            _, restored = await client.expect_event(2085)
            pen = ChangeDungeonPenaltyNot.decode(restored)
            self.assertEqual((pen.in_dungeon, pen.is_penalty, pen.penalty_level, pen.penalty_id),
                             (False, False, 1, 2))
            self.assertGreaterEqual(pen.duration, 95)
            self.assertLess(pen.duration, 210)

        self.run_async(self.with_server(scenario))

    def test_dungeon_rank_uses_score_ratio_and_card_rewards_roll_from_table(self):
        """5017 computes rank from mapPartyScoreList / nTotalMosterHP (not mapPartyDPS),
        and 5090 rolls real items from dungeonreward.lua instead of always granting meat."""
        import random
        from darkblood.games import loot
        from darkblood.games.entities.character import CharacterClass
        from darkblood.games.network import messages

        # Roll 80 rewards for Act1_G1_A30 (Mage / Sorcerer) and verify variety (equipment + consumables, not only meat)
        random.seed(42)
        rolled = {loot.roll_dungeon_reward('Act1_G1_A30', int(CharacterClass.SORCERER))[0] for _ in range(80)}
        self.assertGreater(len(rolled), 5, f'Expected varied dungeon rewards, got {rolled}')
        self.assertTrue(any(code.startswith(('W', 'A')) for code in rolled),
                        f'Expected weapon/armor drops in dungeon rewards, got {rolled}')

        # Live-captured 5017 values: score=7357, dps=246, nTotalMosterHP=14803 -> ratio 0.497 -> A (3)
        from darkblood.core.serialization.wire import JSerBufferWriter

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RankHero', char_class=int(CharacterClass.MAGE)))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.expect_event(2410)

            client.send_event(5013, messages.StartGameReq(map_code='Act1_G1_A30').encode())
            await client.expect_event(5014)
            await client.expect_event(2023)

            # Kill a monster so dungeon_exp > 0 and bonus_exp / final_total_exp are non-zero
            kill = struct.pack('<iII', 0x7fffffff, hashing.jhash('1npi01n0') & 0xFFFFFFFF, 0x03000fa2)
            client.send_event(5063, kill)
            await client.expect_event(5086)

            w5017 = JSerBufferWriter()
            w5017.write_bool(True)
            for m in ({char_id: 7357}, {char_id: 246}):
                w5017.write_u8(0x17)
                w5017.write_varuint(len(m))
                for k, v in m.items():
                    w5017.write_u8(0x0F)
                    w5017.write_i64(k)
                    w5017.write_i32(v)
            w5017.write_i32(14803)  # nTotalMosterHP
            client.send_event(5017, w5017.to_bytes())
            # Bonus clear EXP triggers a 5086 before 5018
            await client.expect_event(5086)
            _, ack5018 = await client.expect_event(5018)
            parsed = messages.FinishGameAck.decode(ack5018)
            sr = parsed.rewards[char_id]
            self.assertEqual(sr.rank, 3)  # A, NOT SSS (6)
            self.assertGreater(sr.exp, 0)
            self.assertGreater(sr.bonus_exp, 0)
            self.assertEqual(sr.final_total_exp, sr.exp + sr.bonus_exp)
            self.assertEqual(parsed.rank_first, 3)
            self.assertEqual(parsed.rank_final, 3)
            self.assertEqual(parsed.box_grade, 1)

            char = session.GameSession.store().get('OfflinePlayer', char_id)
            exp_after_clear = char['level'], char['exp']
            client.send_event(5017, w5017.to_bytes(), correlation=42)
            correlation, repeated_result = await client.expect_event(5018)
            self.assertEqual((correlation, repeated_result), (42, ack5018))
            self.assertEqual((char['level'], char['exp']), exp_after_clear)

            # Pick a reward card (5090 -> 5091) and verify item is added to inventory
            from darkblood.player_management.characters import add_reward_items, free_bag_slots
            char = session.GameSession.store().get('OfflinePlayer', char_id)
            card_request = struct.pack('<ii', 0x7fffffff, 0)

            # Full inventory delivers dungeon chest reward to mailbox with result 294 (JERI_DUN_REWARD_00 -> UI_3329)
            fillers = add_reward_items(char, [('Ihppa0001', 1)] * free_bag_slots(char))
            full_inventory = list(char['items'])
            char['gold'] = parsed.extra_box_cost * 2
            char['u66'] = char['gold']
            client.send_event(5090, struct.pack('<ii', 0x7fffffff, 2))
            _, ack5091_mail = await client.expect_event(5091)
            res_m, uid_m, hash_m = struct.unpack_from('<iqI', ack5091_mail, 0)
            box_type_m, box_cost_m = struct.unpack_from('<ii', ack5091_mail, 24)
            self.assertEqual((res_m, uid_m, box_type_m, box_cost_m),
                             (results.DUN_REWARD_SENT_MAIL, char_id, 2, parsed.extra_box_cost))
            self.assertNotEqual(hash_m, 0)
            self.assertEqual(char['items'], full_inventory)
            self.assertEqual(char['gold'], parsed.extra_box_cost)
            inbox = session.GameSession.store().get_mail_inbox(char_id)
            self.assertEqual(len(inbox), 1)
            await client.expect_event(2227)  # PostNewArrivalNot
            for filler in fillers:
                char['items'].remove(filler)

            before_claim = len(char['items'])
            client.send_event(5090, card_request)
            _, ack5091 = await client.expect_event(5091)
            res, uid, item_hash = struct.unpack_from('<iqI', ack5091, 0)
            self.assertEqual((res, uid), (0, char_id))
            self.assertNotEqual(item_hash, 0)
            self.assertGreater(len(char['items']), before_claim)
            after_claim = len(char['items'])

            client.send_event(5090, card_request)
            _, ack5091 = await client.expect_event(5091)
            self.assertEqual(ack5091, struct.pack('<i', results.INVALID_STATE))
            self.assertEqual(len(char['items']), after_claim)

            # Duplicate extra chest 2 and out-of-range extra chest 3 are rejected
            self.assertEqual(parsed.rewards[char_id].extra_box_count, 1)
            self.assertGreater(parsed.extra_box_cost, 0)
            for bad_idx in (2, 3):
                client.send_event(5090, struct.pack('<ii', 0x7fffffff, bad_idx))
                _, ack5091_bad = await client.expect_event(5091)
                self.assertEqual(ack5091_bad, struct.pack('<i', results.INVALID_STATE))

            # The next run can award a new card, but only after a victory.
            for victory in (False, True):
                client.send_event(5013, messages.StartGameReq(map_code='Act1_G1_A30').encode())
                await client.expect_event(5014)
                client.send_event(5017, bytes([victory]))
                await client.expect_event(5018)
                client.send_event(5090, card_request)
                _, ack5091 = await client.expect_event(5091)
                if victory:
                    self.assertEqual(struct.unpack_from('<iq', ack5091), (0, char_id))
                    self.assertGreater(len(char['items']), after_claim)
                else:
                    self.assertEqual(ack5091, struct.pack('<i', results.INVALID_STATE))
                    self.assertEqual(len(char['items']), after_claim)

        self.run_async(self.with_server(scenario))

    def test_fortress_challenge_limit_and_special_entry_item_enforcement(self):
        """Issue #22: Citadel challenge opportunities and required entry items are tracked & enforced."""
        from darkblood.games.network import messages
        from darkblood.games.progression import refresh_dungeon_entry_limits
        from darkblood.games.world import GameWorldManager
        import datetime

        # Unit check for weekly Monday reset & daily +1 charge
        c = {}
        mon = datetime.datetime(2026, 11, 23, 12, 0).timestamp()  # Monday
        tue = datetime.datetime(2026, 11, 24, 12, 0).timestamp()  # Tuesday
        next_mon = datetime.datetime(2026, 11, 30, 12, 0).timestamp()  # Next Monday
        self.assertTrue(refresh_dungeon_entry_limits(c, now=mon))
        self.assertEqual(c['citadel_play_count'], 3)
        c['citadel_play_count'] = 1
        self.assertTrue(refresh_dungeon_entry_limits(c, now=tue))
        self.assertEqual(c['citadel_play_count'], 2)  # +1 daily charge
        fri = datetime.datetime(2026, 11, 27, 12, 0).timestamp()
        self.assertTrue(refresh_dungeon_entry_limits(c, now=fri))
        self.assertEqual(c['citadel_play_count'], 5)
        self.assertFalse(refresh_dungeon_entry_limits(c, now=fri))
        sun = datetime.datetime(2026, 11, 29, 12, 0).timestamp()
        c['citadel_play_count'] = 6
        self.assertTrue(refresh_dungeon_entry_limits(c, now=sun))
        self.assertEqual(c['citadel_play_count'], 7)

        c['citadel_play_count'] = 0
        next_wed = datetime.datetime(2026, 12, 2, 12, 0).timestamp()
        away = dict(c)
        self.assertTrue(refresh_dungeon_entry_limits(away, now=next_wed))
        self.assertEqual(away['citadel_play_count'], 5)
        self.assertTrue(refresh_dungeon_entry_limits(c, now=next_mon))
        self.assertEqual(c['citadel_play_count'], 3)  # Monday weekly reset

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('FortressHero'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<q', created, 10)[0]
            client.send_event(2006, struct.pack('<iq', 0x7fffffff, char_id))
            await client.expect_event(2007)
            await client.expect_event(2410)
            client.send_event(5124)
            await client.expect_event(5125)

            char = GameWorldManager.get().get_player(char_id).char_data
            self.assertEqual(char['citadel_play_count'], 3)

            # 1. Fortress (Citadel_A13): 3 entries succeed (2631 decrements 2 -> 1 -> 0), 4th blocked with 5222
            for expected_remain in (2, 1, 0):
                client.send_event(5013, messages.StartGameReq(map_code='Citadel_A13').encode())
                _, not2631 = await client.expect_event(2631)
                self.assertEqual(struct.unpack_from('<h', not2631, 0)[0], expected_remain)
                _, ack5014 = await client.expect_event(5014)
                self.assertEqual(struct.unpack_from('<i', ack5014, 0)[0], 0)
                await client.expect_event(2023)

            client.send_event(5013, messages.StartGameReq(map_code='Citadel_A13').encode())
            _, fail5222 = await client.expect_event(5222)
            self.assertEqual(struct.unpack_from('<q', fail5222, 0)[0], char_id)
            _, ack5014_fail = await client.expect_event(5014)
            self.assertEqual(struct.unpack_from('<i', ack5014_fail, 0)[0], 139)

            # 2. Special dungeon requiring entry item (Act4_G2_R13 needs IticR5040 x2, EnterLimit=6)
            client.send_event(5013, messages.StartGameReq(map_code='Act4_G2_R13').encode())
            _, fail5136 = await client.expect_event(5136)
            self.assertEqual(struct.unpack_from('<q', fail5136, 0)[0], char_id)
            _, ack5014_noitem = await client.expect_event(5014)
            self.assertEqual(struct.unpack_from('<i', ack5014_noitem, 0)[0], 138)

            # Grant 2x IticR5040 -> entry succeeds, consumes item (2037) & increments daily count (2318)
            next_uid = max((i.get('uid', 0) for i in char.get('items', [])), default=0) + 1
            char.setdefault('items', []).append({
                'uid': next_uid, 'code': 'IticR5040', 'container': 3, 'slot': 18, 'count': 2,
            })
            client.send_event(5013, messages.StartGameReq(map_code='Act4_G2_R13').encode())
            _, not2318 = await client.expect_event(2318)
            self.assertIn('Act4_G2_R13'.encode('utf-16-le'), not2318)
            await client.expect_event(2037)  # consumed ticket tombstone
            _, ack5014_ok = await client.expect_event(5014)
            self.assertEqual(struct.unpack_from('<i', ack5014_ok, 0)[0], 0)
            await client.expect_event(2023)
            self.assertFalse(any(i.get('code') == 'IticR5040' for i in char.get('items', [])))
            self.assertEqual(char['daily_dun_enter_counts']['Act4_G2_R13'], 1)

            # Clearing a clear-limited dungeon (ClearLimit=3) counts it and pushes 2443.
            client.send_event(5017, b'\x01')
            _, not2443 = await client.expect_event(2443)
            self.assertEqual(messages.DailyDunClearCountUpdateNot.decode(not2443).clear_counts, {'Act4_G2_R13': 1})
            await client.expect_event(5018)
            self.assertEqual(char['daily_dun_clear_counts']['Act4_G2_R13'], 1)

            # Reaching daily EnterLimit=6 blocks entry with 5222 + 5014(139) even if tickets exist
            char['daily_dun_enter_counts']['Act4_G2_R13'] = 6
            char['items'].append({
                'uid': next_uid + 1, 'code': 'IticR5040', 'container': 3, 'slot': 18, 'count': 2,
            })
            client.send_event(5013, messages.StartGameReq(map_code='Act4_G2_R13').encode())
            _, fail5222_daily = await client.expect_event(5222)
            self.assertEqual(struct.unpack_from('<q', fail5222_daily, 0)[0], char_id)
            _, ack5014_lim = await client.expect_event(5014)
            self.assertEqual(struct.unpack_from('<i', ack5014_lim, 0)[0], 139)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
