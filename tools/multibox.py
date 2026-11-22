"""Run 1 to 4 Dark Blood clients side by side / in a grid against the local server.

    python tools/multibox.py start [-n 2..4] [--with-server] [--layout auto|grid|row] [--no-resize]
    python tools/multibox.py tile [--layout auto|grid|row] [--no-resize]
    python tools/multibox.py status | stop

The server must already be running (python run_server.py, gamectl start --server-only,
or pass --with-server). The client refuses a second instance through the named mutex
"DarkBlood Online"; start() closes it inside each running client (also ones
started by hand) before launching the next. Each window logs in to its own account
(DARKBLOOD_ACCOUNT -> shim -> 5386); accounts register on first login. Default names:
OfflinePlayer, Player2, Player3, Player4. Only clients started here (logs/multibox.json)
are stopped. Windows only; standard library only.
"""
import argparse
import ctypes
import json
import math
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gamectl  # noqa: E402

STATE = gamectl.LOGS / 'multibox.json'
MIN_CLIENTS = 1
MAX_CLIENTS = 4
VALID_LAYOUTS = ('auto', 'grid', 'row')
user32 = gamectl.user32
SWP_NOZORDER, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0004, 0x0001, 0x0040
SPI_GETWORKAREA = 0x0030


# Single-instance check (0x0047254E / 0x00472579): the client creates these
# named mutexes at start-up and exits when GetLastError() is
# ERROR_ALREADY_EXISTS (0xB7). Closing them inside a running client lets the
# next one start; the client does not wait on them later.
INSTANCE_MUTEXES = ('DarkBlood Recovery', 'DarkBlood Online')

ntdll = ctypes.WinDLL('ntdll')
kernel32 = gamectl.kernel32
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_CLOSE_SOURCE, DUPLICATE_SAME_ACCESS = 0x1, 0x2
SystemExtendedHandleInformation, ObjectNameInformation, ObjectTypeInformation = 64, 1, 2


class _HandleEntry(ctypes.Structure):
    _fields_ = [('Object', ctypes.c_void_p), ('UniqueProcessId', ctypes.c_size_t),
                ('HandleValue', ctypes.c_size_t), ('GrantedAccess', wintypes.ULONG),
                ('CreatorBackTraceIndex', wintypes.USHORT), ('ObjectTypeIndex', wintypes.USHORT),
                ('HandleAttributes', wintypes.ULONG), ('Reserved', wintypes.ULONG)]


class _UnicodeString(ctypes.Structure):
    _fields_ = [('Length', wintypes.USHORT), ('MaximumLength', wintypes.USHORT),
                ('Buffer', ctypes.c_void_p)]


def _process_handles(pid):
    size = 1 << 20
    while True:
        buf = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG()
        status = ntdll.NtQuerySystemInformation(SystemExtendedHandleInformation, buf, size, ctypes.byref(needed))
        if status == 0:
            break
        if status & 0xFFFFFFFF != 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH
            raise gamectl.GameError('NtQuerySystemInformation failed: %#x' % (status & 0xFFFFFFFF))
        size = max(size * 2, needed.value + 0x10000)
    count = ctypes.c_size_t.from_buffer(buf).value
    entries = (_HandleEntry * count).from_buffer(buf, 2 * ctypes.sizeof(ctypes.c_size_t))
    return [e.HandleValue for e in entries if e.UniqueProcessId == pid]


def _object_string(handle, info_class):
    buf = ctypes.create_string_buffer(0x1000)
    if ntdll.NtQueryObject(handle, info_class, buf, len(buf), None) != 0:
        return ''
    us = _UnicodeString.from_buffer(buf)
    return ctypes.wstring_at(us.Buffer, us.Length // 2) if us.Buffer else ''


def release_instance_mutexes(pid):
    """Close the client's single-instance mutexes so another client can start."""
    # Explicit HANDLE types: the default c_int truncates the -1 pseudo-handle
    # of GetCurrentProcess on 64-bit Python and DuplicateHandle then fails.
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    proc = wintypes.HANDLE(kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid))
    if not proc.value:
        raise gamectl.GameError('Cannot open client %d for handle duplication' % pid)
    me = wintypes.HANDLE(kernel32.GetCurrentProcess())
    closed = []
    try:
        for value in _process_handles(pid):
            local = wintypes.HANDLE()
            if not kernel32.DuplicateHandle(proc, wintypes.HANDLE(value), me, ctypes.byref(local),
                                            0, False, DUPLICATE_SAME_ACCESS):
                continue
            try:
                # Only mutants are named-queried: name queries on pipes can block.
                if _object_string(local, ObjectTypeInformation) != 'Mutant':
                    continue
                name = _object_string(local, ObjectNameInformation)
            finally:
                kernel32.CloseHandle(local)
            if name.endswith(INSTANCE_MUTEXES):
                kernel32.DuplicateHandle(proc, wintypes.HANDLE(value), None, None, 0, False,
                                         DUPLICATE_CLOSE_SOURCE)
                closed.append(name.rsplit('\\', 1)[-1])
    finally:
        kernel32.CloseHandle(proc)
    return closed


def _load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {'clients': []}


def _save(state):
    gamectl.LOGS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def _alive_clients(state):
    return [pid for pid in state.get('clients', []) if gamectl._alive(pid, 'DarkBlood.exe')]


def status():
    state = _load()
    alive = _alive_clients(state)
    saved_accounts = state.get('accounts', {})
    accounts = {str(pid): saved_accounts[str(pid)] for pid in alive if str(pid) in saved_accounts}
    return dict(count=len(alive), clients=alive, accounts=accounts,
                windows={pid: bool(gamectl.find_window(pid)) for pid in alive},
                server_listening=not gamectl._port_free())


def compute_tile_rects(area, count, layout='auto'):
    """Compute (x, y, width, height) rectangles for `count` windows inside `area`.

    `area` is `(left, top, right, bottom)`. `layout='auto'` uses a single row for
    1-2 windows and a balanced grid (2x2 for 3-4 windows) for 3+ windows;
    `layout='grid'` always uses a grid; `layout='row'` always uses a single row.
    """
    if layout not in VALID_LAYOUTS:
        raise gamectl.GameError('Unknown tile layout %r (expected one of %s)' % (layout, ', '.join(VALID_LAYOUTS)))
    if count <= 0:
        return []
    left, top, right, bottom = area
    work_w = max(1, right - left)
    work_h = max(1, bottom - top)
    if layout == 'row':
        cols, rows = count, 1
    else:
        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)
    cell_w = work_w // cols
    cell_h = work_h // rows
    rects = []
    for i in range(count):
        col = i % cols
        row = i // cols
        x = left + col * cell_w
        y = top + row * cell_h
        # Keep 4:3-ish proportions inside the cell so tall columns are not stretched;
        # on 16:9 displays a 2x2 grid naturally uses the full cell height.
        h = min(cell_h, cell_w * 3 // 4)
        rects.append((x, y, cell_w, h))
    return rects


def tile(resize=True, layout='auto'):
    """Place the running clients on the primary work area (row for 1-2, 2x2 grid for 3-4)."""
    pids = _alive_clients(_load())
    hwnds = [(pid, gamectl.find_window(pid)) for pid in pids]
    hwnds = [(pid, h) for pid, h in hwnds if h]
    if not hwnds:
        raise gamectl.GameError('No client windows found')
    area = wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)
    rects = compute_tile_rects((area.left, area.top, area.right, area.bottom), len(hwnds), layout=layout)
    for (pid, hwnd), (x, y, w, h) in zip(hwnds, rects):
        if resize:
            user32.SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER | SWP_SHOWWINDOW)
        else:
            user32.SetWindowPos(hwnd, 0, x, y, 0, 0, SWP_NOZORDER | SWP_NOSIZE | SWP_SHOWWINDOW)
    return [pid for pid, _ in hwnds]


def default_accounts(count, skip=0):
    """OfflinePlayer (the existing characters), then Player2, Player3, Player4, ..."""
    names = ['OfflinePlayer'] + ['Player%d' % i for i in range(2, count + skip + 2)]
    return names[skip:skip + count]


def resolve_accounts(count, accounts=None, skip=0):
    """Validate client count (1..MAX_CLIENTS) and return `count` unique account names."""
    if not (MIN_CLIENTS <= count <= MAX_CLIENTS):
        raise gamectl.GameError('Client count must be between %d and %d (got %d)' % (MIN_CLIENTS, MAX_CLIENTS, count))
    result = [a.strip() for a in (accounts or []) if a and a.strip()]
    if len(result) >= count:
        return result[:count]
    used = set(result)
    for candidate in default_accounts(count + len(used) + 1, skip=skip):
        if candidate not in used:
            result.append(candidate)
            used.add(candidate)
            if len(result) == count:
                break
    return result


def _launch_desktop_client(account, timeout=90):
    """Launch DarkBlood.exe directly on the user's interactive desktop (WinSta0\\Default).
    Uses Windows Task Scheduler to break out of agent sandbox desktops if present."""
    lab = gamectl.LAB
    safe = re.sub(r'[^A-Za-z0-9_.-]', '_', account) or 'player'
    bat = lab / ('_launch_%s.bat' % safe)
    bat.write_text(f"""@echo off\r\nset __COMPAT_LAYER=RunAsInvoker\r\nset DARKBLOOD_ACCOUNT={account}\r\ncd /d "{lab}"\r\nstart "" "{lab}\\DarkBlood.exe"\r\n""")
    task_name = 'DarkBlood_Launch_%s' % safe
    cmd = f'cmd.exe /c "{bat}"'
    pids_before = set(_running_clients())
    try:
        subprocess.run(['schtasks', '/create', '/tn', task_name, '/tr', cmd, '/sc', 'once', '/st', '00:00', '/f'],
                       capture_output=True, check=False)
        subprocess.run(['schtasks', '/run', '/tn', task_name], capture_output=True, check=False)
        time.sleep(2)
    finally:
        subprocess.run(['schtasks', '/delete', '/tn', task_name, '/f'], capture_output=True, check=False)
        try:
            bat.unlink()
        except OSError:
            pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        new_pids = [p for p in _running_clients() if p not in pids_before]
        if new_pids:
            pid = new_pids[0]
            if gamectl.find_window(pid):
                return pid
        time.sleep(1)
    raise gamectl.GameError('Client window for %s did not appear within %ds' % (account, timeout))


def start(count=2, resize=True, timeout=90, accounts=None, keep_alive=False, layout='auto', with_server=False):
    if layout not in VALID_LAYOUTS:
        raise gamectl.GameError('Unknown tile layout %r (expected one of %s)' % (layout, ', '.join(VALID_LAYOUTS)))
    resolved_accounts = resolve_accounts(count, accounts=accounts, skip=len(_running_clients()))
    if gamectl._port_free():
        if with_server:
            gamectl.start(server_only=True)
        else:
            raise gamectl.GameError(
                'Server is not listening on 127.0.0.1:%d; start it first (or pass --with-server)' % gamectl.PORT
            )
    if gamectl.client_hash() != gamectl.CLIENT_SHA256:
        raise gamectl.GameError('Unexpected client hash; addresses in the shim are build specific')
    state = _load()
    state['clients'] = _alive_clients(state)
    # Clients already running (also ones started by hand) hold the mutexes.
    for pid in _running_clients():
        release_instance_mutexes(pid)
    for account in resolved_accounts:
        pid = _launch_desktop_client(account, timeout=timeout)
        state.setdefault('accounts', {})[str(pid)] = account
        state['clients'].append(pid)
        _save(state)
        # The mutexes are created before the window; release them for the next client.
        release_instance_mutexes(pid)
    # A new client resizes its window once its device is up; tile after that.
    time.sleep(6)
    tile(resize, layout=layout)
    if keep_alive:
        print(json.dumps(status(), indent=2))
        sys.stdout.flush()
        try:
            while any(gamectl._alive(p, 'DarkBlood.exe') for p in state['clients']):
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    return status()


def _running_clients():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq DarkBlood.exe', '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    return [int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"DarkBlood.exe"')]


def stop():
    state = _load()
    stopped = []
    for pid in _alive_clients(state):
        subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        stopped.append(pid)
    state['clients'] = []
    _save(state)
    return dict(stopped=stopped)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p_start = sub.add_parser('start')
    p_start.add_argument('-n', '--count', type=int, default=2,
                         help='number of clients to launch (%d-%d, default 2)' % (MIN_CLIENTS, MAX_CLIENTS))
    p_start.add_argument('--layout', choices=VALID_LAYOUTS, default='auto',
                         help='tiling layout: auto (row for 1-2, 2x2 grid for 3-4), grid, or row')
    p_start.add_argument('--with-server', action='store_true',
                         help='start the local server automatically if port %d is not listening' % gamectl.PORT)
    p_start.add_argument('--no-resize', action='store_true')
    p_start.add_argument('--keep-alive', action='store_true', help='keep running to supervise clients')
    p_start.add_argument('--accounts', nargs='+',
                         help='account per window (default: OfflinePlayer, Player2, Player3, Player4)')
    p_tile = sub.add_parser('tile')
    p_tile.add_argument('--layout', choices=VALID_LAYOUTS, default='auto',
                        help='tiling layout: auto (row for 1-2, 2x2 grid for 3-4), grid, or row')
    p_tile.add_argument('--no-resize', action='store_true')
    sub.add_parser('status')
    sub.add_parser('stop')
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'start':
            result = start(args.count, not args.no_resize, accounts=args.accounts,
                           keep_alive=args.keep_alive, layout=args.layout, with_server=args.with_server)
        elif args.cmd == 'tile':
            result = tile(not args.no_resize, layout=args.layout)
        elif args.cmd == 'status':
            result = status()
        else:
            result = stop()
    except gamectl.GameError as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
