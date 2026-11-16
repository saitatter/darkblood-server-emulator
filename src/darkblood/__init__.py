"""Dark Blood offline server emulator (layout modelled on MHServerEmu; see docs/ARCHITECTURE.md)."""

from pathlib import Path


# Repository root (src/darkblood/__init__.py -> parents[2]); logs/ and data/ live here.
REPO_ROOT = Path(__file__).resolve().parents[2]
