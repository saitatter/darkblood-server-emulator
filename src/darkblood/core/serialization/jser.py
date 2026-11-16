"""JSerBuffer / JEvent primitives recovered from client 0xA1EB90/0xB35E50.

Varuints use 7-bit groups terminated by a byte with bit 7 SET (unlike
ProudNet scalars, see core.network.proudnet)."""
import struct


def varuint(value):
    if not 0 <= value <= 0xffffffff:
        raise ValueError('JSerBuffer length must fit uint32')
    result = bytearray()
    while value >= 128:
        result.append(value & 127)
        value >>= 7
    result.append(value | 128)
    return bytes(result)


def wide_string(text):
    raw = text.encode('utf-16le')
    return varuint(len(raw)) + raw


def event(opcode, body=b'', correlation=0):
    # Nonempty body includes a compression boolean; empty body omits it.
    return (struct.pack('<IQ', opcode, correlation) + varuint(len(body))
            + (b'\x00' + body if body else b''))


class WireError(ValueError):
    pass


def read_varuint(data, offset):
    value = shift = 0
    while True:
        if offset >= len(data):
            raise WireError('Truncated J-varuint')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte & 128:
            return value, offset
        shift += 7
        if shift > 35:
            raise WireError('J-varuint too long')


def parse_event(data):
    """Return (opcode, correlation, compressed, body) for a JEvent."""
    if len(data) < 13:
        raise WireError('Truncated JEvent header')
    opcode, correlation = struct.unpack_from('<IQ', data)
    size, offset = read_varuint(data, 12)
    if size == 0:
        return opcode, correlation, False, b''
    if offset + 1 + size > len(data):
        raise WireError('Truncated JEvent body')
    return opcode, correlation, bool(data[offset]), data[offset + 1:offset + 1 + size]


def to_i32(value: int) -> int:
    """Reinterpret an unsigned 32-bit value (e.g. a jhash) as signed."""
    return value - (1 << 32) if value >= 1 << 31 else value
