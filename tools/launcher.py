"""Dark Blood Online — Custom Launcher (Bifrost-inspired dark UI).

    python tools/launcher.py

Features:
  - Extracts and displays the DarkBlood.exe client icon in the header & taskbar.
  - Scrollable News feed populated from the repository's latest git commits
    (with GitHub API fallback if .git is absent).
  - Configurable Server IP/Host, Game Port, Relay Port, Account, and Multibox count.
  - Modular Patches (Hacks & Improvements) toggle list mapped 1:1 to client_hook/patches/*.c.
  - Built-in TCP connection probe, local server start/stop, and hook DLL rebuild/deploy.
"""
import io
import json
import hashlib
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

IS_FROZEN = bool(getattr(sys, 'frozen', False))
ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent.parent
if not IS_FROZEN:
    sys.path.insert(0, str(ROOT / 'src'))
    sys.path.insert(0, str(ROOT / 'tools'))

from darkblood.core import options  # noqa: E402
from darkblood.games.gm_bridge import GM_BRIDGE_HOST, GM_BRIDGE_PORT, SERVER_LIVE_COMMANDS  # noqa: E402
import gamectl  # noqa: E402
import updater  # noqa: E402

CLIENT_DIR = gamectl.LAB
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


def extract_client_icon_bytes(exe_path=CLIENT_EXE):
    """Extract the primary RT_GROUP_ICON from DarkBlood.exe as .ico bytes (or None)."""
    if not exe_path.exists():
        return None
    try:
        import pefile
    except ImportError:
        return None
    pe = None
    try:
        pe = pefile.PE(str(exe_path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        if not hasattr(pe, 'DIRECTORY_ENTRY_RESOURCE'):
            return None
        rt_icon = {}
        group_data = None
        for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if entry.id == 3:  # RT_ICON
                for icon_e in entry.directory.entries:
                    if icon_e.directory.entries:
                        s = icon_e.directory.entries[0].data.struct
                        rt_icon[icon_e.id] = pe.get_data(s.OffsetToData, s.Size)
            elif entry.id == 14 and group_data is None:  # RT_GROUP_ICON
                for grp_e in entry.directory.entries:
                    if grp_e.directory.entries:
                        s = grp_e.directory.entries[0].data.struct
                        group_data = pe.get_data(s.OffsetToData, s.Size)
                        break
        if not group_data or len(group_data) < 6:
            return None
        reserved, img_type, count = struct.unpack_from('<HHH', group_data, 0)
        if img_type != 1 or count == 0:
            return None
        entries = []
        for i in range(count):
            off = 6 + i * 14
            if off + 14 > len(group_data):
                break
            w, h, colors, res, planes, bpp, size, icon_id = struct.unpack_from('<BBBBHHIH', group_data, off)
            blob = rt_icon.get(icon_id)
            if blob:
                entries.append((w, h, colors, res, planes, bpp, blob))
        if not entries:
            return None
        out = bytearray(struct.pack('<HHH', reserved, 1, len(entries)))
        data_offset = 6 + 16 * len(entries)
        for w, h, colors, res, planes, bpp, blob in entries:
            out.extend(struct.pack('<BBBBHHII', w, h, colors, res, planes, bpp, len(blob), data_offset))
            data_offset += len(blob)
        for *_, blob in entries:
            out.extend(blob)
        return bytes(out)
    except Exception:
        return None
    finally:
        if pe is not None:
            pe.close()


# Map local git author emails/names to GitHub usernames so offline `git log`
# displays GitHub handles instead of local real names.
_GITHUB_USERNAMES = {
    'andrei.voicu133@gmail.com': 'saitatter',
    'voicu andrei-daniel': 'saitatter',
    'cri999sti@gmail.com': 'CristianVita',
}


def _resolve_github_username(name: str, email: str = '', login: str = '') -> str:
    if login:
        return login
    email_low = (email or '').strip().lower()
    if email_low in _GITHUB_USERNAMES:
        return _GITHUB_USERNAMES[email_low]
    if email_low.endswith('@users.noreply.github.com'):
        local_part = email_low.split('@', 1)[0]
        return local_part.split('+', 1)[-1]
    name_low = (name or '').strip().lower()
    if name_low in _GITHUB_USERNAMES:
        return _GITHUB_USERNAMES[name_low]
    return name or 'unknown'


def _current_release_tags(flags):
    """Return (current_tag, previous_tag) for the installed/latest release."""
    cur = ''
    ver_file = ROOT / updater.VERSION_FILE
    if ver_file.is_file():
        v = ver_file.read_text(encoding='utf-8', errors='replace').strip()
        if v.startswith('v'):
            cur = v
    try:
        proc = subprocess.run(
            ['git', 'tag', '--sort=-creatordate', '--list', 'v*'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=5, creationflags=flags,
        )
        if proc.returncode == 0:
            tags = [t.strip() for t in proc.stdout.splitlines() if t.strip()]
            if cur:
                if cur in tags:
                    idx = tags.index(cur)
                    return cur, (tags[idx + 1] if idx + 1 < len(tags) else '')
                return cur, (tags[0] if tags else '')
            if tags:
                return tags[0], (tags[1] if len(tags) > 1 else '')
    except Exception:
        pass
    return cur, ''


def _resolve_github_release_range(cur_tag: str, prev_tag: str):
    """Resolve (cur_tag, prev_tag) from GitHub Releases API when prev_tag is unknown."""
    if cur_tag and prev_tag:
        return cur_tag, prev_tag
    try:
        api = f'https://api.github.com/repos/{updater.GITHUB_REPO}/releases?per_page=15'
        req = urllib.request.Request(api, headers={'User-Agent': 'DarkBlood-Launcher'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            releases = json.loads(resp.read().decode('utf-8'))
        tags = [
            (r.get('tag_name') or '').strip()
            for r in releases
            if not r.get('draft') and (r.get('tag_name') or '').strip()
        ]
        if not tags:
            return cur_tag, prev_tag
        if cur_tag and cur_tag in tags:
            idx = tags.index(cur_tag)
            return cur_tag, (tags[idx + 1] if idx + 1 < len(tags) else '')
        if not cur_tag:
            return tags[0], (tags[1] if len(tags) > 1 else '')
    except Exception:
        pass
    return cur_tag, prev_tag


VISIBLE_COMMIT_TYPES = frozenset({'feat', 'fix'})


def _is_user_facing_commit(subject: str) -> bool:
    ctype, _, _ = parse_commit_prefix(subject)
    return ctype.lower() in VISIBLE_COMMIT_TYPES


def _parse_github_commit_items(items, limit=None):
    commits = []
    for item in items:
        sha = item.get('sha', '')
        c = item.get('commit', {})
        gh_author = item.get('author') or {}
        c_author = c.get('author') or {}
        subject = (c.get('message', '') or '').splitlines()[0]
        if '[skip ci]' in subject or 'github-actions[bot]' in (c_author.get('name', '') or '').lower():
            continue
        if not _is_user_facing_commit(subject):
            continue
        author = _resolve_github_username(
            c_author.get('name', ''),
            c_author.get('email', ''),
            gh_author.get('login', ''),
        )
        date = (c_author.get('date', '') or '')[:10]
        commits.append({
            'sha': sha, 'short': sha[:7],
            'date': date, 'author': author, 'subject': subject,
        })
        if limit is not None and len(commits) >= limit:
            break
    return commits


def fetch_recent_commits(limit=None):
    """Return list of dicts {sha, short, date, author, subject} (FEAT/FIX only) for the current release."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    cur_tag, prev_tag = _current_release_tags(flags)
    rev_spec = f'{prev_tag}..{cur_tag}' if (cur_tag and prev_tag) else (cur_tag or 'HEAD')
    label = f'release {cur_tag}' if cur_tag else 'local git'
    try:
        git_args = ['git', 'log', rev_spec, '--no-merges',
                    '--pretty=format:%H\x1f%h\x1f%ad\x1f%an\x1f%ae\x1f%s', '--date=short']
        if limit is not None:
            git_args.insert(3, f'-n{limit * 3}')
        proc = subprocess.run(
            git_args,
            cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=8, creationflags=flags,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            commits = []
            for line in proc.stdout.splitlines():
                parts = line.split('\x1f')
                if len(parts) == 6:
                    if '[skip ci]' in parts[5] or 'github-actions[bot]' in parts[3].lower():
                        continue
                    if not _is_user_facing_commit(parts[5]):
                        continue
                    commits.append({
                        'sha': parts[0], 'short': parts[1],
                        'date': parts[2],
                        'author': _resolve_github_username(parts[3], parts[4]),
                        'subject': parts[5],
                    })
                    if limit is not None and len(commits) >= limit:
                        break
            if commits:
                return commits, label
    except Exception:
        pass

    # Fallback: GitHub REST API — use /compare/{prev_tag}...{cur_tag} so ONLY commits
    # belonging to the current release are shown (never commits from older releases).
    try:
        cur_tag, prev_tag = _resolve_github_release_range(cur_tag, prev_tag)
        if cur_tag and prev_tag:
            api_url = f'https://api.github.com/repos/{updater.GITHUB_REPO}/compare/{prev_tag}...{cur_tag}'
            req = urllib.request.Request(api_url, headers={'User-Agent': 'DarkBlood-Launcher'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            # GitHub /compare returns commits oldest-first; reverse for newest-first display.
            items = list(reversed(data.get('commits') or []))
            return _parse_github_commit_items(items, limit=limit), f'release {cur_tag}'

        base_api = f'https://api.github.com/repos/{updater.GITHUB_REPO}/commits?per_page=100'
        api_url = base_api + (f'&sha={cur_tag}' if cur_tag else '')
        req = urllib.request.Request(api_url, headers={'User-Agent': 'DarkBlood-Launcher'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return _parse_github_commit_items(data, limit=limit), (f'release {cur_tag}' if cur_tag else 'GitHub')
    except Exception as exc:
        # Offline portable fallback: parse bundled RELEASE_NOTES.md (Features & Bug Fixes only)
        notes_file = ROOT / 'RELEASE_NOTES.md'
        if notes_file.is_file():
            commits = []
            section_kind = None
            pat = re.compile(r'^- (?:(?:\*\*([^*\n]+)\*\*:\s*)?)(.+?) \(`([0-9a-f]{7})`, @([^)]+)\)$')
            for raw_line in notes_file.read_text(encoding='utf-8', errors='replace').splitlines():
                s = raw_line.strip()
                if s.startswith('#### '):
                    low = s.lower()
                    if 'feature' in low:
                        section_kind = 'feat'
                    elif 'fix' in low:
                        section_kind = 'fix'
                    else:
                        section_kind = None
                    continue
                if section_kind not in VISIBLE_COMMIT_TYPES:
                    continue
                m = pat.match(s)
                if m:
                    scope, desc, sha, user = m.groups()
                    subj = f'{section_kind}({scope}): {desc}' if scope else f'{section_kind}: {desc}'
                    commits.append({'sha': sha, 'short': sha, 'date': cur_tag or 'release', 'author': user, 'subject': subj})
                    if limit is not None and len(commits) >= limit:
                        break
            if commits:
                return commits, (f'release {cur_tag} (offline)' if cur_tag else 'release notes')
        return [], f'unavailable ({exc.__class__.__name__})'


def parse_commit_prefix(subject):
    """Extract conventional-commit type (feat/fix/docs/...) and clean title."""
    m = re.match(r'^([a-z]+)(?:\(([^)]+)\))?:\s*(.+)$', subject)
    if m:
        return m.group(1), m.group(2) or '', m.group(3)
    return 'chore', '', subject


def probe_tcp(host, port, timeout=1.5):
    """Return (reachable: bool, detail: str) for a TCP endpoint."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            ms = (time.perf_counter() - t0) * 1000.0
            return True, f'Online ({ms:.0f} ms)'
    except OSError:
        return False, 'Offline'


def stage_client_folder(exe_path: Path, target_dir: Path = CLIENT_DIR,
                        hook_dll: Path = HOOK_BUILT_DLL, verify_hash: bool = True):
    """Stage a clean playable copy in `target_dir` without modifying the original game folder.

    Copies root files from `exe_path.parent`, backs up `steam_api.dll` to `steam_api.dll.bak`,
    deploys `hook_dll`, and links `Data/` via a Windows directory junction (`mklink /J`).
    """
    exe_path = Path(exe_path).resolve()
    if not exe_path.is_file():
        raise FileNotFoundError(f'DarkBlood.exe not found: {exe_path}')
    if verify_hash:
        digest = hashlib.sha256(exe_path.read_bytes()).hexdigest()
        if digest != gamectl.CLIENT_SHA256:
            raise ValueError(
                f'Unsupported DarkBlood.exe SHA-256 ({digest[:12]}...). '
                f'Expected {gamectl.CLIENT_SHA256[:12]}... (Steam build 1.6.5#0).'
            )
    src_dir = exe_path.parent
    target_dir = Path(target_dir).resolve()
    if src_dir == target_dir:
        raise ValueError('Source folder is already the staged client folder.')
    target_dir.mkdir(parents=True, exist_ok=True)

    for item in src_dir.iterdir():
        if item.is_file():
            dst = target_dir / item.name
            if item.name.lower() == 'steam_api.dll':
                bak = target_dir / 'steam_api.dll.bak'
                if not bak.exists():
                    shutil.copy2(item, bak)
            else:
                shutil.copy2(item, dst)

    src_data = src_dir / 'Data'
    dst_data = target_dir / 'Data'
    if src_data.is_dir() and not dst_data.exists():
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        proc = subprocess.run(
            ['cmd.exe', '/c', 'mklink', '/J', str(dst_data), str(src_data)],
            capture_output=True, text=True, creationflags=flags,
        )
        if proc.returncode != 0:
            raise RuntimeError(f'Failed to link Data junction: {proc.stderr or proc.stdout}')

    if Path(hook_dll).is_file():
        shutil.copy2(hook_dll, target_dir / 'steam_api.dll')
    return target_dir


def ensure_hook_deployed(client_dir: Path = CLIENT_DIR, hook_dll: Path = HOOK_BUILT_DLL) -> bool:
    """Ensure the bundled `client_hook/steam_api.dll` is installed in `client_dir`.

    Backs up any original `steam_api.dll` to `steam_api.dll.bak` on first deploy.
    Returns True if a fresh copy was written, False if already up to date or unavailable.
    """
    src = Path(hook_dll)
    dst_dir = Path(client_dir)
    dst = dst_dir / 'steam_api.dll'
    if not src.is_file() or not dst_dir.is_dir():
        return False
    src_bytes = src.read_bytes()
    if dst.is_file():
        try:
            if dst.read_bytes() == src_bytes:
                return False
        except OSError:
            pass
        bak = dst_dir / 'steam_api.dll.bak'
        if not bak.exists():
            try:
                shutil.copy2(dst, bak)
            except OSError:
                pass
    try:
        shutil.copy2(src, dst)
        return True
    except PermissionError:
        # Another game instance already has steam_api.dll mapped; keep going if present.
        if dst.is_file():
            return False
        raise


def parse_gm_commands_doc(doc_path: Path = None) -> list:
    """Parse `docs/GM_COMMANDS.md` tables into structured command dicts."""
    path = doc_path or (ROOT / 'docs' / 'GM_COMMANDS.md')
    if not path.is_file():
        return []
    commands = []
    category = 'General'
    link_re = re.compile(r'\[([^\]]+)\]\([^)]+\)')
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if line.startswith('### '):
            category = line[4:].strip()
            continue
        if not line.startswith('| `'):
            continue
        cols = [c.strip() for c in line.strip('|').split('|')]
        if len(cols) < 4:
            continue
        name = cols[0].strip('`').strip()
        if not name:
            continue
        desc = cols[1]
        params = cols[2].replace('`', '').replace('\\|', '|')
        example = link_re.sub(r'\1', cols[3]).replace('`', '')
        commands.append({
            'name': name,
            'category': category,
            'description': desc,
            'params': params,
            'example': example,
            'live': name.lower() in SERVER_LIVE_COMMANDS,
        })
    if not any(c['name'] == 'dualskill' for c in commands):
        commands.append({
            'name': 'dualskill',
            'category': 'Skills & Buffs',
            'description': 'Activate or extend Dual Skill duration directly',
            'params': '[days=30]',
            'example': '%dualskill 30',
            'live': True,
        })
    return commands


def query_gm_bridge(payload: dict, host: str = GM_BRIDGE_HOST, port: int = GM_BRIDGE_PORT,
                    timeout: float = 2.5) -> dict:
    """Send a single JSON-line request to the localhost GM bridge and return its response dict."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall((json.dumps(payload) + '\n').encode('utf-8'))
            buf = bytearray()
            while b'\n' not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
            if not buf:
                return {'ok': False, 'message': 'Empty response from server.'}
            return json.loads(buf.decode('utf-8', errors='replace').splitlines()[0])
    except OSError as exc:
        return {'ok': False, 'offline': True, 'message': f'Server GM bridge offline ({exc}).'}
    except Exception as exc:
        return {'ok': False, 'message': str(exc)}


def launch_clients(account, count=1):
    """Launch 1..4 DarkBlood.exe instances directly against the configured server."""
    if not CLIENT_EXE.exists():
        raise RuntimeError(f'Client executable not found: {CLIENT_EXE}')
    ensure_hook_deployed(CLIENT_DIR, HOOK_BUILT_DLL)
    if not CLIENT_DLL.exists():
        raise RuntimeError(f'Hook DLL not found: {CLIENT_DLL}')

    import multibox
    for pid in multibox._running_clients():
        try:
            multibox.release_instance_mutexes(pid)
        except Exception:
            pass

    count = max(1, min(4, int(count)))
    base_acc = (account or 'OfflinePlayer').strip() or 'OfflinePlayer'
    accounts = [base_acc] + [f'{base_acc}_{i}' for i in range(2, count + 1)]
    if base_acc == 'OfflinePlayer' and count > 1:
        accounts = multibox.default_accounts(count)

    launched = []
    rects = multibox.compute_tile_rects(multibox._work_area(), count) if count > 1 else None
    for idx, acc in enumerate(accounts):
        env = os.environ.copy()
        env['__COMPAT_LAYER'] = 'RunAsInvoker'
        env['DARKBLOOD_ACCOUNT'] = acc
        if rects is not None:
            env['DARKBLOOD_WINDOW_RECT'] = '%d,%d,%d,%d' % rects[idx]
        proc = subprocess.Popen([str(CLIENT_EXE)], cwd=str(CLIENT_DIR), env=env)
        launched.append((proc.pid, acc))
        if idx + 1 < count:
            time.sleep(2.5)
            try:
                multibox.release_instance_mutexes(proc.pid)
            except Exception:
                pass
    return launched


class ScrollFrame(tk.Frame):
    """Dark-themed vertical scrollable container with flicker-free atomic swaps."""
    def __init__(self, parent, bg=BG_CARD, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self._bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                       style='Dark.Vertical.TScrollbar')
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._bind_inner(self.inner)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')

        # Bind wheel only while pointer is over this scroll area
        self.canvas.bind('<Enter>', self._bind_wheel)
        self.canvas.bind('<Leave>', self._unbind_wheel)

    def _bind_inner(self, frame):
        frame.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        frame.bind('<Enter>', self._bind_wheel)
        frame.bind('<Leave>', self._unbind_wheel)

    def new_offscreen_inner(self):
        return tk.Frame(self.canvas, bg=self._bg)

    def swap_inner(self, new_inner):
        """Atomically replace inner frame to avoid Win32 white/light-theme redraw flash."""
        old = self.inner
        self._bind_inner(new_inner)
        new_inner.update_idletasks()
        self.inner = new_inner
        self.canvas.itemconfigure(self._win, window=new_inner, width=max(1, self.canvas.winfo_width()))
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.canvas.yview_moveto(0.0)
        if old is not None and old is not new_inner:
            old.destroy()

    def _bind_wheel(self, _event=None):
        self.canvas.bind_all('<MouseWheel>', self._on_wheel)

    def _unbind_wheel(self, _event=None):
        self.canvas.unbind_all('<MouseWheel>')

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')


class DarkBloodLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Dark Blood Online — Custom Launcher')
        self.configure(bg=BG_DARK)
        self.minsize(880, 580)
        self.geometry('980x640')

        self._server_proc = None
        self._patch_vars = {}
        self._header_icon_img = None
        self._temp_ico_path = None
        self._active_tab = 'news'

        self._configure_styles()
        self._load_client_icon()
        self._build_header()
        self._build_body()
        self._build_footer()

        self._load_values()
        self._switch_tab('news')
        self._refresh_client_badge()
        self._refresh_commits()
        self._probe_server_async()
        self._check_updates_async()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _configure_styles(self):
        style = ttk.Style(self)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure(
            'Dark.Vertical.TScrollbar',
            background='#2c3245', troughcolor=BG_CARD, bordercolor=BG_CARD,
            arrowcolor=TEXT_DIM, relief='flat', width=10,
        )
        style.map('Dark.Vertical.TScrollbar', background=[('active', '#3d455e')])

    def _load_client_icon(self):
        bundled = ROOT / 'assets' / 'darkblood.ico'
        ico_bytes = bundled.read_bytes() if bundled.is_file() else extract_client_icon_bytes(CLIENT_EXE)
        if not ico_bytes:
            return
        try:
            if bundled.is_file():
                self.iconbitmap(str(bundled))
            else:
                fd, tmp_path = tempfile.mkstemp(prefix='darkblood_icon_', suffix='.ico')
                os.close(fd)
                Path(tmp_path).write_bytes(ico_bytes)
                self._temp_ico_path = tmp_path
                self.iconbitmap(tmp_path)
        except Exception:
            pass
        try:
            from PIL import Image, ImageTk
            img = Image.open(io.BytesIO(ico_bytes))
            # Pick largest available icon frame (48x48)
            img = img.convert('RGBA').resize((46, 46), Image.LANCZOS)
            self._header_icon_img = ImageTk.PhotoImage(img)
        except Exception:
            self._header_icon_img = None

    def _reload_header_icon(self):
        self._load_client_icon()
        if self._header_icon_img is not None and getattr(self, '_header_icon_lbl', None) is not None:
            self._header_icon_lbl.configure(image=self._header_icon_img, text='', bg=BG_HEADER, width=0, height=0)

    def _make_btn(self, parent, text, command, bg=BG_CARD_ALT, hover=BORDER, fg=TEXT_MAIN,
                  font=('Segoe UI', 9, 'bold'), padx=12, pady=6):
        btn = tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=hover, activeforeground=fg,
            relief='flat', bd=0, cursor='hand2', font=font, padx=padx, pady=pady,
        )
        btn.bind('<Enter>', lambda e: btn.configure(bg=hover) if btn['state'] != 'disabled' else None)
        btn.bind('<Leave>', lambda e: btn.configure(bg=bg) if btn['state'] != 'disabled' else None)
        return btn

    def _make_entry(self, parent, textvariable, width=18):
        return tk.Entry(
            parent, textvariable=textvariable, width=width,
            bg=BG_INPUT, fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
            relief='flat', bd=0, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT,
            font=('Segoe UI', 9),
        )

    # ---- Header ---------------------------------------------------------

    def _build_header(self):
        header = tk.Frame(self, bg=BG_HEADER, height=74)
        header.pack(fill='x')
        header.pack_propagate(False)

        left = tk.Frame(header, bg=BG_HEADER)
        left.pack(side='left', padx=18, pady=12)

        if self._header_icon_img is not None:
            self._header_icon_lbl = tk.Label(left, image=self._header_icon_img, bg=BG_HEADER)
            self._header_icon_lbl.pack(side='left', padx=(0, 12))
        else:
            self._header_icon_lbl = tk.Label(
                left, text='DB', bg=ACCENT, fg='white',
                font=('Segoe UI', 14, 'bold'), width=3, height=1,
            )
            self._header_icon_lbl.pack(side='left', padx=(0, 12))

        title_box = tk.Frame(left, bg=BG_HEADER)
        title_box.pack(side='left')
        tk.Label(title_box, text='DARK BLOOD ONLINE', bg=BG_HEADER, fg=TEXT_MAIN,
                 font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        tk.Label(title_box, text='OFFLINE SERVER EMULATOR  •  CUSTOM LAUNCHER',
                 bg=BG_HEADER, fg=GOLD, font=('Segoe UI', 8, 'bold')).pack(anchor='w')

        # Center/Right Navigation Tabs
        self._nav_frame = tk.Frame(header, bg=BG_HEADER)
        self._nav_frame.pack(side='left', padx=(34, 0), fill='y')
        self._tab_btns = {}
        for tab_id, label in (('news', 'NEWS & SERVER'), ('patches', 'PATCHES & HACKS'), ('gm', 'GM COMMANDS')):
            b = tk.Button(
                self._nav_frame, text=label, command=lambda t=tab_id: self._switch_tab(t),
                bg=BG_HEADER, fg=TEXT_DIM, activebackground=BG_CARD, activeforeground=TEXT_MAIN,
                relief='flat', bd=0, cursor='hand2', font=('Segoe UI', 9, 'bold'), padx=14,
            )
            if tab_id != 'gm':
                b.pack(side='left', fill='y')
            self._tab_btns[tab_id] = b

        # Right status pills
        right = tk.Frame(header, bg=BG_HEADER)
        right.pack(side='right', padx=18)

        self.srv_pill = tk.Label(
            right, text='● Checking server...', bg=BG_CARD_ALT, fg=TEXT_DIM,
            font=('Segoe UI', 8, 'bold'), padx=10, pady=4, cursor='hand2',
        )
        self.srv_pill.pack(anchor='e')
        self.srv_pill.bind('<Button-1>', lambda e: self._probe_server_async())

        self.client_badge = tk.Label(
            right, text='Checking client...', bg=BG_HEADER, fg=TEXT_MUTED,
            font=('Segoe UI', 8), cursor='hand2',
        )
        self.client_badge.pack(anchor='e', pady=(3, 0))
        self.client_badge.bind('<Button-1>', lambda e: self._setup_client_dialog())

        # Crimson divider line
        tk.Frame(self, bg=ACCENT, height=2).pack(fill='x')

    def _switch_tab(self, tab_id):
        if tab_id == 'gm' and not self._is_gm_enabled():
            tab_id = 'news'
        self._active_tab = tab_id
        for tid, btn in self._tab_btns.items():
            if tid == tab_id:
                btn.configure(fg=TEXT_MAIN, bg=BG_CARD)
            else:
                btn.configure(fg=TEXT_DIM, bg=BG_HEADER)
        page = self._pages.get(tab_id)
        if page is not None:
            page.tkraise()
        if tab_id == 'gm':
            self._refresh_gm_players_async()

    def _is_gm_enabled(self) -> bool:
        var = self._patch_vars.get('gm_mode')
        return bool(var.get()) if var is not None else bool(options.get('gm_mode'))

    def _sync_gm_tab_visibility(self):
        btn = self._tab_btns.get('gm')
        if btn is None:
            return
        if self._is_gm_enabled():
            if not btn.winfo_ismapped():
                btn.pack(side='left', fill='y')
        else:
            if btn.winfo_ismapped():
                btn.pack_forget()
            if self._active_tab == 'gm':
                self._switch_tab('news')

    # ---- Body (News & Server + Patches + GM Commands) -------------------

    def _build_body(self):
        self.body = tk.Frame(self, bg=BG_DARK)
        self.body.pack(fill='both', expand=True, padx=16, pady=14)
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_columnconfigure(0, weight=1)

        self.news_page = tk.Frame(self.body, bg=BG_DARK)
        self.patches_page = tk.Frame(self.body, bg=BG_DARK)
        self.gm_page = tk.Frame(self.body, bg=BG_DARK)
        self._pages = {
            'news': self.news_page,
            'patches': self.patches_page,
            'gm': self.gm_page,
        }
        for page in self._pages.values():
            page.grid(row=0, column=0, sticky='nsew')

        self._build_news_page()
        self._build_patches_page()
        self._build_gm_page()

    def _build_news_page(self):
        # Two-column Bifrost layout: Left = News/Commits feed, Right = Server & Account panel
        left_card = tk.Frame(self.news_page, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        left_card.pack(side='left', fill='both', expand=True, padx=(0, 12))

        news_hdr = tk.Frame(left_card, bg=BG_CARD_ALT, height=38)
        news_hdr.pack(fill='x')
        news_hdr.pack_propagate(False)
        tk.Label(news_hdr, text='RELEASE CHANGELOG', bg=BG_CARD_ALT, fg=GOLD,
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=12)
        self.news_source_lbl = tk.Label(news_hdr, text='', bg=BG_CARD_ALT, fg=TEXT_MUTED,
                                        font=('Segoe UI', 8))
        self.news_source_lbl.pack(side='left', padx=(4, 0))
        self._make_btn(
            news_hdr, 'Refresh', self._refresh_commits,
            bg=BG_CARD, hover=BORDER, fg=TEXT_DIM, font=('Segoe UI', 8, 'bold'), padx=8, pady=2,
        ).pack(side='right', padx=(4, 8), pady=6)
        self.update_btn = self._make_btn(
            news_hdr, 'Check Updates', self._on_update_click,
            bg=BG_CARD, hover=BORDER, fg=TEXT_DIM, font=('Segoe UI', 8, 'bold'), padx=8, pady=2,
        )
        self.update_btn.pack(side='right', padx=(4, 0), pady=6)
        self._update_status = None

        self.news_scroll = ScrollFrame(left_card, bg=BG_CARD)
        self.news_scroll.pack(fill='both', expand=True, padx=4, pady=(4, 0))

        tk.Frame(left_card, bg=BORDER, height=1).pack(fill='x')
        self.news_pager = tk.Frame(left_card, bg=BG_CARD_ALT, height=34)
        self.news_pager.pack(fill='x')
        self.news_pager.pack_propagate(False)
        self._all_commits = []
        self._commits_page = 1
        self._commits_page_size = 15

        # Right panel: Server Connection + Account + Active Patches summary
        right_col = tk.Frame(self.news_page, bg=BG_DARK, width=320)
        right_col.pack(side='right', fill='y')
        right_col.pack_propagate(False)

        # Server card
        srv_card = tk.Frame(right_col, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        srv_card.pack(fill='x', pady=(0, 12))

        srv_hdr = tk.Frame(srv_card, bg=BG_CARD_ALT, height=34)
        srv_hdr.pack(fill='x')
        srv_hdr.pack_propagate(False)
        tk.Label(srv_hdr, text='SERVER CONNECTION', bg=BG_CARD_ALT, fg=GOLD,
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=12)

        srv_body = tk.Frame(srv_card, bg=BG_CARD, padx=12, pady=10)
        srv_body.pack(fill='x')

        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.relay_port_var = tk.StringVar()
        self.account_var = tk.StringVar()
        self.clients_var = tk.IntVar(value=1)

        tk.Label(srv_body, text='Server IP / Host', bg=BG_CARD, fg=TEXT_DIM,
                 font=('Segoe UI', 8, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        self._make_entry(srv_body, self.host_var, width=28).grid(
            row=1, column=0, columnspan=2, sticky='ew', ipady=4, pady=(2, 8))

        tk.Label(srv_body, text='Game Port', bg=BG_CARD, fg=TEXT_DIM,
                 font=('Segoe UI', 8, 'bold')).grid(row=2, column=0, sticky='w')
        tk.Label(srv_body, text='Relay Port', bg=BG_CARD, fg=TEXT_DIM,
                 font=('Segoe UI', 8, 'bold')).grid(row=2, column=1, sticky='w', padx=(8, 0))
        self._make_entry(srv_body, self.port_var, width=12).grid(
            row=3, column=0, sticky='ew', ipady=4, pady=(2, 8))
        self._make_entry(srv_body, self.relay_port_var, width=12).grid(
            row=3, column=1, sticky='ew', ipady=4, padx=(8, 0), pady=(2, 8))

        tk.Label(srv_body, text='Account Name', bg=BG_CARD, fg=TEXT_DIM,
                 font=('Segoe UI', 8, 'bold')).grid(row=4, column=0, sticky='w')
        tk.Label(srv_body, text='Clients (1-4)', bg=BG_CARD, fg=TEXT_DIM,
                 font=('Segoe UI', 8, 'bold')).grid(row=4, column=1, sticky='w', padx=(8, 0))
        self._make_entry(srv_body, self.account_var, width=16).grid(
            row=5, column=0, sticky='ew', ipady=4, pady=(2, 10))
        spin = tk.Spinbox(
            srv_body, from_=1, to=4, textvariable=self.clients_var, width=6,
            bg=BG_INPUT, fg=TEXT_MAIN, buttonbackground=BG_CARD_ALT,
            insertbackground=TEXT_MAIN, relief='flat', bd=0,
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            font=('Segoe UI', 9),
        )
        spin.grid(row=5, column=1, sticky='ew', ipady=4, padx=(8, 0), pady=(2, 10))

        btn_row = tk.Frame(srv_body, bg=BG_CARD)
        btn_row.grid(row=6, column=0, columnspan=2, sticky='ew')
        self._make_btn(btn_row, 'Test Server', self._probe_server_async,
                       bg=BG_CARD_ALT, hover=BORDER, font=('Segoe UI', 8, 'bold'), padx=10, pady=5).pack(
            side='left', fill='x', expand=True, padx=(0, 6))
        self.local_srv_btn = self._make_btn(
            btn_row, 'Start Local Server', self._toggle_local_server,
            bg=BG_CARD_ALT, hover=BORDER, font=('Segoe UI', 8, 'bold'), padx=10, pady=5)
        self.local_srv_btn.pack(side='right', fill='x', expand=True)

        self.conn_detail = tk.Label(srv_body, text='', bg=BG_CARD, fg=TEXT_MUTED,
                                    font=('Segoe UI', 8), wraplength=290, justify='left')
        self.conn_detail.grid(row=7, column=0, columnspan=2, sticky='w', pady=(8, 0))

        srv_body.columnconfigure(0, weight=3)
        srv_body.columnconfigure(1, weight=2)

        # Quick Patches summary card
        patch_card = tk.Frame(right_col, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        patch_card.pack(fill='both', expand=True)

        phdr = tk.Frame(patch_card, bg=BG_CARD_ALT, height=34)
        phdr.pack(fill='x')
        phdr.pack_propagate(False)
        tk.Label(phdr, text='PATCHES & HACKS', bg=BG_CARD_ALT, fg=GOLD,
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=12)

        pbody = tk.Frame(patch_card, bg=BG_CARD, padx=12, pady=10)
        pbody.pack(fill='both', expand=True)
        self.patch_summary_lbl = tk.Label(
            pbody, text='', bg=BG_CARD, fg=TEXT_MAIN,
            font=('Segoe UI', 9), justify='left', wraplength=290,
        )
        self.patch_summary_lbl.pack(anchor='w', pady=(0, 10))
        self._make_btn(
            pbody, 'Configure Patches & Hacks  →', lambda: self._switch_tab('patches'),
            bg=BG_CARD_ALT, hover=BORDER, fg=LINK_BLUE, font=('Segoe UI', 9, 'bold'), padx=12, pady=6,
        ).pack(fill='x', side='bottom')

    def _build_patches_page(self):
        card = tk.Frame(self.patches_page, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill='both', expand=True)

        hdr = tk.Frame(card, bg=BG_CARD_ALT, height=40)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(hdr, text='MODULAR PATCHES  (CLIENT HOOKS + SERVER OPTIONS)',
                 bg=BG_CARD_ALT, fg=GOLD, font=('Segoe UI', 9, 'bold')).pack(side='left', padx=12)
        self._make_btn(
            hdr, 'Reset Defaults', self._reset_defaults,
            bg=BG_CARD, hover=BORDER, fg=TEXT_DIM, font=('Segoe UI', 8, 'bold'), padx=10, pady=3,
        ).pack(side='right', padx=10, pady=6)

        self.patches_scroll = ScrollFrame(card, bg=BG_CARD)
        self.patches_scroll.pack(fill='both', expand=True, padx=6, pady=6)

        inner = self.patches_scroll.inner
        for cat_id, cat_title in options.CATEGORIES:
            keys = [k for k in options.OPTIONS if options.PATCH_META.get(k, ('', ''))[0] == cat_id]
            if not keys:
                continue
            tk.Label(inner, text=cat_title.upper(), bg=BG_CARD, fg=GOLD,
                     font=('Segoe UI', 8, 'bold')).pack(anchor='w', padx=10, pady=(10, 4))
            for key in keys:
                _, default, label, desc = options.OPTIONS[key]
                _, src_file = options.PATCH_META[key]
                var = tk.BooleanVar(value=default)
                var.trace_add('write', lambda *_: self._update_patch_summary())
                self._patch_vars[key] = var

                row_card = tk.Frame(inner, bg=BG_CARD_ALT, highlightbackground=BORDER, highlightthickness=1)
                row_card.pack(fill='x', padx=8, pady=3)

                top_row = tk.Frame(row_card, bg=BG_CARD_ALT)
                top_row.pack(fill='x', padx=10, pady=(6, 2))
                cb = tk.Checkbutton(
                    top_row, text=label, variable=var,
                    bg=BG_CARD_ALT, fg=TEXT_MAIN, selectcolor=BG_INPUT,
                    activebackground=BG_CARD_ALT, activeforeground=TEXT_MAIN,
                    font=('Segoe UI', 9, 'bold'), cursor='hand2',
                )
                cb.pack(side='left')
                tk.Label(top_row, text=src_file, bg=BG_INPUT, fg=LINK_BLUE,
                         font=('Consolas', 8), padx=6, pady=1).pack(side='right')

                tk.Label(row_card, text=desc, bg=BG_CARD_ALT, fg=TEXT_DIM,
                         font=('Segoe UI', 8), wraplength=820, justify='left').pack(
                    anchor='w', padx=(34, 10), pady=(0, 7))

    def _build_gm_page(self):
        """Build the searchable GM Commands console & live execution tab (visible when gm_mode=1)."""
        self._gm_commands = parse_gm_commands_doc()
        self._gm_players = []
        self._gm_selected_cmd = None

        card = tk.Frame(self.gm_page, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill='both', expand=True)

        # Header + Search + Target Player selector
        hdr = tk.Frame(card, bg=BG_CARD_ALT, height=44)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)
        tk.Label(hdr, text='GM COMMANDS', bg=BG_CARD_ALT, fg=GOLD,
                 font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(12, 10))

        self.gm_search_var = tk.StringVar()
        self.gm_search_var.trace_add('write', lambda *_: self._render_gm_list())
        tk.Label(hdr, text='Search:', bg=BG_CARD_ALT, fg=TEXT_DIM,
                 font=('Segoe UI', 8, 'bold')).pack(side='left', padx=(4, 4))
        search_entry = self._make_entry(hdr, self.gm_search_var, width=24)
        search_entry.pack(side='left', ipady=3, pady=8)

        self.gm_cat_var = tk.StringVar(value='All')
        cats = ['All', 'Live Executable'] + sorted({c['category'] for c in self._gm_commands})
        cat_menu = tk.OptionMenu(hdr, self.gm_cat_var, *cats, command=lambda *_: self._render_gm_list())
        cat_menu.configure(
            bg=BG_INPUT, fg=TEXT_MAIN, activebackground=BORDER, activeforeground=TEXT_MAIN,
            highlightthickness=1, highlightbackground=BORDER, relief='flat', bd=0,
            font=('Segoe UI', 8), cursor='hand2',
        )
        cat_menu['menu'].configure(bg=BG_CARD_ALT, fg=TEXT_MAIN, activebackground=ACCENT, activeforeground='white')
        cat_menu.pack(side='left', padx=(8, 4), pady=8)

        self._make_btn(
            hdr, 'Refresh Players', self._refresh_gm_players_async,
            bg=BG_CARD, hover=BORDER, fg=TEXT_DIM, font=('Segoe UI', 8, 'bold'), padx=8, pady=3,
        ).pack(side='right', padx=(4, 10), pady=8)

        self.gm_player_var = tk.StringVar(value='Auto (active character)')
        self.gm_player_menu = tk.OptionMenu(hdr, self.gm_player_var, 'Auto (active character)')
        self.gm_player_menu.configure(
            bg=BG_INPUT, fg=TEXT_MAIN, activebackground=BORDER, activeforeground=TEXT_MAIN,
            highlightthickness=1, highlightbackground=BORDER, relief='flat', bd=0,
            font=('Segoe UI', 8), cursor='hand2',
        )
        self.gm_player_menu['menu'].configure(bg=BG_CARD_ALT, fg=TEXT_MAIN, activebackground=ACCENT, activeforeground='white')
        self.gm_player_menu.pack(side='right', padx=(4, 4), pady=8)
        tk.Label(hdr, text='Target:', bg=BG_CARD_ALT, fg=TEXT_DIM,
                 font=('Segoe UI', 8, 'bold')).pack(side='right', padx=(8, 2))

        # Main split: Left = command list, Right = command details
        split = tk.Frame(card, bg=BG_CARD)
        split.pack(fill='both', expand=True, padx=8, pady=(8, 6))

        list_wrap = tk.Frame(split, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        list_wrap.pack(side='left', fill='both', expand=True, padx=(0, 8))

        self.gm_listbox = tk.Listbox(
            list_wrap, bg=BG_CARD_ALT, fg=TEXT_MAIN,
            selectbackground=ACCENT, selectforeground='white',
            activestyle='none', relief='flat', bd=0, highlightthickness=0,
            font=('Consolas', 9),
        )
        gm_sb = ttk.Scrollbar(list_wrap, orient='vertical', command=self.gm_listbox.yview,
                              style='Dark.Vertical.TScrollbar')
        self.gm_listbox.configure(yscrollcommand=gm_sb.set)
        self.gm_listbox.pack(side='left', fill='both', expand=True)
        gm_sb.pack(side='right', fill='y')
        self.gm_listbox.bind('<<ListboxSelect>>', self._on_gm_select)
        self.gm_listbox.bind('<Double-Button-1>', lambda e: self._fill_gm_example())

        detail_card = tk.Frame(split, bg=BG_CARD_ALT, width=320,
                               highlightbackground=BORDER, highlightthickness=1)
        detail_card.pack(side='right', fill='y')
        detail_card.pack_propagate(False)

        self.gm_detail_title = tk.Label(
            detail_card, text='Select a GM command', bg=BG_CARD_ALT, fg=GOLD,
            font=('Consolas', 11, 'bold'), anchor='w',
        )
        self.gm_detail_title.pack(fill='x', padx=12, pady=(12, 4))

        self.gm_detail_badge = tk.Label(
            detail_card, text='', bg=BG_CARD_ALT, fg=TEXT_DIM,
            font=('Segoe UI', 8, 'bold'), anchor='w',
        )
        self.gm_detail_badge.pack(fill='x', padx=12, pady=(0, 8))

        self.gm_detail_body = tk.Label(
            detail_card,
            text='Search any command on the left.\n\n'
                 '• [LIVE] commands execute directly on the online character from this launcher.\n'
                 '• [CHAT] commands are client-side cheats — click Copy %cmd and paste in game chat (Enter) or press Ctrl+Shift+C.',
            bg=BG_CARD_ALT, fg=TEXT_MAIN, font=('Segoe UI', 9),
            justify='left', wraplength=294, anchor='nw',
        )
        self.gm_detail_body.pack(fill='both', expand=True, padx=12, pady=(0, 8))

        self.gm_count_lbl = tk.Label(
            detail_card, text='', bg=BG_CARD_ALT, fg=TEXT_MUTED,
            font=('Segoe UI', 8), anchor='w',
        )
        self.gm_count_lbl.pack(fill='x', padx=12, pady=(0, 10))

        # Bottom execution bar
        tk.Frame(card, bg=BORDER, height=1).pack(fill='x')
        exec_bar = tk.Frame(card, bg=BG_CARD_ALT, padx=10, pady=8)
        exec_bar.pack(fill='x')

        tk.Label(exec_bar, text='%', bg=BG_CARD_ALT, fg=GOLD,
                 font=('Consolas', 10, 'bold')).pack(side='left', padx=(0, 4))
        self.gm_cmd_var = tk.StringVar()
        cmd_entry = self._make_entry(exec_bar, self.gm_cmd_var, width=42)
        cmd_entry.pack(side='left', fill='x', expand=True, ipady=4, padx=(0, 8))
        cmd_entry.bind('<Return>', lambda e: self._send_gm_command())

        self._make_btn(
            exec_bar, 'Copy %cmd', self._copy_gm_command,
            bg=BG_CARD, hover=BORDER, fg=TEXT_DIM, font=('Segoe UI', 8, 'bold'), padx=10, pady=5,
        ).pack(side='left', padx=(0, 6))
        self.gm_send_btn = self._make_btn(
            exec_bar, '▶ Send to Game', self._send_gm_command,
            bg=ACCENT, hover=ACCENT_HOVER, fg='white', font=('Segoe UI', 8, 'bold'), padx=14, pady=5,
        )
        self.gm_send_btn.pack(side='left')

        self.gm_result_lbl = tk.Label(
            card, text='Ready — start local server & log in a character to execute [LIVE] commands.',
            bg=BG_CARD, fg=TEXT_MUTED, font=('Segoe UI', 8), anchor='w', padx=12, pady=4,
        )
        self.gm_result_lbl.pack(fill='x')

        self._gm_filtered = []
        self._render_gm_list()

    def _render_gm_list(self):
        q = (self.gm_search_var.get() or '').strip().lower()
        cat = self.gm_cat_var.get()
        filtered = []
        for c in self._gm_commands:
            if cat == 'Live Executable' and not c['live']:
                continue
            elif cat not in ('All', 'Live Executable') and c['category'] != cat:
                continue
            if q:
                hay = f"{c['name']} {c['description']} {c['params']} {c['category']}".lower()
                if q not in hay:
                    continue
            filtered.append(c)
        self._gm_filtered = filtered
        self.gm_listbox.delete(0, 'end')
        for c in filtered:
            tag = '[LIVE]' if c['live'] else '[CHAT]'
            self.gm_listbox.insert('end', f" {tag} {c['name']:<18}  {c['description']}")
        live_cnt = sum(1 for c in filtered if c['live'])
        self.gm_count_lbl.config(text=f'{len(filtered)} commands shown ({live_cnt} live-executable)')

    def _on_gm_select(self, _event=None):
        sel = self.gm_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._gm_filtered):
            return
        c = self._gm_filtered[idx]
        self._gm_selected_cmd = c
        self.gm_detail_title.config(text=f"%{c['name']}")
        if c['live']:
            self.gm_detail_badge.config(text=f"● SERVER LIVE  •  {c['category']}", fg=OK_GREEN)
        else:
            self.gm_detail_badge.config(text=f"● IN-GAME CHAT ONLY  •  {c['category']}", fg=WARN_AMBER)
        body = (
            f"{c['description']}\n\n"
            f"Parameters:\n  {c['params']}\n\n"
            f"Example:\n  {c['example']}"
        )
        self.gm_detail_body.config(text=body)
        self._fill_gm_example()

    def _fill_gm_example(self):
        c = self._gm_selected_cmd
        if not c:
            return
        ex = c['example'].split('—')[0].split('/')[0].strip()
        if ex.startswith('%'):
            ex = ex[1:].strip()
        self.gm_cmd_var.set(ex if ex else c['name'])

    def _refresh_gm_players_async(self):
        def worker():
            resp = query_gm_bridge({'action': 'list_players'})
            self.after(0, lambda: self._apply_gm_players(resp))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_gm_players(self, resp):
        menu = self.gm_player_menu['menu']
        menu.delete(0, 'end')
        self._gm_players = resp.get('players', []) if resp.get('ok') else []
        choices = ['Auto (active character)'] + [
            f"{p['name']} (Lv.{p['level']}, #{p['char_id']})" for p in self._gm_players
        ]
        for ch in choices:
            menu.add_command(label=ch, command=lambda v=ch: self.gm_player_var.set(v))
        if self.gm_player_var.get() not in choices:
            self.gm_player_var.set(choices[0])
        if resp.get('offline'):
            self.gm_result_lbl.config(text='Local server offline — start server to execute [LIVE] commands.', fg=TEXT_MUTED)
        elif not self._gm_players:
            self.gm_result_lbl.config(text='Server online — log in a character to execute [LIVE] commands.', fg=WARN_AMBER)
        else:
            self.gm_result_lbl.config(text=f'Server online — {len(self._gm_players)} character(s) connected.', fg=OK_GREEN)

    def _selected_gm_char_id(self):
        label = self.gm_player_var.get()
        m = re.search(r'#(\d+)\)$', label)
        return int(m.group(1)) if m else None

    def _copy_gm_command(self):
        cmd = (self.gm_cmd_var.get() or '').strip()
        if not cmd:
            return
        text = cmd if cmd.startswith('%') else f'%{cmd}'
        self.clipboard_clear()
        self.clipboard_append(text)
        self.gm_result_lbl.config(text=f'Copied "{text}" to clipboard (paste in game chat).', fg=LINK_BLUE)

    def _send_gm_command(self):
        cmd = (self.gm_cmd_var.get() or '').strip()
        if not cmd:
            return
        char_id = self._selected_gm_char_id()
        self.gm_send_btn.config(state='disabled')
        self.gm_result_lbl.config(text=f'Executing %{cmd}...', fg=TEXT_DIM)

        def worker():
            resp = query_gm_bridge({'action': 'exec', 'command': cmd, 'char_id': char_id})
            self.after(0, lambda: self._on_gm_result(cmd, resp))

        threading.Thread(target=worker, daemon=True).start()

    def _on_gm_result(self, cmd, resp):
        self.gm_send_btn.config(state='normal')
        msg = resp.get('message', 'Done.')
        if resp.get('ok'):
            self.gm_result_lbl.config(text=f'✓ {msg}', fg=OK_GREEN)
            self._refresh_gm_players_async()
        elif resp.get('client_only'):
            text = cmd if cmd.startswith('%') else f'%{cmd}'
            self.clipboard_clear()
            self.clipboard_append(text)
            self.gm_result_lbl.config(text=f'Copied "{text}" — {msg}', fg=WARN_AMBER)
        else:
            self.gm_result_lbl.config(text=f'✗ {msg}', fg=ERR_RED)

    # ---- Footer (Always-visible Bifrost-style Play Bar) -----------------

    def _build_footer(self):
        tk.Frame(self, bg=BORDER, height=1).pack(fill='x')
        footer = tk.Frame(self, bg=BG_HEADER, height=62)
        footer.pack(fill='x')
        footer.pack_propagate(False)

        right = tk.Frame(footer, bg=BG_HEADER)
        right.pack(side='right', padx=16)

        try:
            cfg_display = options.OPTIONS_PATH.relative_to(ROOT).as_posix()
        except ValueError:
            cfg_display = str(options.OPTIONS_PATH)
        self.status_var = tk.StringVar(value=f'Config: {cfg_display}')
        tk.Label(footer, textvariable=self.status_var, bg=BG_HEADER, fg=TEXT_DIM,
                 font=('Segoe UI', 8), anchor='w').pack(side='left', padx=16, fill='x', expand=True)

        self._make_btn(right, 'Save Config', self._save_config,
                       bg=BG_CARD_ALT, hover=BORDER, padx=12, pady=8).pack(side='left', padx=(0, 8))
        self.build_btn = None
        if not IS_FROZEN and HOOK_BUILD_BAT.is_file():
            self.build_btn = self._make_btn(right, 'Build & Deploy Hook', self._build_hook,
                                            bg=BG_CARD_ALT, hover=BORDER, padx=12, pady=8)
            self.build_btn.pack(side='left', padx=(0, 12))

        self.play_btn = self._make_btn(
            right, '▶  PLAY DARK BLOOD', self._launch,
            bg=ACCENT, hover=ACCENT_HOVER, fg='white',
            font=('Segoe UI', 10, 'bold'), padx=22, pady=9,
        )
        self.play_btn.pack(side='left')

    # ---- Data loading & actions -----------------------------------------

    def _load_values(self):
        cfg = options.read_all()
        self.host_var.set(cfg['network']['host'])
        self.port_var.set(str(cfg['network']['port']))
        self.relay_port_var.set(str(cfg['network']['relay_port']))
        self.account_var.set(cfg['launcher']['account'])
        self.clients_var.set(cfg['launcher']['clients'])
        for key, var in self._patch_vars.items():
            var.set(bool(cfg['options'].get(key, options.OPTIONS[key][1])))
        self._update_patch_summary()
        self._sync_gm_tab_visibility()

    def _update_patch_summary(self):
        enabled = [options.OPTIONS[k][2] for k, v in self._patch_vars.items() if v.get()]
        total = len(self._patch_vars)
        preview = '\n'.join(f'• {name}' for name in enabled[:5])
        if len(enabled) > 5:
            preview += f'\n• +{len(enabled) - 5} more...'
        if not preview:
            preview = 'No patches enabled.'
        self.patch_summary_lbl.config(text=f'{len(enabled)} / {total} enabled\n\n{preview}')
        self._sync_gm_tab_visibility()

    def _refresh_commits(self):
        for child in self.news_scroll.inner.winfo_children():
            child.destroy()
        for child in self.news_pager.winfo_children():
            child.destroy()
        tk.Label(self.news_scroll.inner, text='Loading release changelog...', bg=BG_CARD, fg=TEXT_MUTED,
                 font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=12)

        def worker():
            commits, source = fetch_recent_commits(limit=None)
            self.after(0, lambda: self._render_commits(commits, source))
        threading.Thread(target=worker, daemon=True).start()

    def _render_commits(self, commits, source):
        self._all_commits = list(commits or [])
        self._commits_page = 1
        self.news_source_lbl.config(text=f'({source}, {len(self._all_commits)})' if self._all_commits else f'({source})')
        if not self._all_commits:
            for child in self.news_scroll.inner.winfo_children():
                child.destroy()
            for child in self.news_pager.winfo_children():
                child.destroy()
            tk.Label(self.news_scroll.inner, text=f'Could not load commits ({source}).',
                     bg=BG_CARD, fg=ERR_RED, font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=12)
            return
        self._show_commits_page(1)

    def _show_commits_page(self, page: int):
        total = len(self._all_commits)
        psize = self._commits_page_size
        total_pages = max(1, (total + psize - 1) // psize)
        page = max(1, min(page, total_pages))
        self._commits_page = page

        # Build the next page off-screen and swap atomically to prevent Win32 light-theme flash.
        new_inner = self.news_scroll.new_offscreen_inner()
        start = (page - 1) * psize
        for c in self._all_commits[start:start + psize]:
            ctype, scope, title = parse_commit_prefix(c['subject'])
            bg_pill, fg_pill = COMMIT_BADGES.get(ctype, ('#2b3040', '#a6afc4'))

            item = tk.Frame(new_inner, bg=BG_CARD_ALT,
                            highlightbackground=BORDER, highlightthickness=1)
            item.pack(fill='x', padx=6, pady=4)

            top = tk.Frame(item, bg=BG_CARD_ALT)
            top.pack(fill='x', padx=10, pady=(7, 2))

            tag_text = f'{ctype.upper()}' + (f'({scope})' if scope else '')
            tk.Label(top, text=tag_text, bg=bg_pill, fg=fg_pill,
                     font=('Consolas', 7, 'bold'), padx=6, pady=1).pack(side='left', padx=(0, 8))

            sha_lbl = tk.Label(top, text=c['short'], bg=BG_CARD_ALT, fg=LINK_BLUE,
                               font=('Consolas', 8, 'underline'), cursor='hand2')
            sha_lbl.pack(side='right')
            sha_lbl.bind('<Button-1>', lambda e, s=c['sha']: webbrowser.open(f'{REPO_URL}/commit/{s}'))

            tk.Label(top, text=c['date'], bg=BG_CARD_ALT, fg=TEXT_MUTED,
                     font=('Segoe UI', 8)).pack(side='right', padx=(0, 8))

            tk.Label(item, text=title, bg=BG_CARD_ALT, fg=TEXT_MAIN,
                     font=('Segoe UI', 9, 'bold'), wraplength=540, justify='left').pack(
                anchor='w', padx=10, pady=(1, 2))
            tk.Label(item, text=f'by {c["author"]}', bg=BG_CARD_ALT, fg=TEXT_MUTED,
                     font=('Segoe UI', 8)).pack(anchor='w', padx=10, pady=(0, 6))

        self.news_scroll.swap_inner(new_inner)
        self._render_pager(page, total_pages, total)

    def _render_pager(self, page: int, total_pages: int, total_items: int):
        new_bar = tk.Frame(self.news_pager, bg=BG_CARD_ALT)
        left_bar = tk.Frame(new_bar, bg=BG_CARD_ALT)
        left_bar.pack(side='left', padx=8, pady=4)

        def add_tab(label, target_page, active=False, disabled=False):
            bg = ACCENT if active else BG_CARD
            fg = 'white' if active else (TEXT_MUTED if disabled else TEXT_DIM)
            btn = tk.Label(
                left_bar, text=label, bg=bg, fg=fg,
                cursor='arrow' if disabled else 'hand2',
                font=('Segoe UI', 8, 'bold'), padx=8, pady=3,
            )
            if not disabled:
                btn.bind('<Button-1>', lambda e, p=target_page: self._show_commits_page(p))
                if not active:
                    btn.bind('<Enter>', lambda e, b=btn: b.configure(bg=BORDER, fg=TEXT_MAIN))
                    btn.bind('<Leave>', lambda e, b=btn: b.configure(bg=BG_CARD, fg=TEXT_DIM))
            btn.pack(side='left', padx=2)

        add_tab('‹', page - 1, disabled=(page <= 1))

        # Build compact numbered tab list: 1 ... page-1 [page] page+1 ... total_pages
        if total_pages <= 7:
            pages = list(range(1, total_pages + 1))
        else:
            pages = [1]
            lo = max(2, page - 1)
            hi = min(total_pages - 1, page + 1)
            if lo > 2:
                pages.append(None)
            pages.extend(range(lo, hi + 1))
            if hi < total_pages - 1:
                pages.append(None)
            pages.append(total_pages)

        for p in pages:
            if p is None:
                tk.Label(left_bar, text='…', bg=BG_CARD_ALT, fg=TEXT_MUTED,
                         font=('Segoe UI', 8)).pack(side='left', padx=2)
            else:
                add_tab(str(p), p, active=(p == page))

        add_tab('›', page + 1, disabled=(page >= total_pages))

        tk.Label(
            new_bar, text=f'Page {page}/{total_pages}  •  {total_items} changes',
            bg=BG_CARD_ALT, fg=TEXT_MUTED, font=('Segoe UI', 8),
        ).pack(side='right', padx=10)

        old_children = list(self.news_pager.winfo_children())
        new_bar.update_idletasks()
        new_bar.pack(fill='both', expand=True)
        for child in old_children:
            child.destroy()

    def _collect_and_save(self):
        net = options.validate_network(
            self.host_var.get(), self.port_var.get(), self.relay_port_var.get())
        launcher = {
            'account': self.account_var.get().strip() or options.LAUNCHER_DEFAULTS['account'],
            'clients': self.clients_var.get(),
        }
        values = {key: var.get() for key, var in self._patch_vars.items()}
        options.write_all(values=values, network=net, launcher=launcher)
        return net, launcher, values

    def _save_config(self):
        try:
            net, _, _ = self._collect_and_save()
        except ValueError as exc:
            messagebox.showerror('Invalid Configuration', str(exc))
            return False
        self.status_var.set(
            f'Saved ({net["host"]}:{net["port"]}, relay {net["relay_port"]}) -> {options.OPTIONS_PATH}')
        return True

    def _reset_defaults(self):
        self.host_var.set(options.NETWORK_DEFAULTS['host'])
        self.port_var.set(str(options.NETWORK_DEFAULTS['port']))
        self.relay_port_var.set(str(options.NETWORK_DEFAULTS['relay_port']))
        self.account_var.set(options.LAUNCHER_DEFAULTS['account'])
        self.clients_var.set(options.LAUNCHER_DEFAULTS['clients'])
        for key, (_, default, _, _) in options.OPTIONS.items():
            self._patch_vars[key].set(default)
        self.status_var.set('Defaults restored (click Save Config or PLAY to write).')

    def _refresh_client_badge(self):
        def check():
            if not CLIENT_EXE.exists():
                text, color = 'Client Missing  •  Click to Setup', ERR_RED
            elif not CLIENT_DLL.exists():
                text, color = 'Client OK  •  Click to Deploy Hook', WARN_AMBER
            else:
                try:
                    ok_hash = (gamectl.client_hash() == gamectl.CLIENT_SHA256)
                    text = 'Client Verified  •  Hook Ready' if ok_hash else 'Client Hash Mismatch'
                    color = OK_GREEN if ok_hash else WARN_AMBER
                except Exception:
                    text, color = 'Client Found  •  Hook Ready', OK_GREEN
            self.after(0, lambda: self.client_badge.config(text=text, fg=color))
        threading.Thread(target=check, daemon=True).start()

    def _probe_server_async(self):
        try:
            net = options.validate_network(
                self.host_var.get(), self.port_var.get(), self.relay_port_var.get())
        except ValueError as exc:
            self.conn_detail.config(text=f'Invalid address: {exc}', fg=ERR_RED)
            return
        self.srv_pill.config(text=f'● Probing {net["host"]}:{net["port"]}...', fg=TEXT_DIM)

        def run():
            ok, msg = probe_tcp(net['host'], net['port'])
            _, relay_msg = probe_tcp(net['host'], net['relay_port'], timeout=0.8)
            pill_txt = f'● {net["host"]}:{net["port"]}  {msg}'
            pill_fg = OK_GREEN if ok else ERR_RED
            detail = f'Game :{net["port"]} {msg}  |  Relay :{net["relay_port"]} {relay_msg}'
            self.after(0, lambda: (
                self.srv_pill.config(text=pill_txt, fg=pill_fg),
                self.conn_detail.config(text=detail, fg=OK_GREEN if ok else TEXT_MUTED),
            ))
        threading.Thread(target=run, daemon=True).start()

    def _toggle_local_server(self):
        if self._server_proc is not None and self._server_proc.poll() is None:
            self._server_proc.terminate()
            self._server_proc = None
            self.local_srv_btn.config(text='Start Local Server')
            self.conn_detail.config(text='Local server stopped.', fg=TEXT_MUTED)
            self.after(400, self._probe_server_async)
            return

        if not gamectl._port_free():
            self.conn_detail.config(text='Server is already listening on 127.0.0.1:9400.', fg=OK_GREEN)
            self._probe_server_async()
            return

        flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        if IS_FROZEN:
            flags |= getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            server_cmd = [sys.executable, '--server']
        else:
            server_cmd = [sys.executable, str(ROOT / 'run_server.py')]
        self._server_proc = subprocess.Popen(
            server_cmd,
            cwd=str(ROOT), creationflags=flags,
        )
        self.local_srv_btn.config(text='Stop Local Server')
        self.conn_detail.config(text=f'Local server started (PID {self._server_proc.pid}).', fg=OK_GREEN)
        self.after(900, self._probe_server_async)

    def _setup_client_dialog(self):
        chosen = filedialog.askopenfilename(
            title='Select DarkBlood.exe (Steam build 1.6.5#0)',
            filetypes=[('DarkBlood.exe', 'DarkBlood.exe'), ('Executables', '*.exe')],
        )
        if not chosen:
            return
        self.status_var.set('Staging client folder and verifying SHA-256...')

        def run():
            try:
                stage_client_folder(Path(chosen))
                self.after(0, lambda: (
                    self._reload_header_icon(),
                    self.status_var.set(f'Client staged in {CLIENT_DIR}'),
                    self._refresh_client_badge(),
                ))
            except Exception as exc:
                self.after(0, lambda: (
                    self.status_var.set(f'Client setup failed: {exc}'),
                    messagebox.showerror('Client Setup Failed', str(exc)),
                ))

        threading.Thread(target=run, daemon=True).start()

    def _build_hook(self):
        if not HOOK_BUILD_BAT.exists():
            # Portable release install: deploy prebuilt client_hook/steam_api.dll directly
            if HOOK_BUILT_DLL.is_file():
                try:
                    CLIENT_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(HOOK_BUILT_DLL, CLIENT_DLL)
                    self._finish_build(True, f'Deployed prebuilt {CLIENT_DLL.name}')
                except OSError as exc:
                    self._finish_build(False, f'Deploy failed (close running game first): {exc}')
                return
            messagebox.showerror('Build Hook', f'Missing build script: {HOOK_BUILD_BAT}')
            return
        self.build_btn.config(state='disabled')
        self.status_var.set('Building modular steam_api.dll...')

        def run():
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            proc = subprocess.run(
                ['cmd.exe', '/c', str(HOOK_BUILD_BAT)],
                cwd=str(HOOK_BUILD_BAT.parent),
                capture_output=True, text=True, creationflags=flags,
            )
            if proc.returncode != 0:
                lines = (proc.stderr or proc.stdout or 'Build failed').strip().splitlines()
                err = lines[-1] if lines else 'Build failed'
                self.after(0, lambda: self._finish_build(False, f'Build failed: {err}'))
                return
            try:
                shutil.copy2(HOOK_BUILT_DLL, CLIENT_DLL)
            except OSError as exc:
                self.after(0, lambda: self._finish_build(
                    False, f'Built DLL, but copy failed (close running game first): {exc}'))
                return
            self.after(0, lambda: self._finish_build(True, f'Built and deployed {CLIENT_DLL}'))

        threading.Thread(target=run, daemon=True).start()

    def _finish_build(self, ok, message):
        if self.build_btn is not None:
            self.build_btn.config(state='normal')
        self.status_var.set(message)
        if ok:
            self._refresh_client_badge()

    def _check_updates_async(self):
        self.update_btn.config(state='disabled', text='Checking...')

        def run():
            st = updater.check_for_updates(ROOT, releases_only=True)
            self.after(0, lambda: self._apply_update_status(st))

        threading.Thread(target=run, daemon=True).start()

    def _apply_update_status(self, st):
        self._update_status = st
        self.update_btn.config(state='normal')
        if st.error:
            self.update_btn.config(text='Check Releases', bg=BG_CARD, fg=TEXT_MUTED)
            return
        if st.up_to_date:
            self.update_btn.config(text=f'Up to date ({st.short_current})', bg=BG_CARD, fg=OK_GREEN)
            return
        self.update_btn.config(text=f'⬆ Release {st.short_remote}', bg=ACCENT, fg='white')
        self.status_var.set(
            f'New release available on GitHub: {st.short_current} -> {st.short_remote}'
        )

    def _on_update_click(self):
        st = self._update_status
        if st is None or st.up_to_date or st.error:
            self._check_updates_async()
            return
        msg = (
            f'Update Dark Blood Server Emulator from {st.short_current} to published release {st.short_remote}?\n\n'
            'User data (data/, research/, darkblood_options.ini) is preserved.'
        )
        if not messagebox.askyesno('Update to Published Release', msg):
            return
        # Stop local server if started by this launcher so updated code loads cleanly
        if self._server_proc is not None and self._server_proc.poll() is None:
            self._server_proc.terminate()
            self._server_proc = None
            self.local_srv_btn.config(text='Start Local Server')

        self.update_btn.config(state='disabled', text='Updating...')
        self.status_var.set(f'Downloading release {st.short_remote} from GitHub...')

        def run():
            res = updater.apply_update(ROOT, releases_only=True)
            self.after(0, lambda: self._finish_update(res))

        threading.Thread(target=run, daemon=True).start()

    def _finish_update(self, res):
        self.update_btn.config(state='normal')
        self.status_var.set(res.message)
        if not res.ok:
            self.update_btn.config(text='Retry Update', bg=ACCENT, fg='white')
            messagebox.showerror('Update Failed', res.message)
            return
        ver_label = res.new_sha if res.new_sha.startswith('v') else res.new_sha[:7]
        self.update_btn.config(text=f'Up to date ({ver_label})', bg=BG_CARD, fg=OK_GREEN)
        self._update_status = updater.UpdateStatus(
            mode=res.mode, current_sha=res.new_sha, remote_sha=res.new_sha, up_to_date=True,
        )
        self._refresh_commits()
        if res.hook_changed and not IS_FROZEN and HOOK_BUILD_BAT.exists():
            self._build_hook()
        if res.launcher_changed:
            if messagebox.askyesno('Launcher Updated',
                                   f'{res.message}\n\nThe launcher itself was updated. Restart now?'):
                restart_cmd = [sys.executable] if IS_FROZEN else [sys.executable, str(Path(__file__).resolve())]
                subprocess.Popen(restart_cmd, cwd=str(ROOT))
                self.destroy()
                return
        messagebox.showinfo('Update Complete', res.message)

    def _launch(self):
        if not self._save_config():
            return
        account = self.account_var.get().strip() or 'OfflinePlayer'
        count = max(1, min(4, self.clients_var.get()))
        self.status_var.set(f'Launching {count} client(s) as {account}...')

        def run():
            try:
                launched = launch_clients(account, count)
                desc = ', '.join(f'{acc} (PID {pid})' for pid, acc in launched)
                msg = f'Launched: {desc}'
            except Exception as exc:
                msg = f'Launch failed: {exc}'
            self.after(0, lambda: self.status_var.set(msg))

        threading.Thread(target=run, daemon=True).start()

    def _on_close(self):
        if self._server_proc is not None and self._server_proc.poll() is None:
            if messagebox.askyesno('Local Server Running', 'Stop the local server started by this launcher?'):
                self._server_proc.terminate()
        if self._temp_ico_path:
            try:
                os.unlink(self._temp_ico_path)
            except OSError:
                pass
        self.destroy()


def _self_check() -> int:
    """Verify bundled server, tooling, and GUI modules import cleanly (used by release CI)."""
    import darkblood.__main__  # noqa: F401
    import darkblood.frontend.server  # noqa: F401
    import darkblood.games.session  # noqa: F401
    import gamectl  # noqa: F401
    import multibox  # noqa: F401
    import updater  # noqa: F401
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if '--check' in args:
        return _self_check()
    if '--server' in args:
        from darkblood.__main__ import main as server_main
        server_main()
        return 0
    updater.cleanup_old_binaries(ROOT)
    app = DarkBloodLauncher()
    app.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
