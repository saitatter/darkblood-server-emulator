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


def tsv_rows(path):
    """Data rows (header skipped) of a TSV file as lists of tab-separated columns."""
    return [line.split('\t') for line in Path(path).read_text(encoding='utf-8', errors='replace').splitlines()[1:]]


_LUA_TOKEN = re.compile(r'\s*(?:(\{|\}|=|,)|"((?:[^"\\]|\\.)*)"|([-+]?[0-9][0-9.eE+-]*)|([A-Za-z_]\w*))')


def lua_table(text, loader):
    """The table literal passed to `assert(<loader>({ ... }), ...)`, as Python lists/dicts.

    A table whose entries are all `key = value` becomes a dict, one with only
    positional entries a list (strings, numbers and nested tables). Returns []
    when the section is missing.
    """
    start = text.find(loader + '({')
    if start == -1:
        return []
    pos = start + len(loader) + 1

    def token():
        nonlocal pos
        m = _LUA_TOKEN.match(text, pos)
        if not m:
            raise ValueError(f'{loader}: unexpected Lua at {text[pos:pos + 40]!r}')
        pos = m.end()
        return m

    def value(m):
        if m.group(1) == '{':
            return table()
        if m.group(2) is not None:
            return m.group(2)
        if m.group(3) is not None:
            num = m.group(3)
            return float(num) if any(c in num for c in '.eE') else int(num)
        return m.group(4)

    def table():
        nonlocal pos
        keyed, items = {}, []
        while True:
            m = token()
            if m.group(1) == '}':
                return keyed if keyed and not items else items
            if m.group(1) == ',':
                continue
            if m.group(4) is not None:
                after = _LUA_TOKEN.match(text, pos)
                if after and after.group(1) == '=':
                    pos = after.end()
                    keyed[m.group(4)] = value(token())
                    continue
            items.append(value(m))

    first = token()
    if first.group(1) != '{':
        return []
    return table()


def bundled_asset(name, override=None):
    """assets/<name> when it should be used: it exists and no client-data override replaces it."""
    if override:
        return None
    path = ASSETS_DIR / name
    return path if path.is_file() else None
