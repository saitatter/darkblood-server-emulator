"""Run the experimental client-compatible transport on 127.0.0.1:9400
(game) and 127.0.0.1:9401 (square relay announced by opcode 5134)."""
import asyncio
import logging
from bootstrap_server import BootstrapServer
from game_wire import RELAY_PORT


async def main():
    game = BootstrapServer()
    relay = BootstrapServer(port=RELAY_PORT, role='relay')
    await game.start()
    await relay.start()
    async with game.server, relay.server:
        await asyncio.gather(game.server.serve_forever(), relay.server.serve_forever())


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
