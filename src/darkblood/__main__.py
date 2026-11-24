"""Entry point: ``python -m darkblood`` (with src/ on sys.path) or ``python run_server.py``.

Runs the client-compatible transport on 127.0.0.1:9400 (game) and
127.0.0.1:9401 (square/room relay announced by opcode 5134).
"""
import asyncio
import logging
import sys

from darkblood import REPO_ROOT
from darkblood.frontend.relay import RELAY_PORT
from darkblood.frontend.server import BootstrapServer
from darkblood.games.gm_bridge import start_gm_bridge


async def serve():
    game = BootstrapServer()
    relay = BootstrapServer(port=RELAY_PORT, role='relay')
    await game.start()
    await relay.start()
    gm_bridge = None
    try:
        gm_bridge = await start_gm_bridge()
    except OSError:
        gm_bridge = None
    try:
        servers = [game.server, relay.server]
        if gm_bridge is not None:
            servers.append(gm_bridge)
        try:
            await asyncio.gather(*(s.serve_forever() for s in servers))
        finally:
            for s in servers:
                s.close()
                await s.wait_closed()
    finally:
        game.close_log()
        relay.close_log()


def main():
    handlers = None
    if sys.stderr is None:
        log_dir = REPO_ROOT / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers = [logging.FileHandler(log_dir / 'server.log', encoding='utf-8')]
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=handlers)
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
