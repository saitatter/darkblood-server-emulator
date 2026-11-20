"""JSerBuffer / JEvent primitives recovered from client 0xA1EB90/0xB35E50.

Varuints use 7-bit groups terminated by a byte with bit 7 SET (unlike
ProudNet scalars, see core.network.proudnet)."""
import struct
import zlib


# Header word of every client request body: 0x00A1E620 writes it, and reply
# handlers read the same slot as the result via 0x00A1EA20. Observed live.
REQUEST_HEADER = 0x7FFFFFFF
REQUEST_HEADER_BYTES = b'\xff\xff\xff\x7f'


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


def read_wide(data: bytes, offset: int = 0):
    """Read length-prefixed UTF-16LE string from bytes, returning (text, next_offset)."""
    length, noff = read_varuint(data, offset)
    val = data[noff:noff + length].decode('utf-16le', errors='replace').rstrip('\x00')
    return val, noff + length


def event(opcode, body=b'', correlation=0, compress=False):
    # Nonempty body includes a compression boolean; empty body omits it.
    if body and compress:
        compressed_body = struct.pack('<I', len(body)) + zlib.compress(body)
        return (struct.pack('<IQ', opcode, correlation) + varuint(len(compressed_body))
                + b'\x01' + compressed_body)
    return (struct.pack('<IQ', opcode, correlation) + varuint(len(body))
            + (b'\x00' + body if body else b''))


def strip_prefix(data: bytes, prefix: bytes = b'\xff\xff\xff\x7f') -> bytes:
    """Strips client correlation/call prefix (e.g. 0x7FFFFFFF from 0x00408C60) if present."""
    if data and data.startswith(prefix):
        return data[len(prefix):]
    return data


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
        # Client form: flag 1 + 4-byte uncompressed size + zlib compressed stream.
        # Note: Some client events (e.g. 2203) set compressed=True with plain raw bodies.
        if len(body) > 6 and body[4] == 0x78:
            try:
                inflated = zlib.decompress(body[4:])
                if len(inflated) == struct.unpack_from('<I', body)[0]:
                    body = inflated
            except Exception:
                pass
        else:
            try:
                body = zlib.decompress(body)
            except Exception:
                pass
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

    def expect_tag(self, tag: int) -> None:
        """Consume a container tag byte (0x0F..0x1A; 0x00B35010 skips others)."""
        got = self.read_u8()
        if got != tag:
            raise WireError(f'Expected tag 0x{tag:02X}, got 0x{got:02X} at offset {self.offset - 1}')

    def read_tagged_vector(self, item_parser):
        """Tag 0x10, J-varuint count, elements."""
        self.expect_tag(0x10)
        return self.read_vector(item_parser)

    def read_tagged_map(self, key_parser, value_parser):
        """Tag 0x17, J-varuint count, then per pair tag 0x0F, key, value."""
        self.expect_tag(0x17)
        result = {}
        for _ in range(self.read_varuint()):
            self.expect_tag(0x0F)
            key = key_parser(self)
            result[key] = value_parser(self)
        return result

    def read_tagged_set(self, item_parser):
        """Tag 0x13, J-varuint count, elements."""
        self.expect_tag(0x13)
        return self.read_vector(item_parser)

    def read_empty_container(self, tag: int) -> None:
        """A container whose element layout is not recovered: only the empty form is accepted."""
        self.expect_tag(tag)
        count = self.read_varuint()
        if count:
            raise WireError(f'Container 0x{tag:02X} with {count} elements of unknown layout')

    def read_rest(self) -> bytes:
        return self.read_bytes(self.remaining)

    def peek(self, count: int) -> bytes:
        return self.data[self.offset:self.offset + count]

    def expect_bytes(self, expected: bytes) -> None:
        got = self.read_bytes(len(expected))
        if got != expected:
            raise WireError(f'Expected {expected.hex()}, got {got.hex()} at offset {self.offset - len(expected)}')

