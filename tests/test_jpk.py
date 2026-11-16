"""JPK reader/packer round trips on synthetic archives (no game data needed)."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

from jpk_extractor import MAGIC, Archive, decrypt_data, encrypt_data  # noqa: E402
from jpk_pack import pack, stored_blob, varint, wstr, wrap_j  # noqa: E402


def synthetic(path, files, encrypted):
    """Write an archive with the layout documented in docs/JPK_FORMAT.md."""
    header = MAGIC + struct.pack('<II', 14, 1) + b'\x00' * (0x218 - 16)
    blobs, table, offset = [], bytearray(), 0
    for name, plain in files:
        blob = wrap_j(plain) if name.endswith('.j') else plain
        if encrypted:
            blob = encrypt_data(blob)
        table += wstr(name) + wstr('d:\\build\\' + name)
        table += struct.pack('<IIIIB', 0x5334D051, 0, len(blob), offset, 1)
        blobs.append(blob)
        offset += len(blob)
    toc = struct.pack('<IIBBBI', len(files), offset, 0, 0, int(encrypted),
                      2 if encrypted else 0xFFFFFFFF) + bytes(table)
    path.write_bytes(header + struct.pack('<I', len(toc)) + toc + b''.join(blobs))


FILES = [('data\\dict\\a.lua', b'\x1bLuaQ\x00 table'),
         ('data\\effect\\b.eff.j', b'EFFECT = {\r\n' * 50)]


class JpkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cipher_inverse(self):
        data = bytes(range(256)) * 3
        self.assertEqual(decrypt_data(encrypt_data(data)), data)

    def test_varint_terminal_bit(self):
        self.assertEqual(varint(0), b'\x80')
        self.assertEqual(varint(0x695c), bytes([0x5c, 0x52, 0x81]))  # observed .j header

    def test_read_and_identical_rebuild(self):
        for encrypted in (False, True):
            src = self.dir / ('e%d.jpk' % encrypted)
            synthetic(src, FILES, encrypted)
            arc = Archive(str(src))
            self.assertEqual(arc.encrypted, encrypted)
            self.assertEqual([arc.read(e) for e in arc.entries], [p for _, p in FILES])
            out, used = pack(src, None, {})
            self.assertEqual(out, src.read_bytes())
            self.assertEqual(used, [])

    def test_replace_entries(self):
        src, dst = self.dir / 'src.jpk', self.dir / 'dst.jpk'
        synthetic(src, FILES, encrypted=True)
        new_lua, new_eff = b'\x1bLuaQ\x00 edited and longer', b'EFFECT = { }'
        _, used = pack(src, dst, {'data/dict/A.lua': new_lua, 'data\\effect\\b.eff': new_eff})
        self.assertEqual(used, ['data\\dict\\a.lua', 'data\\effect\\b.eff'])
        arc = Archive(str(dst))
        self.assertEqual([arc.read(e) for e in arc.entries], [new_lua, new_eff])
        self.assertEqual([e.crc for e in arc.entries], [0x5334D051] * 2)
        self.assertEqual(stored_blob(arc, arc.entries[0], new_lua), encrypt_data(new_lua))

    def test_unknown_entry_rejected(self):
        src = self.dir / 'src.jpk'
        synthetic(src, FILES, encrypted=False)
        with self.assertRaises(KeyError):
            pack(src, None, {'data\\missing.lua': b''})


if __name__ == '__main__':
    unittest.main()
