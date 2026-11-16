"""JSerBuffer / JEvent primitives recovered from client 0xA1EB90/0xB35E50.

Varuints use 7-bit groups terminated by a byte with bit 7 SET (unlike
ProudNet scalars, see core.network.proudnet)."""
import struct
import zlib


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


def event(opcode, body=b'', correlation=0, compress=False):
    # Nonempty body includes a compression boolean; empty body omits it.
    if body and compress:
        compressed_body = struct.pack('<I', len(body)) + zlib.compress(body)
        return (struct.pack('<IQ', opcode, correlation) + varuint(len(compressed_body))
                + b'\x01' + compressed_body)
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


def parse_event(data, decompress=True):
    """Return (opcode, correlation, compressed, body) for a JEvent."""
    if len(data) < 13:
        raise WireError('Truncated JEvent header')
    opcode, correlation = struct.unpack_from('<IQ', data)
    size, offset = read_varuint(data, 12)
    if size == 0:
        return opcode, correlation, False, b''
    if offset + 1 + size > len(data):
        raise WireError('Truncated JEvent body')
    compressed = bool(data[offset])
    body = data[offset + 1:offset + 1 + size]
    if compressed and decompress:
        # Client form: flag 1 + 4-byte uncompressed size + zlib compressed stream
        try:
            body = zlib.decompress(body[4:])
        except Exception:
            body = zlib.decompress(body)
    return opcode, correlation, compressed, body


def to_i32(value: int) -> int:
    """Reinterpret an unsigned 32-bit value (e.g. a jhash) as signed."""
    return value - (1 << 32) if value >= 1 << 31 else value


class JSerBufferReader:
    """Reader for Dark Blood's binary JSerBuffer serialization streams.

    Features bounds checking, varuints with inverted terminal bit (bit 7 set),
    UTF-16LE wide strings, vectors and signed/unsigned primitives.
    """
    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.offset = offset

    @property
    def remaining(self) -> int:
        return max(0, len(self.data) - self.offset)

    def has_remaining(self) -> bool:
        return self.offset < len(self.data)

    def read_bytes(self, count: int) -> bytes:
        if count < 0:
            raise WireError(f'Invalid negative byte count: {count}')
        if self.offset + count > len(self.data):
            raise WireError(f'Truncated read: needed {count} bytes, have {self.remaining}')
        val = self.data[self.offset:self.offset + count]
        self.offset += count
        return val

    def read_varuint(self) -> int:
        val, self.offset = read_varuint(self.data, self.offset)
        return val

    def read_bool(self) -> bool:
        return bool(self.read_u8())

    def read_i8(self) -> int:
        return struct.unpack_from('<b', self.read_bytes(1))[0]

    def read_u8(self) -> int:
        return struct.unpack_from('<B', self.read_bytes(1))[0]

    def read_i16(self) -> int:
        return struct.unpack_from('<h', self.read_bytes(2))[0]

    def read_u16(self) -> int:
        return struct.unpack_from('<H', self.read_bytes(2))[0]

    def read_i32(self) -> int:
        return struct.unpack_from('<i', self.read_bytes(4))[0]

    def read_u32(self) -> int:
        return struct.unpack_from('<I', self.read_bytes(4))[0]

    def read_i64(self) -> int:
        return struct.unpack_from('<q', self.read_bytes(8))[0]

    def read_u64(self) -> int:
        return struct.unpack_from('<Q', self.read_bytes(8))[0]

    def read_f32(self) -> float:
        return struct.unpack_from('<f', self.read_bytes(4))[0]

    def read_f64(self) -> float:
        return struct.unpack_from('<d', self.read_bytes(8))[0]

    def read_wstring(self) -> str:
        byte_len = self.read_varuint()
        raw = self.read_bytes(byte_len)
        return raw.decode('utf-16le', errors='replace').rstrip('\x00')

    def read_string(self) -> str:
        byte_len = self.read_varuint()
        raw = self.read_bytes(byte_len)
        return raw.decode('utf-8', errors='replace').rstrip('\x00')

    def read_vector(self, item_parser):
        count = self.read_varuint()
        return [item_parser(self) for _ in range(count)]

