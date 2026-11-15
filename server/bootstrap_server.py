"""Loopback ProudNet server for the Dark Blood client.

Handshake recovered from the client (see docs/PROTOCOL.md):
  C->S 0x30 report      S->C 0x05 settings + RSA public key (handler 0xB5C8D0)
  C->S 0x06 keys        S->C 0x07 session-key accepted       (handler 0xB5CF80)
  C->S 0x08 request     S->C 0x0B connection success         (handler 0xB5ED30)
Application messages from the client arrive AES-wrapped as type 0x26.
"""
import asyncio
import json
import logging
import struct
import time
import uuid
from pathlib import Path

from proudnet import (ProtocolError, connection_success, frame, pop_frame,
                      read_scalar, scalar)
from proudnet_crypto import AES, CryptoError, RSAKey, envelope_decrypt, envelope_encrypt
import game_wire

logger = logging.getLogger('ProudNet')

AES_KEY_BITS = 128
FAST_KEY_BITS = 128


def server_settings():
    # Reader 0xB70DE0 (fixed-width little-endian fields); defaults 0xB82850.
    return (struct.pack('<B', 0)                     # +00 fallback method
            + struct.pack('<iii', 0x10000, 0x10000, 60000)  # +04 +08 +0C
            + struct.pack('<B', 2)                   # +10 direct-P2P start condition
            + struct.pack('<i', 0x7fffffff)          # +14 over-send threshold
            + struct.pack('<B', 1)                   # +18 Nagle
            + struct.pack('<ii', AES_KEY_BITS, FAST_KEY_BITS)  # +1C +20 key lengths (bits)
            + bytes([0, 1, 0, 0])                    # +24..+27
            + bytes([1, 0, 0])                       # +2C..+2E
            + struct.pack('<i', 0))                  # +28


def read_blob(data, offset):
    result = read_scalar(data, offset)
    if result is None:
        raise ProtocolError('Truncated blob length')
    size, start = result
    if size < 0 or start + size > len(data):
        raise ProtocolError('Truncated blob')
    return data[start:start + size], start + size


class Session:
    def __init__(self, server, reader, writer, host_id):
        self.server, self.reader, self.writer = server, reader, writer
        self.peer = writer.get_extra_info('peername')
        self.host_id = host_id
        self.state = 'new'
        self.aes = None
        self.fast_key = None
        self.app = game_wire.GameSession(self)

    def record(self, event, data=b'', **extra):
        self.server.record(self.peer, event, data, **extra)

    async def send_payload(self, payload, note=None):
        wire = frame(payload)
        self.record('send', wire, note=note)
        self.writer.write(wire)
        await self.writer.drain()

    async def send_event(self, event_bytes, note=None):
        await self.send_payload(b'\x02' + event_bytes, note=note)

    async def run(self):
        buffer = bytearray()
        self.record('connect')
        try:
            while True:
                data = await self.reader.read(65536)
                if not data:
                    break
                self.record('recv', data)
                buffer.extend(data)
                while True:
                    payload = pop_frame(buffer)
                    if payload is None:
                        break
                    await self.handle(payload)
        except (ConnectionError, OSError, ProtocolError, CryptoError) as exc:
            logger.info('%s closed: %r', self.peer, exc)
        finally:
            self.record('disconnect')
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def handle(self, payload):
        kind = payload[0]
        self.record('message', payload)
        if kind == 0x30 and self.state == 'new':
            if len(payload) != 5 or struct.unpack('<I', payload[1:])[0] != 0x4000000f:
                raise ProtocolError('Unsupported transport report')
            key = self.server.rsa.public_der()
            await self.send_payload(b'\x05\x00' + server_settings() + scalar(len(key)) + key,
                                    note='server connection hint')
            self.state = 'keys'
        elif kind == 0x06 and self.state == 'keys':
            session_cipher, offset = read_blob(payload, 1)
            fast_cipher, offset = read_blob(payload, offset)
            if offset != len(payload):
                raise ProtocolError('Trailing bytes in session-key message')
            session_key = self.server.rsa.oaep_decrypt(session_cipher)
            self.aes = AES(session_key)
            self.fast_key = envelope_decrypt(self.aes, fast_cipher)
            self.record('session-key', session_key, fast_key=self.fast_key.hex())
            await self.send_payload(b'\x07', note='session key accepted')
            self.state = 'request'
        elif kind == 0x08 and self.state == 'request':
            await self.send_payload(connection_success(self.host_id, self.server.guid, self.peer),
                                    note='connection success')
            self.state = 'connected'
            await self.app.on_connected()
        elif self.state != 'connected':
            raise ProtocolError('Unexpected message 0x%02x in state %s' % (kind, self.state))
        elif kind == 0x1c and len(payload) == 13:
            # Client timer at 0xB4A225; pong reader 0xB5F220.
            await self.send_payload(b'\x1e' + payload[1:9] + struct.pack('<Q', int(time.monotonic() * 1000)))
        elif payload == b'\x1d':
            await self.send_payload(b'\x1f')
        elif kind in (0x26, 0x27):
            await self.handle_encrypted(payload)
        elif kind in (0x02, 0x03):
            await self.app.on_user_message(payload[1:])
        else:
            self.record('unhandled', payload)

    async def handle_encrypted(self, payload):
        # Writer 0xB762C0: type, encryption mode (u8), scalar length, ciphertext.
        if payload[0] != 0x26:
            self.record('unhandled-fast', payload)
            return
        mode = payload[1]
        cipher, offset = read_blob(payload, 2)
        plain = envelope_decrypt(self.aes, cipher)
        # Reliable sends prefix a u16 encryption counter (writer 0x955E30).
        counter = struct.unpack_from('<H', plain)[0]
        self.record('decrypted', plain, mode=mode, counter=counter)
        await self.handle(plain[2:])


class BootstrapServer:
    def __init__(self, host='127.0.0.1', port=9400, log_path=Path('logs/wire.jsonl'),
                 key_path=Path('logs/server_rsa.key')):
        if host != '127.0.0.1':
            raise ValueError('The research server must bind to IPv4 loopback')
        self.host, self.port = host, port
        self.log_path = Path(log_path)
        self.guid = uuid.UUID('a1d7e8c2-5a20-44af-94e1-52424c4f4f44').bytes_le
        self.rsa = RSAKey.load_or_create(str(key_path))
        self.server = None
        self.next_host_id = 2

    async def start(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info('Listening on %s:%s', self.host, self.port)

    def record(self, peer, event, data=b'', **extra):
        entry = dict(time=time.time(), peer=peer, event=event, hex=data.hex())
        entry.update({k: v for k, v in extra.items() if v is not None})
        with self.log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry) + '\n')
        logger.info('%s %s %s %s', peer, event, data.hex(' ')[:600],
                    ' '.join('%s=%s' % kv for kv in extra.items() if kv[1] is not None))

    async def handle_client(self, reader, writer):
        host_id = self.next_host_id
        self.next_host_id += 1
        await Session(self, reader, writer, host_id).run()
