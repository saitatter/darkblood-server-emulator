"""Shared asset path resolution, test override lookup and Lua dict section helpers."""
import os
import re
from pathlib import Path
from darkblood import REPO_ROOT


ROOT = REPO_ROOT


ASSETS_DIR = REPO_ROOT / 'assets'


ID_RE = re.compile(r'^ {4}ID = "([^"]+)",?$')


NAME_RE = re.compile(r'^ {6}"([^"]+)",?$')


ITEM_RE = re.compile(r'^ {6}\{"([^"]+)", (-?\d+)\},?$')


def data_root():
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    base = Path(env) if env else ROOT.parent / 'darkblood-client-data'
    return base / 'lua_src' / 'data' / 'dict'


def _env_override(filename: str):
    """Return Path to a test override file if explicitly placed in DARKBLOOD_CLIENT_DATA."""
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    if env:
        p = Path(env) / 'lua_src' / 'data' / 'dict' / filename
        if p.is_file():
            return p
    return None


def _quest_override_files():
    """Return quest files if explicitly placed in DARKBLOOD_CLIENT_DATA."""
    env = os.environ.get('DARKBLOOD_CLIENT_DATA')
    if env:
        root = Path(env) / 'lua_src' / 'data' / 'dict'
        if root.is_dir():
            files = sorted(root.glob('quest_*.lua'))
            if files:
                return files
    return []


def _quest_files():
    q_override = _quest_override_files()
    if q_override:
        return q_override
    root = data_root()
    return sorted(root.glob('quest_act*.lua')) if root.exists() else []


def _entries(path, item_re):
    """Yield (ID, [StoreList values]) for top-level entries of a dict file."""
    if not path.exists():
        return
    current, values, inside = None, [], False
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        m = ID_RE.match(line)
        if m:
            current = m.group(1)
            continue
        if line.startswith('    StoreList = {') and current:
            if line.rstrip().endswith('{}') or line.rstrip().endswith('{},'):
                yield current, []
                continue
            inside, values = True, []
            continue
        if inside:
            if line.startswith('    }'):
                yield current, values
                inside = False
                continue
            m = item_re.match(line)
            if m:
                values.append(m.groups() if m.lastindex and m.lastindex > 1 else m.group(1))


def _section(text, loader):
    """Body of `assert(<loader>({ ... }), "<loader>")` (first occurrence)."""
    start = text.find(loader + '({')
    if start == -1:
        return ''
    end = text.find('}), "%s")' % loader, start)
    return text[start:end if end != -1 else len(text)]


def _top_entries(section):
    """Split a dict section into its top-level `  {` ... `  },` entries."""
    return re.split(r'\n  \{\n', section)[1:]

