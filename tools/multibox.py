"""Run several Dark Blood clients side by side against the local server (multiplayer tests).

    python tools/multibox.py start [-n 2] [--no-resize]   launch clients and tile them
    python tools/multibox.py tile [--no-resize]           re-tile the running clients
    python tools/multibox.py status | stop

The server must already be running (python run_server.py, or gamectl start
--server-only). Every client logs in as the same local account, so create one
character per window and select a different one in each: the server keeps the
selection per connection. Only clients started here (logs/multibox.json) are
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


def start(count=2, resize=True, timeout=90):
    if gamectl._port_free():
        raise gamectl.GameError('Server is not listening on 127.0.0.1:%d; start it first' % gamectl.PORT)
    if gamectl.client_hash() != gamectl.CLIENT_SHA256:
        raise gamectl.GameError('Unexpected client hash; addresses in the shim are build specific')
    state = _load()
    state['clients'] = _alive_clients(state)
    env = dict(os.environ, __COMPAT_LAYER='RunAsInvoker')
    new = []
    for _ in range(count):
        proc = subprocess.Popen([str(gamectl.LAB / 'DarkBlood.exe')], cwd=str(gamectl.LAB), env=env)
        new.append(proc.pid)
        state['clients'].append(proc.pid)
        _save(state)
        time.sleep(3)  # stagger: both clients share Data/ and the shim's log files
    deadline = time.time() + timeout
    while time.time() < deadline:
        alive = [pid for pid in new if gamectl._alive(pid, 'DarkBlood.exe')]
        if len(alive) < len(new):
            raise gamectl.GameError('A client exited during start-up (single-instance check?): %r' % new)
        if all(gamectl.find_window(pid) for pid in new):
            break
        time.sleep(1)
    else:
        raise gamectl.GameError('Client windows did not appear within %ds' % timeout)
    tile(resize)
    return status()


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
    p_tile = sub.add_parser('tile')
    p_tile.add_argument('--no-resize', action='store_true')
    sub.add_parser('status')
    sub.add_parser('stop')
    args = parser.parse_args(argv)
    try:
        if args.cmd == 'start':
            result = start(args.count, not args.no_resize)
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
