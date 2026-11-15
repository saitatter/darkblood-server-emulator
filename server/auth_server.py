import asyncio
import logging
from packet import Packet, Opcodes

logger = logging.getLogger("AuthServer")

class AuthServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 10001):
        self.host = host
        self.port = port
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info(f"[+] AuthServer listening on {self.host}:{self.port}")

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        logger.info(f"[*] New client connection from: {peer}")

        buffer = bytearray()
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                buffer.extend(data)
                logger.info(f"[NET RECV] {len(data)} bytes from {peer}: {data.hex(' ')}")

                # Try parsing packets
                while len(buffer) >= 4:
                    pkt, pkt_len = Packet.parse(bytes(buffer))
                    if pkt is None and pkt_len > len(buffer):
                        break # Need more data
                    if pkt is None:
                        # Raw handshake or non-standard framing; respond with ACK
                        logger.info(f"[HANDSHAKE] Raw incoming data ({len(buffer)} bytes)")
                        ack = Packet(Opcodes.S2C_HANDSHAKE_ACK)
                        ack.write_uint32(0) # Success code
                        writer.write(ack.pack())
                        await writer.drain()
                        buffer.clear()
                        break

                    buffer = buffer[pkt_len:]
                    await self.process_packet(pkt, writer)

        except ConnectionResetError:
            pass
        except Exception as e:
            logger.error(f"[!] Error handling client {peer}: {e}")
        finally:
            logger.info(f"[-] Client {peer} disconnected.")
            writer.close()
            await writer.wait_closed()

    async def process_packet(self, pkt: Packet, writer: asyncio.StreamWriter):
        logger.info(f"[PKT] Opcode: {hex(pkt.opcode)} (Payload: {len(pkt.payload)} bytes)")

        if pkt.opcode in (Opcodes.C2S_HANDSHAKE_REQ, 0x0000):
            logger.info("[AUTH] Client Handshake -> Sending Handshake ACK & Server List")
            ack = Packet(Opcodes.S2C_HANDSHAKE_ACK)
            ack.write_uint32(0)
            writer.write(ack.pack())
            await writer.drain()

            # Send Server List
            slist = Packet(Opcodes.S2C_SERVER_LIST)
            slist.write_uint16(1) # 1 Server
            slist.write_uint16(1) # Server ID
            slist.write_unicode("Dark Blood Local")
            slist.write_uint8(1)  # Status: Normal (Green)
            slist.write_uint16(1) # 1 Channel
            slist.write_uint16(1) # Channel ID
            slist.write_unicode("Channel 1 [Local]")
            slist.write_string("127.0.0.1")
            slist.write_uint16(10002) # Lobby port
            writer.write(slist.pack())
            await writer.drain()

        elif pkt.opcode == Opcodes.C2S_LOGIN_REQ:
            logger.info("[AUTH] Login Request -> Login Success")
            resp = Packet(Opcodes.S2C_LOGIN_RESP)
            resp.write_uint32(0) # 0 = Success
            resp.write_string("account_local_01")
            writer.write(resp.pack())
            await writer.drain()
