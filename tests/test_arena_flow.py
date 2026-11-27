"""Tests for Arena matches, teams, ladder rankings, and 1v1 town duels."""
from __future__ import annotations

import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.serialization.jser import varuint
from darkblood.games.network import messages


class ArenaFlowTest(ServerTestCase):
    def test_arena_and_duel_lifecycle(self):
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('Gladiator'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # 1. 1v1 Duel Challenge (5100 -> 5101)
            target_uid = 99998888
            client.send_event(5100, messages.DuelRequestReq(target_uid=target_uid).encode())
            _, ack5101 = await client.expect_event(5101)
            self.assertEqual(struct.unpack_from('<iq', ack5101[:12]), (0, target_uid))

            # 2. 1v1 Duel Refusal (5112 -> 5113)
            client.send_event(5112, messages.DuelRefuseReq(challenger_uid=target_uid).encode())
            _, ack5113 = await client.expect_event(5113)
            self.assertEqual(struct.unpack_from('<iq', ack5113[:12]), (0, target_uid))

            # 3. 1v1 Duel Start (5097 -> 5098 ack, then 5099 not)
            client.send_event(5097, messages.DuelStartReq(opponent_uid=target_uid).encode())
            _, ack5098 = await client.expect_event(5098)
            self.assertEqual(struct.unpack_from('<i', ack5098[:4])[0], 0)
            _, not5099 = await client.expect_event(5099)
            self.assertEqual(len(not5099), 36)  # 36-byte duel session blob

            # 4. 1v1 Duel Result (5105 -> 5106)
            client.send_event(5105, messages.DuelResultReq(winner_uid=char_id, loser_uid=target_uid).encode())
            _, ack5106 = await client.expect_event(5106)
            self.assertEqual(struct.unpack_from('<i', ack5106[:4])[0], 0)

            # 5. Arena Square Channel List (2304 -> 2305)
            client.send_event(2304, messages.ArenaSquareListReq(server_key=1).encode())
            _, ack2305 = await client.expect_event(2305)
            self.assertEqual(struct.unpack_from('<i', ack2305[:4])[0], 0)

            # 6. Arena Room List (2306 -> 2307)
            client.send_event(2306, messages.ArenaGetRoomListReq(page=0).encode())
            _, ack2307 = await client.expect_event(2307)
            self.assertEqual(struct.unpack_from('<i', ack2307[:4])[0], 0)

            # 7. Arena Invite List (2308 -> 2309)
            client.send_event(2308, messages.ArenaGetInviteListReq().encode())
            _, ack2309 = await client.expect_event(2309)
            self.assertEqual(struct.unpack_from('<i', ack2309[:4])[0], 0)

            # 8. Arena Team Creation (5269 -> 5270)
            team_name = "BloodHounds"
            encoded_name = team_name.encode('utf-16le')
            name_payload = varuint(len(encoded_name)) + encoded_name + struct.pack('<h', 1)
            client.send_event(5269, name_payload)
            _, ack5270 = await client.expect_event(5270)
            self.assertEqual(struct.unpack_from('<i', ack5270[:4])[0], 0)
            self.assertIn(encoded_name, ack5270)

            # 9. Arena Team Join (5271 -> 5272)
            client.send_event(5271, messages.ArenaTeamJoinReq(team_id=1).encode())
            _, ack5272 = await client.expect_event(5272)
            self.assertEqual(struct.unpack_from('<I', ack5272[:4])[0], 0)
            self.assertEqual(struct.unpack_from('<q', ack5272, 4)[0], 1)

            # 10. Arena Team Leave (5274 -> 5275)
            client.send_event(5274, messages.ArenaTeamLeaveReq().encode())
            _, ack5275 = await client.expect_event(5275)
            self.assertEqual(struct.unpack_from('<i', ack5275[:4])[0], 0)

            # 11. League Season Arena Leaderboard (2550 -> 2551)
            client.send_event(2550, messages.LeagueSeasonArenaGetRankReq(season_id=1).encode())
            _, ack2551 = await client.expect_event(2551)
            self.assertEqual(struct.unpack_from('<i', ack2551[:4])[0], 0)

            # 12. League Season Arena Player Rank (2552 -> 2553)
            client.send_event(2552, messages.LeagueSeasonArenaGetMyRankReq(season_id=1).encode())
            _, ack2553 = await client.expect_event(2553)
            self.assertEqual(struct.unpack_from('<ii', ack2553), (0, 1))

        self.run_async(self.with_server(scenario))

    def test_arena_room_creation_and_membership_flow(self):
        """End-to-end room lifecycle: create room (5153), list rooms (2306), join (5145), leave (5148)."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RoomMaster'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # 1. Create match room (5153 -> 5154)
            room_info = messages.ArenaRoomInfo(
                room_id=10,
                room_name="Champion Colosseum",
                map_id=2,
                game_mode=1,
                max_players=8,
                password="secret",
                notice="Ranked 1v1 Practice"
            )
            client.send_event(5153, messages.ArenaCreateRoomReq(room=room_info).encode())
            _, ack5154 = await client.expect_event(5154)
            created_ack = messages.ArenaCreateRoomAck.decode(ack5154)
            self.assertEqual(created_ack.result, 0)
            self.assertEqual(created_ack.room.room_id, 10)
            self.assertEqual(created_ack.room.room_name, "Champion Colosseum")
            self.assertEqual(created_ack.room.host_uid, char_id)

            # 2. Get Room List (2306 -> 2307) and confirm created room appears
            client.send_event(2306, messages.ArenaGetRoomListReq(page=0).encode())
            _, ack2307 = await client.expect_event(2307)
            room_list_ack = messages.ArenaGetRoomListAck.decode(ack2307)
            self.assertEqual(room_list_ack.result, 0)
            self.assertTrue(any(r.room_id == 10 for r in room_list_ack.rooms))

            # 3. Join Match Room (5145 -> 5146)
            client.send_event(5145, messages.ArenaJoinRoomReq(room_id=10, password="secret").encode())
            _, ack5146 = await client.expect_event(5146)
            join_ack = messages.ArenaJoinRoomAck.decode(ack5146)
            self.assertEqual(join_ack.result, 0)
            self.assertEqual(join_ack.room.room_id, 10)
            self.assertEqual(join_ack.host_uid, char_id)

            # 4. Leave Match Room (5148 -> 5149)
            client.send_event(5148, messages.ArenaLeaveRoomReq().encode())
            _, ack5149 = await client.expect_event(5149)
            leave_ack = messages.ArenaLeaveRoomAck.decode(ack5149)
            self.assertEqual(leave_ack.result, 0)

        self.run_async(self.with_server(scenario))

    def test_joining_a_closed_room_does_not_recreate_it(self):
        from darkblood.games.network import results

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RoomCloser'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            room = messages.ArenaRoomInfo(room_id=23, room_name='Closing Arena')
            client.send_event(5153, messages.ArenaCreateRoomReq(room=room).encode())
            await client.expect_event(5154)
            client.send_event(5148, messages.ArenaLeaveRoomReq().encode())
            await client.expect_event(5149)

            client.send_event(5145, messages.ArenaJoinRoomReq(room_id=23).encode())
            _, joined = await client.expect_event(5146)
            self.assertEqual(messages.ArenaJoinRoomAck.decode(joined).result, results.ROOM_NOT_EXISTS)
            client.send_event(2306, messages.ArenaGetRoomListReq(page=0).encode())
            _, listing = await client.expect_event(2307)
            self.assertEqual(messages.ArenaGetRoomListAck.decode(listing).rooms, [])

        self.run_async(self.with_server(scenario))

    def test_arena_teams_switch_and_management_flow(self):
        """End-to-end team management: create team, leave, join team, switch teams."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('TeamLeader'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # 1. Create first team "Vanguard" (5269 -> 5270)
            client.send_event(5269, messages.ArenaTeamCreateReq(team_name="Vanguard", team_type=1).encode())
            _, ack5270 = await client.expect_event(5270)
            team1_ack = messages.ArenaTeamCreateAck.decode(ack5270)
            self.assertEqual(team1_ack.result, 0)
            self.assertEqual(team1_ack.team_name, "Vanguard")
            self.assertEqual(team1_ack.member_count, 1)
            t1_id = team1_ack.team_id

            # 2. Leave first team (5274 -> 5275)
            client.send_event(5274, messages.ArenaTeamLeaveReq().encode())
            _, ack5275 = await client.expect_event(5275)
            self.assertEqual(struct.unpack_from('<i', ack5275[:4])[0], 0)

            # 3. Create second team "ShadowLegion" (5269 -> 5270)
            client.send_event(5269, messages.ArenaTeamCreateReq(team_name="ShadowLegion", team_type=2).encode())
            _, ack5270_2 = await client.expect_event(5270)
            team2_ack = messages.ArenaTeamCreateAck.decode(ack5270_2)
            self.assertEqual(team2_ack.result, 0)
            self.assertEqual(team2_ack.team_name, "ShadowLegion")
            t2_id = team2_ack.team_id

            # 4. Join back first team (5271 -> 5272)
            client.send_event(5271, messages.ArenaTeamJoinReq(team_id=t1_id).encode())
            _, ack5272 = await client.expect_event(5272)
            join_ack = messages.ArenaTeamJoinAck.decode(ack5272)
            self.assertEqual(join_ack.result, 0)
            self.assertEqual(join_ack.team_id, t1_id)

        self.run_async(self.with_server(scenario))

    def test_league_season_rankings_and_team_flow(self):
        """Exercise league ranks, arena lists, and the arena team lifecycle."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RankChallenger'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # 1. Query Season 1 Leaderboard (2550 -> 2551)
            client.send_event(2550, messages.LeagueSeasonArenaGetRankReq(season_id=1).encode())
            _, ack2551 = await client.expect_event(2551)
            rank_ack = messages.LeagueSeasonArenaGetRankAck.decode(ack2551)
            self.assertEqual(rank_ack.result, 0)
            self.assertEqual(rank_ack.season_id, 1)
            self.assertGreaterEqual(len(rank_ack.ranks), 5)
            self.assertEqual(rank_ack.ranks[0].rank, 1)
            self.assertEqual(rank_ack.ranks[0].char_name, "BloodLord")
            self.assertGreaterEqual(rank_ack.ranks[0].score, 2000)

            # 2. Query Player's Personal Rank (2552 -> 2553)
            client.send_event(2552, messages.LeagueSeasonArenaGetMyRankReq(season_id=1).encode())
            _, ack2553 = await client.expect_event(2553)
            my_rank_ack = messages.LeagueSeasonArenaGetMyRankAck.decode(ack2553)
            self.assertEqual(my_rank_ack.result, 0)
            self.assertGreaterEqual(my_rank_ack.my_rank, 1)

            # 3. Arena Square List (2304 -> 2305)
            client.send_event(2304, messages.ArenaSquareListReq(server_key=1).encode())
            _, ack2305 = await client.expect_event(2305)
            self.assertEqual(struct.unpack_from('<i', ack2305[:4])[0], 0)

            # 4. Arena Room List (2306 -> 2307)
            client.send_event(2306, messages.ArenaGetRoomListReq(page=0).encode())
            _, ack2307 = await client.expect_event(2307)
            self.assertEqual(struct.unpack_from('<i', ack2307[:4])[0], 0)

            # 5. Team Create (5269 -> 5270)
            client.send_event(5269, messages.ArenaTeamCreateReq(team_name="ArenaTeam", team_type=1).encode())
            _, ack5270 = await client.expect_event(5270)
            create_ack = messages.ArenaTeamCreateAck.decode(ack5270)
            self.assertEqual(create_ack.result, 0)
            self.assertEqual(create_ack.team_name, "ArenaTeam")

            # 6. Team Join (5271 -> 5272)
            client.send_event(5271, messages.ArenaTeamJoinReq(team_id=create_ack.team_id).encode())
            _, ack5272 = await client.expect_event(5272)
            join_ack = messages.ArenaTeamJoinAck.decode(ack5272)
            self.assertEqual(join_ack.result, 0)
            self.assertEqual(join_ack.team_id, create_ack.team_id)

            # 7. Team Leave (5274 -> 5275)
            client.send_event(5274, messages.ArenaTeamLeaveReq().encode())
            _, ack5275 = await client.expect_event(5275)
            self.assertEqual(struct.unpack_from('<i', ack5275[:4])[0], 0)

        self.run_async(self.with_server(scenario))

    def test_extended_arena_room_team_and_league_opcodes(self):
        """Test newly recovered Arena square, room, team, random matching, and league charstat opcodes."""
        from darkblood.games.network.messages.arena import (
            ArenaBanishUserAck, ArenaBanishUserReq,
            ArenaChangeRoomCharInfoAck, ArenaChangeRoomCharInfoReq,
            ArenaChangeRoomHostAck, ArenaChangeRoomHostReq,
            ArenaChangeSlotCharInfoAck, ArenaChangeSlotCharInfoReq,
            ArenaChangeTeamInfoAck, ArenaChangeTeamInfoReq,
            ArenaJoinLayerAck, ArenaJoinLayerReq,
            ArenaRandomMatchingRequestAck, ArenaRandomMatchingRequestReq,
            ArenaReadyGameAck, ArenaReadyGameReq,
            ArenaStartGameAck, ArenaStartGameReq,
            ArenaTeamBanishAck, ArenaTeamBanishReq,
            ArenaTeamChangeHostAck, ArenaTeamChangeHostReq,
            LeagueSeasonArenaCharStatInitAck, LeagueSeasonArenaCharStatInitReq,
            LeagueSeasonArenaCharStatUpdateAck, LeagueSeasonArenaCharStatUpdateReq,
        )

        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('ArenaHero', char_class=1))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            client.send_event(5142, ArenaJoinLayerReq(layer_net_id=10).encode())
            _, r = await client.expect_event(5143)
            self.assertEqual(ArenaJoinLayerAck.decode(r).join_layer_net_id, 10)

            client.send_event(5163, ArenaBanishUserReq(target_uid=99).encode())
            _, r = await client.expect_event(5164)
            self.assertEqual(ArenaBanishUserAck.decode(r).result, 0)

            client.send_event(5168, ArenaChangeRoomHostReq(new_host_uid=99).encode())
            _, r = await client.expect_event(5169)
            self.assertEqual(ArenaChangeRoomHostAck.decode(r).new_host_uid, 99)

            client.send_event(5172, ArenaStartGameReq().encode())
            _, r = await client.expect_event(5173)
            self.assertEqual(ArenaStartGameAck.decode(r).result, 0)

            client.send_event(5182, ArenaReadyGameReq(is_ready=True).encode())
            _, r = await client.expect_event(5183)
            self.assertTrue(ArenaReadyGameAck.decode(r).is_ready)

            client.send_event(5202, ArenaRandomMatchingRequestReq(match_type=1).encode())
            _, r = await client.expect_event(5203)
            self.assertEqual(ArenaRandomMatchingRequestAck.decode(r).result, 0)

            client.send_event(5265, ArenaChangeRoomCharInfoReq(team_id=2, is_ready=True).encode())
            _, r = await client.expect_event(5266)
            self.assertEqual(ArenaChangeRoomCharInfoAck.decode(r).team_id, 2)

            client.send_event(5267, ArenaChangeSlotCharInfoReq(slot_idx=1).encode())
            _, r = await client.expect_event(5268)
            self.assertEqual(ArenaChangeSlotCharInfoAck.decode(r).result, 0)

            client.send_event(5282, ArenaTeamBanishReq(target_uid=99).encode())
            _, r = await client.expect_event(5283)
            self.assertEqual(ArenaTeamBanishAck.decode(r).result, 0)

            client.send_event(5286, ArenaTeamChangeHostReq(new_host_uid=99).encode())
            _, r = await client.expect_event(5287)
            self.assertEqual(ArenaTeamChangeHostAck.decode(r).new_host_uid, 99)

            client.send_event(5301, ArenaChangeTeamInfoReq(team_type=2, team_name='Titans').encode())
            _, r = await client.expect_event(5302)
            ack = ArenaChangeTeamInfoAck.decode(r)
            self.assertEqual((ack.result, ack.team_type, ack.team_name), (0, 2, 'Titans'))

            client.send_event(2556, LeagueSeasonArenaCharStatUpdateReq(season_stat={'STR': 5}).encode())
            _, r = await client.expect_event(2557)
            self.assertEqual(LeagueSeasonArenaCharStatUpdateAck.decode(r).season_stat.get('STR'), 5)

            client.send_event(2561, LeagueSeasonArenaCharStatInitReq().encode())
            _, r = await client.expect_event(2562)
            self.assertEqual(LeagueSeasonArenaCharStatInitAck.decode(r).result, 0)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
