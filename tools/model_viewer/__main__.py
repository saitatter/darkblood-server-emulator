"""Dark Blood model viewer.

    py -3.13 tools/model_viewer [file.x|file.prt|file.ani ...] [--data DIR]

Requires: pip install -r tools/model_viewer/requirements.txt (Python 3.10+).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'client_data')]

from app import run  # noqa: E402

if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
