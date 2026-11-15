"""Dark Blood's observed ProudNet framing (x86 client 1.6.5#0).

Evidence: frame writer 0xB7FBE0, reader 0xB7FD80, signed scalar writer
0xB95CB0/reader 0xB95D90. See docs/PROTOCOL.md for remaining unknowns.
"""
import struct

MAGIC = b'\x13\x57'
MAX_FRAME = 1024 * 1024


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
