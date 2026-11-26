"""Main window: menus, header bar, docks, playback and file handling."""
import time
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDockWidget, QFileDialog, QHBoxLayout,
                               QMainWindow, QMessageBox, QToolButton, QVBoxLayout, QWidget)

import dbmesh
import scene as sc
from panels import AssetBrowser, Outliner, Properties, Timeline
from style import ANIM_EXT, MODEL_EXT, default_data_root
from viewport import Viewport


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
