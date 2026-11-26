"""Blender-style orbit camera (row-vector matrices, Z-up world)."""
import math
from dataclasses import dataclass

import numpy as np


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
