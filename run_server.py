"""Start the local Dark Blood server from the repository root: ``python run_server.py``."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from darkblood.__main__ import main  # noqa: E402

if __name__ == '__main__':
    main()
