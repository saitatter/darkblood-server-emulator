"""Comprehensive tests for ProudNet framing, scalars, TCP fragmentation/coalescing,
and bounded JSerBuffer/JEvent serialization (Milestone P1).
"""
import struct
import unittest
import zlib

from darkblood.core.network import proudnet
from darkblood.core.serialization import jser


class ProudNetTransportTest(unittest.TestCase):
    def test_signed_scalar_boundaries(self):
        # 1-byte signed range: -128 to 127
        self.assertEqual(proudnet.scalar(0), b'\x01\x00')
        self.assertEqual(proudnet.scalar(127), b'\x01\x7f')
        self.assertEqual(proudnet.scalar(-128), b'\x01\x80')

        # 2-byte signed range: 128 to 32767, -32768 to -129
        self.assertEqual(proudnet.scalar(128), b'\x02\x80\x00')
        self.assertEqual(proudnet.scalar(32767), b'\x02\xff\x7f')
        self.assertEqual(proudnet.scalar(-129), b'\x02\x7f\xff')
        self.assertEqual(proudnet.scalar(-32768), b'\x02\x00\x80')

        # 4-byte signed range: 32768 to 2147483647, -2147483648 to -32769
        self.assertEqual(proudnet.scalar(32768), b'\x04\x00\x80\x00\x00')
        self.assertEqual(proudnet.scalar(2147483647), b'\x04\xff\xff\xff\x7f')
        self.assertEqual(proudnet.scalar(-2147483648), b'\x04\x00\x00\x00\x80')

        # 8-byte signed range: beyond 32-bit
        self.assertEqual(proudnet.scalar(2147483648), b'\x08\x00\x00\x00\x80\x00\x00\x00\x00')
        self.assertEqual(proudnet.scalar(-2147483649), b'\x08\xff\xff\xff\x7f\xff\xff\xff\xff')

        # Beyond 64-bit raises OverflowError
        with self.assertRaises(OverflowError):
            proudnet.scalar(1 << 63)
        with self.assertRaises(OverflowError):
            proudnet.scalar(-(1 << 63) - 1)

    def test_read_scalar_boundaries_and_invalid_widths(self):
        # Valid reads
        val, end = proudnet.read_scalar(b'\x01\x05')
        self.assertEqual((val, end), (5, 2))

        val, end = proudnet.read_scalar(b'\x02\x00\x01')
        self.assertEqual((val, end), (256, 3))

        val, end = proudnet.read_scalar(b'\x04\x00\x00\x01\x00')
        self.assertEqual((val, end), (65536, 5))

        # Truncated data returns None
        self.assertIsNone(proudnet.read_scalar(b''))
        self.assertIsNone(proudnet.read_scalar(b'\x02\x01'))
        self.assertIsNone(proudnet.read_scalar(b'\x04\x01\x02\x03'))

        # Invalid width bytes raise ProtocolError
        for invalid_w in (0, 3, 5, 6, 7, 9, 255):
            with self.assertRaises(proudnet.ProtocolError):
                proudnet.read_scalar(bytes([invalid_w, 0x01]))

    def test_first_client_captured_frame_regression_fixture(self):
        """Regression test for the documented initial frame: 13 57 01 05 30 0F 00 00 40."""
        fixture = bytearray(b'\x13\x57\x01\x05\x30\x0f\x00\x00\x40')
        payload = proudnet.pop_frame(fixture)
        self.assertEqual(payload, b'\x30\x0f\x00\x00\x40')
        self.assertEqual(len(fixture), 0)

        # Dissect payload
        msg_type = payload[0]
        u32_param = struct.unpack_from('<I', payload, 1)[0]
        self.assertEqual(msg_type, 0x30)
        self.assertEqual(u32_param, 0x4000000F)

    def test_tcp_fragmented_frames(self):
        """Simulate TCP delivery in arbitrary 1-byte or small chunks."""
        full_frame = proudnet.frame(b'DarkBlood_TCP_Test')
        buf = bytearray()
        for i in range(len(full_frame) - 1):
            buf.append(full_frame[i])
            self.assertIsNone(proudnet.pop_frame(buf), f"Frame popped prematurely at byte {i}")
        buf.append(full_frame[-1])
        payload = proudnet.pop_frame(buf)
        self.assertEqual(payload, b'DarkBlood_TCP_Test')
        self.assertEqual(len(buf), 0)

    def test_tcp_coalesced_frames(self):
        """Simulate multiple ProudNet frames arriving in a single TCP read."""
        f1 = proudnet.frame(b'Frame1')
        f2 = proudnet.frame(b'Frame2_Middle')
        f3 = proudnet.frame(b'Frame3_Last')
        buf = bytearray(f1 + f2 + f3)

        self.assertEqual(proudnet.pop_frame(buf), b'Frame1')
        self.assertEqual(proudnet.pop_frame(buf), b'Frame2_Middle')
        self.assertEqual(proudnet.pop_frame(buf), b'Frame3_Last')
        self.assertIsNone(proudnet.pop_frame(buf))
        self.assertEqual(len(buf), 0)

    def test_invalid_magic_and_oversized_frames(self):
        with self.assertRaises(proudnet.ProtocolError):
            proudnet.pop_frame(bytearray(b'\x99\x99\x01\x05hello'))

        with self.assertRaises(proudnet.ProtocolError):
            proudnet.frame(b'')

        with self.assertRaises(proudnet.ProtocolError):
            proudnet.frame(b'X' * (proudnet.MAX_FRAME + 1))


class JSerBufferSerializationTest(unittest.TestCase):
    def test_varuint_inverted_terminal_bit(self):
        # Bit 7 terminates: 0 -> 0x80, 1 -> 0x81, 127 -> 0xFF, 128 -> 0x00 0x81
        self.assertEqual(jser.varuint(0), b'\x80')
        self.assertEqual(jser.varuint(1), b'\x81')
        self.assertEqual(jser.varuint(127), b'\xff')
        self.assertEqual(jser.varuint(128), b'\x00\x81')
        self.assertEqual(jser.varuint(255), b'\x7f\x81')
        self.assertEqual(jser.varuint(16383), b'\x7f\xff')
        self.assertEqual(jser.varuint(16384), b'\x00\x00\x81')

        # Roundtrip through read_varuint
        for num in (0, 1, 64, 127, 128, 255, 1000, 16384, 65535, 12345678):
            encoded = jser.varuint(num)
            decoded, end = jser.read_varuint(encoded, 0)
            self.assertEqual(decoded, num)
            self.assertEqual(end, len(encoded))

    def test_varuint_errors(self):
        with self.assertRaises(ValueError):
            jser.varuint(-1)
        with self.assertRaises(ValueError):
            jser.varuint(0x100000000)

        # Truncated varuint (never has terminal bit 7 set)
        with self.assertRaises(jser.WireError):
            jser.read_varuint(b'\x01\x02\x03', 0)

        # Excessively long varuint (> 35 bits shift)
        with self.assertRaises(jser.WireError):
            jser.read_varuint(b'\x01\x01\x01\x01\x01\x01', 0)

    def test_jser_buffer_reader_primitives(self):
        # Pack various primitives into a buffer
        data = (
            struct.pack('<b', -42) +
            struct.pack('<B', 200) +
            struct.pack('<h', -1234) +
            struct.pack('<H', 50000) +
            struct.pack('<i', -999999) +
            struct.pack('<I', 3000000000) +
            struct.pack('<q', -9876543210123) +
            struct.pack('<Q', 1234567890123456789) +
            struct.pack('<f', 3.14159) +
            struct.pack('<d', 2.718281828459) +
            struct.pack('<?', True) +
            jser.wide_string('DarkBlood') +
            jser.varuint(5) + b'hello'
        )

        r = jser.JSerBufferReader(data)
        self.assertTrue(r.has_remaining())
        self.assertEqual(r.read_i8(), -42)
        self.assertEqual(r.read_u8(), 200)
        self.assertEqual(r.read_i16(), -1234)
        self.assertEqual(r.read_u16(), 50000)
        self.assertEqual(r.read_i32(), -999999)
        self.assertEqual(r.read_u32(), 3000000000)
        self.assertEqual(r.read_i64(), -9876543210123)
        self.assertEqual(r.read_u64(), 1234567890123456789)
        self.assertAlmostEqual(r.read_f32(), 3.14159, places=4)
        self.assertAlmostEqual(r.read_f64(), 2.718281828459, places=8)
        self.assertTrue(r.read_bool())
        self.assertEqual(r.read_wstring(), 'DarkBlood')
        self.assertEqual(r.read_string(), 'hello')
        self.assertFalse(r.has_remaining())

    def test_jser_buffer_reader_vector_and_bounds(self):
        # Vector of 3 i32 integers
        vec_data = jser.varuint(3) + struct.pack('<iii', 10, 20, 30)
        r = jser.JSerBufferReader(vec_data)
        items = r.read_vector(lambda reader: reader.read_i32())
        self.assertEqual(items, [10, 20, 30])

        # Truncated read raises WireError
        short_r = jser.JSerBufferReader(b'\x01\x02')
        with self.assertRaises(jser.WireError):
            short_r.read_i32()

    def test_event_framing_and_compression(self):
        # Uncompressed event
        evt_uncomp = jser.event(2007, b'payload123', correlation=99)
        op, corr, comp, body = jser.parse_event(evt_uncomp)
        self.assertEqual((op, corr, comp, body), (2007, 99, False, b'payload123'))

        # Empty body event
        evt_empty = jser.event(2131, b'')
        op, corr, comp, body = jser.parse_event(evt_empty)
        self.assertEqual((op, corr, comp, body), (2131, 0, False, b''))

        # Compressed event (zlib)
        large_body = b'A' * 500 + b'B' * 500
        evt_comp = jser.event(5020, large_body, compress=True)
        op, corr, comp, body = jser.parse_event(evt_comp)
        self.assertEqual((op, comp), (5020, True))
        self.assertEqual(body, large_body)


if __name__ == '__main__':
    unittest.main()
