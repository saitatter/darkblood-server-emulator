"""Automated flow tests for Multiplayer Spatial Movement and Party Management (Milestone P6)."""
import struct
import unittest

from tests.common import ServerTestCase, create_request, lobby_flow
from darkblood.core.serialization.jser import event
from darkblood.games.network.messages.party import (
    PartyAcceptInviteAck, PartyAcceptInviteNot, PartyAcceptInviteReq,
    LegacyPartyInviteReq, PartyInviteAck, PartyInviteNot, PartyInviteReq,
    PartyJoinAck, PartyJoinReq, PartyKickAck, PartyKickReq,
    PartyLeaveAck, PartyLeaveReq, UserJoinSquareNot, UserLeaveSquareNot
)
from darkblood.games.world import GameWorldManager, PartyManager
from headless_client import HeadlessClient


class PartyWireMessagesTest(unittest.TestCase):
    """Unit tests for spatial movement and party wire message serialization."""

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

        self.assertEqual(LegacyPartyInviteReq.decode(LegacyPartyInviteReq(target_uid=7777).encode()).target_uid, 7777)

        inv_ack = PartyInviteAck(result=0).encode()
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

        acc_ack = PartyAcceptInviteAck(result=0).encode()
        self.assertEqual(PartyAcceptInviteAck.decode(acc_ack).result, 0)

        acc_not = PartyAcceptInviteNot(party_id=1, member_uid=7777, member_name='WarriorY', is_leader=False).encode()
        dec_acc_not = PartyAcceptInviteNot.decode(acc_not)
        self.assertEqual(dec_acc_not.party_id, 1)
        self.assertEqual(dec_acc_not.member_uid, 7777)
        self.assertEqual(dec_acc_not.member_name, 'WarriorY')
        self.assertFalse(dec_acc_not.is_leader)


class MultiplayerAndPartyFlowTest(ServerTestCase):
    """End-to-end integration flow tests with multi-client network sessions."""

    def test_town_join_and_leave_notifications(self):
        """Verify the server announces peers joining and leaving a town square."""
        async def scenario(client1):
            world = GameWorldManager._instance = GameWorldManager()

            # Client 1 joins square as "Runner1"
            await lobby_flow(client1)
            client1.send_event(2012, create_request('Runner1', char_class=1))
            _, created1 = await client1.expect_event(2013)
            char_id1 = struct.unpack_from('<Q', created1, 10)[0]
            client1.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id1))
            await client1.expect_event(2007)
            await client1.expect_event(2410)
            # The town has loaded (5124): peers already there are sent now.
            client1.send_event(5124, struct.pack('<i', 0x7fffffff))
            await client1.expect_event(5125)

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
                # The town has loaded (5124): peers already there are sent now.
                client2.send_event(5124, struct.pack('<i', 0x7fffffff))
                await client2.expect_event(5125)

                # Client 1 gets the join notification (5021) at Watcher2's 2006, then
                # the layer spawn (5027, 5096) once Watcher2 is ready for town peers.
                _, join_payload = await client1.expect_event(5021)
                join_not = UserJoinSquareNot.decode(join_payload)
                self.assertEqual(join_not.char_id, char_id2)
                self.assertEqual(join_not.char_name, 'Watcher2')
                await client1.expect_event(5027)
                await client1.expect_event(5096)

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
            world = GameWorldManager._instance = GameWorldManager()
            pm = PartyManager.get()
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
            # The town has loaded (5124): peers already there are sent now.
            client1.send_event(5124, struct.pack('<i', 0x7fffffff))
            await client1.expect_event(5125)

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
                # The town has loaded (5124): peers already there are sent now.
                client2.send_event(5124, struct.pack('<i', 0x7fffffff))
                await client2.expect_event(5125)

                await lobby_flow(client3)
                client3.send_event(2012, create_request('Hero3', char_class=3))
                _, created3 = await client3.expect_event(2013)
                char_id3 = struct.unpack_from('<Q', created3, 10)[0]
                client3.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id3))
                await client3.expect_event(2007)
                await client3.expect_event(2410)
                # The town has loaded (5124): peers already there are sent now.
                client3.send_event(5124, struct.pack('<i', 0x7fffffff))
                await client3.expect_event(5125)

                # Acceptance by host UID cannot create a party on its own.
                client3.send_event(5054, PartyAcceptInviteReq(host_uid=char_id1).encode())
                _, rejection = await client3.expect_event(5055)
                self.assertNotEqual(PartyAcceptInviteAck.decode(rejection).result, 0)
                self.assertIsNone(pm.get_player_party(char_id1))

                # Drain 5021 join notifications from clients
                # 1. Leader (Client 1) invites Client 2 via Opcode 2100 (eEGS_PARTY_INVITE_REQ)
                # The client addresses peers by UID with the server key (31) in bits 54-58.
                client1.send_event(2100, LegacyPartyInviteReq(target_uid=(0x1F << 54) | char_id2).encode())
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

                # A known party ID is not an invitation to that party.
                client3.send_event(2102, PartyJoinReq(party_id=party.party_id).encode())
                _, rejection = await client3.expect_event(2103)
                self.assertNotEqual(PartyJoinAck.decode(rejection).result, 0)
                self.assertEqual(set(party.members), {char_id1, char_id2})

                # 3. Leader invites Client 3 by nickname via Opcode 5092
                # (eERC_INVITE_USE_NICK_REQ, prefix + J-wstring); the result is a 5050.
                # J-wstring length is a byte-count varint (bit 7 ends it): 6 -> 0x86.
                client1.send_event(5092, bytes.fromhex('ffffff7f') + bytes([0x86]) + 'Hero3'[:3].encode('utf-16le'))
                _, unknown = await client1.expect_event(5050)
                self.assertNotEqual(PartyInviteAck.decode(unknown).result, 0)  # "Her" is no character
                client1.send_event(5092, bytes.fromhex('ffffff7f') + bytes([0x8a]) + 'Hero3'.encode('utf-16le'))
                _, ack5050 = await client1.expect_event(5050)
                inv_ack5050 = PartyInviteAck.decode(ack5050)
                self.assertEqual(inv_ack5050.result, 0)

                # Client 3 receives Opcode 5051
                _, not5051_c3 = await client3.expect_event(5051)
                self.assertEqual(PartyInviteNot.decode(not5051_c3).inviter_uid, char_id1)

                # 5054 carries the host's square UID before its character UID.
                client3.send_event(5054, struct.pack('<iqq', 0x7fffffff, 0x12345678, char_id1))
                _, ack5055 = await client3.expect_event(5055)
                self.assertEqual(PartyAcceptInviteAck.decode(ack5055).result, 0)

                # Party now has 3 members
                self.assertEqual(len(party.members), 3)
                self.assertIn(char_id3, party.members)
                client3.send_event(5054, PartyAcceptInviteReq(host_uid=char_id1).encode())
                _, replay = await client3.expect_event(5055)
                self.assertNotEqual(PartyAcceptInviteAck.decode(replay).result, 0)
                self.assertEqual(set(party.members), {char_id1, char_id2, char_id3})

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
