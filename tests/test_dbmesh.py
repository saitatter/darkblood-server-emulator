"""tools/dbmesh.py: Dark Blood .x/.prt/.ani layout (client loader 0x00B1DDB0)."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import dbmesh  # noqa: E402

IDENT = struct.pack('<16f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(b | 0x80)   # JSerBuffer: the last group has bit 7 set
            return bytes(out)
        out.append(b)


def string(s):
    b = s.encode('ascii')
    return varint(len(b)) + b


def mesh_stream():
    verts = [(0, 0, 0), (10, 0, 0), (0, 10, 0)]
    out = bytearray(b'\x01' + struct.pack('<i', 1) + b'\x01\x01')   # present, ?, valid, skin
    out += struct.pack('<II', 3, 1)
    for x, y, z in verts:
        out += struct.pack('<8f', x, y, z, 0, 0, -1, x / 10, y / 10)
    out += struct.pack('<3H', 0, 1, 2) + struct.pack('<I', 0)
    out += varint(1) + struct.pack('<5I', 0, 0, 1, 0, 3)
    out += struct.pack('<I', 1) + varint(0)
    out += struct.pack('<17f', 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 3.2)
    out += varint(1) + string('tex.tga')
    out += struct.pack('<3I', 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)          # adjacency
    out += struct.pack('<i', 1) + struct.pack('<f', 0.0)                    # bones, min infl
    out += string('bone') + struct.pack('<I', 3) + varint(3) + struct.pack('<3I', 0, 1, 2)
    out += varint(3) + struct.pack('<3f', 1, 1, 1) + IDENT
    return bytes(out)


def model_file(with_mesh=True):
    ms = mesh_stream() if with_mesh else b''
    out = bytearray(varint(len(ms)) + (b'\x00' + ms if ms else b''))
    # root frame '' -> child 'bone' (has mesh)
    out += string('') + IDENT + bytes([0, 0, 1])
    out += string('bone') + IDENT + bytes([1 if with_mesh else 0, 0, 0])
    out += struct.pack('<4I', 2, 1, 2, 1)
    # one animation set with one track
    out += struct.pack('<i', 1) + string('Anim-1') + struct.pack('<d', 4800.0) + struct.pack('<ii', 0, 1)
    out += string('bone') + struct.pack('<3i', 2, 2, 2)
    out += struct.pack('<5f', 0, 0, 0, 0, 1) + struct.pack('<5f', 160, 0, 0, 0, 1)   # rotation
    out += struct.pack('<4f', 0, 0, 0, 0) + struct.pack('<4f', 160, 5, 0, 0)        # translation
    out += struct.pack('<4f', 0, 1, 1, 1) + struct.pack('<4f', 160, 1, 1, 1)        # scale
    return bytes(out)


class DbMeshTest(unittest.TestCase):
    def test_parse_mesh_skin_and_animation(self):
        m = dbmesh.parse(model_file())
        self.assertEqual(len(m.meshes), 1)
        mesh = m.meshes[0]
        self.assertEqual((mesh.vertex_count, mesh.face_count), (3, 1))
        self.assertEqual(mesh.frame, 'bone')
        self.assertEqual(mesh.materials[0].texture, 'tex.tga')
        self.assertEqual([b.name for b in mesh.bones], ['bone'])
        self.assertEqual(mesh.bones[0].vertices, [0, 1, 2])
        self.assertEqual([f.name for f in m.frames()], ['', 'bone'])
        self.assertEqual(m.anim_params, (2, 1, 2, 1))
        track = m.animations[0].tracks[0]
        self.assertEqual(track.frame, 'bone')
        self.assertEqual(track.translations[1], (160.0, (5.0, 0.0, 0.0)))
        self.assertEqual(m.animations[0].length_ticks, 160.0)

    def test_animation_only_file(self):
        m = dbmesh.parse(model_file(with_mesh=False))
        self.assertEqual(m.meshes, [])
        self.assertEqual(len(m.animations), 1)
        with tempfile.TemporaryDirectory() as d, self.assertRaises(dbmesh.MeshFormatError):
            m.path = os.path.join(d, 'a.ani')
            dbmesh.export_obj(m, d)

    def test_export_obj(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'm.x'
            p.write_bytes(model_file())
            (Path(d) / 'TEX.tga').write_bytes(b'')
            obj = dbmesh.export_obj(dbmesh.load(p), Path(d) / 'out')
            text = obj.read_text()
            self.assertEqual(text.count('\nv '), 3)
            self.assertIn('f 1/1/1 3/3/3 2/2/2', text)     # winding reversed for right-handed OBJ
            self.assertIn('map_kd tex.tga', (Path(d) / 'out' / 'm.mtl').read_text().lower())

    def test_rejects_directx_xof(self):
        with self.assertRaises(dbmesh.MeshFormatError):
            dbmesh.parse(b'xof 0303bzip0032....')

    @unittest.skipUnless((ROOT.parent / 'darkblood-client-data' / 'files' / 'data' / 'unit').is_dir(),
                         'private client data workspace not present')
    def test_real_goblin(self):
        p = ROOT.parent / 'darkblood-client-data/files/data/unit/monster/goblin/goblin_archer.x'
        m = dbmesh.load(p)
        self.assertEqual((len(m.meshes), m.vertex_count, m.face_count), (7, 2301, 2838))


if __name__ == '__main__':
    unittest.main()
