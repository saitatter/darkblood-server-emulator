"""Tests for relay server handshake and isolation."""
import asyncio
from collections import deque
import struct
import unittest
from unittest.mock import patch

from tests.common import ServerTestCase
from darkblood.core.network.proudnet import read_scalar, scalar
from darkblood.core.serialization.jser import JSerBufferReader
from headless_client import HeadlessClient


class RelayFlowTest(ServerTestCase):
    def test_join_group_ack_roster_matches_client_reader(self):
        # Reader 0x0090DD90: 0x10, varuint count, then u64 UID + i32 HostID per
        # member with no pair byte. Live, a 0x0F byte made the client key UID 3
        # as 0x30F, so JP2PClient::SendTo never found the peer.
        from darkblood.frontend.relay import join_group_ack
        ack = join_group_ack(0x10007, [(2, 0x23), (3, 0x22)])
        roster = (b'\x10\x82' + struct.pack('<QI', 2, 0x23) + struct.pack('<QI', 3, 0x22))
        self.assertEqual(ack, b'\x01' + struct.pack('<HI', 3001, 0x10007) + scalar(len(roster)) + roster)

    def test_relay_handshake_without_welcome(self):
        async def scenario(client):
            await client.connect()
            client.send_event(2131)
            try:
                payload = await asyncio.wait_for(client.expect(0x02), 0.5)
            except asyncio.TimeoutError:
                payload = None
            return payload

        self.assertIsNone(self.run_async(self.with_server(scenario, role='relay')))

    def test_group_switch_isolates_rosters_and_forwarding(self):
        layer_a = bytes.fromhex('00000000 0100000000000000 01000000aeaf985f 0000000000000000')
        layer_b = bytes.fromhex('00000000 0100000000000000 05000000aeaf985f 0000000000000000')

        def request(client, rmi_id, args):
            client.send(struct.pack('<BH', 1, rmi_id) + args)

        async def roster(client):
            while True:
                payload = await client.expect(1)
                rmi_id, group_id = struct.unpack_from('<HI', payload, 1)
                if rmi_id == 3001:
                    size, start = read_scalar(payload, 7)
                    reader = JSerBufferReader(payload[start:])
                    self.assertEqual(reader.remaining, size)
                    self.assertEqual(reader.read_u8(), 0x10)
                    members = {}
                    for _ in range(reader.read_varuint()):
                        # Pairs are untagged: 0x006AFA10's 0x0F check reads no byte.
                        uid = reader.read_u64()
                        members[uid] = reader.read_u32()
                    self.assertEqual(reader.remaining, 0)
                    return group_id, members

        async def leave_notice(client):
            payload = await client.expect(1)
            rmi_id, member_id, group_id = struct.unpack_from('<HII', payload, 1)
            self.assertEqual(rmi_id, 0xF61E)
            return member_id, group_id

        async def scenario(first):
            second = HeadlessClient(port=first.port)
            third = HeadlessClient(port=first.port)
            try:
                await first.connect()
                await second.connect()
                await third.connect()
                request(first, 1001, layer_a)
                group_a, members = await roster(first)
                host_a = members[101]
                request(second, 1001, layer_a)
                self.assertEqual((await roster(first))[0], group_a)
                _, members = await roster(second)
                self.assertEqual(set(members), {101, 102})
                host_b = members[102]

                request(third, 1001, layer_b)
                group_b, members = await roster(third)
                self.assertNotEqual(group_a, group_b)
                self.assertEqual(set(members), {103})
                host_c = members[103]

                sender_frame = b'\x15' + scalar(2) + struct.pack('<iIiI', host_b, 4, host_c, 5)
                first.send(sender_frame + scalar(1) + b'x')
                self.assertEqual(await second.expect(0x19), b'\x19' + struct.pack('<iI', host_a, 4) + scalar(1) + b'x')
                with self.assertRaises(asyncio.TimeoutError):
                    await asyncio.wait_for(third.expect(0x19), 0.1)

                request(second, 1001, layer_b)
                self.assertEqual(await leave_notice(first), (host_b, group_a))
                self.assertEqual(await leave_notice(second), (host_b, group_a))
                self.assertEqual(await roster(second), (group_b, {102: host_b, 103: host_c}))
                self.assertEqual(await roster(third), (group_b, {102: host_b, 103: host_c}))

                request(second, 1002, layer_a)  # stale leave must preserve the new group
                request(second, 1001, layer_b)
                self.assertEqual(await roster(second), (group_b, {102: host_b, 103: host_c}))
                await second.close()
                self.assertEqual(await leave_notice(third), (host_b, group_b))
            finally:
                await second.close()
                await third.close()

        with patch('darkblood.games.state.pending_relay', deque((101, 102, 103))):
            self.run_async(self.with_server(scenario, role='relay'))


if __name__ == '__main__':
    unittest.main()
