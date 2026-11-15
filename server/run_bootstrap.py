"""Run the experimental client-compatible transport on 127.0.0.1:9400."""
import asyncio
import logging
from bootstrap_server import BootstrapServer


async def main():
    server = BootstrapServer()
    await server.start()
    async with server.server:
        await server.server.serve_forever()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
