"""Tests for dungeon gameplay: layer transition, combat events, deaths, and rank reward choices."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow, wide
from darkblood.core import hashing
from darkblood.games import session
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

            # 1. Map transition / Gate (2344 -> 2345)
            client.send_event(2344, bytes.fromhex('ffffff7f00000000aeaf985f'))
            _, ack2345 = await client.expect_event(2345)
            self.assertEqual(struct.unpack_from('<IQQ', ack2345), (0, hashing.jhash('Act1') << 32, 1))

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

            # 10. Choice reward party rank (5090 -> 5091)
            client.send_event(5090, struct.pack('<ii', 0x7fffffff, 0))
            _, ack5091 = await client.expect_event(5091)
            self.assertEqual(struct.unpack_from('<iq', ack5091)[:2], (0, char['id']))

            # 10b. Leave room (5005 -> 5006)
            client.send_event(5005, b'')
            _, ack5006 = await client.expect_event(5006)
            self.assertEqual(struct.unpack_from('<i', ack5006)[0], 0)

            # 11. Back to square (5045 -> 5046)
            client.send_event(5045, struct.pack('<i', 0x7fffffff))
            _, ack5046 = await client.expect_event(5046)
            self.assertEqual(struct.unpack_from('<i', ack5046)[0], 0)

            # 12. Party invite (5049 -> 5050)
            client.send_event(5049, PartyInviteReq(target_uid=12345).encode())
            _, ack5050 = await client.expect_event(5050)
            self.assertEqual(struct.unpack_from('<i', ack5050)[0], 0)

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

            client.send_event(2441, CharSlotExtendReq(item_uid=900).encode())
            _, r = await client.expect_event(2442)
            self.assertEqual(struct.unpack_from('<IB', r), (0, 6))

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


if __name__ == '__main__':
    unittest.main()
