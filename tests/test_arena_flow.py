"""Tests for Arena matches, teams, ladder rankings, and 1v1 town duels."""
from __future__ import annotations

import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.serialization.jser import varuint
from darkblood.games.handlers.arena.league import league_ladder
from darkblood.games.network import messages
from darkblood.games.session import GameSession


class LeagueLadderTest(unittest.TestCase):
    def test_placement_and_order(self):
        def char(cid, rating, wins, losses=0, draws=0):
            return dict(id=cid, name=f'C{cid}', level=30, char_class=2, league_arena=dict(
                rating=rating, win_count=wins, lose_count=losses, draw_count=draws))
        ladder = league_ladder([
            char(1, 1500, 5, 4),           # 9 games: still in placement
            char(2, 1500, 10),             # ties on rating: more wins first
            char(3, 1500, 7, 3),
            char(4, 1800, 3, 6, 1),
            dict(id=5, name='NoRecord'),   # never played
        ])
        self.assertEqual([(e.rank, e.char_uid) for e in ladder], [(1, 4), (2, 2), (3, 3)])
        self.assertEqual((ladder[0].char_class, ladder[0].char_level, ladder[0].draws), (2, 30, 1))


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
            client.send_event(2012, create_request('DuelMage', char_class=3))
            _, target = await client.expect_event(2013)
            target_uid = struct.unpack_from('<Q', target, 10)[0]
            client.send_event(5100, messages.DuelRequestReq(target_uid=target_uid).encode())
            _, ack5101 = await client.expect_event(5101)
            duel = messages.DuelRequestAck.decode(ack5101)
            self.assertEqual((duel.result, duel.target_uid, duel.target_name, duel.char_class, duel.level),
                             (0, target_uid, 'DuelMage', 3, 1))

            # 2. 1v1 Duel Refusal (5112 -> 5113)
            client.send_event(5112, messages.DuelRefuseReq(challenger_uid=target_uid).encode())
            _, ack5113 = await client.expect_event(5113)
            refused = messages.DuelRefuseAck.decode(ack5113)
            self.assertEqual((refused.result, refused.target_uid, refused.target_name,
                              refused.char_class, refused.level), (0, target_uid, 'DuelMage', 3, 1))

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

            # 12. League Season Arena Player Rank (2552 -> 2553): a new character is in placement
            client.send_event(2552, messages.LeagueSeasonArenaGetMyRankReq(season_id=1).encode())
            _, ack2553 = await client.expect_event(2553)
            self.assertEqual(struct.unpack_from('<ii', ack2553), (0, -1))

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

            from headless_client import HeadlessClient

            guest = HeadlessClient(port=client.port)
            try:
                await lobby_flow(guest)
                guest.send_event(2012, create_request('ArenaRoomGuest'))
                _, guest_created = await guest.expect_event(2013)
                guest_id = struct.unpack_from('<Q', guest_created, 10)[0]
                guest.send_event(2006, struct.pack('<iQ', 0x7fffffff, guest_id))
                await guest.expect_event(2007)
                guest.send_event(5145, messages.ArenaJoinRoomReq(room_id=10, password="secret").encode())
                await guest.expect_event(5146)

                client.send_event(5148, messages.ArenaLeaveRoomReq().encode())
                _, ack5149 = await client.expect_event(5149)
                self.assertEqual(messages.ArenaLeaveRoomAck.decode(ack5149).result, 0)

                guest.send_event(2306, messages.ArenaGetRoomListReq(page=0).encode())
                _, remaining = await guest.expect_event(2307)
                room = next(r for r in messages.ArenaGetRoomListAck.decode(remaining).rooms if r.room_id == 10)
                self.assertEqual(room.host_uid, guest_id)
            finally:
                await guest.close()

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
            self.assertEqual(join_ack.member_count, 1)

            client.send_event(5271, messages.ArenaTeamJoinReq(team_id=t1_id).encode())
            _, retry = await client.expect_event(5272)
            self.assertEqual(messages.ArenaTeamJoinAck.decode(retry).member_count, 1)

            client.send_event(5271, messages.ArenaTeamJoinReq(team_id=t2_id).encode())
            _, returned = await client.expect_event(5272)
            self.assertEqual(messages.ArenaTeamJoinAck.decode(returned).member_count, 1)

        self.run_async(self.with_server(scenario))

    def test_league_season_rankings_and_team_flow(self):
        """Exercise league ranks, arena lists, and the arena team lifecycle."""
        async def scenario(client):
            await lobby_flow(client)
            client.send_event(2012, create_request('RankChallenger'))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2012, create_request('RankLeader'))
            _, created2 = await client.expect_event(2013)
            leader_id = struct.unpack_from('<Q', created2, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)

            # Two stored characters past placement; the ladder is built from them.
            store = GameSession.store()
            store.get('OfflinePlayer', leader_id)['league_arena'] = dict(
                rating=1700, win_count=12, lose_count=3, draw_count=0, win_streak=4)
            store.get('OfflinePlayer', char_id)['league_arena'] = dict(
                rating=1450, win_count=6, lose_count=4, draw_count=1)
            store.save()

            # 1. Query the ladder (2550 -> 2551): page index echoed, ordered by rating
            client.send_event(2550, messages.LeagueSeasonArenaGetRankReq(season_id=1).encode())
            _, ack2551 = await client.expect_event(2551)
            rank_ack = messages.LeagueSeasonArenaGetRankAck.decode(ack2551)
            self.assertEqual(rank_ack.result, 0)
            self.assertEqual(rank_ack.season_id, 1)
            self.assertEqual([(e.rank, e.char_name) for e in rank_ack.ranks],
                             [(1, 'RankLeader'), (2, 'RankChallenger')])
            leader = rank_ack.ranks[0]
            self.assertEqual((leader.char_uid, leader.server_id, leader.wins, leader.losses,
                              leader.rating, leader.win_streak), (leader_id, 1, 12, 3, 1700, 4))

            # 2. Query Player's Personal Rank (2552 -> 2553)
            client.send_event(2552, messages.LeagueSeasonArenaGetMyRankReq(season_id=1).encode())
            _, ack2553 = await client.expect_event(2553)
            my_rank_ack = messages.LeagueSeasonArenaGetMyRankAck.decode(ack2553)
            self.assertEqual(my_rank_ack.result, 0)
            self.assertEqual(my_rank_ack.my_rank, 2)

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

            client.send_event(5269, messages.ArenaTeamCreateReq(team_name='Challengers', team_type=1).encode())
            _, created_team = await client.expect_event(5270)
            team_id = messages.ArenaTeamCreateAck.decode(created_team).team_id

            client.send_event(5301, ArenaChangeTeamInfoReq(team_type=2, team_name='Titans').encode())
            _, r = await client.expect_event(5302)
            ack = ArenaChangeTeamInfoAck.decode(r)
            self.assertEqual((ack.result, ack.team_type, ack.team_name), (0, 2, 'Titans'))

            client.send_event(5271, messages.ArenaTeamJoinReq(team_id=team_id).encode())
            _, joined_team = await client.expect_event(5272)
            team = messages.ArenaTeamJoinAck.decode(joined_team)
            self.assertEqual((team.result, team.team_type, team.team_name), (0, 2, 'Titans'))

            client.send_event(2556, LeagueSeasonArenaCharStatUpdateReq(season_stat={'STR': 5}).encode())
            _, r = await client.expect_event(2557)
            self.assertEqual(LeagueSeasonArenaCharStatUpdateAck.decode(r).season_stat.get('STR'), 5)

            client.send_event(2561, LeagueSeasonArenaCharStatInitReq().encode())
            _, r = await client.expect_event(2562)
            self.assertEqual(LeagueSeasonArenaCharStatInitAck.decode(r).result, 0)

        self.run_async(self.with_server(scenario))


    def test_arena_room_creation_with_occupied_ids(self):
        from headless_client import HeadlessClient

        async def create_room(client, name, room_id):
            await lobby_flow(client)
            client.send_event(2012, create_request(name))
            _, created = await client.expect_event(2013)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            await client.expect_event(2007)
            room = messages.ArenaRoomInfo(room_id=room_id, room_name=name)
            client.send_event(5153, messages.ArenaCreateRoomReq(room=room).encode())
            _, reply = await client.expect_event(5154)
            ack = messages.ArenaCreateRoomAck.decode(reply)
            self.assertEqual(ack.result, 0)
            return ack.room

        async def scenario(client):
            first_room = await create_room(client, 'FirstRoom', 1)
            second_client = HeadlessClient(port=client.port)
            third_client = HeadlessClient(port=client.port)
            try:
                second_room = await create_room(second_client, 'SecondRoom', 1)
                third_room = await create_room(third_client, 'ThirdRoom', 0)
                self.assertEqual(first_room.room_id, 1)
                self.assertEqual(len({first_room.room_id, second_room.room_id, third_room.room_id}), 3)

                client.send_event(2306, messages.ArenaGetRoomListReq().encode())
                _, reply = await client.expect_event(2307)
                rooms = messages.ArenaGetRoomListAck.decode(reply).rooms
                self.assertEqual(
                    {room.room_id: (room.room_name, room.host_uid) for room in rooms},
                    {room.room_id: (room.room_name, room.host_uid)
                     for room in (first_room, second_room, third_room)},
                )
            finally:
                await third_client.close()
                await second_client.close()

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
