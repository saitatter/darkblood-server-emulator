"""Dark Blood offline server emulator (layout modelled on MHServerEmu; see docs/ARCHITECTURE.md)."""

import os
from pathlib import Path
import sys


# Repository / install root; logs/, data/ and assets/ live here.
if getattr(sys, 'frozen', False):
    REPO_ROOT = Path(sys.executable).resolve().parent
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get('DARKBLOOD_DATA', REPO_ROOT / 'data'))
