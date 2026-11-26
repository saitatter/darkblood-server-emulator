"""Paths, runtime flags, and Bifrost dark-theme palette for Dark Blood Launcher."""
import sys
from pathlib import Path

IS_FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parents[3]
if not IS_FROZEN:
    for _p in (str(ROOT / 'src'), str(ROOT / 'tools' / 'automation'), str(ROOT / 'tools' / 'launcher')):
        if _p not in sys.path:
            sys.path.insert(0, _p)

CLIENT_DIR = ROOT / 'research' / 'client'
CLIENT_EXE = CLIENT_DIR / 'DarkBlood.exe'
CLIENT_DLL = CLIENT_DIR / 'steam_api.dll'
HOOK_BUILD_BAT = ROOT / 'client_hook' / 'build.bat'
HOOK_BUILT_DLL = ROOT / 'client_hook' / 'steam_api.dll'
REPO_URL = 'https://github.com/saitatter/darkblood-server-emulator'
GITHUB_COMMITS_API = 'https://api.github.com/repos/saitatter/darkblood-server-emulator/commits?per_page=25'

# Dark Blood / Bifrost color palette
BG_DARK = '#111318'
BG_HEADER = '#161922'
BG_CARD = '#1b1e29'
BG_CARD_ALT = '#212533'
BG_INPUT = '#262b3b'
BORDER = '#2e3447'
ACCENT = '#c82333'
ACCENT_HOVER = '#e02f40'
ACCENT_DARK = '#991b27'
GOLD = '#d8ae58'
TEXT_MAIN = '#eef1f8'
TEXT_DIM = '#9aa2b8'
TEXT_MUTED = '#6a728a'
OK_GREEN = '#3ddc84'
WARN_AMBER = '#f5b041'
ERR_RED = '#ff5c5c'
LINK_BLUE = '#58a6ff'

COMMIT_BADGES = {
    'feat':     ('#1e4620', '#5ce07a'),
    'fix':      ('#4a3210', '#f7b955'),
    'docs':     ('#16324f', '#6cb6ff'),
    'refactor': ('#37214d', '#c792ea'),
    'test':     ('#183f47', '#56d4dd'),
    'chore':    ('#2b3040', '#a6afc4'),
}
