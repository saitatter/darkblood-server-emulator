"""moderngl renderer for the Dark Blood model viewer (works on- and off-screen)."""
import math
from dataclasses import dataclass
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image

import scene as sc
import dbmesh

MESH_VS = """
#version 330
uniform mat4 u_mvp;
in vec3 in_pos; in vec3 in_nor; in vec2 in_uv; in vec3 in_col;
out vec3 v_nor; out vec2 v_uv; out vec3 v_col; out vec3 v_pos;
void main() {
    v_nor = in_nor; v_uv = in_uv; v_col = in_col; v_pos = in_pos;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

MESH_FS = """
#version 330
uniform int u_mode;            // 0 solid, 1 material, 2 weights, 3 flat colour (wire)
uniform bool u_has_tex;
uniform sampler2D u_tex;
uniform vec4 u_tint;
uniform float u_alpha_cut;     // < 0 disables
uniform vec3 u_eye;
uniform vec3 u_key;
in vec3 v_nor; in vec2 v_uv; in vec3 v_col; in vec3 v_pos;
out vec4 f_color;
void main() {
    if (u_mode == 3) { f_color = u_tint; return; }
    vec3 n = normalize(v_nor);
    vec3 view = normalize(u_eye - v_pos);
    if (dot(n, view) < 0.0) n = -n;                       // two-sided lighting
    float key = max(dot(n, normalize(u_key)), 0.0);
    float fill = max(dot(n, normalize(vec3(-0.6, 0.5, 0.3))), 0.0);
    float hemi = 0.5 + 0.5 * n.z;
    float rim = pow(1.0 - max(dot(n, view), 0.0), 3.0);
    vec4 base;
    if (u_mode == 2) base = vec4(v_col, 1.0);
    else if (u_mode == 1) {
        base = u_has_tex ? texture(u_tex, v_uv) : vec4(0.8, 0.8, 0.8, 1.0);
        base.rgb *= u_tint.rgb;
        if (u_alpha_cut >= 0.0 && base.a < u_alpha_cut) discard;
    } else base = vec4(0.80, 0.80, 0.80, 1.0);
    vec3 light;
    if (u_mode == 0) light = vec3(0.30 + 0.25 * hemi) + vec3(0.62) * key + vec3(0.18) * fill + vec3(0.12) * rim;
    else if (u_mode == 2) light = vec3(0.55 + 0.45 * key);
    else light = vec3(0.42 + 0.18 * hemi) + vec3(0.70, 0.68, 0.64) * key + vec3(0.20, 0.22, 0.26) * fill;
    vec3 rgb = base.rgb * light;
    if (u_mode == 0) {
        vec3 h = normalize(normalize(u_key) + view);
        rgb += vec3(0.25) * pow(max(dot(n, h), 0.0), 40.0);
    }
    f_color = vec4(rgb, u_mode == 1 && u_alpha_cut < 0.0 ? base.a : 1.0);
}
"""

LINE_VS = """
#version 330
uniform mat4 u_mvp;
uniform float u_point;
in vec3 in_pos; in vec4 in_col;
out vec4 v_col;
void main() { v_col = in_col; gl_Position = u_mvp * vec4(in_pos, 1.0); gl_PointSize = u_point; }
"""

LINE_FS = """
#version 330
in vec4 v_col; out vec4 f_color;
uniform bool u_round;
void main() {
    if (u_round) { vec2 d = gl_PointCoord - vec2(0.5); if (dot(d, d) > 0.25) discard; }
    f_color = v_col;
}
"""

BG_VS = """
#version 330
in vec2 in_pos; out float v_y;
void main() { v_y = in_pos.y * 0.5 + 0.5; gl_Position = vec4(in_pos, 0.999, 1.0); }
"""

BG_FS = """
#version 330
uniform vec3 u_top; uniform vec3 u_bottom;
in float v_y; out vec4 f_color;
void main() { f_color = vec4(mix(u_bottom, u_top, v_y), 1.0); }
"""


def look_at(eye, target, up):
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    if np.linalg.norm(s) < 1e-6:
        s = np.cross(f, np.array([0.0, 1.0, 0.0]))
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2] = s, u, -f
    m[3, 0], m[3, 1], m[3, 2] = -s @ eye, -u @ eye, f @ eye
    return m  # row-vector view matrix


def perspective(fovy, aspect, near, far):
    t = 1.0 / math.tan(fovy / 2)
    m = np.zeros((4, 4))
    m[0, 0], m[1, 1] = t / aspect, t
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = -1.0
    m[3, 2] = 2 * far * near / (near - far)
    return m


def orthographic(h, aspect, near, far):
    m = np.eye(4)
    m[0, 0], m[1, 1] = 1 / (h * aspect), 1 / h
    m[2, 2] = -2 / (far - near)
    m[3, 2] = -(far + near) / (far - near)
    return m


@dataclass
class Camera:
    target: np.ndarray = None
    yaw: float = math.radians(-60)
    pitch: float = math.radians(15)
    dist: float = 300.0
    fov: float = math.radians(40)
    ortho: bool = False

    def __post_init__(self):
        if self.target is None:
            self.target = np.zeros(3)

    @property
    def eye(self):
        cp = math.cos(self.pitch)
        return self.target + self.dist * np.array([cp * math.cos(self.yaw), cp * math.sin(self.yaw),
                                                   math.sin(self.pitch)])

    def basis(self):
        v = look_at(self.eye, self.target, np.array([0.0, 0.0, 1.0]))
        return v[:3, 0], v[:3, 1], -v[:3, 2]   # right, up, forward

    def view(self):
        return look_at(self.eye, self.target, np.array([0.0, 0.0, 1.0]))

    def proj(self, aspect):
        near, far = max(self.dist * 0.002, 0.01), self.dist * 50 + 1000
        if self.ortho:
            return orthographic(self.dist * math.tan(self.fov / 2), aspect, -far, far)
        return perspective(self.fov, aspect, near, far)

    def orbit(self, dx, dy):
        self.yaw -= dx * 0.008
        self.pitch = max(-math.pi / 2 + 1e-3, min(math.pi / 2 - 1e-3, self.pitch + dy * 0.008))

    def pan(self, dx, dy, height):
        r, u, _ = self.basis()
        k = 2 * self.dist * math.tan(self.fov / 2) / max(height, 1)
        self.target = self.target - r * dx * k + u * dy * k

    def zoom(self, steps):
        self.dist = max(0.05, self.dist * (0.88 ** steps))

    def frame(self, lo, hi):
        self.target = (lo + hi) / 2
        r = max(float(np.linalg.norm(hi - lo)) / 2, 1.0)
        self.dist = r / math.sin(self.fov / 2) * 1.05

    def set_view(self, name):
        views = {'front': (-90, 0), 'back': (90, 0), 'right': (0, 0), 'left': (180, 0),
                 'top': (-90, 89.9), 'bottom': (-90, -89.9)}
        y, p = views[name]
        self.yaw, self.pitch = math.radians(y), math.radians(p)


@dataclass
class ViewSettings:
    shading: str = 'material'        # wire | solid | material | weights
    show_bones: bool = True
    show_grid: bool = True
    wire_overlay: bool = False
    backface_cull: bool = False
    alpha_mode: str = 'clip'         # clip | blend | off
    selected_bone: str = ''
    selected_mesh: object = None


def load_image(path):
    img = Image.open(path)
    img.load()
    return img.convert('RGBA')


class GpuMesh:
    def __init__(self, ctx, prog, wire_prog, md):
        self.md = md
        n = len(md.positions)
        self.n = n
        self.dyn = ctx.buffer(reserve=n * 9 * 4, dynamic=True)
        self.uv = ctx.buffer(md.uvs.astype('f4').tobytes())
        self.ibo = ctx.buffer(md.indices.astype('u4').tobytes())
        fmt = [(self.dyn, '3f 3f 3f', 'in_pos', 'in_nor', 'in_col'), (self.uv, '2f', 'in_uv')]
        self.vao = ctx.vertex_array(prog, fmt, self.ibo, index_element_size=4)
        self.bounds = (np.zeros(3), np.zeros(3))

    def update(self, pos, nor, col):
        data = np.empty((self.n, 9), dtype='f4')
        data[:, 0:3], data[:, 3:6], data[:, 6:9] = pos, nor, col
        self.dyn.write(data.tobytes())
        self.bounds = (pos.min(axis=0), pos.max(axis=0))

    def release(self):
        for r in (self.vao, self.dyn, self.uv, self.ibo):
            r.release()


class Renderer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.mesh_prog = ctx.program(vertex_shader=MESH_VS, fragment_shader=MESH_FS)
        self.line_prog = ctx.program(vertex_shader=LINE_VS, fragment_shader=LINE_FS)
        self.bg_prog = ctx.program(vertex_shader=BG_VS, fragment_shader=BG_FS)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype='f4')
        self.bg_vbo = ctx.buffer(quad.tobytes())
        self.bg_vao = ctx.vertex_array(self.bg_prog, [(self.bg_vbo, '2f', 'in_pos')])
        self.line_vbo = ctx.buffer(reserve=1 << 20, dynamic=True)
        self.line_vao = ctx.vertex_array(self.line_prog, [(self.line_vbo, '3f 4f', 'in_pos', 'in_col')])
        self.meshes = {}
        self.textures = {}
        self.tex_paths = {}
        self.white = ctx.texture((1, 1), 4, b'\xff\xff\xff\xff')
        self.joints = np.zeros((0, 3))
        self.parents = []
        self.scene_bounds = (np.full(3, -50.0), np.full(3, 50.0))

    # ------------------------------------------------------------------ resources
    def texture(self, path):
        key = str(path)
        if key not in self.textures:
            try:
                img = load_image(path)
                tex = self.ctx.texture(img.size, 4, img.tobytes())
                tex.build_mipmaps()
                tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
                tex.anisotropy = 16.0
                tex.repeat_x = tex.repeat_y = True
                has_alpha = img.getextrema()[3][0] < 250
                self.textures[key] = (tex, has_alpha)
            except Exception:
                self.textures[key] = (None, False)
        return self.textures[key]

    def sync(self, scene):
        """Create GPU meshes for new scene meshes and drop removed ones."""
        live = {id(md): md for obj in scene.objects for md in obj.meshes}
        for k in list(self.meshes):
            if k not in live:
                self.meshes.pop(k).release()
        for k, md in live.items():
            if k not in self.meshes:
                self.meshes[k] = GpuMesh(self.ctx, self.mesh_prog, None, md)

    def update(self, scene, settings):
        self.sync(scene)
        results, joints, parents = scene.evaluate()
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for obj, md, pos, nor in results:
            if settings.shading == 'weights':
                col = sc.weight_colors(md.weights_for(settings.selected_bone))
            else:
                col = np.zeros((len(pos), 3), dtype=np.float32)
            g = self.meshes[id(md)]
            g.update(pos, nor, col)
            if md.visible and obj.visible:
                lo, hi = np.minimum(lo, g.bounds[0]), np.maximum(hi, g.bounds[1])
        if not np.isfinite(lo).all():
            if len(joints):
                lo, hi = joints.min(axis=0), joints.max(axis=0)
            else:
                lo, hi = np.full(3, -50.0), np.full(3, 50.0)
        self.scene_bounds = (lo, hi)
        self.joints, self.parents = joints, parents
        self.joint_names = scene.base.skeleton.names if scene.base else []
        # Armature display: frames that deform something (or are animated), each
        # linked to its nearest displayed ancestor, like Blender bones.
        used = {n for obj in scene.objects for md in obj.meshes for n in md.bone_names}
        if not used and scene.clip is not None:
            used = set(scene.clip.tracks)
        self.bone_mask = [bool(n) and n in used for n in self.joint_names]
        self.bone_parent = []
        for i, p in enumerate(parents):
            while p >= 0 and not self.bone_mask[p]:
                p = parents[p]
            self.bone_parent.append(p)

    # ------------------------------------------------------------------ drawing
    def _lines(self, mvp, verts, mode, point=1.0, depth=True):
        if not len(verts):
            return
        data = np.asarray(verts, dtype='f4')
        self.line_vbo.orphan(max(data.nbytes, 1 << 20))
        self.line_vbo.write(data.tobytes())
        self.line_prog['u_mvp'].write(mvp.astype('f4').tobytes())
        self.line_prog['u_point'].value = point
        self.line_prog['u_round'].value = mode == moderngl.POINTS
        if depth:
            self.ctx.enable(moderngl.DEPTH_TEST)
        else:
            self.ctx.disable(moderngl.DEPTH_TEST)
        self.line_vao.render(mode, vertices=len(data))

    def grid_lines(self):
        lo, hi = self.scene_bounds
        size = max(float(np.max(hi - lo)), 1.0)
        step = 10 ** math.floor(math.log10(size / 2))
        half = step * 10
        out = []
        for i in range(-10, 11):
            x = i * step
            c = (0.33, 0.33, 0.33, 1.0) if i % 5 else (0.40, 0.40, 0.40, 1.0)
            cx = (0.90, 0.24, 0.30, 1.0) if i == 0 else c   # X axis (red) along y = 0
            cy = (0.47, 0.75, 0.15, 1.0) if i == 0 else c   # Y axis (green) along x = 0
            out += [(-half, x, 0, *cx), (half, x, 0, *cx), (x, -half, 0, *cy), (x, half, 0, *cy)]
        return out

    def bone_lines(self, selected):
        segs, pts = [], []
        names = self.joint_names
        for i, p in enumerate(self.bone_parent):
            if not self.bone_mask[i]:
                continue
            sel = names[i] == selected and selected
            c = (1.0, 0.62, 0.15, 1.0) if sel else (0.35, 0.75, 1.0, 0.9)
            pts.append((*self.joints[i], *c))
            if p >= 0 and np.linalg.norm(self.joints[i] - self.joints[p]) > 1e-4:
                segs += [(*self.joints[p], *c), (*self.joints[i], *c)]
        return segs, pts

    def render(self, fbo, width, height, cam, settings):
        ctx = self.ctx
        fbo.use()
        ctx.viewport = (0, 0, width, height)
        ctx.clear(0.18, 0.18, 0.18, 1.0, depth=1.0)
        ctx.disable(moderngl.DEPTH_TEST | moderngl.CULL_FACE | moderngl.BLEND)
        self.bg_prog['u_top'].value = (0.26, 0.27, 0.29)
        self.bg_prog['u_bottom'].value = (0.15, 0.15, 0.16)
        self.bg_vao.render(moderngl.TRIANGLE_STRIP)

        aspect = width / max(height, 1)
        vp = cam.view() @ cam.proj(aspect)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        if settings.show_grid:
            self._lines(vp, self.grid_lines(), moderngl.LINES)

        ctx.enable(moderngl.DEPTH_TEST)
        if settings.backface_cull:
            ctx.enable(moderngl.CULL_FACE)
            ctx.front_face = 'ccw'
        p = self.mesh_prog
        p['u_mvp'].write(vp.astype('f4').tobytes())
        p['u_eye'].value = tuple(cam.eye)
        r, u, f = cam.basis()
        p['u_key'].value = tuple(-f + u * 0.8 + r * 0.6)
        mode = {'solid': 0, 'material': 1, 'weights': 2, 'wire': 3}[settings.shading]
        if mode != 3:
            for blend_pass in ((False, True) if settings.alpha_mode == 'blend' else (False,)):
                self._draw_meshes(settings, mode, blend_pass)
        if mode == 3 or settings.wire_overlay:
            ctx.depth_func = '<='
            ctx.wireframe = True
            ctx.enable(moderngl.BLEND)
            p['u_mode'].value = 3
            col = (0.0, 0.0, 0.0, 0.55) if mode != 3 else (0.85, 0.85, 0.85, 1.0)
            p['u_tint'].value = col
            if mode == 3:
                ctx.disable(moderngl.DEPTH_TEST)
            for g in self.meshes.values():
                if self._visible(g):
                    g.vao.render(moderngl.TRIANGLES)
            ctx.wireframe = False
        ctx.disable(moderngl.CULL_FACE)
        if settings.selected_mesh is not None and id(settings.selected_mesh) in self.meshes:
            g = self.meshes[id(settings.selected_mesh)]
            ctx.wireframe = True
            p['u_mode'].value = 3
            p['u_tint'].value = (1.0, 0.55, 0.1, 0.9)
            ctx.enable(moderngl.BLEND)
            g.vao.render(moderngl.TRIANGLES)
            ctx.wireframe = False
        if settings.show_bones and len(self.joints):
            ctx.enable(moderngl.PROGRAM_POINT_SIZE)
            segs, pts = self.bone_lines(settings.selected_bone)
            self._lines(vp, segs, moderngl.LINES, depth=False)
            self._lines(vp, pts, moderngl.POINTS, point=5.0, depth=False)
        self._gizmo(cam, width, height)

    def _visible(self, g):
        return g.md.visible

    def _draw_meshes(self, settings, mode, blend_pass):
        ctx, p = self.ctx, self.mesh_prog
        p['u_mode'].value = mode
        for g in self.meshes.values():
            if not self._visible(g):
                continue
            md = g.md
            for mat_i, start, count in md.groups:
                mat = md.materials[mat_i] if mat_i < len(md.materials) else None
                tex, alpha = (None, False)
                if mat is not None and mat.texture:
                    key = (md.model_path, mat.texture)
                    if key not in self.tex_paths:
                        self.tex_paths[key] = dbmesh.find_texture(md.model_path, mat.texture)
                    tp = self.tex_paths[key]
                    if tp is not None:
                        tex, alpha = self.texture(tp)
                is_blend = settings.alpha_mode == 'blend' and alpha
                if blend_pass != is_blend and settings.alpha_mode == 'blend':
                    continue
                (tex or self.white).use(0)
                p['u_tex'].value = 0
                p['u_has_tex'].value = tex is not None
                tint = mat.diffuse if mat is not None else (1, 1, 1, 1)
                p['u_tint'].value = tuple(min(1.0, max(0.0, c)) for c in tint[:3]) + (1.0,)
                if mode == 1 and alpha and settings.alpha_mode == 'clip':
                    p['u_alpha_cut'].value = 0.5
                elif mode == 1 and is_blend:
                    p['u_alpha_cut'].value = -1.0
                else:
                    p['u_alpha_cut'].value = -2.0 if mode != 1 else 0.0
                if is_blend:
                    ctx.enable(moderngl.BLEND)
                    ctx.depth_mask = False
                else:
                    ctx.disable(moderngl.BLEND)
                    ctx.depth_mask = True
                g.vao.render(moderngl.TRIANGLES, vertices=count, first=start)
        ctx.depth_mask = True

    def _gizmo(self, cam, width, height):
        """Blender-style axis gizmo in the top-right corner."""
        size = int(min(110, width / 5, height / 4))
        if size < 40:
            return
        ctx = self.ctx
        ctx.viewport = (width - size - 8, height - size - 8, size, size)
        rot = cam.view().copy()
        rot[3, :3] = 0
        m = rot @ orthographic(1.3, 1.0, -2, 2)
        axes = [((1, 0, 0), (0.90, 0.24, 0.30)), ((0, 1, 0), (0.47, 0.75, 0.15)),
                ((0, 0, 1), (0.25, 0.52, 0.95))]
        segs, pts = [], []
        for v, c in axes:
            segs += [(0, 0, 0, *c, 1.0), (*v, *c, 1.0)]
            pts.append((*v, *c, 1.0))
            pts.append((-v[0], -v[1], -v[2], *[x * 0.55 for x in c], 0.8))
        ctx.enable(moderngl.PROGRAM_POINT_SIZE | moderngl.BLEND)
        self._lines(m, segs, moderngl.LINES, depth=False)
        self._lines(m, pts, moderngl.POINTS, point=max(9.0, size / 8), depth=False)
        ctx.viewport = (0, 0, width, height)
        self.gizmo_rect = (width - size - 8, 8, size, size)
        self.gizmo_matrix = m

    def gizmo_labels(self):
        """Screen positions (in gizmo-local pixels) of the X/Y/Z labels."""
        if not hasattr(self, 'gizmo_matrix'):
            return []
        x0, y0, s, _ = self.gizmo_rect
        out = []
        for name, v in (('X', (1, 0, 0)), ('Y', (0, 1, 0)), ('Z', (0, 0, 1))):
            c = np.array([*v, 1.0]) @ self.gizmo_matrix
            out.append((name, x0 + (c[0] * 0.5 + 0.5) * s, y0 + (0.5 - c[1] * 0.5) * s))
        return out
