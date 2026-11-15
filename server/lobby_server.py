import asyncio
import logging
from packet import Packet, Opcodes

logger = logging.getLogger("LobbyServer")

class LobbyServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 10002):
        self.host = host
        self.port = port
        self.server = None
        self.characters = [
            {
                "id": 1,
                "name": "LocalHero",
                "class_id": 1,  # Warrior
                "level": 1,
                "map_id": 1001, # Act 1 Town
            }
        ]

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info(f"[+] LobbyServer listening on {self.host}:{self.port}")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        logger.info(f"[*] Lobby client connection from: {peer}")

        # Send Character list on connect
        await self.send_character_list(writer)

        buffer = bytearray()
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                buffer.extend(data)
                while len(buffer) >= 4:
                    pkt, pkt_len = Packet.parse(bytes(buffer))
                    if pkt is None and pkt_len > len(buffer):
                        break
                    if pkt is None:
                        buffer.clear()
                        break
                    buffer = buffer[pkt_len:]
                    await self.process_packet(pkt, writer)

        except ConnectionResetError:
            pass
        except Exception as e:
            logger.error(f"[!] Error handling lobby client {peer}: {e}")
        finally:
            logger.info(f"[-] Lobby client {peer} disconnected.")
            writer.close()
            await writer.wait_closed()

    async def send_character_list(self, writer: asyncio.StreamWriter):
        pkt = Packet(Opcodes.S2C_CHAR_LIST)
        pkt.write_uint16(len(self.characters))
        for char in self.characters:
            pkt.write_uint32(char["id"])
            pkt.write_unicode(char["name"])
            pkt.write_uint8(char["class_id"])
            pkt.write_uint16(char["level"])
            pkt.write_uint32(char["map_id"])
        writer.write(pkt.pack())
        await writer.drain()
        logger.info(f"[LOBBY] Sent character list ({len(self.characters)} characters)")

    async def process_packet(self, pkt: Packet, writer: asyncio.StreamWriter):
        logger.info(f"[LOBBY PKT] Opcode: {hex(pkt.opcode)}")

        if pkt.opcode == Opcodes.C2S_SELECT_CHAR_REQ:
            logger.info("[LOBBY] Character Selected -> Sending Enter World")
            resp = Packet(Opcodes.S2C_ENTER_WORLD)
            resp.write_uint32(0)     # Success
            resp.write_uint32(1001)  # Map ID (Act 1 Town)
            resp.write_uint16(10003) # Zone Server Port
            writer.write(resp.pack())
            await writer.drain()
