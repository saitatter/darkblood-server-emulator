"""Shared test fixtures and helpers for Dark Blood server test suite."""
import asyncio
import logging
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.TemporaryDirectory()
os.environ['DARKBLOOD_DATA'] = TMP.name  # never the real character database
# Always a private temporary directory: tests write and delete fixture dict files
# (e.g. quest_act1.lua) there, so they must never point at the real client data.
os.environ['DARKBLOOD_CLIENT_DATA'] = TMP.name
# Launcher options (e.g. game multipliers) are read live by the server: tests use
# the defaults, never the developer's research/client/darkblood_options.ini.
os.environ['DARKBLOOD_OPTIONS'] = str(Path(TMP.name) / 'darkblood_options.ini')
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))
for _sub in ('automation', 'launcher', 'codegen', 'client_data', 'reverse'):
    if str(ROOT / 'tools' / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / 'tools' / _sub))

from darkblood.core.serialization import jser  # noqa: E402
from darkblood.frontend.server import BootstrapServer  # noqa: E402
from headless_client import HeadlessClient, lobby_flow  # noqa: E402


def wide(text: str) -> bytes:
    raw = text.encode('utf-16le')
    return jser.varuint(len(raw)) + raw


def create_request(name: str, char_class: int = 1) -> bytes:
    # Observed 2012 layout: i32, u8 class, wstr, u32 face, u32 hair, 5 x u8, u8.
    return (struct.pack('<iB', 0x7fffffff, char_class) + wide(name)
            + struct.pack('<II', 1, 1) + bytes([50] * 5) + b'\x00')


# Captured 5040 tail after the message text (vectors, i32 1, -1 fields); not decoded.
CHAT_TAIL = bytes.fromhex('001080108001000000') + b'\xff' * 28


def chat_request(text: str, channel: int = 0) -> bytes:
    """5040 body in the captured client form (no header)."""
    from darkblood.games.network.messages import ChatReq
    return ChatReq(channel=channel, message=text).encode()


class ServerTestCase(unittest.TestCase):
    """Base class for tests requiring an async server instance."""

    def run_async(self, coro):
        return asyncio.run(asyncio.wait_for(coro, 30))

    async def with_server(self, scenario, role='game'):
        server = BootstrapServer(port=0, role=role,
                                 log_path=Path(TMP.name) / 'wire.jsonl',
                                 key_path=Path(TMP.name) / 'rsa.key')
        await server.start()
        port = server.server.sockets[0].getsockname()[1]
        client = HeadlessClient(port=port)
        # A request the generated decoder rejects is dropped by the dispatcher;
        # fail the test instead of letting it pass on a missing reply.
        with self.assertNoLogs_dispatcher():
            try:
                return await scenario(client)
            finally:
                try:
                    await client.close()
                finally:
                    server.server.close()
                    await server.server.wait_closed()
                    server.close_log()

    def assertNoLogs_dispatcher(self):
        test = self

        class _Guard(logging.Handler):
            def __enter__(self):
                self.records = []
                logging.getLogger('darkblood.games.dispatcher').addHandler(self)
                return self

            def emit(self, record):
                if record.levelno >= logging.WARNING:
                    self.records.append(self.format(record))

            def __exit__(self, *exc):
                logging.getLogger('darkblood.games.dispatcher').removeHandler(self)
                if self.records and exc[0] is None:
                    test.fail('dispatcher reported: ' + '; '.join(self.records))
                return False

        return _Guard()
