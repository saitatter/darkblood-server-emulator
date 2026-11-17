"""Run several Dark Blood clients side by side against the local server (multiplayer tests).

    python tools/multibox.py start [-n 2] [--no-resize]   launch clients and tile them
    python tools/multibox.py tile [--no-resize]           re-tile the running clients
    python tools/multibox.py status | stop

The server must already be running (python run_server.py, or gamectl start
--server-only). The client refuses a second instance through the named mutex
"DarkBlood Online"; start() closes it inside each running client (also ones
started by hand) before launching the next. Each window logs in to its own account (DARKBLOOD_ACCOUNT -> shim -> 5386);
accounts register on first login. Default names: OfflinePlayer, Player2, ... Only clients started here (logs/multibox.json) are
stopped. Windows only; standard library only.
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gamectl  # noqa: E402

STATE = gamectl.LOGS / 'multibox.json'
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
    return dict(clients=alive, windows={pid: bool(gamectl.find_window(pid)) for pid in alive},
                server_listening=not gamectl._port_free())


def tile(resize=True):
    """Place the running clients next to each other on the primary work area."""
    pids = _alive_clients(_load())
    hwnds = [(pid, gamectl.find_window(pid)) for pid in pids]
    hwnds = [(pid, h) for pid, h in hwnds if h]
    if not hwnds:
        raise gamectl.GameError('No client windows found')
    area = wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)
    width = (area.right - area.left) // len(hwnds)
    height = area.bottom - area.top
    for i, (pid, hwnd) in enumerate(hwnds):
        x = area.left + i * width
        if resize:
            # Keep 4:3-ish proportions inside the column; the game scales its
            # back buffer to the window in windowed mode.
            h = min(height, width * 3 // 4)
            user32.SetWindowPos(hwnd, 0, x, area.top, width, h, SWP_NOZORDER | SWP_SHOWWINDOW)
        else:
            user32.SetWindowPos(hwnd, 0, x, area.top, 0, 0, SWP_NOZORDER | SWP_NOSIZE | SWP_SHOWWINDOW)
    return [pid for pid, _ in hwnds]


def default_accounts(count, skip=0):
    """OfflinePlayer (the existing characters), then Player2, Player3, ..."""
    names = ['OfflinePlayer'] + ['Player%d' % i for i in range(2, count + skip + 2)]
    return names[skip:skip + count]


def start(count=2, resize=True, timeout=90, accounts=None):
    if gamectl._port_free():
        raise gamectl.GameError('Server is not listening on 127.0.0.1:%d; start it first' % gamectl.PORT)
    if gamectl.client_hash() != gamectl.CLIENT_SHA256:
        raise gamectl.GameError('Unexpected client hash; addresses in the shim are build specific')
    state = _load()
    state['clients'] = _alive_clients(state)
    env = dict(os.environ, __COMPAT_LAYER='RunAsInvoker')
    # Clients already running (also ones started by hand) hold the mutexes.
    for pid in _running_clients():
        release_instance_mutexes(pid)
    accounts = list(accounts or default_accounts(count, skip=len(_running_clients())))
    for i in range(count):
        account = accounts[i] if i < len(accounts) else 'Player%d' % (i + 2)
        # The shim logs in as DARKBLOOD_ACCOUNT (Steam persona + auth ticket in 5386).
        proc = subprocess.Popen([str(gamectl.LAB / 'DarkBlood.exe')], cwd=str(gamectl.LAB),
                                env=dict(env, DARKBLOOD_ACCOUNT=account))
        state.setdefault('accounts', {})[str(proc.pid)] = account
        state['clients'].append(proc.pid)
        _save(state)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not gamectl._alive(proc.pid, 'DarkBlood.exe'):
                raise gamectl.GameError('Client %d exited during start-up' % proc.pid)
            if gamectl.find_window(proc.pid):
                break
            time.sleep(1)
        else:
            raise gamectl.GameError('Client %d window did not appear within %ds' % (proc.pid, timeout))
        # The mutexes are created before the window; release them for the next client.
        release_instance_mutexes(proc.pid)
    # A new client resizes its window once its device is up; tile after that.
    time.sleep(8)
    tile(resize)
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
    p_start.add_argument('-n', '--count', type=int, default=2)
    p_start.add_argument('--no-resize', action='store_true')
    p_start.add_argument('--accounts', nargs='+', help='account per window (default: OfflinePlayer, Player2, ...)')
    p_tile = sub.add_parser('tile')
    p_tile.add_argument('--no-resize', action='store_true')
    sub.add_parser('status')
    sub.add_parser('stop')
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'start':
            result = start(args.count, not args.no_resize, accounts=args.accounts)
        elif args.cmd == 'tile':
            result = tile(not args.no_resize)
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
