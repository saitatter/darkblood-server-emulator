"""Dark Blood's observed ProudNet framing (x86 client 1.6.5#0).

Evidence: frame writer 0xB7FBE0, reader 0xB7FD80, signed scalar writer
0xB95CB0/reader 0xB95D90. See docs/PROTOCOL.md for remaining unknowns.
"""
import struct


MAGIC = b'\x13\x57'
MAX_FRAME = 1024 * 1024
# The client's Fast cipher dispatch (0x00B82AE0) accepts 512, 1024 or 2048 bits.
FAST_KEY_BITS = 512


class ProtocolError(ValueError):
    pass


def scalar(value):
    for width in (1, 2, 4, 8):
        if -(1 << (8 * width - 1)) <= value < (1 << (8 * width - 1)):
            return bytes([width]) + value.to_bytes(width, 'little', signed=True)
    raise OverflowError('ProudNet scalar exceeds signed 64-bit range')


def read_scalar(data, offset=0):
    if offset >= len(data):
        return None
    width = data[offset]
    if width not in (1, 2, 4, 8):
        raise ProtocolError('Invalid scalar width: {}'.format(width))
    end = offset + 1 + width
    if end > len(data):
        return None
    return int.from_bytes(data[offset + 1:end], 'little', signed=True), end


def frame(payload):
    if not 0 < len(payload) <= MAX_FRAME:
        raise ProtocolError('Invalid frame length')
    return MAGIC + scalar(len(payload)) + payload


def pop_frame(buffer):
    """Return one payload and remove it, or None for an incomplete TCP frame."""
    if len(buffer) < 2:
        return None
    if buffer[:2] != MAGIC:
        raise ProtocolError('Invalid ProudNet frame magic')
    result = read_scalar(buffer, 2)
    if result is None:
        return None
    size, start = result
    if not 0 < size <= MAX_FRAME:
        raise ProtocolError('Invalid frame length: {}'.format(size))
    if len(buffer) < start + size:
        return None
    payload = bytes(buffer[start:start + size])
    del buffer[:start + size]
    return payload


def blob(data):
    return scalar(len(data)) + data


def wide_string(text):
    raw = text.encode('utf-16le')
    return scalar(len(raw) // 2) + raw


def connection_success(host_id, server_guid, peer):
    # Handler 0xB5ED30: host ID u32, GUID raw16, user data blob,
    # endpoint (UTF-16 address + little-endian u16 port).
    return (b'\x0b' + struct.pack('<I', host_id) + server_guid
            + blob(b'') + wide_string(peer[0]) + struct.pack('<H', peer[1]))


# Square relay endpoint (opcode 5134). Reader 0xA48910 copies 6 raw bytes
# into the buffer at [handler owner + 0x6C]; JP2PFactory::Connect (0x956A90)
# uses them as IPv4 address bytes in network order + u16 little-endian port.
RELAY_PORT = 9401


def relay_address(port=RELAY_PORT):
    return bytes([127, 0, 0, 1]) + struct.pack('<H', port)


# Square UIDs carry the server-list key in bits 54-58 (0x00A614A0).
# 0x0087DBB0 omits the "(server)" name suffix when peer and own square UIDs
# share key 31.
SQUARE_UID_KEY_BITS = 0x1F << 54
SQUARE_UID_MASK = (1 << 54) - 1
PEER_SERVER_BITS = SQUARE_UID_KEY_BITS


def square_uid(square_id: int) -> int:
    """Wire square UID: server key 31 in bits 54-58 plus the local square id."""
    return SQUARE_UID_KEY_BITS | (int(square_id) & SQUARE_UID_MASK)
