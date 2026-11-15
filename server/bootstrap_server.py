"""Experimental loopback ProudNet bootstrap; application RPCs are recorded."""
import asyncio
import json
import logging
import struct
import time
import uuid
from pathlib import Path

from proudnet import ProtocolError, connection_success, frame, pop_frame
from game_wire import welcome

logger = logging.getLogger('ProudNet')


class BootstrapServer:
    def __init__(self, host='127.0.0.1', port=9400, log_path=Path('logs/wire.jsonl')):
        if host != '127.0.0.1':
            raise ValueError('The research server must bind to IPv4 loopback')
        self.host, self.port = host, port
        self.log_path = Path(log_path)
        self.guid = uuid.UUID('a1d7e8c2-5a20-44af-94e1-52424c4f4f44').bytes_le
        self.server = None
        self.next_host_id = 2

    async def start(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info('Listening on %s:%s', self.host, self.port)

    def record(self, peer, event, data=b''):
        with self.log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(time=time.time(), peer=peer, event=event,
                                         hex=data.hex())) + '\n')
        logger.info('%s %s %s', peer, event, data.hex(' '))

    async def handle_client(self, reader, writer):
        peer = writer.get_extra_info('peername')
        host_id = self.next_host_id
        self.next_host_id += 1
        state = 'new'
        buffer = bytearray()
        self.record(peer, 'connect')
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                self.record(peer, 'recv', data)
                buffer.extend(data)
                while True:
                    payload = pop_frame(buffer)
                    if payload is None:
                        break
                    self.record(peer, 'message', payload)
                    reply = None
                    if payload[0] == 0x30 and state == 'new':
                        if len(payload) != 5 or struct.unpack('<I', payload[1:])[0] != 0x4000000f:
                            raise ProtocolError('Unsupported transport report')
                        # Handler 0xB5CF80 accepts this empty message and emits
                        # type 8. Local experiment deliberately uses plaintext;
                        # the encrypted type 5/6 exchange is not implemented.
                        reply = b'\x07'
                        state = 'request'
                    elif payload[0] == 8 and state == 'request':
                        reply = connection_success(host_id, self.guid, peer)
                        state = 'connected'
                    elif payload[0] == 0x1c and state == 'connected' and len(payload) == 13:
                        # Client timer at 0xB4A225; pong reader 0xB5F220.
                        reply = b'\x1e' + payload[1:9] + struct.pack('<Q', int(time.monotonic() * 1000))
                    elif payload == b'\x1d' and state == 'connected':
                        reply = b'\x1f'
                    if reply is not None:
                        wire = frame(reply)
                        self.record(peer, 'send', wire)
                        writer.write(wire)
                        await writer.drain()
                        if payload[0] == 8 and state == 'connected':
                            greeting = frame(b'\x02' + welcome())
                            self.record(peer, 'send', greeting)
                            writer.write(greeting)
                            await writer.drain()
        except (ConnectionError, OSError, ProtocolError) as exc:
            logger.info('%s closed: %s', peer, exc)
        finally:
            self.record(peer, 'disconnect')
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
