"""Loopback-only wire recorder. Sends no invented protocol replies."""
import argparse
import asyncio
import json
import time
from pathlib import Path


async def serve(port, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('a', encoding='utf-8', buffering=1) as log:
        async def client(reader, writer):
            peer = writer.get_extra_info('peername')
            session = '{}:{}'.format(*peer)
            def record(kind, data=b''):
                entry = dict(time=time.time(), session=session, event=kind, hex=data.hex())
                log.write(json.dumps(entry) + '\n')
                print(entry, flush=True)
            record('connect')
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    record('recv', data)
            except (ConnectionError, OSError) as exc:
                record('error: ' + str(exc))
            finally:
                record('disconnect')
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionError:
                    pass
        server = await asyncio.start_server(client, '127.0.0.1', port)
        print('Recording 127.0.0.1:{} -> {}'.format(port, output), flush=True)
        async with server:
            await server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=9400)
    parser.add_argument('--output', type=Path, default=Path('logs/wire.jsonl'))
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.port, args.output))
    except KeyboardInterrupt:
        pass
