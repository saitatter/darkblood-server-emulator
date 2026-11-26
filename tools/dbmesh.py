#!/usr/bin/env python3
"""Parse Dark Blood skinned-mesh files (``.x`` units, ``.prt`` parts) and export them.

The client's ``.x`` files are not DirectX X files (only 14 effect files carry
the ``xof 0303bzip0032`` magic; those are not handled here). The layout below
follows the client's own loader (build in docs/STATUS.md), verified by
disassembly on 2026-11-26 and checked against every extracted mesh:

* ``0x00B1DDB0`` top level. The JPK ``.j`` wrapper is a JSerBuffer sub-buffer
  (varint length, u8 flag, bytes); the extractor already removes it. Inside:
    sub-buffer   mesh stream (varint length, u8 flag, bytes)
    frame tree   read from the outer stream, see below
    u32 x4       passed to D3DXCreateAnimationController (max outputs,
                 animation sets, tracks, events)
    animations   ``0x00B1CD60``: i32 set_count; per set: string name, f64
                 ticks_per_second, i32 playback type, i32 animation_count ->
                 D3DXCreateKeyframedAnimationSet; per animation (one per frame
                 name): string frame, i32 x3 key counts, then raw rotation keys
                 (f32 time + quaternion x,y,z,w), translation keys (f32 time +
                 xyz) and scale keys (f32 time + xyz) -> RegisterAnimationSRTKeys.
                 The three counts were equal in every extracted file, so which
                 count belongs to which key type is not settled.
* ``.ani`` files use the same layout with an empty mesh stream and no meshes.
* ``0x00B1D6E0`` frame, recursive (D3DXFRAME):
    string name; f32[16] TransformationMatrix (row-major, D3D row vectors);
    bool has_mesh; bool has_sibling; bool has_child
    if has_mesh: one mesh container is read from the *mesh stream*
    if has_child: frame (-> pFrameFirstChild +0x4C), then if has_sibling: frame (+0x48)
* mesh container, from the mesh stream:
    bool present; i32 unknown; bool valid; bool has_skin
    u32 vertex_count; u32 face_count
    D3DXCreateMeshFVF(faces, vertices, 0x220 MANAGED, FVF 0x112 = XYZ|NORMAL|TEX1)
    ``0x00B1D530``: vertex bytes (count * 32: pos[3], normal[3], uv[2]),
      u16 indices (faces * 3), u32 attribute ids (faces),
      vector<D3DXATTRIBUTERANGE> (varint n; AttribId, FaceStart, FaceCount,
      VertexStart, VertexCount)
    u32 material_count; string name; D3DMATERIAL9[material_count] (68 bytes)
    vector<string> texture names (``0x008FA810``; one per material)
    u32 adjacency[faces * 3]
    if has_skin: i32 bone_count -> D3DXCreateSkinInfoFVF(vertices, 0x112, bones)
      ``0x00B1D2E0``: f32 min_bone_influence; per bone:
        string name; u32 influence_count; vector<u32> vertices;
        vector<f32> weights; f32[16] offset matrix
* strings / vectors use JSerBuffer varints (7-bit groups, last byte has bit 7 SET).
  Files are written untagged, so the serializer's type-tag bytes are absent.

Usage:
    python tools/dbmesh.py info  <file-or-dir>              # .x / .prt / .ani
    python tools/dbmesh.py export <file-or-dir> --out DIR   # Wavefront OBJ + MTL + textures
"""
import argparse
import os
import shutil
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

MESH_SUFFIXES = ('.x', '.prt')
ANIM_SUFFIXES = ('.ani',)
VERTEX_STRIDE = 32
IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


class MeshFormatError(ValueError):
    pass


class Reader:
    """Untagged JSerBuffer reader."""

    def __init__(self, data, pos=0, end=None):
        self.d = data
        self.i = pos
        self.end = len(data) if end is None else end

    def need(self, n):
        if n < 0 or self.i + n > self.end:
            raise MeshFormatError('truncated at 0x%X (need %d bytes)' % (self.i, n))

    def raw(self, n):
        self.need(n)
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def unpack(self, fmt):
        size = struct.calcsize(fmt)
        self.need(size)
        v = struct.unpack_from(fmt, self.d, self.i)
        self.i += size
        return v

    def u8(self):
        return self.unpack('<B')[0]

    def bool(self):
        return self.u8() != 0

    def u32(self):
        return self.unpack('<I')[0]

    def i32(self):
        return self.unpack('<i')[0]

    def f32(self):
        return self.unpack('<f')[0]

    def varint(self):
        v = s = 0
        while True:
            b = self.u8()
            v |= (b & 0x7F) << s
            s += 7
            if b & 0x80:
                return v
            if s > 35:
                raise MeshFormatError('varint too long at 0x%X' % self.i)

    def string(self):
        n = self.varint()
        return self.raw(n).decode('cp949', 'replace')

    def count(self, limit=1 << 20):
        n = self.varint()
        if n > limit:
            raise MeshFormatError('implausible count %d at 0x%X' % (n, self.i))
        return n

    def sub(self):
        """JSerBuffer sub-buffer: varint length, u8 flag, bytes (0x00B35E50)."""
        n = self.varint()
        if n == 0:
            return Reader(b''), 0
        flag = self.u8()
        self.need(n)
        r = Reader(self.d, self.i, self.i + n)
        self.i += n
        return r, flag


@dataclass
class Material:
    diffuse: tuple
    ambient: tuple
    specular: tuple
    emissive: tuple
    power: float
    texture: str = ''


@dataclass
class Group:
    material: int
    face_start: int
    face_count: int


@dataclass
class Bone:
    name: str
    vertices: list
    weights: list
    offset: tuple          # 16 floats, row-major


@dataclass
class Mesh:
    frame: str
    positions: list        # flat xyz, D3D left-handed mesh space
    normals: list
    uvs: list              # flat uv, D3D convention (v grows downward)
    indices: list          # flat u16 triangle list, clockwise front faces
    groups: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    name: str = ''
    unknown_i32: int = 0
    bones: list = field(default_factory=list)
    min_bone_influence: float = 0.0

    @property
    def vertex_count(self):
        return len(self.positions) // 3

    @property
    def face_count(self):
        return len(self.indices) // 3


@dataclass
class Frame:
    name: str
    matrix: tuple          # 16 floats, row-major, local to parent
    mesh: int = -1         # index into Model.meshes
    children: list = field(default_factory=list)


@dataclass
class Track:
    frame: str
    rotations: list        # [(time, (x, y, z, w)), ...]
    translations: list     # [(time, (x, y, z)), ...]
    scales: list           # [(time, (x, y, z)), ...]


@dataclass
class AnimationSet:
    name: str
    ticks_per_second: float
    playback: int
    tracks: list

    @property
    def length_ticks(self):
        return max((k[-1][0] for t in self.tracks for k in (t.rotations, t.translations, t.scales) if k),
                   default=0.0)


@dataclass
class Model:
    path: str
    root: Frame
    meshes: list
    anim_params: tuple = ()
    animations: list = field(default_factory=list)

    def frames(self):
        out, stack = [], [self.root]
        while stack:
            f = stack.pop()
            out.append(f)
            stack.extend(reversed(f.children))
        return out

    @property
    def vertex_count(self):
        return sum(m.vertex_count for m in self.meshes)

    @property
    def face_count(self):
        return sum(m.face_count for m in self.meshes)


def _read_mesh(ms, frame_name):
    present = ms.bool()
    unknown = ms.i32()
    valid = ms.bool()
    has_skin = ms.bool()
    if not (present and valid):
        raise MeshFormatError('mesh container flags present=%d valid=%d' % (present, valid))
    nv, nf = ms.u32(), ms.u32()
    if nv == 0 or nf == 0 or nv > 0x10000:
        raise MeshFormatError('implausible counts: %d vertices, %d faces' % (nv, nf))
    verts = ms.unpack('<%df' % (nv * 8))
    positions, normals, uvs = [], [], []
    for k in range(0, len(verts), 8):
        positions.extend(verts[k:k + 3])
        normals.extend(verts[k + 3:k + 6])
        uvs.extend(verts[k + 6:k + 8])
    indices = list(ms.unpack('<%dH' % (nf * 3)))
    if max(indices) >= nv:
        raise MeshFormatError('index out of range')
    face_attr = ms.unpack('<%dI' % nf)
    groups = []
    for _ in range(ms.count()):
        attrib, f0, fc, _v0, _vc = ms.unpack('<5I')
        groups.append(Group(attrib, f0, fc))
    if not groups:
        for f, a in enumerate(face_attr):
            if groups and groups[-1].material == a:
                groups[-1].face_count += 1
            else:
                groups.append(Group(a, f, 1))

    n_mat = ms.u32()
    if n_mat > 256:
        raise MeshFormatError('implausible material count %d' % n_mat)
    name = ms.string()
    materials = []
    for _ in range(n_mat):
        f = ms.unpack('<17f')
        materials.append(Material(f[0:4], f[4:8], f[8:12], f[12:16], f[16]))
    textures = [ms.string() for _ in range(ms.count(4096))]
    for k, t in enumerate(textures[:n_mat]):
        materials[k].texture = t
    ms.raw(nf * 12)  # adjacency

    mesh = Mesh(frame_name, positions, normals, uvs, indices, groups, materials, name, unknown)
    if has_skin:
        n_bones = ms.i32()
        if not 0 <= n_bones <= 1024:
            raise MeshFormatError('implausible bone count %d' % n_bones)
        mesh.min_bone_influence = ms.f32()
        for _ in range(n_bones):
            bname = ms.string()
            ms.u32()  # influence count, repeated by the vectors below
            bverts = list(ms.unpack('<%dI' % ms.count()))
            bweights = list(ms.unpack('<%df' % ms.count()))
            offset = ms.unpack('<16f')
            mesh.bones.append(Bone(bname, bverts, bweights, offset))
    return mesh


def _read_frame(fs, ms, meshes, depth=0):
    if depth > 256:
        raise MeshFormatError('frame tree too deep')
    frame = Frame(fs.string(), fs.unpack('<16f'))
    has_mesh, has_sibling, has_child = fs.bool(), fs.bool(), fs.bool()
    if has_mesh:
        meshes.append(_read_mesh(ms, frame.name))
        frame.mesh = len(meshes) - 1
    siblings = []
    if has_child:
        child, child_sibs = _read_frame(fs, ms, meshes, depth + 1)
        frame.children = [child] + child_sibs
    if has_sibling:
        sib, more = _read_frame(fs, ms, meshes, depth)
        siblings = [sib] + more
    return frame, siblings


def _keys(fs, n, width):
    v = fs.unpack('<%df' % (n * (width + 1)))
    step = width + 1
    return [(v[k], tuple(v[k + 1:k + step])) for k in range(0, len(v), step)]


def _read_animations(fs):
    sets = []
    n_sets = fs.i32()
    if not 0 <= n_sets <= 4096:
        raise MeshFormatError('implausible animation set count %d' % n_sets)
    for _ in range(n_sets):
        name = fs.string()
        (tps,) = fs.unpack('<d')
        playback, n_anim = fs.i32(), fs.i32()
        if not 0 <= n_anim <= 4096:
            raise MeshFormatError('implausible animation count %d' % n_anim)
        tracks = []
        for _ in range(n_anim):
            frame = fs.string()
            c0, c1, c2 = fs.i32(), fs.i32(), fs.i32()
            if min(c0, c1, c2) < 0 or max(c0, c1, c2) > 1 << 20:
                raise MeshFormatError('implausible key counts')
            rot = _keys(fs, c0, 4)
            trans = _keys(fs, c1, 3)
            scale = _keys(fs, c2, 3)
            tracks.append(Track(frame, rot, trans, scale))
        sets.append(AnimationSet(name, tps, playback, tracks))
    return sets


def parse(data, path=''):
    """Parse a mesh (.x/.prt) or animation (.ani) file. Models may have no meshes."""
    if data.startswith(b'xof '):
        raise MeshFormatError('DirectX compressed X file (xof bzip) is not supported')
    fs = Reader(data)
    ms, _flag = fs.sub()
    meshes = []
    root, siblings = _read_frame(fs, ms, meshes)
    if siblings:  # never observed; keep them under a synthetic root
        root = Frame('', IDENTITY, -1, [root] + siblings)
    anim = fs.unpack('<4I') if fs.end - fs.i >= 16 else ()
    animations = _read_animations(fs) if fs.end - fs.i >= 4 else []
    return Model(path, root, meshes, anim, animations)


def load(path):
    path = Path(path)
    return parse(path.read_bytes(), str(path))


# --------------------------------------------------------------------------- math

def mat_mul(a, b):
    """Row-major 4x4 product a*b (D3D row-vector convention: v' = v * a * b)."""
    return tuple(sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4))


def transform_point(m, p):
    x, y, z = p
    return (x * m[0] + y * m[4] + z * m[8] + m[12],
            x * m[1] + y * m[5] + z * m[9] + m[13],
            x * m[2] + y * m[6] + z * m[10] + m[14])


def combined_matrices(model):
    """Map frame name -> combined (model-space) matrix in bind pose."""
    out = {}

    def walk(f, parent):
        m = mat_mul(f.matrix, parent)
        out[f.name] = m
        for c in f.children:
            walk(c, m)

    walk(model.root, IDENTITY)
    return out


# ------------------------------------------------------------------------- export

def find_texture(mesh_path, name):
    """Resolve a texture name case-insensitively in the mesh's own folder."""
    if not name:
        return None
    folder = Path(mesh_path).parent
    direct = folder / name
    if direct.is_file():
        return direct
    want = name.lower()
    try:
        for entry in folder.iterdir():
            if entry.name.lower() == want:
                return entry
    except OSError:
        pass
    return None


def export_obj(model, out_dir):
    """Export the bind-pose model as one OBJ (right-handed, Z mirrored) + MTL."""
    if not model.meshes:
        raise MeshFormatError('no mesh in frame tree (skeleton/animation only)')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(model.path).stem
    combined = combined_matrices(model)
    lines = ['# Dark Blood mesh %s' % Path(model.path).name, 'mtllib %s.mtl' % stem]
    mtl, base, mat_base = [], 0, 0
    for mi, mesh in enumerate(model.meshes):
        # Skinned meshes are stored in model space; rigid ones in their frame's space.
        world = IDENTITY if mesh.bones else combined.get(mesh.frame, IDENTITY)
        lines.append('o %s' % (mesh.frame or 'mesh%d' % mi))
        p, n, t = mesh.positions, mesh.normals, mesh.uvs
        for k in range(mesh.vertex_count):
            x, y, z = transform_point(world, p[3 * k:3 * k + 3])
            lines.append('v %.6f %.6f %.6f' % (x, y, -z))
        for k in range(mesh.vertex_count):
            lines.append('vt %.6f %.6f' % (t[2 * k], 1.0 - t[2 * k + 1]))
        for k in range(mesh.vertex_count):
            nx, ny, nz = n[3 * k:3 * k + 3]
            nx, ny, nz = (nx * world[0] + ny * world[4] + nz * world[8],
                          nx * world[1] + ny * world[5] + nz * world[9],
                          nx * world[2] + ny * world[6] + nz * world[10])
            lines.append('vn %.6f %.6f %.6f' % (nx, ny, -nz))
        for g in mesh.groups:
            lines.append('usemtl mat%d' % (mat_base + g.material))
            for f in range(g.face_start, g.face_start + g.face_count):
                a, b, c = (base + x + 1 for x in mesh.indices[3 * f:3 * f + 3])
                # D3D: left-handed, clockwise front faces. Mirroring Z and reversing
                # the winding keeps the model looking the same in right-handed OBJ.
                lines.append('f %d/%d/%d %d/%d/%d %d/%d/%d' % (a, a, a, c, c, c, b, b, b))
        for k, m in enumerate(mesh.materials):
            mtl += ['newmtl mat%d' % (mat_base + k), 'Kd %.4f %.4f %.4f' % m.diffuse[:3],
                    'Ka %.4f %.4f %.4f' % m.ambient[:3], 'Ks %.4f %.4f %.4f' % m.specular[:3],
                    'Ns %.4f' % m.power, 'd %.4f' % m.diffuse[3]]
            tex = find_texture(model.path, m.texture)
            if tex:
                shutil.copyfile(tex, out_dir / tex.name)
                mtl.append('map_Kd %s' % tex.name)
            mtl.append('')
        base += mesh.vertex_count
        mat_base += max(len(mesh.materials), 1)
    (out_dir / (stem + '.obj')).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (out_dir / (stem + '.mtl')).write_text('\n'.join(mtl), encoding='utf-8')
    return out_dir / (stem + '.obj')


def iter_meshes(root, suffixes=MESH_SUFFIXES):
    root = Path(root)
    if root.is_file():
        yield root
        return
    for dp, _dn, fn in os.walk(root):
        for f in sorted(fn):
            if f.lower().endswith(suffixes):
                yield Path(dp) / f


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sp = sub.add_parser('info', help='print mesh summary')
    sp.add_argument('path')
    sp = sub.add_parser('export', help='export OBJ/MTL (+ textures)')
    sp.add_argument('path')
    sp.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    if args.cmd == 'info':
        ok = failed = 0
        for p in iter_meshes(args.path, MESH_SUFFIXES + ANIM_SUFFIXES):
            try:
                m = load(p)
            except (MeshFormatError, struct.error) as e:
                failed += 1
                print('%s: FAILED %s' % (p, e))
                continue
            ok += 1
            print('%s: %d mesh(es), %d verts, %d tris, %d frames, %d bones, %d anim set(s), textures %s'
                  % (p, len(m.meshes), m.vertex_count, m.face_count, len(m.frames()),
                     sum(len(x.bones) for x in m.meshes), len(m.animations),
                     [t.texture for x in m.meshes for t in x.materials]))
        print('parsed %d, failed %d' % (ok, failed))
        return 1 if failed else 0

    src = Path(args.path)
    ok = failed = 0
    for p in iter_meshes(src):
        rel = p.parent.relative_to(src) if src.is_dir() else Path('.')
        try:
            export_obj(load(p), Path(args.out) / rel)
            ok += 1
        except (MeshFormatError, struct.error) as e:
            failed += 1
            print('skip %s: %s' % (p, e), file=sys.stderr)
    print('exported %d meshes, %d skipped' % (ok, failed))
    return 0


if __name__ == '__main__':
    sys.exit(main())
