"""OpenGL viewport widget: Blender-style navigation over the moderngl renderer."""
import math

import moderngl
from PySide6.QtCore import Qt, Signal
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel

import camera
import renderer as rd


class Viewport(QOpenGLWidget):
    changed = Signal()

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.cam = camera.Camera()
        self.settings = rd.ViewSettings()
        self.renderer = None
        self.ctx = None
        self.dirty = True
        self.pending_frame = False
        self.last = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(False)
        self.hud = QLabel(self)
        self.hud.setObjectName('hud')
        self.hud.move(12, 8)
        self.hud.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.axis_labels = {}
        for n, c in (('X', '#ff5b6b'), ('Y', '#9be03a'), ('Z', '#5b9bff')):
            lab = QLabel(n, self)
            lab.setObjectName('gizmo')
            lab.setStyleSheet('color: %s' % c)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.axis_labels[n] = lab
        self.empty = QLabel('Drop a .x / .prt / .ani file here\nor pick one in the Asset Browser', self)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet('background: transparent; color: #8a8a8a; font-size: 12pt;')
        self.empty.setAttribute(Qt.WA_TransparentForMouseEvents)

    # ---------------------------------------------------------------- GL
    def initializeGL(self):
        self.ctx = moderngl.create_context()
        self.renderer = rd.Renderer(self.ctx)

    def resizeGL(self, w, h):
        self.empty.setGeometry(0, 0, self.width(), self.height())

    def paintGL(self):
        if self.renderer is None:
            return
        if self.dirty:
            self.renderer.update(self.scene, self.settings)
            self.dirty = False
            if self.pending_frame:
                self.cam.frame(*self.renderer.scene_bounds)
                self.pending_frame = False
        dpr = self.devicePixelRatioF()
        w, h = int(self.width() * dpr), int(self.height() * dpr)
        fbo = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        self.renderer.render(fbo, w, h, self.cam, self.settings)
        for name, x, y in self.renderer.gizmo_labels():
            lab = self.axis_labels[name]
            lab.adjustSize()
            lab.move(int(x / dpr - lab.width() / 2), int(y / dpr - lab.height() / 2))
        self.empty.setVisible(not self.scene.objects)
        self._update_hud()

    def _update_hud(self):
        view = 'Orthographic' if self.cam.ortho else 'Perspective'
        names = {(-90, 0): 'Front', (90, 0): 'Back', (0, 0): 'Right', (180, 0): 'Left',
                 (-90, 90): 'Top', (-90, -90): 'Bottom'}
        key = (round(math.degrees(self.cam.yaw)) % 360, round(math.degrees(self.cam.pitch)))
        label = 'User'
        for (y, p), n in names.items():
            if key == (y % 360, p):
                label = n
        lines = ['%s %s' % (label, view)]
        if self.scene.base is not None:
            s = self.scene
            obj = s.base
            frame = ''
            if s.clip is not None:
                frame = '(%d) ' % int(round(s.ticks / s.clip.tps * s.clip.fps))
            lines.append('%s%s' % (frame, obj.name))
            if self.settings.shading == 'weights':
                lines.append('Weights: %s' % (self.settings.selected_bone or '(select a bone)'))
        self.hud.setText('\n'.join(lines))
        self.hud.adjustSize()

    def refresh(self, frame=False):
        self.dirty = True
        self.pending_frame = self.pending_frame or frame
        self.update()

    # ---------------------------------------------------------------- input
    def mousePressEvent(self, e):
        self.last = e.position()
        self.setFocus()

    def mouseReleaseEvent(self, e):
        self.last = None

    def mouseMoveEvent(self, e):
        if self.last is None:
            return
        d = e.position() - self.last
        self.last = e.position()
        b, mods = e.buttons(), e.modifiers()
        pan = (b & Qt.RightButton) or ((b & (Qt.MiddleButton | Qt.LeftButton)) and mods & Qt.ShiftModifier)
        if pan:
            self.cam.pan(d.x(), d.y(), self.height())
        elif (b & Qt.MiddleButton) and mods & Qt.ControlModifier:
            self.cam.zoom(-d.y() / 40)
        elif b & (Qt.MiddleButton | Qt.LeftButton):
            self.cam.orbit(d.x(), d.y())
        self.update()

    def wheelEvent(self, e):
        self.cam.zoom(e.angleDelta().y() / 120)
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.frame_all()

    def frame_all(self):
        if self.renderer is not None:
            self.cam.frame(*self.renderer.scene_bounds)
        self.update()

    def keyPressEvent(self, e):
        k, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        views = {Qt.Key_1: ('back' if ctrl else 'front'), Qt.Key_3: ('left' if ctrl else 'right'),
                 Qt.Key_7: ('bottom' if ctrl else 'top')}
        if k in views:
            self.cam.set_view(views[k])
        elif k == Qt.Key_5:
            self.cam.ortho = not self.cam.ortho
        elif k in (Qt.Key_Home, Qt.Key_F, Qt.Key_Period):
            self.frame_all()
        elif k in (Qt.Key_4, Qt.Key_6):
            self.cam.orbit(-20 if k == Qt.Key_4 else 20, 0)
        elif k in (Qt.Key_8, Qt.Key_2):
            self.cam.orbit(0, 20 if k == Qt.Key_8 else -20)
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            self.cam.zoom(1)
        elif k == Qt.Key_Minus:
            self.cam.zoom(-1)
        else:
            super().keyPressEvent(e)
            return
        self.update()
