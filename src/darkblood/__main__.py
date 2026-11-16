"""Entry point: ``python -m darkblood`` (with src/ on sys.path) or ``python run_server.py``.

Runs the client-compatible transport on 127.0.0.1:9400 (game) and
127.0.0.1:9401 (square/room relay announced by opcode 5134).
"""
import asyncio
import logging

from darkblood.frontend.relay import RELAY_PORT
from darkblood.frontend.server import BootstrapServer


async def serve():
    game = BootstrapServer()
    relay = BootstrapServer(port=RELAY_PORT, role='relay')
    await game.start()
    await relay.start()
    async with game.server, relay.server:
        await asyncio.gather(game.server.serve_forever(), relay.server.serve_forever())


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
