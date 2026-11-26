"""Application entry: OpenGL surface format, theme and command line."""
import argparse
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

from style import STYLE
from window import MainWindow


def run(argv):
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
