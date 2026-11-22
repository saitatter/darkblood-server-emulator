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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

from darkblood.core import options  # noqa: E402
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


def fetch_recent_commits(limit=25):
    """Return list of dicts {sha, short, date, author, subject} from local git or GitHub."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        proc = subprocess.run(
            ['git', 'log', f'-n{limit}', '--pretty=format:%H\x1f%h\x1f%ad\x1f%an\x1f%ae\x1f%s', '--date=short'],
            cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=5, creationflags=flags,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            commits = []
            for line in proc.stdout.splitlines():
                parts = line.split('\x1f')
                if len(parts) == 6:
                    commits.append({
                        'sha': parts[0], 'short': parts[1],
                        'date': parts[2],
                        'author': _resolve_github_username(parts[3], parts[4]),
                        'subject': parts[5],
                    })
            if commits:
                return commits, 'local git'
    except Exception:
        pass

    # Fallback: GitHub REST API
    try:
        req = urllib.request.Request(
            GITHUB_COMMITS_API, headers={'User-Agent': 'DarkBlood-Launcher'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        commits = []
        for item in data[:limit]:
            sha = item.get('sha', '')
            c = item.get('commit', {})
            gh_author = item.get('author') or {}
            c_author = c.get('author') or {}
            author = _resolve_github_username(
                c_author.get('name', ''),
                c_author.get('email', ''),
                gh_author.get('login', ''),
            )
            date = (c_author.get('date', '') or '')[:10]
            subject = (c.get('message', '') or '').splitlines()[0]
            commits.append({
                'sha': sha, 'short': sha[:7],
                'date': date, 'author': author, 'subject': subject,
            })
        return commits, 'GitHub'
    except Exception as exc:
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


def launch_clients(account, count=1):
    """Launch 1..4 DarkBlood.exe instances directly against the configured server."""
    if not CLIENT_EXE.exists():
        raise RuntimeError(f'Client executable not found: {CLIENT_EXE}')
    if not CLIENT_DLL.exists():
        raise RuntimeError(f'Hook DLL not found: {CLIENT_DLL} (click "Build Hook")')

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
    for idx, acc in enumerate(accounts):
        env = os.environ.copy()
        env['__COMPAT_LAYER'] = 'RunAsInvoker'
        env['DARKBLOOD_ACCOUNT'] = acc
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
    """Dark-themed vertical scrollable container."""
    def __init__(self, parent, bg=BG_CARD, **kwargs):
        super().__init__(parent, bg=bg, **kwargs)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                       style='Dark.Vertical.TScrollbar')
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')

        # Bind wheel only while pointer is over this scroll area
        self.canvas.bind('<Enter>', self._bind_wheel)
        self.canvas.bind('<Leave>', self._unbind_wheel)
        self.inner.bind('<Enter>', self._bind_wheel)
        self.inner.bind('<Leave>', self._unbind_wheel)

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
        ico_bytes = extract_client_icon_bytes(CLIENT_EXE)
        if not ico_bytes:
            return
        try:
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
            tk.Label(left, image=self._header_icon_img, bg=BG_HEADER).pack(side='left', padx=(0, 12))
        else:
            badge = tk.Label(left, text='DB', bg=ACCENT, fg='white',
                             font=('Segoe UI', 14, 'bold'), width=3, height=1)
            badge.pack(side='left', padx=(0, 12))

        title_box = tk.Frame(left, bg=BG_HEADER)
        title_box.pack(side='left')
        tk.Label(title_box, text='DARK BLOOD ONLINE', bg=BG_HEADER, fg=TEXT_MAIN,
                 font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        tk.Label(title_box, text='OFFLINE SERVER EMULATOR  •  CUSTOM LAUNCHER',
                 bg=BG_HEADER, fg=GOLD, font=('Segoe UI', 8, 'bold')).pack(anchor='w')

        # Center/Right Navigation Tabs
        nav = tk.Frame(header, bg=BG_HEADER)
        nav.pack(side='left', padx=(34, 0), fill='y')
        self._tab_btns = {}
        for tab_id, label in (('news', 'NEWS & SERVER'), ('patches', 'PATCHES & HACKS')):
            b = tk.Button(
                nav, text=label, command=lambda t=tab_id: self._switch_tab(t),
                bg=BG_HEADER, fg=TEXT_DIM, activebackground=BG_HEADER, activeforeground=TEXT_MAIN,
                relief='flat', bd=0, cursor='hand2', font=('Segoe UI', 9, 'bold'), padx=14,
            )
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
        self._active_tab = tab_id
        for tid, btn in self._tab_btns.items():
            if tid == tab_id:
                btn.configure(fg=TEXT_MAIN, bg=BG_CARD)
            else:
                btn.configure(fg=TEXT_DIM, bg=BG_HEADER)
        if tab_id == 'news':
            self.patches_page.pack_forget()
            self.news_page.pack(fill='both', expand=True)
        else:
            self.news_page.pack_forget()
            self.patches_page.pack(fill='both', expand=True)

    # ---- Body (News & Server Page + Patches Page) -----------------------

    def _build_body(self):
        self.body = tk.Frame(self, bg=BG_DARK)
        self.body.pack(fill='both', expand=True, padx=16, pady=14)

        self.news_page = tk.Frame(self.body, bg=BG_DARK)
        self.patches_page = tk.Frame(self.body, bg=BG_DARK)

        self._build_news_page()
        self._build_patches_page()

    def _build_news_page(self):
        # Two-column Bifrost layout: Left = News/Commits feed, Right = Server & Account panel
        left_card = tk.Frame(self.news_page, bg=BG_CARD, highlightbackground=BORDER, highlightthickness=1)
        left_card.pack(side='left', fill='both', expand=True, padx=(0, 12))

        news_hdr = tk.Frame(left_card, bg=BG_CARD_ALT, height=38)
        news_hdr.pack(fill='x')
        news_hdr.pack_propagate(False)
        tk.Label(news_hdr, text='LATEST REPOSITORY NEWS (COMMITS)', bg=BG_CARD_ALT, fg=GOLD,
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
        self.news_scroll.pack(fill='both', expand=True, padx=4, pady=4)

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

    def _update_patch_summary(self):
        enabled = [options.OPTIONS[k][2] for k, v in self._patch_vars.items() if v.get()]
        total = len(self._patch_vars)
        preview = '\n'.join(f'• {name}' for name in enabled[:5])
        if len(enabled) > 5:
            preview += f'\n• +{len(enabled) - 5} more...'
        if not preview:
            preview = 'No patches enabled.'
        self.patch_summary_lbl.config(text=f'{len(enabled)} / {total} enabled\n\n{preview}')

    def _refresh_commits(self):
        for child in self.news_scroll.inner.winfo_children():
            child.destroy()
        tk.Label(self.news_scroll.inner, text='Loading latest commits...', bg=BG_CARD, fg=TEXT_MUTED,
                 font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=12)

        def worker():
            commits, source = fetch_recent_commits(limit=25)
            self.after(0, lambda: self._render_commits(commits, source))
        threading.Thread(target=worker, daemon=True).start()

    def _render_commits(self, commits, source):
        for child in self.news_scroll.inner.winfo_children():
            child.destroy()
        self.news_source_lbl.config(text=f'({source})')
        if not commits:
            tk.Label(self.news_scroll.inner, text=f'Could not load commits ({source}).',
                     bg=BG_CARD, fg=ERR_RED, font=('Segoe UI', 9)).pack(anchor='w', padx=12, pady=12)
            return

        for c in commits:
            ctype, scope, title = parse_commit_prefix(c['subject'])
            bg_pill, fg_pill = COMMIT_BADGES.get(ctype, ('#2b3040', '#a6afc4'))

            item = tk.Frame(self.news_scroll.inner, bg=BG_CARD_ALT,
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
        self._server_proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'run_server.py')],
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
        self.build_btn.config(state='normal')
        self.status_var.set(message)
        if ok:
            self._refresh_client_badge()

    def _check_updates_async(self):
        self.update_btn.config(state='disabled', text='Checking...')

        def run():
            st = updater.check_for_updates(ROOT)
            self.after(0, lambda: self._apply_update_status(st))

        threading.Thread(target=run, daemon=True).start()

    def _apply_update_status(self, st):
        self._update_status = st
        self.update_btn.config(state='normal')
        if st.error:
            self.update_btn.config(text='Check Updates', bg=BG_CARD, fg=TEXT_MUTED)
            return
        if st.up_to_date:
            self.update_btn.config(text=f'Up to date ({st.short_current})', bg=BG_CARD, fg=OK_GREEN)
            return
        label = f'⬆ Update ({st.behind})' if st.mode == 'git' and st.behind > 0 else '⬆ Update Available'
        self.update_btn.config(text=label, bg=ACCENT, fg='white')
        self.status_var.set(
            f'Update available on GitHub: {st.short_current} -> {st.short_remote} ({st.behind} new commit(s))'
        )

    def _on_update_click(self):
        st = self._update_status
        if st is None or st.up_to_date or st.error:
            self._check_updates_async()
            return
        msg = (
            f'Update Dark Blood Server Emulator from {st.short_current} to {st.short_remote}?\n\n'
            f'Mode: {st.mode.upper()} ({st.behind} new commit(s))\n'
            'User data (data/, research/, darkblood_options.ini) is preserved.'
        )
        if not messagebox.askyesno('Update from GitHub', msg):
            return
        # Stop local server if started by this launcher so updated code loads cleanly
        if self._server_proc is not None and self._server_proc.poll() is None:
            self._server_proc.terminate()
            self._server_proc = None
            self.local_srv_btn.config(text='Start Local Server')

        self.update_btn.config(state='disabled', text='Updating...')
        self.status_var.set('Downloading latest version from GitHub...')

        def run():
            res = updater.apply_update(ROOT)
            self.after(0, lambda: self._finish_update(res))

        threading.Thread(target=run, daemon=True).start()

    def _finish_update(self, res):
        self.update_btn.config(state='normal')
        self.status_var.set(res.message)
        if not res.ok:
            self.update_btn.config(text='Retry Update', bg=ACCENT, fg='white')
            messagebox.showerror('Update Failed', res.message)
            return
        self.update_btn.config(text=f'Up to date ({res.new_sha[:7]})', bg=BG_CARD, fg=OK_GREEN)
        self._update_status = updater.UpdateStatus(
            mode=res.mode, current_sha=res.new_sha, remote_sha=res.new_sha, up_to_date=True,
        )
        self._refresh_commits()
        if res.hook_changed and HOOK_BUILD_BAT.exists():
            self._build_hook()
        if res.launcher_changed:
            if messagebox.askyesno('Launcher Updated',
                                   f'{res.message}\n\nThe launcher itself was updated. Restart now?'):
                subprocess.Popen([sys.executable, str(Path(__file__).resolve())], cwd=str(ROOT))
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


def main():
    app = DarkBloodLauncher()
    app.mainloop()


if __name__ == '__main__':
    main()
