"""Blender-like Qt theme, shared constants and pixmap helpers."""
import os
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

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


def is_xof(path):
    """DirectX compressed X effects (14 files) use another format; hide them."""
    try:
        with open(path, 'rb') as f:
            return f.read(4) == b'xof '
    except OSError:
        return True
