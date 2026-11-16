#!/usr/bin/env python3
"""
Dark Blood Online — Local Server Emulator (Auth + Lobby)
"""

import asyncio
import logging
import signal
from auth_server import AuthServer
from lobby_server import LobbyServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)

async def main():
    print("=" * 60)
    print(" Dark Blood Online (Project Hound) — Server Emulator")
    print("=" * 60)

    auth = AuthServer("127.0.0.1", 10001)
    lobby = LobbyServer("127.0.0.1", 10002)

    await auth.start()
    await lobby.start()

    print("[*] Server emulator cluster is running on localhost (127.0.0.1)")
    print("[*] Press Ctrl+C to stop.")

    try:
        await asyncio.Event().wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass

if __name__ == "__main__":
    asyncio.run(main())
