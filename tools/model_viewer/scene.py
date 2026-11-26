"""Scene, pose evaluation and CPU skinning for Dark Blood models (no Qt, no GL).

Conventions
-----------
* All matrices are row-major for D3D-style row vectors: ``p' = p @ M``.
* Game data is D3D left-handed, Y-up. The viewer world is Blender-like
  right-handed, Z-up. ``D3D_TO_WORLD`` swaps Y and Z, which flips handedness
  without mirroring the model and also turns D3D's clockwise front faces into
  counter-clockwise ones, so indices stay untouched.
* Skinning follows D3DX: ``bone = offset[b] @ combined[frame named b]``.
* Animation keys were verified against the .ani frame matrices: the stored
  quaternion is the conjugate of the D3DX rotation matrix's quaternion.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'client_data'))
import dbmesh  # noqa: E402

D3D_TO_WORLD = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=np.float64)


def mat(m16):
    return np.array(m16, dtype=np.float64).reshape(4, 4)


def quat_to_mat3(q):
    """Rows of the D3DX rotation for stored (conjugated) quaternions, vectorised (..., 4)."""
    x, y, z, w = -q[..., 0], -q[..., 1], -q[..., 2], q[..., 3]
    m = np.empty(q.shape[:-1] + (3, 3))
    m[..., 0, 0] = 1 - 2 * (y * y + z * z)
    m[..., 0, 1] = 2 * (x * y + z * w)
    m[..., 0, 2] = 2 * (x * z - y * w)
    m[..., 1, 0] = 2 * (x * y - z * w)
    m[..., 1, 1] = 1 - 2 * (x * x + z * z)
    m[..., 1, 2] = 2 * (y * z + x * w)
    m[..., 2, 0] = 2 * (x * z + y * w)
    m[..., 2, 1] = 2 * (y * z - x * w)
    m[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return m


def _slerp(a, b, t):
    d = float(np.dot(a, b))
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        r = a + (b - a) * t
    else:
        th = np.arccos(min(1.0, d))
        s = np.sin(th)
        r = (np.sin((1 - t) * th) * a + np.sin(t * th) * b) / s
    return r / (np.linalg.norm(r) or 1.0)


class Channel:
    def __init__(self, keys, width):
        self.times = np.array([k[0] for k in keys], dtype=np.float64)
        self.values = np.array([k[1] for k in keys], dtype=np.float64).reshape(-1, width)

    def sample(self, t, slerp=False):
        n = len(self.times)
        if n == 1 or t <= self.times[0]:
            return self.values[0]
        if t >= self.times[-1]:
            return self.values[-1]
        i = int(np.searchsorted(self.times, t, side='right')) - 1
        t0, t1 = self.times[i], self.times[i + 1]
        f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        a, b = self.values[i], self.values[i + 1]
        return _slerp(a, b, f) if slerp else a + (b - a) * f


class Clip:
    """A playable animation set."""

    def __init__(self, aset, source):
        self.name = aset.name
        self.source = source
        self.tps = aset.ticks_per_second or 4800.0
        self.length = aset.length_ticks
        self.tracks = {}
        deltas = []
        for t in aset.tracks:
            ch = (Channel(t.rotations, 4) if t.rotations else None,
                  Channel(t.translations, 3) if t.translations else None,
                  Channel(t.scales, 3) if t.scales else None)
            self.tracks[t.frame] = ch
            if ch[0] is not None and len(ch[0].times) > 1:
                deltas.append(float(np.min(np.diff(ch[0].times))))
        step = min([d for d in deltas if d > 0], default=self.tps / 30.0)
        self.fps = self.tps / step if step else 30.0

    @property
    def duration(self):
        return self.length / self.tps if self.tps else 0.0

    @property
    def frame_count(self):
        return int(round(self.duration * self.fps)) + 1

    def local(self, name, ticks):
        ch = self.tracks.get(name)
        if ch is None:
            return None
        rot, trans, scale = ch
        m = np.eye(4)
        r = quat_to_mat3(rot.sample(ticks, True)) if rot is not None else np.eye(3)
        s = scale.sample(ticks) if scale is not None else np.ones(3)
        m[:3, :3] = r * s[:, None]
        if trans is not None:
            m[3, :3] = trans.sample(ticks)
        return m


@dataclass
class Skeleton:
    names: list
    parents: list
    bind_local: np.ndarray      # (F, 4, 4)
    meshes_of: list             # frame -> mesh index or -1
    index: dict = field(default_factory=dict)

    @classmethod
    def from_model(cls, model):
        names, parents, local, meshes = [], [], [], []

        def walk(f, parent):
            i = len(names)
            names.append(f.name)
            parents.append(parent)
            local.append(mat(f.matrix))
            meshes.append(f.mesh)
            for c in f.children:
                walk(c, i)

        walk(model.root, -1)
        sk = cls(names, parents, np.array(local), meshes)
        for i, n in enumerate(names):
            if n and n not in sk.index:
                sk.index[n] = i
        return sk

    def pose(self, clip=None, ticks=0.0):
        combined = np.empty_like(self.bind_local)
        for i, name in enumerate(self.names):
            loc = clip.local(name, ticks) if (clip is not None and name) else None
            if loc is None:
                loc = self.bind_local[i]
            p = self.parents[i]
            combined[i] = loc if p < 0 else loc @ combined[p]
        return combined


class MeshData:
    """Static arrays and skin weights of one mesh container."""

    def __init__(self, model, mesh_index, frame_index):
        m = model.meshes[mesh_index]
        self.mesh = m
        self.model_path = model.path
        self.frame_index = frame_index
        self.name = m.frame or m.name or 'mesh%d' % mesh_index
        self.positions = np.array(m.positions, dtype=np.float64).reshape(-1, 3)
        self.normals = np.array(m.normals, dtype=np.float64).reshape(-1, 3)
        self.uvs = np.array(m.uvs, dtype=np.float32).reshape(-1, 2)
        self.indices = np.array(m.indices, dtype=np.uint32)
        self.groups = [(g.material, g.face_start * 3, g.face_count * 3) for g in m.groups]
        self.materials = m.materials
        self.visible = True
        n = len(self.positions)
        self.bone_names = [b.name for b in m.bones]
        self.offsets = np.array([mat(b.offset) for b in m.bones]) if m.bones else np.zeros((0, 4, 4))
        # Dense (vertex, bone) weights, then the strongest four per vertex.
        self.dense = np.zeros((n, len(m.bones)), dtype=np.float32)
        for bi, b in enumerate(m.bones):
            if b.vertices:
                idx = np.array(b.vertices, dtype=np.int64)
                ok = idx < n
                self.dense[idx[ok], bi] += np.array(b.weights, dtype=np.float32)[ok]
        if m.bones:
            k = min(4, len(m.bones))
            top = np.argsort(-self.dense, axis=1)[:, :k]
            w = np.take_along_axis(self.dense, top, axis=1)
            s = w.sum(axis=1, keepdims=True)
            self.unweighted = int(np.count_nonzero(s[:, 0] <= 1e-6))
            s[s <= 1e-6] = 1.0
            self.top_idx, self.top_w = top, (w / s).astype(np.float64)
        else:
            self.unweighted = 0
            self.top_idx = self.top_w = None

    @property
    def skinned(self):
        return len(self.bone_names) > 0

    def deform(self, bone_mats, rigid_mat):
        """Return (positions, normals) in D3D model space."""
        p4 = np.c_[self.positions, np.ones(len(self.positions))]
        if self.skinned and bone_mats is not None:
            pos = np.zeros((len(p4), 3))
            nor = np.zeros((len(p4), 3))
            for k in range(self.top_idx.shape[1]):
                mk = bone_mats[self.top_idx[:, k]]                     # (N, 4, 4)
                w = self.top_w[:, k:k + 1]
                pos += w * np.einsum('ni,nij->nj', p4, mk)[:, :3]
                nor += w * np.einsum('ni,nij->nj', self.normals, mk[:, :3, :3])
        else:
            pos = (p4 @ rigid_mat)[:, :3]
            nor = self.normals @ rigid_mat[:3, :3]
        ln = np.linalg.norm(nor, axis=1, keepdims=True)
        ln[ln == 0] = 1
        return pos, nor / ln

    def weights_for(self, bone_name):
        if not self.skinned or bone_name not in self.bone_names:
            return np.zeros(len(self.positions), dtype=np.float32)
        return self.dense[:, self.bone_names.index(bone_name)]


class SceneObject:
    """One loaded file: a base model (owns the skeleton) or a part attached to it."""

    def __init__(self, model, attached_to=None):
        self.model = model
        self.path = Path(model.path)
        self.name = self.path.name
        self.skeleton = Skeleton.from_model(model)
        self.attached_to = attached_to
        self.visible = True
        self.meshes = []
        for fi, mi in enumerate(self.skeleton.meshes_of):
            if mi >= 0:
                self.meshes.append(MeshData(model, mi, fi))

    def bone_matrices(self, md, own_combined, base_combined, base_skeleton):
        mats = np.empty((len(md.bone_names), 4, 4))
        for b, name in enumerate(md.bone_names):
            m = None
            if base_skeleton is not None and name in base_skeleton.index:
                m = base_combined[base_skeleton.index[name]]
            elif name in self.skeleton.index:
                m = own_combined[self.skeleton.index[name]]
            mats[b] = md.offsets[b] @ (m if m is not None else np.eye(4))
        return mats

    @property
    def bone_count(self):
        return len({n for md in self.meshes for n in md.bone_names})


class Scene:
    def __init__(self):
        self.objects = []
        self.clip = None
        self.ticks = 0.0

    @property
    def base(self):
        return self.objects[0] if self.objects else None

    def clear(self):
        self.objects = []
        self.clip = None
        self.ticks = 0.0

    def load(self, path, attach=False):
        model = dbmesh.load(path)
        if attach and self.base is not None:
            obj = SceneObject(model, attached_to=self.base)
            self.objects.append(obj)
        else:
            self.clear()
            obj = SceneObject(model)
            self.objects.append(obj)
            if model.animations:
                self.clip = Clip(model.animations[0], Path(path).name)
        return obj

    def load_animation(self, path, index=0):
        model = dbmesh.load(path)
        if not model.animations:
            raise dbmesh.MeshFormatError('file has no animation sets')
        clip = Clip(model.animations[min(index, len(model.animations) - 1)], Path(path).name)
        if self.base is None:  # an .ani alone: show its skeleton
            self.objects.append(SceneObject(model))
        self.clip = clip
        self.ticks = 0.0
        return clip

    def matched_tracks(self):
        if self.clip is None or self.base is None:
            return 0, 0
        idx = self.base.skeleton.index
        return sum(1 for n in self.clip.tracks if n in idx), len(self.clip.tracks)

    def evaluate(self):
        """Yield (obj, mesh, positions, normals) in world space plus joint segments."""
        base = self.base
        if base is None:
            return [], np.zeros((0, 3)), []
        base_comb = base.skeleton.pose(self.clip, self.ticks)
        out = []
        for obj in self.objects:
            own = base_comb if obj is base else obj.skeleton.pose(None)
            for md in obj.meshes:
                if obj is base:
                    bm = obj.bone_matrices(md, own, None, None) if md.skinned else None
                else:
                    bm = obj.bone_matrices(md, own, base_comb, base.skeleton) if md.skinned else None
                pos, nor = md.deform(bm, own[md.frame_index])
                out.append((obj, md, _to_world(pos), _to_world(nor)))
        joints = _to_world(base_comb[:, 3, :3])
        return out, joints, base.skeleton.parents


def _to_world(v):
    return v[:, [0, 2, 1]]


def weight_colors(w):
    """Blender weight-paint ramp: blue, cyan, green, yellow, red."""
    stops = np.array([[0, 0, 1], [0, 1, 1], [0, 1, 0], [1, 1, 0], [1, 0, 0]], dtype=np.float32)
    x = np.clip(w, 0, 1) * 4
    i = np.minimum(x.astype(int), 3)
    f = (x - i)[:, None]
    return stops[i] * (1 - f) + stops[i + 1] * f


def related_animations(model_path, data_root=None):
    """Guess .ani files that drive a model: same folder first, then class folders for parts."""
    p = Path(model_path)
    stem = p.stem.lower()
    cands = sorted(p.parent.glob('*.ani'))
    # Prefer animations sharing the longest name prefix with the model.
    def score(a):
        n, k = a.stem.lower(), 0
        while k < min(len(n), len(stem)) and n[k] == stem[k]:
            k += 1
        return -k, a.name.lower()
    return sorted(cands, key=score)
