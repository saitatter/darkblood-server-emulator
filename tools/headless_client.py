"""Headless ProudNet client that speaks to the emulator like DarkBlood.exe.

It reproduces the client side of the recovered handshake (0x30 -> 0x05 ->
0x06 -> 0x07 -> 0x08 -> 0x0B) with real RSA-OAEP-SHA1 and AES envelopes, then
sends encrypted game events (type 0x26, mode 1, u16 counter prefix). Request
bodies mirror those captured from the live client (see docs/PROTOCOL.md §5).

This exercises the server without the game window. It does not prove that the
real client parses a response; schema changes still need one bounded live run.

    python tools/headless_client.py --port 9400      # walk the lobby flow
"""
import argparse
import asyncio
import hashlib
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from darkblood.core.network.crypto import AES, envelope_encrypt  # noqa: E402
from darkblood.core.network.proudnet import blob, frame, pop_frame, read_scalar  # noqa: E402
from darkblood.core.serialization.jser import event, parse_event, varuint  # noqa: E402
from darkblood.frontend.server import server_settings  # noqa: E402

TRANSPORT_REPORT = b'\x30' + struct.pack('<I', 0x4000000f)


def _der_read(data, offset, tag):
    if data[offset] != tag:
        raise ValueError('DER tag 0x%02x expected' % tag)
    size = data[offset + 1]
    offset += 2
    if size & 0x80:
        count = size & 0x7f
        size = int.from_bytes(data[offset:offset + count], 'big')
        offset += count
    return data[offset:offset + size], offset + size


def parse_public_key(der):
    body, _ = _der_read(der, 0, 0x30)
    n, offset = _der_read(body, 0, 0x02)
    e, _ = _der_read(body, offset, 0x02)
    return int.from_bytes(n, 'big'), int.from_bytes(e, 'big')


def _mgf1(seed, length):
    out = b''
    counter = 0
    while len(out) < length:
        out += hashlib.sha1(seed + struct.pack('>I', counter)).digest()
        counter += 1
    return out[:length]


def oaep_encrypt(n, e, message, label=b''):
    k = (n.bit_length() + 7) // 8
    hl = 20
    db = hashlib.sha1(label).digest() + b'\x00' * (k - len(message) - 2 * hl - 2) + b'\x01' + message
    seed = os.urandom(hl)
    masked_db = bytes(a ^ b for a, b in zip(db, _mgf1(seed, k - hl - 1)))
    masked_seed = bytes(a ^ b for a, b in zip(seed, _mgf1(masked_db, hl)))
    em = b'\x00' + masked_seed + masked_db
    return pow(int.from_bytes(em, 'big'), e, n).to_bytes(k, 'big')


class HeadlessClient:
    def __init__(self, host='127.0.0.1', port=9400, timeout=5.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.buffer = bytearray()
        self.counter = 0
        self.aes = None
        self.received = []  # every payload, in order

    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.send(TRANSPORT_REPORT)
        hint = await self.expect(0x05)
        # 0x05, bool, fixed-width settings (reader 0xB70DE0), scalar-length DER key
        size, start = read_scalar(hint, 2 + len(server_settings()))
        n, e = parse_public_key(hint[start:start + size])
        session_key, fast_key = os.urandom(16), os.urandom(16)
        self.aes = AES(session_key)
        self.send(b'\x06' + blob(oaep_encrypt(n, e, session_key))
                  + blob(envelope_encrypt(self.aes, fast_key)))
        await self.expect(0x07)
        self.send(b'\x08')
        return await self.expect(0x0b)

    def send(self, payload):
        self.writer.write(frame(payload))

    def send_event(self, opcode, body=b'', correlation=1, compressed=False):
        if compressed:  # client form: flag 1, u32 inflated size + zlib stream
            import zlib
            packed = struct.pack('<I', len(body)) + zlib.compress(body)
            raw = struct.pack('<IQ', opcode, correlation) + varuint(len(packed)) + b'\x01' + packed
        else:
            raw = event(opcode, body, correlation)
        plain = struct.pack('<H', self.counter) + b'\x02' + raw
        self.counter += 1
        cipher = envelope_encrypt(self.aes, plain)
        self.send(b'\x26\x01' + blob(cipher))

    async def read_payload(self):
        while True:
            payload = pop_frame(self.buffer)
            if payload is not None:
                self.received.append(payload)
                return payload
            data = await asyncio.wait_for(self.reader.read(65536), self.timeout)
            if not data:
                raise ConnectionError('server closed the connection')
            self.buffer.extend(data)

    async def expect(self, kind):
        while True:
            payload = await self.read_payload()
            if payload[0] == kind:
                return payload

    async def expect_event(self, opcode):
        """Return (correlation, body) of the next game event with `opcode`."""
        while True:
            payload = await self.expect(0x02)
            got, correlation, _, body = parse_event(payload[1:])
            if got == opcode:
                return correlation, body

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def lobby_flow(client, char_id=None):
    """Walk the observed path: welcome -> 2402 -> 2001 -> 2021 -> 5028 -> 2008 -> 2006.
    Returns a dict opcode -> response body."""
    out = {}
    await client.connect()
    _, out[5020] = await client.expect_event(5020)
    for request, response, body in (
            (2402, 2403, b''),
            (2001, 2002, struct.pack('<iI', 0x7fffffff, 1)),
            (2021, 2022, struct.pack('<iI', 0x7fffffff, 1)),
            (5028, 5029, struct.pack('<iQ', 0x7fffffff, 1))):
        client.send_event(request, body)
        _, out[response] = await client.expect_event(response)
    _, out[5134] = await client.expect_event(5134)
    client.send_event(2008)
    _, out[2009] = await client.expect_event(2009)
    if char_id is not None:
        client.send_event(2006, struct.pack('<iQ', 0x7fffffff, char_id))
        _, out[2007] = await client.expect_event(2007)
    return out


async def _main(args):
    client = HeadlessClient(port=args.port)
    try:
        out = await lobby_flow(client, args.select)
    finally:
        await client.close()
    for opcode, body in out.items():
        print('%d: %d bytes %s' % (opcode, len(body), body[:48].hex()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=9400)
    parser.add_argument('--select', type=int, help='character id to select (sends 2006)')
    asyncio.run(_main(parser.parse_args()))
