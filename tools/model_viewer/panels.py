"""Dock panels: asset browser, outliner, properties and timeline."""
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QScrollArea, QSlider, QTabWidget, QToolButton,
                               QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import dbmesh
import scene as sc
from style import ANIM_EXT, MODEL_EXT, checker_pixmap, is_xof, pil_to_pixmap
from textures import load_image


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
            files = sorted(f for f in fn if f.lower().endswith(exts) and not is_xof(Path(dp) / f))
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
                                img = load_image(tp)
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
        img = load_image(key)
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
