"""End-to-end server tests driven by the headless client (no game window).

    python -m unittest discover -s tests -v
"""
import asyncio
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory()
os.environ['DARKBLOOD_DATA'] = TMP.name  # must be set before characters is imported
sys.path.insert(0, str(ROOT / 'server'))
sys.path.insert(0, str(ROOT / 'tools'))

from bootstrap_server import BootstrapServer  # noqa: E402
import game_wire  # noqa: E402
from headless_client import HeadlessClient, lobby_flow  # noqa: E402


def wide(text):
    raw = text.encode('utf-16le')
    return game_wire.varuint(len(raw)) + raw


def create_request(name, char_class=1):
    # Observed 2012 layout: i32, u8 class, wstr, u32 face, u32 hair, 5 x u8, u8.
    return (struct.pack('<iB', 0x7fffffff, char_class) + wide(name)
            + struct.pack('<II', 1, 1) + bytes([50] * 5) + b'\x00')


class HeadlessFlowTest(unittest.TestCase):
    def run_async(self, coro):
        return asyncio.run(asyncio.wait_for(coro, 30))

    async def with_server(self, scenario, role='game'):
        server = BootstrapServer(port=0, role=role,
                                 log_path=Path(TMP.name) / 'wire.jsonl',
                                 key_path=Path(TMP.name) / 'rsa.key')
        await server.start()
        port = server.server.sockets[0].getsockname()[1]
        client = HeadlessClient(port=port)
        try:
            return await scenario(client)
        finally:
            await client.close()
            server.server.close()
            await server.server.wait_closed()

    def test_lobby_and_selection(self):
        async def scenario(client):
            out = await lobby_flow(client)
            client.send_event(2012, create_request('Headless'))
            _, created = await client.expect_event(2013)
            self.assertEqual(struct.unpack_from('<I', created)[0], 0)
            char_id = struct.unpack_from('<Q', created, 10)[0]  # u32 result (4B) + varuint+sliders (6B) -> u64 id
            self.assertEqual(created[18], 1)  # level
            self.assertEqual(created[19], 1)  # knight
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, out[2007] = await client.expect_event(2007)
            return out

        out = self.run_async(self.with_server(scenario))
        for opcode in (2403, 2002, 2022, 5029, 2009, 2007):
            self.assertEqual(struct.unpack_from('<I', out[opcode])[0], 0, opcode)
        # 5134: 6 raw bytes, IPv4 network order + u16 LE port (verified live).
        self.assertEqual(out[5134], bytes([127, 0, 0, 1]) + struct.pack('<H', game_wire.RELAY_PORT))

    def test_town_and_tutorial_opcodes(self):
        async def scenario(client):
            await client.connect()
            # Friend list 2131 -> 2132
            client.send_event(2131)
            _, ack2132 = await client.expect_event(2132)
            self.assertEqual(struct.unpack_from('<I', ack2132)[0], 0)

            # Opcode 2569 -> 2570
            client.send_event(2569)
            _, ack2570 = await client.expect_event(2570)
            self.assertEqual(struct.unpack_from('<I', ack2570)[0], 0)

            # Clear tutorial 2082 -> 2083 (triggers Scene 9)
            client.send_event(2082, struct.pack('<iB', 0x7fffffff, 0))
            _, ack2083 = await client.expect_event(2083)
            self.assertEqual(struct.unpack_from('<I', ack2083)[0], 0)

            # Tutorial quest start 2346 -> 2347
            client.send_event(2346)
            _, ack2347 = await client.expect_event(2347)
            self.assertEqual(struct.unpack_from('<I', ack2347)[0], 0)

            # Taming monster insert 2348 -> 2349
            client.send_event(2348)
            _, ack2349 = await client.expect_event(2349)
            self.assertEqual(struct.unpack_from('<I', ack2349)[0], 0)

            # Taming monster delete 2350 -> 2351
            client.send_event(2350)
            _, ack2351 = await client.expect_event(2351)
            self.assertEqual(struct.unpack_from('<I', ack2351)[0], 0)

            # Roulette info 2390 -> 2391
            client.send_event(2390)
            _, ack2391 = await client.expect_event(2391)
            self.assertEqual(struct.unpack_from('<I', ack2391)[0], 0)
            self.assertEqual(len(ack2391), 25)

        self.run_async(self.with_server(scenario))

    def test_thief_creation_and_selection(self):
        async def scenario(client):
            out = await lobby_flow(client)
            # Create Thief (char_class = 4)
            client.send_event(2012, create_request('ThiefTester', char_class=4))
            _, created = await client.expect_event(2013)
            self.assertEqual(struct.unpack_from('<I', created)[0], 0)
            # Layout: u32 result (4B), varuint+sliders (6B), u64 id (8B), u8 level (1B), u8 char_class (1B)
            self.assertEqual(created[18], 1)  # level must be 1
            self.assertEqual(created[19], 4)  # class must be Thief (4)
            char_id = struct.unpack_from('<Q', created, 10)[0]
            # Select the Thief character
            client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
            _, ack2007 = await client.expect_event(2007)
            self.assertEqual(struct.unpack_from('<I', ack2007)[0], 0)
            return ack2007

        ack = self.run_async(self.with_server(scenario))
        self.assertIsNotNone(ack)

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


if __name__ == '__main__':
    unittest.main()
