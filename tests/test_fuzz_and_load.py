"""Fuzzing, protocol robustness (pre-auth / malformed) and 10-client concurrency tests."""
import asyncio
import random
import struct
import unittest

from tests.common import ServerTestCase, chat_request, create_request, lobby_flow
from darkblood.core.network.proudnet import MAX_FRAME, ProtocolError, frame, pop_frame, read_scalar, scalar
from darkblood.core.serialization.jser import WireError, read_varuint, varuint
from headless_client import HeadlessClient


class WireFuzzTest(unittest.TestCase):
    """Fuzz JSerBuffer varuints, ProudNet scalars and TCP frame reassembly."""

    def test_varuint_boundary_and_random_roundtrips(self):
        rng = random.Random(20261121)
        values = [0, 1, 127, 128, 16383, 16384, (1 << 21) - 1, (1 << 28) - 1, (1 << 32) - 1]
        values += [rng.randint(0, (1 << 32) - 1) for _ in range(250)]
        for v in values:
            enc = varuint(v)
            dec, off = read_varuint(enc, 0)
            self.assertEqual(dec, v)
            self.assertEqual(off, len(enc))

    def test_varuint_rejects_truncated_and_unterminated(self):
        with self.assertRaises(WireError):
            read_varuint(b'', 0)
        with self.assertRaises(WireError):
            read_varuint(b'\x01\x02\x03', 0)  # no terminating high bit
        with self.assertRaises(WireError):
            read_varuint(b'\x01' * 12, 0)

    def test_proudnet_scalar_boundaries_and_invalid_widths(self):
        for v in (-2**63, -2**31 - 1, -2**31, -32769, -32768, -129, -128, -1, 0,
                  1, 127, 128, 32767, 32768, 2**31 - 1, 2**31, 2**63 - 1):
            enc = scalar(v)
            res = read_scalar(enc, 0)
            self.assertEqual(res, (v, len(enc)))
        for bad_width in (0, 3, 5, 6, 7, 9, 255):
            with self.assertRaises(ProtocolError):
                read_scalar(bytes([bad_width, 0, 0, 0, 0, 0, 0, 0, 0]), 0)
        self.assertIsNone(read_scalar(b'\x04\x01\x02', 0))

    def test_pop_frame_handles_fragmentation_and_rejects_corrupt_streams(self):
        f1 = frame(b'\x02hello')
        f2 = frame(b'\x02world!')
        buf = bytearray()
        out = []
        for b in f1 + f2:
            buf.append(b)
            p = pop_frame(buf)
            if p is not None:
                out.append(p)
        self.assertEqual(out, [b'\x02hello', b'\x02world!'])
        self.assertEqual(len(buf), 0)

        with self.assertRaises(ProtocolError):
            pop_frame(bytearray(b'\x00\x00\x01\x05hello'))
        with self.assertRaises(ProtocolError):
            pop_frame(bytearray(b'\x13\x57' + scalar(MAX_FRAME + 1)))
        with self.assertRaises(ProtocolError):
            pop_frame(bytearray(b'\x13\x57' + scalar(0)))


class ProtocolRobustnessAndLoadTest(ServerTestCase):
    """Out-of-order / pre-auth resilience and 10-client simultaneous load test."""

    def test_pre_auth_gameplay_packets_are_ignored_until_login(self):
        async def scenario(client):
            await client.connect()
            await client.expect_event(2)
            # Send gameplay opcodes before authenticating with 5386: server must stay up
            # and ignore them, then still accept a valid login afterward.
            client.send_event(2008, b'')
            client.send_event(5040, chat_request('unauthorized'))
            await asyncio.sleep(0.05)

            client.send_event(5386, bytes.fromhex('0088') + b'DBACC:PreAuthTester;Message bytes=13 data=01472C68')
            await client.expect_event(5020)
            client.send_event(2008, b'')
            _, body2009 = await client.expect_event(2009)
            self.assertGreaterEqual(len(body2009), 4)

        self.run_async(self.with_server(scenario))

    def test_ten_simultaneous_clients_login_select_and_chat(self):
        async def scenario(primary):
            clients = [primary] + [HeadlessClient(port=primary.port) for _ in range(9)]
            try:
                async def join_town(idx, c):
                    c.account = f'LoadAcc{idx}'
                    name = f'LoadHero{idx}'
                    await lobby_flow(c)
                    c.send_event(2012, create_request(name, char_class=(idx % 6) + 1))
                    _, created = await c.expect_event(2013)
                    char_id = struct.unpack_from('<Q', created, 10)[0]
                    c.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
                    await c.expect_event(2007)
                    await c.expect_event(2410)
                    c.send_event(5124, struct.pack('<i', 0x7fffffff))
                    await c.expect_event(5125)
                    return char_id

                char_ids = await asyncio.gather(*(join_town(i, c) for i, c in enumerate(clients)))
                self.assertEqual(len(set(char_ids)), 10)

                # Broadcast normal town chat (channel=1) from client 0; all 10 clients receive 5041
                clients[0].send_event(5040, chat_request('Hello all 10!', channel=1))
                acks = await asyncio.gather(*(c.expect_event(5041) for c in clients))
                self.assertEqual(len(acks), 10)
            finally:
                for c in clients[1:]:
                    await c.close()

        self.run_async(self.with_server(scenario))


if __name__ == '__main__':
    unittest.main()
