"""Qt user interface of the Dark Blood model viewer (Blender-like layout)."""
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image
from PySide6.QtCore import QSettings, QSize, QSortFilterProxyModel, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QIcon, QImage, QKeySequence, QPainter,
                           QPixmap, QStandardItem, QStandardItemModel, QSurfaceFormat)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
                               QDialog, QDockWidget, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QScrollArea, QSlider, QTabWidget,
                               QToolButton, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import dbmesh
import renderer as rd
import scene as sc

MODEL_EXT = ('.x', '.prt')
ANIM_EXT = ('.ani',)

STYLE = """
* { font-family: 'Segoe UI', sans-serif; font-size: 9pt; color: #d6d6d6; }
QMainWindow, QWidget { background: #303030; }
QMainWindow::separator { background: #1d1d1d; width: 2px; height: 2px; }
QDockWidget { titlebar-close-icon: none; }
QDockWidget::title { background: #282828; padding: 5px 8px; border-bottom: 1px solid #1d1d1d; }
QMenuBar { background: #232323; border-bottom: 1px solid #1a1a1a; }
QMenuBar::item { padding: 4px 10px; background: transparent; }
QMenuBar::item:selected, QMenu::item:selected { background: #4772b3; color: white; }
QMenu { background: #181818; border: 1px solid #3a3a3a; padding: 4px; }
QMenu::item { padding: 5px 24px 5px 18px; border-radius: 3px; }
QMenu::separator { height: 1px; background: #333; margin: 4px 6px; }
QTreeView, QTreeWidget, QListWidget { background: #282828; alternate-background-color: #2b2b2b;
    border: none; outline: 0; }
QTreeView::item, QTreeWidget::item, QListWidget::item { padding: 2px 0; }
QTreeView::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {
    background: #4772b3; color: white; }
QTreeView::item:hover, QTreeWidget::item:hover, QListWidget::item:hover { background: #3a3a3a; }
QHeaderView::section { background: #282828; border: none; padding: 4px; }
QLineEdit, QComboBox { background: #1d1d1d; border: 1px solid #3d3d3d; border-radius: 4px;
    padding: 4px 6px; selection-background-color: #4772b3; }
QLineEdit:focus, QComboBox:focus { border-color: #4772b3; }
QComboBox QAbstractItemView { background: #1d1d1d; selection-background-color: #4772b3; }
QPushButton, QToolButton { background: #545454; border: 1px solid #3d3d3d; border-radius: 4px;
    padding: 4px 9px; }
QPushButton:hover, QToolButton:hover { background: #656565; }
QToolButton:checked, QPushButton:checked { background: #4772b3; border-color: #4772b3; color: white; }
QTabWidget::pane { border: none; background: #303030; }
QTabBar::tab { background: #282828; padding: 6px 10px; border: none; margin-right: 1px; }
QTabBar::tab:selected { background: #3d3d3d; color: white; }
QSlider::groove:horizontal { height: 4px; background: #1d1d1d; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4772b3; border-radius: 2px; }
QSlider::handle:horizontal { background: #e0e0e0; width: 10px; margin: -5px 0; border-radius: 5px; }
QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; background: #545454;
    border: 1px solid #3d3d3d; }
QCheckBox::indicator:checked { background: #4772b3; border-color: #4772b3; }
QScrollBar:vertical { background: #282828; width: 10px; }
QScrollBar::handle:vertical { background: #4a4a4a; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QStatusBar { background: #232323; color: #9a9a9a; }
#header { background: #2b2b2b; border-bottom: 1px solid #1d1d1d; }
#hud { background: transparent; color: #e8e8e8; font-size: 9pt; }
#gizmo { background: transparent; font-weight: bold; font-size: 8pt; }
#timeline { background: #2b2b2b; border-top: 1px solid #1d1d1d; }
"""


def default_data_root():
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    repo = Path(__file__).resolve().parents[2]
    base = Path(env) if env else repo.parent / 'darkblood-client-data'
    return base / 'files'


def pil_to_pixmap(img, size=None):
    img = img.convert('RGBA')
    if size:
        img = img.copy()
        img.thumbnail((size, size))
    qimg = QImage(img.tobytes('raw', 'RGBA'), img.width, img.height, 4 * img.width,
                  QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def checker_pixmap(pix):
    out = QPixmap(pix.size())
    p = QPainter(out)
    s = 8
    for y in range(0, pix.height(), s):
        for x in range(0, pix.width(), s):
            p.fillRect(x, y, s, s, QColor('#555' if (x // s + y // s) % 2 else '#777'))
    p.drawPixmap(0, 0, pix)
    p.end()
    return out


def _is_xof(path):
    """DirectX compressed X effects (14 files) use another format; hide them."""
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'xof '
    except OSError:
        return True


# ============================================================================ viewport

class Viewport(QOpenGLWidget):
    changed = Signal()

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.cam = rd.Camera()
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


# ============================================================================ panels

class AssetBrowser(QWidget):
    open_requested = Signal(str, str)   # path, action: open | attach | anim

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search…  (e.g. goblin, mf_body, run)')
        self.search.setClearButtonEnabled(True)
        self.kind = QComboBox()
        self.kind.addItems(['Models', 'Animations', 'All'])
        row.addWidget(self.search, 1)
        row.addWidget(self.kind)
        lay.addLayout(row)
        self.model = QStandardItemModel()
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterRole(Qt.UserRole + 2)
        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        lay.addWidget(self.tree, 1)
        self.count = QLabel()
        self.count.setStyleSheet('color: #8a8a8a;')
        lay.addWidget(self.count)
        self.root = None
        self.search.textChanged.connect(self._filter)
        self.kind.currentIndexChanged.connect(lambda _: self.populate(self.root))
        self.tree.activated.connect(lambda ix: self._activate(ix, 'auto'))
        self.tree.clicked.connect(lambda ix: self._activate(ix, 'auto'))
        self.tree.customContextMenuRequested.connect(self._menu)
        st = self.style()
        self.icons = {'dir': st.standardIcon(st.StandardPixmap.SP_DirIcon),
                      'file': st.standardIcon(st.StandardPixmap.SP_FileIcon),
                      'anim': st.standardIcon(st.StandardPixmap.SP_MediaPlay)}

    def populate(self, root):
        self.root = Path(root) if root else None
        self.model.clear()
        if self.root is None or not self.root.is_dir():
            self.count.setText('Data folder not found — File ▸ Set Data Folder…')
            return
        kind = self.kind.currentText()
        exts = MODEL_EXT if kind == 'Models' else ANIM_EXT if kind == 'Animations' else MODEL_EXT + ANIM_EXT
        dirs = {self.root: self.model.invisibleRootItem()}
        n = 0
        for dp, dn, fn in os.walk(self.root):
            dn.sort()
            files = sorted(f for f in fn if f.lower().endswith(exts) and not _is_xof(Path(dp) / f))
            if not files:
                continue
            d = Path(dp)
            chain = []
            while d not in dirs:
                chain.append(d)
                d = d.parent
            for c in reversed(chain):
                it = QStandardItem(self.icons['dir'], c.name)
                it.setData(str(c), Qt.UserRole + 1)
                it.setData(c.name, Qt.UserRole + 2)
                dirs[c.parent].appendRow(it)
                dirs[c] = it
            for f in files:
                p = Path(dp) / f
                it = QStandardItem(self.icons['anim' if f.lower().endswith(ANIM_EXT) else 'file'], f)
                it.setData(str(p), Qt.UserRole)
                it.setData(str(p.relative_to(self.root)).replace('\\', '/'), Qt.UserRole + 2)
                it.setToolTip(str(p))
                dirs[Path(dp)].appendRow(it)
                n += 1
        self.total = n
        self._filter(self.search.text())
        self.tree.expandToDepth(1)

    def _filter(self, text):
        self.proxy.setFilterFixedString(text.strip())
        if text.strip():
            self.tree.expandAll()
        self.count.setText('%d files in %s' % (getattr(self, 'total', 0), self.root))

    def _path(self, ix):
        return self.proxy.mapToSource(ix).data(Qt.UserRole)

    def _activate(self, ix, action):
        p = self._path(ix)
        if p:
            self.open_requested.emit(p, action)

    def _menu(self, pos):
        ix = self.tree.indexAt(pos)
        p = self._path(ix) if ix.isValid() else None
        if not p:
            return
        m = QMenu(self)
        if p.lower().endswith(ANIM_EXT):
            m.addAction('Play on current model', lambda: self.open_requested.emit(p, 'anim'))
            m.addAction('Open as skeleton', lambda: self.open_requested.emit(p, 'open'))
        else:
            m.addAction('Open', lambda: self.open_requested.emit(p, 'open'))
            m.addAction('Attach to current skeleton', lambda: self.open_requested.emit(p, 'attach'))
        m.addSeparator()
        m.addAction('Show in Explorer', lambda: subprocess.Popen(['explorer', '/select,', p]))
        m.addAction('Copy path', lambda: QApplication.clipboard().setText(p))
        m.exec(self.tree.viewport().mapToGlobal(pos))


class Outliner(QTreeWidget):
    selection = Signal(object, str)   # mesh data or None, bone name
    visibility = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.itemChanged.connect(self._changed)
        self.currentItemChanged.connect(self._current)
        self._building = False

    def rebuild(self, scene):
        self._building = True
        self.clear()
        st = self.style()
        for obj in scene.objects:
            top = QTreeWidgetItem([obj.name + ('  (part)' if obj.attached_to else '')])
            top.setIcon(0, st.standardIcon(st.StandardPixmap.SP_DriveHDIcon))
            top.setFlags(top.flags() | Qt.ItemIsUserCheckable)
            top.setCheckState(0, Qt.Checked if obj.visible else Qt.Unchecked)
            top.setData(0, Qt.UserRole, ('object', obj))
            self.addTopLevelItem(top)
            if obj.meshes:
                grp = QTreeWidgetItem(['Meshes (%d)' % len(obj.meshes)])
                top.addChild(grp)
                for md in obj.meshes:
                    it = QTreeWidgetItem(['%s   %d v / %d f%s' % (md.name, len(md.positions),
                                                                  len(md.indices) // 3,
                                                                  '   skinned' if md.skinned else '')])
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.Checked if md.visible else Qt.Unchecked)
                    it.setData(0, Qt.UserRole, ('mesh', md))
                    grp.addChild(it)
                grp.setExpanded(True)
            if obj is scene.base:
                sk = obj.skeleton
                used = {n for o in scene.objects for md in o.meshes for n in md.bone_names}
                arm = QTreeWidgetItem(['Armature (%d frames)' % len(sk.names)])
                top.addChild(arm)
                items = {}
                for i, (name, p) in enumerate(zip(sk.names, sk.parents)):
                    parent_item = arm
                    q = p
                    while q >= 0 and q not in items:
                        q = sk.parents[q]
                    if q >= 0:
                        parent_item = items[q]
                    if not name:
                        continue
                    it = QTreeWidgetItem([name + ('' if name in used else '  ·')])
                    it.setToolTip(0, 'deforming bone' if name in used else 'frame (no skin weights)')
                    it.setData(0, Qt.UserRole, ('bone', name))
                    if name not in used:
                        it.setForeground(0, QColor('#8a8a8a'))
                    parent_item.addChild(it)
                    items[i] = it
            top.setExpanded(True)
        self._building = False

    def _changed(self, item, col):
        if self._building:
            return
        kind, obj = item.data(0, Qt.UserRole) or (None, None)
        if kind in ('mesh', 'object'):
            obj.visible = item.checkState(0) == Qt.Checked
            if kind == 'object':
                for md in obj.meshes:
                    md.visible = obj.visible
            self.visibility.emit()

    def _current(self, cur, prev):
        if cur is None:
            return
        kind, obj = cur.data(0, Qt.UserRole) or (None, None)
        if kind == 'mesh':
            self.selection.emit(obj, '')
        elif kind == 'bone':
            self.selection.emit(None, obj)
        else:
            self.selection.emit(None, '')


class Properties(QTabWidget):
    play_animation = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbs = {}
        # Object tab
        w = QWidget()
        self.form = QFormLayout(w)
        self.form.setLabelAlignment(Qt.AlignRight)
        self.addTab(w, 'Object')
        # Materials tab
        self.mats = QListWidget()
        self.mats.setIconSize(QSize(64, 64))
        self.mats.itemDoubleClicked.connect(self._preview)
        self.addTab(self.mats, 'Materials')
        # Animation tab
        aw = QWidget()
        al = QVBoxLayout(aw)
        al.setContentsMargins(6, 6, 6, 6)
        self.anim_filter = QLineEdit()
        self.anim_filter.setPlaceholderText('Filter animations…')
        self.anim_filter.setClearButtonEnabled(True)
        self.anims = QListWidget()
        self.anim_info = QLabel()
        self.anim_info.setWordWrap(True)
        self.anim_info.setStyleSheet('color: #9a9a9a;')
        al.addWidget(self.anim_filter)
        al.addWidget(self.anims, 1)
        al.addWidget(self.anim_info)
        self.addTab(aw, 'Animation')
        self.anim_filter.textChanged.connect(self._filter_anims)
        self.anims.itemActivated.connect(self._anim_clicked)
        self.anims.itemClicked.connect(self._anim_clicked)

    def show_scene(self, scene):
        while self.form.rowCount():
            self.form.removeRow(0)
        base = scene.base
        if base is None:
            self.form.addRow(QLabel('No model loaded'))
            self.mats.clear()
            self.anims.clear()
            return
        m = base.model

        def row(k, v):
            lab = QLabel(str(v))
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            self.form.addRow(k, lab)

        row('File', base.name)
        row('Folder', str(base.path.parent))
        row('Objects', len(scene.objects))
        row('Meshes', sum(len(o.meshes) for o in scene.objects))
        row('Vertices', sum(len(md.positions) for o in scene.objects for md in o.meshes))
        row('Triangles', sum(len(md.indices) // 3 for o in scene.objects for md in o.meshes))
        row('Frames', len(base.skeleton.names))
        row('Skin bones', base.bone_count)
        unw = sum(md.unweighted for o in scene.objects for md in o.meshes)
        if unw:
            row('Unweighted verts', unw)
        row('Embedded anim sets', len(m.animations))
        row('Anim controller', ', '.join(str(x) for x in m.anim_params))
        if scene.clip is not None:
            mt, tot = scene.matched_tracks()
            row('Clip', '%s / %s' % (scene.clip.source, scene.clip.name))
            row('Clip tracks', '%d of %d match frames' % (mt, tot))
            row('Clip length', '%.2f s, %d frames @ %.0f fps' % (scene.clip.duration,
                                                                scene.clip.frame_count, scene.clip.fps))
        self._materials(scene)
        self._animations(scene)

    def _materials(self, scene):
        self.mats.clear()
        for obj in scene.objects:
            for md in obj.meshes:
                for k, mat in enumerate(md.materials):
                    tp = dbmesh.find_texture(md.model_path, mat.texture)
                    text = '%s  ·  mat %d\n%s' % (md.name, k, mat.texture or '(no texture)')
                    it = QListWidgetItem(text)
                    if tp is not None:
                        key = str(tp)
                        if key not in self.thumbs:
                            try:
                                img = rd.load_image(tp)
                                alpha = img.getextrema()[3][0] < 250
                                self.thumbs[key] = (checker_pixmap(pil_to_pixmap(img, 64)), img.size, alpha)
                            except Exception:
                                self.thumbs[key] = (None, (0, 0), False)
                        pix, size, alpha = self.thumbs[key]
                        if pix is not None:
                            it.setIcon(QIcon(pix))
                            it.setText(text + '\n%d×%d%s' % (size[0], size[1], ', alpha' if alpha else ''))
                        it.setData(Qt.UserRole, key)
                    else:
                        c = QPixmap(64, 64)
                        c.fill(QColor.fromRgbF(*[min(1, max(0, x)) for x in mat.diffuse[:3]]))
                        it.setIcon(QIcon(c))
                        if mat.texture:
                            it.setText(text + '\n(missing)')
                    self.mats.addItem(it)

    def _preview(self, item):
        key = item.data(Qt.UserRole)
        if not key:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(Path(key).name)
        lay = QVBoxLayout(dlg)
        img = rd.load_image(key)
        pix = checker_pixmap(pil_to_pixmap(img))
        lab = QLabel()
        lab.setPixmap(pix)
        sa = QScrollArea()
        sa.setWidget(lab)
        lay.addWidget(sa)
        lay.addWidget(QLabel('%s — %d×%d' % (key, img.width, img.height)))
        dlg.resize(min(pix.width() + 40, 1100), min(pix.height() + 70, 900))
        dlg.exec()

    def _animations(self, scene):
        self.anims.clear()
        base = scene.base
        for i, a in enumerate(base.model.animations):
            it = QListWidgetItem('★ %s  (embedded)' % (a.name or 'set %d' % i))
            it.setData(Qt.UserRole, (str(base.path), i))
            self.anims.addItem(it)
        for p in sc.related_animations(base.path):
            it = QListWidgetItem(p.name)
            it.setData(Qt.UserRole, (str(p), 0))
            self.anims.addItem(it)
        self.anim_info.setText('%d animations next to %s. Others: Asset Browser ▸ Animations, '
                               'or drop an .ani file.' % (self.anims.count(), base.name))
        self._filter_anims(self.anim_filter.text())

    def _filter_anims(self, text):
        t = text.lower().strip()
        for i in range(self.anims.count()):
            it = self.anims.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _anim_clicked(self, item):
        p, i = item.data(Qt.UserRole)
        self.play_animation.emit(p, i)


class Timeline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('timeline')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        st = self.style()
        self.first = QToolButton()
        self.first.setIcon(st.standardIcon(st.StandardPixmap.SP_MediaSkipBackward))
        self.play = QToolButton()
        self.play.setCheckable(True)
        self.play.setIcon(st.standardIcon(st.StandardPixmap.SP_MediaPlay))
        self.last = QToolButton()
        self.last.setIcon(st.standardIcon(st.StandardPixmap.SP_MediaSkipForward))
        self.slider = QSlider(Qt.Horizontal)
        self.label = QLabel('—')
        self.label.setMinimumWidth(150)
        self.speed = QComboBox()
        self.speed.addItems(['0.1×', '0.25×', '0.5×', '1×', '1.5×', '2×'])
        self.speed.setCurrentText('1×')
        self.loop = QCheckBox('Loop')
        self.loop.setChecked(True)
        self.clip = QLabel('No animation')
        self.clip.setStyleSheet('color: #9a9a9a;')
        for wdg in (self.first, self.play, self.last):
            lay.addWidget(wdg)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        lay.addWidget(self.speed)
        lay.addWidget(self.loop)
        lay.addWidget(self.clip)


# ============================================================================ window

class MainWindow(QMainWindow):
    def __init__(self, files=(), data_root=None):
        super().__init__()
        self.setWindowTitle('Dark Blood Model Viewer')
        self.settings_store = QSettings('darkblood', 'model_viewer')
        self.scene = sc.Scene()
        self.viewport = Viewport(self.scene)
        self.data_root = Path(data_root or self.settings_store.value('data_root', '') or default_data_root())

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self._header())
        cl.addWidget(self.viewport, 1)
        self.timeline = Timeline()
        cl.addWidget(self.timeline)
        self.setCentralWidget(central)

        self.browser = AssetBrowser()
        self.outliner = Outliner()
        self.props = Properties()
        self._dock('Asset Browser', self.browser, Qt.LeftDockWidgetArea)
        self._dock('Outliner', self.outliner, Qt.RightDockWidgetArea)
        self._dock('Properties', self.props, Qt.RightDockWidgetArea)
        self._menus()
        self.setAcceptDrops(True)

        self.browser.open_requested.connect(self.open_path)
        self.outliner.selection.connect(self._select)
        self.outliner.visibility.connect(lambda: self.viewport.refresh())
        self.props.play_animation.connect(self._play_from_list)
        t = self.timeline
        t.play.toggled.connect(self._toggle_play)
        t.first.clicked.connect(lambda: self._seek(0))
        t.last.clicked.connect(lambda: self._seek(1 << 30))
        t.slider.valueChanged.connect(self._slider)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self.last_tick = None

        self.statusBar().showMessage('LMB/MMB orbit · Shift or RMB pan · wheel zoom · 1/3/7 views '
                                     '(Ctrl = opposite) · 5 ortho · F frame · Z shading · Space play')
        self.resize(1500, 900)
        geo = self.settings_store.value('geometry')
        if geo:
            self.restoreGeometry(geo)
        state = self.settings_store.value('state')
        if state:
            self.restoreState(state)
        self.browser.populate(self.data_root)
        for i, f in enumerate(files):
            self.open_path(str(f), 'auto' if i == 0 else 'attach' if f.lower().endswith(MODEL_EXT) else 'anim')
        self._sync_ui()

    # ---------------------------------------------------------------- layout
    def _dock(self, title, widget, area):
        d = QDockWidget(title, self)
        d.setObjectName(title)
        d.setWidget(widget)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(area, d)
        return d

    def _header(self):
        bar = QWidget()
        bar.setObjectName('header')
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)

        def btn(text, tip, slot=None, checkable=False):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            if slot:
                (b.toggled if checkable else b.clicked).connect(slot)
            lay.addWidget(b)
            return b

        btn('Front', 'Numpad 1', lambda: self._view('front'))
        btn('Right', 'Numpad 3', lambda: self._view('right'))
        btn('Top', 'Numpad 7', lambda: self._view('top'))
        self.ortho_btn = btn('Ortho', 'Numpad 5', self._ortho, True)
        btn('Frame', 'F / Home', self.viewport.frame_all)
        lay.addStretch(1)
        self.overlay = {}
        for key, text, tip, on in (('show_bones', 'Bones', 'Show armature', True),
                                   ('show_grid', 'Grid', 'Show floor grid', True),
                                   ('wire_overlay', 'Wire', 'Wireframe overlay', False),
                                   ('backface_cull', 'Cull', 'Backface culling', False)):
            b = btn(text, tip, None, True)
            b.setChecked(on)
            b.toggled.connect(lambda v, k=key: self._set(k, v))
            self.overlay[key] = b
        self.alpha = QComboBox()
        self.alpha.addItems(['Alpha clip', 'Alpha blend', 'Alpha off'])
        self.alpha.currentIndexChanged.connect(
            lambda i: self._set('alpha_mode', ('clip', 'blend', 'off')[i]))
        lay.addWidget(self.alpha)
        lay.addSpacing(12)
        self.shade_group = QButtonGroup(self)
        self.shade_btns = {}
        for key, text in (('wire', 'Wireframe'), ('solid', 'Solid'), ('material', 'Material'),
                          ('weights', 'Weights')):
            b = btn(text, 'Viewport shading (Z cycles)', None, True)
            self.shade_group.addButton(b)
            self.shade_btns[key] = b
            b.clicked.connect(lambda _=False, k=key: self.set_shading(k))
        self.shade_btns['material'].setChecked(True)
        return bar

    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu('&File')
        f.addAction('Open…', self.open_dialog, QKeySequence.Open)
        f.addAction('Attach Part…', lambda: self.open_dialog(attach=True), QKeySequence('Ctrl+Shift+O'))
        f.addAction('Load Animation…', self.anim_dialog, QKeySequence('Ctrl+L'))
        f.addSeparator()
        f.addAction('Set Data Folder…', self.choose_data_root)
        f.addAction('Export OBJ (bind pose)…', self.export_obj, QKeySequence('Ctrl+E'))
        f.addAction('Save Screenshot…', self.screenshot, QKeySequence('F12'))
        f.addSeparator()
        f.addAction('Clear Scene', self.clear_scene)
        f.addAction('Quit', self.close, QKeySequence.Quit)
        v = mb.addMenu('&View')
        for key, text, sc_ in (('wire', 'Wireframe', None), ('solid', 'Solid', None),
                               ('material', 'Material Preview', None), ('weights', 'Weight Paint', None)):
            v.addAction(text, lambda k=key: self.set_shading(k))
        v.addSeparator()
        a = QAction('Cycle Shading', self, shortcut=QKeySequence('Z'))
        a.triggered.connect(self.cycle_shading)
        v.addAction(a)
        a = QAction('Play / Pause', self, shortcut=QKeySequence('Space'))
        a.triggered.connect(lambda: self.timeline.play.toggle())
        v.addAction(a)
        a = QAction('Next Frame', self, shortcut=QKeySequence('Right'))
        a.triggered.connect(lambda: self._step(1))
        v.addAction(a)
        a = QAction('Previous Frame', self, shortcut=QKeySequence('Left'))
        a.triggered.connect(lambda: self._step(-1))
        v.addAction(a)
        a = QAction('Hide Selected Mesh', self, shortcut=QKeySequence('H'))
        a.triggered.connect(self._hide_selected)
        v.addAction(a)
        a = QAction('Unhide All', self, shortcut=QKeySequence('Alt+H'))
        a.triggered.connect(self._unhide)
        v.addAction(a)
        v.addSeparator()
        for d in self.findChildren(QDockWidget):
            v.addAction(d.toggleViewAction())
        h = mb.addMenu('&Help')
        h.addAction('Controls', self._help)

    # ---------------------------------------------------------------- loading
    def open_dialog(self, attach=False):
        start = str(self.data_root if self.data_root.is_dir() else Path.home())
        files, _ = QFileDialog.getOpenFileNames(self, 'Attach part' if attach else 'Open model', start,
                                                'Dark Blood models (*.x *.prt *.ani);;All files (*)')
        for i, f in enumerate(files):
            self.open_path(f, 'attach' if attach or i > 0 else 'open')

    def anim_dialog(self):
        start = str(self.scene.base.path.parent if self.scene.base else self.data_root)
        f, _ = QFileDialog.getOpenFileName(self, 'Load animation', start, 'Animations (*.ani *.x *.prt)')
        if f:
            self.open_path(f, 'anim')

    def open_path(self, path, action='auto'):
        p = Path(path).resolve()
        is_anim = p.suffix.lower() in ANIM_EXT
        if action == 'auto':
            action = 'anim' if (is_anim and self.scene.base is not None) else 'open'
        try:
            if action == 'anim':
                self.scene.load_animation(p)
                self.timeline.play.setChecked(True)
            elif action == 'attach' and self.scene.base is not None:
                if len(self.scene.objects) == 1:
                    # The skeleton's own mesh is the game's fallback body; hide it once
                    # equipment is attached (it would z-fight with the parts).
                    for md in self.scene.base.meshes:
                        md.visible = False
                self.scene.load(p, attach=True)
            else:
                self.timeline.play.setChecked(False)
                self.scene.load(p)
                self.viewport.settings.selected_bone = ''
                self.viewport.settings.selected_mesh = None
                self.viewport.refresh(frame=True)
                self.settings_store.setValue('last_file', str(p))
        except (dbmesh.MeshFormatError, OSError, ValueError) as e:
            self.statusBar().showMessage('Cannot open %s: %s' % (p.name, e), 8000)
            return
        self.setWindowTitle('%s — Dark Blood Model Viewer' % (self.scene.base.name if self.scene.base else ''))
        self.statusBar().showMessage('%s: %s' % ({'anim': 'Animation', 'attach': 'Attached'}.get(action, 'Opened'),
                                                 p), 5000)
        self._sync_ui()

    def _play_from_list(self, path, index):
        try:
            if path == str(self.scene.base.path):
                self.scene.clip = sc.Clip(self.scene.base.model.animations[index], Path(path).name)
                self.scene.ticks = 0.0
            else:
                self.scene.load_animation(path, index)
            self.timeline.play.setChecked(True)
        except (dbmesh.MeshFormatError, OSError) as e:
            self.statusBar().showMessage('Cannot load animation: %s' % e, 8000)
        self._sync_ui(keep_lists=True)

    def clear_scene(self):
        self.timeline.play.setChecked(False)
        self.scene.clear()
        self._sync_ui()

    def choose_data_root(self):
        d = QFileDialog.getExistingDirectory(self, 'Extracted client files (…/darkblood-client-data/files)',
                                             str(self.data_root))
        if d:
            self.data_root = Path(d)
            self.settings_store.setValue('data_root', d)
            self.browser.populate(self.data_root)

    def _sync_ui(self, keep_lists=False):
        if not keep_lists:
            self.outliner.rebuild(self.scene)
        self.props.show_scene(self.scene)
        clip = self.scene.clip
        t = self.timeline
        t.slider.blockSignals(True)
        if clip is not None:
            t.slider.setRange(0, max(clip.frame_count - 1, 0))
            mt, tot = self.scene.matched_tracks()
            t.clip.setText('%s  ·  %s  ·  %d/%d tracks' % (clip.source, clip.name, mt, tot))
        else:
            t.slider.setRange(0, 0)
            t.clip.setText('No animation')
        t.slider.blockSignals(False)
        self._update_time_label()
        self.viewport.refresh()

    # ---------------------------------------------------------------- playback
    def _toggle_play(self, on):
        st = self.style()
        self.timeline.play.setIcon(st.standardIcon(st.StandardPixmap.SP_MediaPause if on
                                                    else st.StandardPixmap.SP_MediaPlay))
        self.last_tick = None
        if on and self.scene.clip is not None:
            self.timer.start()
        else:
            self.timer.stop()

    def _tick(self):
        clip = self.scene.clip
        if clip is None:
            self.timeline.play.setChecked(False)
            return
        now = time.perf_counter()
        dt = 0.0 if self.last_tick is None else now - self.last_tick
        self.last_tick = now
        speed = float(self.timeline.speed.currentText().rstrip('×'))
        t = self.scene.ticks + dt * clip.tps * speed
        if t > clip.length:
            if self.timeline.loop.isChecked() and clip.length > 0:
                t = t % clip.length
            else:
                t = clip.length
                self.timeline.play.setChecked(False)
        self.scene.ticks = t
        self._time_changed()

    def _time_changed(self):
        clip = self.scene.clip
        if clip is not None:
            self.timeline.slider.blockSignals(True)
            self.timeline.slider.setValue(int(round(self.scene.ticks / clip.tps * clip.fps)))
            self.timeline.slider.blockSignals(False)
        self._update_time_label()
        self.viewport.refresh()

    def _update_time_label(self):
        clip = self.scene.clip
        if clip is None:
            self.timeline.label.setText('—')
            return
        sec = self.scene.ticks / clip.tps
        self.timeline.label.setText('frame %d / %d   %.2fs' % (int(round(sec * clip.fps)),
                                                              clip.frame_count - 1, sec))

    def _slider(self, v):
        clip = self.scene.clip
        if clip is not None:
            self.scene.ticks = min(clip.length, v / clip.fps * clip.tps)
            self._update_time_label()
            self.viewport.refresh()

    def _seek(self, frame):
        clip = self.scene.clip
        if clip is not None:
            self.scene.ticks = min(clip.length, frame / clip.fps * clip.tps)
            self._time_changed()

    def _step(self, d):
        clip = self.scene.clip
        if clip is not None:
            f = int(round(self.scene.ticks / clip.tps * clip.fps)) + d
            self._seek(max(0, min(clip.frame_count - 1, f)))

    # ---------------------------------------------------------------- view
    def set_shading(self, key):
        self.viewport.settings.shading = key
        self.shade_btns[key].setChecked(True)
        if key == 'weights' and not self.viewport.settings.selected_bone and self.scene.base:
            names = [n for o in self.scene.objects for md in o.meshes for n in md.bone_names]
            if names:
                self.viewport.settings.selected_bone = names[0]
                self.statusBar().showMessage('Weight paint: select a bone in the Outliner', 6000)
        self.viewport.refresh()

    def cycle_shading(self):
        order = ['wire', 'solid', 'material', 'weights']
        self.set_shading(order[(order.index(self.viewport.settings.shading) + 1) % len(order)])

    def _set(self, key, value):
        setattr(self.viewport.settings, key, value)
        self.viewport.refresh()

    def _view(self, name):
        self.viewport.cam.set_view(name)
        self.viewport.update()

    def _ortho(self, on):
        self.viewport.cam.ortho = on
        self.viewport.update()

    def _select(self, md, bone):
        s = self.viewport.settings
        s.selected_mesh = md
        if bone:
            s.selected_bone = bone
        self.viewport.refresh()

    def _hide_selected(self):
        md = self.viewport.settings.selected_mesh
        if md is not None:
            md.visible = False
            self.outliner.rebuild(self.scene)
            self.viewport.refresh()

    def _unhide(self):
        for o in self.scene.objects:
            o.visible = True
            for md in o.meshes:
                md.visible = True
        self.outliner.rebuild(self.scene)
        self.viewport.refresh()

    # ---------------------------------------------------------------- output
    def export_obj(self):
        base = self.scene.base
        if base is None or not base.model.meshes:
            return
        d = QFileDialog.getExistingDirectory(self, 'Export OBJ to folder')
        if not d:
            return
        out = []
        for obj in self.scene.objects:
            if obj.model.meshes:
                out.append(dbmesh.export_obj(obj.model, d))
        self.statusBar().showMessage('Exported %s' % ', '.join(p.name for p in out), 8000)

    def screenshot(self):
        f, _ = QFileDialog.getSaveFileName(self, 'Save screenshot', 'screenshot.png', 'PNG (*.png)')
        if f:
            self.viewport.grabFramebuffer().save(f)
            self.statusBar().showMessage('Saved %s' % f, 5000)

    def _help(self):
        QMessageBox.information(self, 'Controls', (
            'Viewport\n'
            '  LMB / MMB drag: orbit      Shift+drag or RMB drag: pan\n'
            '  Wheel or Ctrl+MMB: zoom    Double-click, F, Home: frame all\n'
            '  1 / 3 / 7: front / right / top (Ctrl: opposite)   5: ortho\n'
            '  4 6 8 2: rotate view       Z: cycle shading\n\n'
            'Animation\n'
            '  Space: play/pause    ← →: previous/next frame\n\n'
            'Scene\n'
            '  Click a model in the Asset Browser to open it; click an .ani to play it.\n'
            '  Right-click a .prt ▸ Attach to put equipment on the loaded skeleton\n'
            '  (e.g. unit/character/fighter/fighter.x + part/mf/*).\n'
            '  Drop files on the window (.ani plays, .prt attaches, .x opens).\n'
            '  Outliner: tick meshes on/off, pick a bone for Weight Paint; H hides, Alt+H unhides.'))

    # ---------------------------------------------------------------- dnd / close
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            ext = Path(p).suffix.lower()
            if ext in ANIM_EXT:
                self.open_path(p, 'auto')
            elif ext == '.prt' and self.scene.base is not None:
                self.open_path(p, 'attach')
            else:
                self.open_path(p, 'open')

    def closeEvent(self, e):
        self.settings_store.setValue('geometry', self.saveGeometry())
        self.settings_store.setValue('state', self.saveState())
        super().closeEvent(e)


def run(argv):
    import argparse
    ap = argparse.ArgumentParser(description='Dark Blood model viewer')
    ap.add_argument('files', nargs='*', help='.x / .prt / .ani files to open (first opens, rest attach/play)')
    ap.add_argument('--data', help='extracted client files root (default: ../darkblood-client-data/files)')
    ap.add_argument('--screenshot', help='save a PNG of the window after loading, then exit (testing)')
    ap.add_argument('--shading', choices=['wire', 'solid', 'material', 'weights'])
    args = ap.parse_args(argv)
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Dark Blood Model Viewer')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    w = MainWindow(args.files, args.data)
    w.show()
    if args.shading:
        w.set_shading(args.shading)
    if args.screenshot:
        def shot():
            w.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(2500, shot)
    return app.exec()
