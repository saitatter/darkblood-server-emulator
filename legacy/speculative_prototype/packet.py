import struct

class Packet:
    """
    Standard MMO packet container.
    Format: [Length: 2 bytes uint16][Opcode: 2 bytes uint16][Payload: N bytes]
    """
    def __init__(self, opcode: int = 0, payload: bytes = b''):
        self.opcode = opcode
        self.payload = bytearray(payload)

    def write_uint8(self, val: int):
        self.payload.extend(struct.pack('<B', val))

    def write_uint16(self, val: int):
        self.payload.extend(struct.pack('<H', val))

    def write_uint32(self, val: int):
        self.payload.extend(struct.pack('<I', val))

    def write_string(self, text: str, encoding: str = 'utf-8'):
        raw = text.encode(encoding)
        self.write_uint16(len(raw))
        self.payload.extend(raw)

    def write_unicode(self, text: str):
        raw = text.encode('utf-16le')
        self.write_uint16(len(raw))
        self.payload.extend(raw)

    def pack(self) -> bytes:
        total_len = 4 + len(self.payload)
        return struct.pack('<HH', total_len, self.opcode) + bytes(self.payload)

    @classmethod
    def parse(cls, data: bytes):
        if len(data) < 4:
            return None, 0
        total_len, opcode = struct.unpack('<HH', data[:4])
        if len(data) < total_len:
            return None, total_len  # Need more bytes
        payload = data[4:total_len]
        return cls(opcode, payload), total_len

# Common Protocol Opcodes
class Opcodes:
    # Auth / Connection
    C2S_HANDSHAKE_REQ       = 0x1001
    S2C_HANDSHAKE_ACK       = 0x1002
    C2S_LOGIN_REQ           = 0x1003
    S2C_LOGIN_RESP          = 0x1004
    S2C_SERVER_LIST         = 0x1005

    # Lobby / Character
    C2S_SELECT_SERVER_REQ   = 0x2001
    S2C_CHAR_LIST           = 0x2002
    C2S_CREATE_CHAR_REQ     = 0x2003
    S2C_CREATE_CHAR_RESP    = 0x2004
    C2S_SELECT_CHAR_REQ     = 0x2005
    S2C_ENTER_WORLD         = 0x2006

    # Ping / Keepalive
    C2S_PING                = 0x0001
    S2C_PONG                = 0x0002
