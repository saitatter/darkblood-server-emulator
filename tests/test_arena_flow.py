"""Tests for Arena matches, teams, ladder rankings, and 1v1 town duels."""
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


if __name__ == '__main__':
    unittest.main()
