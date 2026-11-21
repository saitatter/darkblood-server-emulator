"""Dark Blood Custom Launcher: configure server IP/port, toggle modular patches, and launch.

    python tools/launcher.py

Writes research/client/darkblood_options.ini. [network] and [client] keys are
loaded by the modular client_hook/steam_api.dll when DarkBlood.exe starts;
[server] keys are read by the local Python server.
"""
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tools'))

from darkblood.core import options  # noqa: E402
import gamectl  # noqa: E402


CLIENT_DIR = gamectl.LAB
CLIENT_EXE = CLIENT_DIR / 'DarkBlood.exe'
CLIENT_DLL = CLIENT_DIR / 'steam_api.dll'
HOOK_BUILD_BAT = ROOT / 'client_hook' / 'build.bat'
HOOK_BUILT_DLL = ROOT / 'client_hook' / 'steam_api.dll'


def probe_tcp(host, port, timeout=1.5):
    """Return (reachable: bool, detail: str) for a TCP endpoint."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            ms = (time.perf_counter() - t0) * 1000.0
            return True, f'Online ({ms:.0f} ms)'
    except OSError as exc:
        return False, f'Offline ({exc.__class__.__name__})'


def launch_clients(account, count=1):
    """Launch 1..4 DarkBlood.exe instances directly against the configured server."""
    if not CLIENT_EXE.exists():
        raise RuntimeError(f'Client executable not found: {CLIENT_EXE}')
    if not CLIENT_DLL.exists():
        raise RuntimeError(f'Hook DLL not found: {CLIENT_DLL} (click "Build & Deploy Hook")')

    import multibox
    running = multibox._running_clients()
    for pid in running:
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
            # Give the instance a moment to create its single-instance mutex, then release it.
            time.sleep(2.5)
            try:
                multibox.release_instance_mutexes(proc.pid)
            except Exception:
                pass
    return launched


class DarkBloodLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Dark Blood Online — Custom Launcher')
        self.minsize(640, 620)
        self.geometry('680x700')
        self._server_proc = None
        self._patch_vars = {}

        self._configure_style()
        self._build_ui()
        self._load_values()
        self._refresh_client_badge()
        self._refresh_server_button()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    def _configure_style(self):
        style = ttk.Style(self)
        for theme in ('vista', 'xpnative', 'clam'):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure('Title.TLabel', font=('Segoe UI', 14, 'bold'))
        style.configure('Sub.TLabel', font=('Segoe UI', 9), foreground='#555555')
        style.configure('Section.TLabelframe.Label', font=('Segoe UI', 10, 'bold'))
        style.configure('PatchName.TCheckbutton', font=('Segoe UI', 9, 'bold'))
        style.configure('PatchFile.TLabel', font=('Consolas', 8), foreground='#2b5b84')
        style.configure('PatchDesc.TLabel', font=('Segoe UI', 8), foreground='#555555')
        style.configure('Play.TButton', font=('Segoe UI', 10, 'bold'), padding=(16, 6))

    def _build_ui(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill='both', expand=True)

        # Header
        hdr = ttk.Frame(root)
        hdr.pack(fill='x', pady=(0, 10))
        ttk.Label(hdr, text='Dark Blood Custom Launcher', style='Title.TLabel').pack(side='left')
        self.client_badge = ttk.Label(hdr, text='Checking client...', style='Sub.TLabel')
        self.client_badge.pack(side='right', pady=(4, 0))

        # Server Connection & Account Frame
        net_frame = ttk.LabelFrame(root, text='Server Connection & Account', style='Section.TLabelframe', padding=10)
        net_frame.pack(fill='x', pady=(0, 10))

        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.relay_port_var = tk.StringVar()
        self.account_var = tk.StringVar()
        self.clients_var = tk.IntVar(value=1)

        # Row 0: Host, Game Port, Relay Port
        ttk.Label(net_frame, text='Server IP / Host:').grid(row=0, column=0, sticky='w', padx=(0, 6))
        ttk.Entry(net_frame, textvariable=self.host_var, width=22).grid(row=0, column=1, sticky='ew', padx=(0, 12))

        ttk.Label(net_frame, text='Game Port:').grid(row=0, column=2, sticky='w', padx=(0, 6))
        ttk.Entry(net_frame, textvariable=self.port_var, width=8).grid(row=0, column=3, sticky='w', padx=(0, 12))

        ttk.Label(net_frame, text='Relay Port:').grid(row=0, column=4, sticky='w', padx=(0, 6))
        ttk.Entry(net_frame, textvariable=self.relay_port_var, width=8).grid(row=0, column=5, sticky='w')

        # Row 1: Account, Clients, Server test / local server toggle
        ttk.Label(net_frame, text='Account:').grid(row=1, column=0, sticky='w', padx=(0, 6), pady=(8, 0))
        ttk.Entry(net_frame, textvariable=self.account_var, width=22).grid(
            row=1, column=1, sticky='ew', padx=(0, 12), pady=(8, 0))

        ttk.Label(net_frame, text='Clients:').grid(row=1, column=2, sticky='w', padx=(0, 6), pady=(8, 0))
        ttk.Spinbox(net_frame, from_=1, to=4, width=6, textvariable=self.clients_var).grid(
            row=1, column=3, sticky='w', padx=(0, 12), pady=(8, 0))

        net_btns = ttk.Frame(net_frame)
        net_btns.grid(row=1, column=4, columnspan=2, sticky='e', pady=(8, 0))
        ttk.Button(net_btns, text='Test Connection', command=self._test_connection).pack(side='left', padx=(0, 6))
        self.local_srv_btn = ttk.Button(net_btns, text='Start Local Server', command=self._toggle_local_server)
        self.local_srv_btn.pack(side='left')

        self.conn_status = ttk.Label(net_frame, text='', style='Sub.TLabel')
        self.conn_status.grid(row=2, column=0, columnspan=6, sticky='w', pady=(6, 0))
        net_frame.columnconfigure(1, weight=1)

        # Patches Frame (scrollable)
        patch_outer = ttk.LabelFrame(root, text='Patches (Hacks & Improvements)', style='Section.TLabelframe', padding=6)
        patch_outer.pack(fill='both', expand=True, pady=(0, 10))

        canvas = tk.Canvas(patch_outer, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(patch_outer, orient='vertical', command=canvas.yview)
        self.patch_inner = ttk.Frame(canvas, padding=(4, 2))
        self.patch_inner.bind(
            '<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        win_id = canvas.create_window((0, 0), window=self.patch_inner, anchor='nw')
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Mouse wheel scrolling
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', _on_wheel)

        self._populate_patches()

        # Action Bar
        actions = ttk.Frame(root)
        actions.pack(fill='x')

        ttk.Button(actions, text='Reset Defaults', command=self._reset_defaults).pack(side='left')
        ttk.Button(actions, text='Save Config', command=self._save_config).pack(side='left', padx=(6, 0))
        self.build_btn = ttk.Button(actions, text='Build & Deploy Hook', command=self._build_hook)
        self.build_btn.pack(side='left', padx=(6, 0))

        ttk.Button(actions, text='Launch Game', style='Play.TButton', command=self._launch).pack(side='right')

        # Status Bar
        self.status_var = tk.StringVar(value=f'Config: {options.OPTIONS_PATH}')
        ttk.Label(root, textvariable=self.status_var, style='Sub.TLabel', wraplength=640).pack(
            fill='x', pady=(8, 0))

    def _populate_patches(self):
        row = 0
        for cat_id, cat_title in options.CATEGORIES:
            keys = [k for k in options.OPTIONS if options.PATCH_META.get(k, ('', ''))[0] == cat_id]
            if not keys:
                continue
            ttk.Label(self.patch_inner, text=cat_title, font=('Segoe UI', 9, 'bold'),
                      foreground='#1f3b5c').grid(row=row, column=0, columnspan=2, sticky='w',
                                                 pady=(8 if row else 2, 4))
            row += 1
            for key in keys:
                _, default, label, desc = options.OPTIONS[key]
                _, src_file = options.PATCH_META[key]
                var = tk.BooleanVar(value=default)
                self._patch_vars[key] = var

                cb = ttk.Checkbutton(self.patch_inner, text=label, variable=var, style='PatchName.TCheckbutton')
                cb.grid(row=row, column=0, sticky='w')
                ttk.Label(self.patch_inner, text=src_file, style='PatchFile.TLabel').grid(
                    row=row, column=1, sticky='e', padx=(8, 4))
                row += 1

                ttk.Label(self.patch_inner, text=desc, style='PatchDesc.TLabel', wraplength=560).grid(
                    row=row, column=0, columnspan=2, sticky='w', padx=(22, 4), pady=(0, 6))
                row += 1
        self.patch_inner.columnconfigure(0, weight=1)

    def _load_values(self):
        cfg = options.read_all()
        self.host_var.set(cfg['network']['host'])
        self.port_var.set(str(cfg['network']['port']))
        self.relay_port_var.set(str(cfg['network']['relay_port']))
        self.account_var.set(cfg['launcher']['account'])
        self.clients_var.set(cfg['launcher']['clients'])
        for key, var in self._patch_vars.items():
            var.set(bool(cfg['options'].get(key, options.OPTIONS[key][1])))

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
        self.status_var.set('Defaults restored (click Save Config or Launch Game to write).')

    def _refresh_client_badge(self):
        def check():
            if not CLIENT_EXE.exists():
                text = 'Client EXE missing'
            elif not CLIENT_DLL.exists():
                text = 'Client OK | Hook DLL missing'
            else:
                try:
                    ok_hash = (gamectl.client_hash() == gamectl.CLIENT_SHA256)
                    text = 'Client verified | Hook ready' if ok_hash else 'Client hash mismatch!'
                except Exception:
                    text = 'Client found | Hook ready'
            self.after(0, lambda: self.client_badge.config(text=text))
        threading.Thread(target=check, daemon=True).start()

    def _refresh_server_button(self):
        running_child = self._server_proc is not None and self._server_proc.poll() is None
        if running_child:
            self.local_srv_btn.config(text='Stop Local Server')
        else:
            self._server_proc = None
            self.local_srv_btn.config(text='Start Local Server')

    def _test_connection(self):
        try:
            net = options.validate_network(
                self.host_var.get(), self.port_var.get(), self.relay_port_var.get())
        except ValueError as exc:
            self.conn_status.config(text=f'Invalid address: {exc}')
            return
        self.conn_status.config(text=f'Probing {net["host"]}:{net["port"]} ...')

        def run():
            ok, msg = probe_tcp(net['host'], net['port'])
            relay_ok, relay_msg = probe_tcp(net['host'], net['relay_port'], timeout=0.8)
            summary = f'Game {net["host"]}:{net["port"]}: {msg}  |  Relay :{net["relay_port"]}: {relay_msg}'
            self.after(0, lambda: self.conn_status.config(text=summary))
        threading.Thread(target=run, daemon=True).start()

    def _toggle_local_server(self):
        if self._server_proc is not None and self._server_proc.poll() is None:
            self._server_proc.terminate()
            self._server_proc = None
            self._refresh_server_button()
            self.conn_status.config(text='Local server stopped.')
            return

        if not gamectl._port_free():
            self.conn_status.config(text='Local server is already listening on 127.0.0.1:9400.')
            return

        flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        self._server_proc = subprocess.Popen(
            [sys.executable, str(ROOT / 'run_server.py')],
            cwd=str(ROOT),
            creationflags=flags,
        )
        self._refresh_server_button()
        self.conn_status.config(text=f'Local server started (PID {self._server_proc.pid}) on 127.0.0.1:9400/9401.')

    def _build_hook(self):
        if not HOOK_BUILD_BAT.exists():
            messagebox.showerror('Build Hook', f'Missing build script: {HOOK_BUILD_BAT}')
            return
        self.build_btn.config(state='disabled')
        self.status_var.set('Building modular steam_api.dll...')

        def run():
            proc = subprocess.run(
                ['cmd.exe', '/c', str(HOOK_BUILD_BAT)],
                cwd=str(HOOK_BUILD_BAT.parent),
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or 'Build failed').strip().splitlines()[-1]
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
        self.destroy()


def main():
    app = DarkBloodLauncher()
    app.mainloop()


if __name__ == '__main__':
    main()
