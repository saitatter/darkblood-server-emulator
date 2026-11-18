"""Automated flow tests for Multiplayer Spatial Movement and Party Management (Milestone P6)."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.serialization.jser import event
from darkblood.games.network.messages.party import (
    PartyAcceptInviteAck, PartyAcceptInviteNot, PartyAcceptInviteReq,
    PartyInviteAck, PartyInviteNot, PartyInviteReq,
    PartyJoinAck, PartyJoinReq, PartyKickAck, PartyKickReq,
    PartyLeaveAck, PartyLeaveReq, UserJoinSquareNot, UserLeaveSquareNot, UserMoveNot
)
from darkblood.games.world import GameWorldManager, PartyManager
from headless_client import HeadlessClient


class PartyWireMessagesTest(unittest.TestCase):
    """Unit tests for spatial movement and party wire message serialization."""

    def test_user_move_message_roundtrip(self):
        # 1. Full 28-byte packet
        msg = UserMoveNot(char_id=1001, x=123.5, y=-456.25, z=78.0, angle=1.57, move_state=2)
        encoded = msg.encode()
        self.assertEqual(len(encoded), 28)

        decoded = UserMoveNot.decode(encoded)
        self.assertEqual(decoded.char_id, 1001)
        self.assertAlmostEqual(decoded.x, 123.5, places=3)
        self.assertAlmostEqual(decoded.y, -456.25, places=3)
        self.assertAlmostEqual(decoded.z, 78.0, places=3)
        self.assertAlmostEqual(decoded.angle, 1.57, places=2)
        self.assertEqual(decoded.move_state, 2)

        # 2. 20-byte packet with 0x7FFFFFFF prefix
        raw_prefix = b'\xff\xff\xff\x7f' + struct.pack('<ffffi', 10.0, 20.0, 30.0, 0.5, 1)
        dec_prefix = UserMoveNot.decode(raw_prefix)
        self.assertAlmostEqual(dec_prefix.x, 10.0, places=3)
        self.assertAlmostEqual(dec_prefix.y, 20.0, places=3)
        self.assertAlmostEqual(dec_prefix.z, 30.0, places=3)
        self.assertAlmostEqual(dec_prefix.angle, 0.5, places=2)
        self.assertEqual(dec_prefix.move_state, 1)

    def test_user_join_and_leave_square_messages(self):
        # Join message
        join = UserJoinSquareNot(char_id=2002, square_id=1, x=50.0, y=60.0, z=70.0,
                                 angle=3.14, char_class=2, level=25, char_name='Paladin')
        enc_join = join.encode()
        dec_join = UserJoinSquareNot.decode(enc_join)
        self.assertEqual(dec_join.char_id, 2002)
        self.assertEqual(dec_join.square_id, 1)
        self.assertAlmostEqual(dec_join.x, 50.0, places=2)
        self.assertAlmostEqual(dec_join.y, 60.0, places=2)
        self.assertAlmostEqual(dec_join.z, 70.0, places=2)
        self.assertEqual(dec_join.char_class, 2)
        self.assertEqual(dec_join.level, 25)
        self.assertEqual(dec_join.char_name, 'Paladin')

        # Leave message
        leave = UserLeaveSquareNot(char_id=2002, reason=0)
        enc_leave = leave.encode()
        dec_leave = UserLeaveSquareNot.decode(enc_leave)
        self.assertEqual(dec_leave.char_id, 2002)
        self.assertEqual(dec_leave.reason, 0)

    def test_party_management_messages(self):
        # Party invite req / ack / not
        inv_req = PartyInviteReq(target_uid=7777)
        self.assertEqual(PartyInviteReq.decode(inv_req.encode()).target_uid, 7777)

        inv_ack = PartyInviteAck(result=0, target_uid=7777).encode()
        self.assertEqual(PartyInviteAck.decode(inv_ack).result, 0)

        inv_not = PartyInviteNot(inviter_uid=6666, inviter_square_uid=4, inviter_name='LeaderX').encode()
        self.assertEqual(inv_not, (
            bytes.fromhex('00 0400000000000000 0a1a000000000000 00000000 8e')
            + 'LeaderX'.encode('utf-16le')
            + bytes.fromhex('00ffff00') + b'\xff' * 16 + b'\x00' * 83
            + b'\x80' + b'\xff' * 10
        ))
        dec_not = PartyInviteNot.decode(inv_not)
        self.assertEqual(dec_not.inviter_uid, 6666)
        self.assertEqual(dec_not.inviter_square_uid, 4)
        self.assertEqual(dec_not.inviter_name, 'LeaderX')

        # Join req / ack
        join_req = PartyJoinReq(party_id=1, host_uid=6666).encode()
        dec_join = PartyJoinReq.decode(join_req)
        self.assertEqual(dec_join.party_id, 1)
        self.assertEqual(dec_join.host_uid, 6666)

        join_ack = PartyJoinAck(result=0, party_id=1).encode()
        self.assertEqual(PartyJoinAck.decode(join_ack).party_id, 1)

        # Leave req / ack
        leave_req = PartyLeaveReq(party_id=1).encode()
        self.assertEqual(PartyLeaveReq.decode(leave_req).party_id, 1)
        leave_ack = PartyLeaveAck(result=0).encode()
        self.assertEqual(PartyLeaveAck.decode(leave_ack).result, 0)

        # Kick req / ack
        kick_req = PartyKickReq(target_uid=8888, party_id=1).encode()
        dec_kick = PartyKickReq.decode(kick_req)
        self.assertEqual(dec_kick.target_uid, 8888)
        self.assertEqual(dec_kick.party_id, 1)

        kick_ack = PartyKickAck(result=0, target_uid=8888).encode()
        dec_kick_ack = PartyKickAck.decode(kick_ack)
        self.assertEqual(dec_kick_ack.result, 0)
        self.assertEqual(dec_kick_ack.target_uid, 8888)

        # Accept invite req / ack / not
        acc_req = PartyAcceptInviteReq(host_uid=6666).encode()
        self.assertEqual(PartyAcceptInviteReq.decode(acc_req).host_uid, 6666)

        acc_ack = PartyAcceptInviteAck(result=0, party_id=1).encode()
        self.assertEqual(PartyAcceptInviteAck.decode(acc_ack).result, 0)

        acc_not = PartyAcceptInviteNot(party_id=1, member_uid=7777, member_name='WarriorY', is_leader=False).encode()
        dec_acc_not = PartyAcceptInviteNot.decode(acc_not)
        self.assertEqual(dec_acc_not.party_id, 1)
        self.assertEqual(dec_acc_not.member_uid, 7777)
        self.assertEqual(dec_acc_not.member_name, 'WarriorY')
        self.assertFalse(dec_acc_not.is_leader)


class MultiplayerAndPartyFlowTest(ServerTestCase):
    """End-to-end integration flow tests with multi-client network sessions."""

    def test_multiplayer_movement_and_spatial_broadcast(self):
        """Verify Opcode 5030 / 5031 movement decoding and spatial broadcasting to nearby peers."""
        async def scenario(client1):
            world = GameWorldManager.get()
            world.players.clear()
            world.squares.clear()

            # Client 1 joins square as "Runner1"
            await lobby_flow(client1)
            client1.send_event(2012, create_request('Runner1', char_class=1))
            _, created1 = await client1.expect_event(2013)
            char_id1 = struct.unpack_from('<Q', created1, 10)[0]
            client1.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id1))
            await client1.expect_event(2007)
            await client1.expect_event(2410)

            # Client 2 joins square as "Watcher2"
            client2 = HeadlessClient(port=client1.port)
            try:
                await lobby_flow(client2)
                client2.send_event(2012, create_request('Watcher2', char_class=2))
                _, created2 = await client2.expect_event(2013)
                char_id2 = struct.unpack_from('<Q', created2, 10)[0]
                client2.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id2))
                await client2.expect_event(2007)
                await client2.expect_event(2410)

                # Client 1 should receive layer spawn (5027, 5096) and join notification (5021) for Watcher2
                await client1.expect_event(5027)
                await client1.expect_event(5096)
                _, join_payload = await client1.expect_event(5021)
                join_not = UserJoinSquareNot.decode(join_payload)
                self.assertEqual(join_not.char_id, char_id2)
                self.assertEqual(join_not.char_name, 'Watcher2')

                # Client 1 moves: sends Opcode 5030 with coordinates
                move_req = UserMoveNot(char_id=char_id1, x=150.0, y=250.0, z=35.0, angle=1.2, move_state=1)
                client1.send_event(5030, move_req.encode())

                # Client 2 should receive movement broadcast (Opcode 5031)
                _, move_broadcast = await client2.expect_event(5031)
                moved_peer = UserMoveNot.decode(move_broadcast)
                self.assertEqual(moved_peer.char_id, char_id1)
                self.assertAlmostEqual(moved_peer.x, 150.0, places=2)
                self.assertAlmostEqual(moved_peer.y, 250.0, places=2)
                self.assertAlmostEqual(moved_peer.z, 35.0, places=2)
                self.assertAlmostEqual(moved_peer.angle, 1.2, places=2)
                self.assertEqual(moved_peer.move_state, 1)

                # Verify position was updated in GameWorldManager
                p1 = world.get_player(char_id1)
                self.assertAlmostEqual(p1.x, 150.0, places=2)
                self.assertAlmostEqual(p1.y, 250.0, places=2)

                # Now Client 2 sends Opcode 5031 directly
                move_req2 = UserMoveNot(char_id=char_id2, x=500.0, y=600.0, z=0.0, angle=3.0, move_state=0)
                client2.send_event(5031, move_req2.encode())

                # Client 1 receives Client 2's movement
                _, move_bcast2 = await client1.expect_event(5031)
                moved_peer2 = UserMoveNot.decode(move_bcast2)
                self.assertEqual(moved_peer2.char_id, char_id2)
                self.assertAlmostEqual(moved_peer2.x, 500.0, places=2)

                # Client 2 leaves square (Opcode 5032)
                client2.send_event(5032, b'')
                await client2.expect_event(5033)

                # Client 1 should receive leave notification (Opcode 5022)
                _, leave_payload = await client1.expect_event(5022)
                leave_not = UserLeaveSquareNot.decode(leave_payload)
                self.assertEqual(leave_not.char_id, char_id2)
            finally:
                await client2.close()

            world.unregister_player(char_id1)

        self.run_async(self.with_server(scenario))

    def test_party_lifecycle_invite_join_leave_kick(self):
        """End-to-end party management flow across multiple connected clients."""
        async def scenario(client1):
            world = GameWorldManager.get()
            pm = PartyManager.get()
            world.players.clear()
            world.squares.clear()
            pm.parties.clear()
            pm.player_party.clear()

            # Client 1: Party Leader "Hero1"
            await lobby_flow(client1)
            client1.send_event(2012, create_request('Hero1', char_class=1))
            _, created1 = await client1.expect_event(2013)
            char_id1 = struct.unpack_from('<Q', created1, 10)[0]
            client1.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id1))
            await client1.expect_event(2007)
            await client1.expect_event(2410)

            # Client 2: Member "Hero2"
            client2 = HeadlessClient(port=client1.port)
            # Client 3: Member "Hero3"
            client3 = HeadlessClient(port=client1.port)

            try:
                await lobby_flow(client2)
                client2.send_event(2012, create_request('Hero2', char_class=2))
                _, created2 = await client2.expect_event(2013)
                char_id2 = struct.unpack_from('<Q', created2, 10)[0]
                client2.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id2))
                await client2.expect_event(2007)
                await client2.expect_event(2410)

                await lobby_flow(client3)
                client3.send_event(2012, create_request('Hero3', char_class=3))
                _, created3 = await client3.expect_event(2013)
                char_id3 = struct.unpack_from('<Q', created3, 10)[0]
                client3.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id3))
                await client3.expect_event(2007)
                await client3.expect_event(2410)

                # Drain 5021 join notifications from clients
                # 1. Leader (Client 1) invites Client 2 via Opcode 2100 (eEGS_PARTY_INVITE_REQ)
                client1.send_event(2100, PartyInviteReq(target_uid=char_id2).encode())
                _, ack2101 = await client1.expect_event(2101)
                inv_ack = PartyInviteAck.decode(ack2101)
                self.assertEqual(inv_ack.result, 0)

                # Client 2 should receive Opcode 5051 (eERC_INVITE_NOT)
                _, not5051 = await client2.expect_event(5051)
                inv_not = PartyInviteNot.decode(not5051)
                self.assertEqual(inv_not.inviter_uid, char_id1)

                # 2. Client 2 accepts invite via Opcode 2102 (eEGS_PARTY_JOIN_REQ)
                client2.send_event(2102, PartyJoinReq(host_uid=inv_not.inviter_uid).encode())
                _, ack2103 = await client2.expect_event(2103)
                join_ack = PartyJoinAck.decode(ack2103)
                self.assertEqual(join_ack.result, 0)

                # Client 1 should receive Opcode 5056 notification of Client 2 joining
                _, not5056 = await client1.expect_event(5056)
                acc_not = PartyAcceptInviteNot.decode(not5056)
                self.assertEqual(acc_not.member_uid, char_id2)

                # Verify party membership in PartyManager
                party = pm.get_player_party(char_id1)
                self.assertIsNotNone(party)
                self.assertEqual(len(party.members), 2)
                self.assertEqual(party.leader_id, char_id1)
                self.assertIn(char_id2, party.members)

                # 3. Leader invites Client 3 via Opcode 5049 (eERC_INVITE_REQ)
                client1.send_event(5049, PartyInviteReq(target_uid=char_id3).encode())
                _, ack5050 = await client1.expect_event(5050)
                inv_ack5050 = PartyInviteAck.decode(ack5050)
                self.assertEqual(inv_ack5050.result, 0)

                # Client 3 receives Opcode 5051
                _, not5051_c3 = await client3.expect_event(5051)
                self.assertEqual(PartyInviteNot.decode(not5051_c3).inviter_uid, char_id1)

                # Client 3 accepts via Opcode 5054 (eERC_ACCEPT_INVITE_REQ)
                client3.send_event(5054, PartyAcceptInviteReq(host_uid=char_id1).encode())
                _, ack5055 = await client3.expect_event(5055)
                self.assertEqual(PartyAcceptInviteAck.decode(ack5055).result, 0)

                # Party now has 3 members
                self.assertEqual(len(party.members), 3)
                self.assertIn(char_id3, party.members)

                # 4. Non-leader (Client 2) tries to kick Client 3 -> should be rejected
                client2.send_event(2106, PartyKickReq(target_uid=char_id3, party_id=party.party_id).encode())
                _, kick_rej = await client2.expect_event(2107)
                self.assertNotEqual(PartyKickAck.decode(kick_rej).result, 0)
                self.assertIn(char_id3, party.members)

                # 5. Leader (Client 1) kicks Client 3 via Opcode 2106
                client1.send_event(2106, PartyKickReq(target_uid=char_id3, party_id=party.party_id).encode())
                _, kick_ack = await client1.expect_event(2107)
                self.assertEqual(PartyKickAck.decode(kick_ack).result, 0)

                # Client 3 receives kick leave notification (Opcode 2105)
                _, kick_leave = await client3.expect_event(2105)
                self.assertEqual(PartyLeaveAck.decode(kick_leave).result, 0)
                self.assertNotIn(char_id3, party.members)
                self.assertEqual(len(party.members), 2)

                # 6. Leader leaves party via Opcode 2104 (eEGS_PARTY_LEAVE_REQ)
                client1.send_event(2104, PartyLeaveReq(party_id=party.party_id).encode())
                _, leave_ack = await client1.expect_event(2105)
                self.assertEqual(PartyLeaveAck.decode(leave_ack).result, 0)

                # Client 2 should be promoted to leader!
                party_c2 = pm.get_player_party(char_id2)
                self.assertIsNotNone(party_c2)
                self.assertEqual(party_c2.leader_id, char_id2)
                self.assertTrue(party_c2.members[char_id2].is_leader)

                # 7. Last member (Client 2) leaves party -> party is disbanded
                client2.send_event(2104, PartyLeaveReq(party_id=party_c2.party_id).encode())
                _, leave_ack2 = await client2.expect_event(2105)
                self.assertEqual(PartyLeaveAck.decode(leave_ack2).result, 0)
                self.assertIsNone(pm.get_player_party(char_id2))
                self.assertIsNone(pm.get_party(party_c2.party_id))
            finally:
                await client2.close()
                await client3.close()

            world.unregister_player(char_id1)

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
