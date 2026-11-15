"""Control a local Dark Blood test session: emulator server + client.

Library used by tools/mcp_server.py, also usable as a CLI:
    python tools/gamectl.py start [--seconds N]
    python tools/gamectl.py status | stop
    python tools/gamectl.py screenshot out.png [--width 1280]
    python tools/gamectl.py keys enter | click 0.5 0.6 | skip-intro
    python tools/gamectl.py events [--all]

Only processes started by this module (recorded in logs/session.json) are
stopped. Windows only; standard library only.
"""
import argparse
import ctypes
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time
import zlib
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAB = ROOT / 'research' / 'client'
LOGS = ROOT / 'logs'
STATE = LOGS / 'session.json'
WIRE = LOGS / 'wire.jsonl'
CLIENT_SHA256 = 'a82ae3d71b596418c1f3593cb63d3f9746318d452143c2e88f6ebbaff339c931'
PORT = 9400

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)


class GameError(RuntimeError):
    pass


def _attach_desktop():
    """Ensure process and calling thread are attached to the interactive desktop."""
    try:
        hwinsta = user32.OpenWindowStationW('WinSta0', False, 0x0000037F)
        if hwinsta:
            user32.SetProcessWindowStation(hwinsta)
        hdesk = user32.OpenDesktopW('Default', 0, False, 0x000001FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


# ------------------------------------------------------------------ processes
def _alive(pid, image=None):
    if not pid:
        return False
    out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/FO', 'CSV', '/NH'],
                         capture_output=True, text=True).stdout
    if '"%d"' % pid not in out:
        return False
    return image is None or image.lower() in out.lower()


def _load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state):
    LOGS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def _port_free(port=PORT):
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def client_hash():
    return hashlib.sha256((LAB / 'DarkBlood.exe').read_bytes()).hexdigest()


def status():
    state = _load_state()
    server = state.get('server_pid')
    client = state.get('client_pid')
    return dict(server_pid=server, server_alive=_alive(server, 'python'),
                client_pid=client, client_alive=_alive(client, 'DarkBlood.exe'),
                started=state.get('started'), wire_offset=state.get('wire_offset', 0),
                window=bool(find_window(client)) if _alive(client, 'DarkBlood.exe') else False)


def start(server_only=False, client_only=False):
    """Start the emulator server and the test client."""
    state = _load_state()
    current = status()
    if current['client_alive'] or current['server_alive']:
        raise GameError('A session is already running; stop it first: %r' % current)
    if client_hash() != CLIENT_SHA256:
        raise GameError('Unexpected client hash; addresses in the shim are build specific')
    LOGS.mkdir(parents=True, exist_ok=True)
    state = dict(started=time.time(), wire_offset=WIRE.stat().st_size if WIRE.exists() else 0)
    if not client_only:
        if not _port_free():
            raise GameError('127.0.0.1:%d is already in use by another process' % PORT)
        log = open(LOGS / 'server.log', 'w')
        server = subprocess.Popen([sys.executable, '-u', str(ROOT / 'server' / 'run_bootstrap.py')],
                                  cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        state['server_pid'] = server.pid
        for _ in range(50):
            if not _port_free():
                break
            time.sleep(0.1)
        else:
            raise GameError('Server did not start listening; see logs/server.log')
    if not server_only:
        env = dict(os.environ, __COMPAT_LAYER='RunAsInvoker')
        si = subprocess.STARTUPINFO()
        si.lpDesktop = 'WinSta0\\Default'
        client = subprocess.Popen([str(LAB / 'DarkBlood.exe')], cwd=str(LAB), env=env, startupinfo=si)
        state['client_pid'] = client.pid
    _save_state(state)
    return status()


def stop():
    state = _load_state()
    stopped = []
    for key, image in (('client_pid', 'DarkBlood.exe'), ('server_pid', 'python')):
        pid = state.get(key)
        if _alive(pid, image):
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
            stopped.append(pid)
    state.pop('client_pid', None)
    state.pop('server_pid', None)
    _save_state(state)
    return dict(stopped=stopped)


# -------------------------------------------------------------------- windows
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.StretchBlt.argtypes = [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.HDC] + [ctypes.c_int] * 4 + [wintypes.DWORD]
gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                            ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def find_window(pid=None):
    _attach_desktop()
    pid = pid or _load_state().get('client_pid')
    found = []

    def callback(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if 'DarkBlood' in title.value or 'DarkBlood' in cls.value:
                found.append(hwnd)
        return True

    if pid:
        user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None


def _window():
    hwnd = find_window()
    if not hwnd:
        raise GameError('Game window not found (is the client running?)')
    return hwnd


def client_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top


def focus(hwnd=None):
    hwnd = hwnd or _window()
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.25)
    return hwnd


def _png(width, height, rgb):
    raw = b''.join(b'\x00' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def screenshot(path=None, width=1280):
    """Capture the game's client area (scaled to `width`), return PNG bytes."""
    hwnd = focus()
    x, y, w, h = client_rect(hwnd)
    if w <= 0 or h <= 0:
        raise GameError('Window has no client area (minimised?)')
    out_w = min(width or w, w)
    out_h = max(1, h * out_w // w)
    screen = user32.GetDC(None)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, out_w, out_h)
    old = gdi32.SelectObject(memory, bitmap)
    gdi32.SetStretchBltMode(memory, 4)  # HALFTONE
    gdi32.StretchBlt(memory, 0, 0, out_w, out_h, screen, x, y, w, h, 0x00CC0020)
    header = struct.pack('<IiiHHIIiiII', 40, out_w, -out_h, 1, 32, 0, 0, 0, 0, 0, 0)
    info = ctypes.create_string_buffer(header + b'\0' * 16)
    pixels = ctypes.create_string_buffer(out_w * out_h * 4)
    gdi32.GetDIBits(memory, bitmap, 0, out_h, pixels, info, 0)
    gdi32.SelectObject(memory, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(None, screen)
    bgra = pixels.raw
    rgb = bytearray(out_w * out_h * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    data = _png(out_w, out_h, bytes(rgb))
    if path:
        Path(path).write_bytes(data)
    return data


# ---------------------------------------------------------------------- input
VK = dict(enter=0x0D, esc=0x1B, escape=0x1B, space=0x20, tab=0x09, alt=0x12, ctrl=0x11,
          shift=0x10, back=0x08, backspace=0x08, up=0x26, down=0x28, left=0x25, right=0x27,
          f1=0x70, f2=0x71, f3=0x72, f4=0x73, f5=0x74, f10=0x79, f12=0x7B, delete=0x2E)
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]


def _vk(name):
    name = name.strip().lower()
    if name in VK:
        return VK[name]
    if len(name) == 1:
        return ord(name.upper())
    raise GameError('Unknown key %r' % name)


def keys(chord, hold=0.05):
    """Press a chord such as 'enter', 'alt+enter' or 'esc'."""
    focus()
    codes = [_vk(part) for part in chord.split('+')]
    for code in codes:
        user32.keybd_event(code, user32.MapVirtualKeyW(code, 0), 0, None)
        time.sleep(hold)
    for code in reversed(codes):
        user32.keybd_event(code, user32.MapVirtualKeyW(code, 0), 2, None)
        time.sleep(hold)
    return 'sent ' + chord


def type_text(text):
    focus()
    for char in text:
        code = user32.VkKeyScanW(ord(char))
        if code == -1:
            raise GameError('Cannot type %r' % char)
        shift = bool(code & 0x100)
        if shift:
            user32.keybd_event(0x10, 0, 0, None)
        user32.keybd_event(code & 0xff, 0, 0, None)
        user32.keybd_event(code & 0xff, 0, 2, None)
        if shift:
            user32.keybd_event(0x10, 0, 2, None)
        time.sleep(0.03)
    return 'typed %d characters' % len(text)


def click(x, y, button='left', double=False):
    """Click at client coordinates; values <= 1 are fractions of the client area."""
    hwnd = focus()
    left, top, w, h = client_rect(hwnd)
    px = left + (int(x * w) if x <= 1 else int(x))
    py = top + (int(y * h) if y <= 1 else int(y))
    user32.SetCursorPos(px, py)
    time.sleep(0.08)
    down, up = (2, 4) if button == 'left' else (8, 16)
    for _ in range(2 if double else 1):
        user32.mouse_event(down, 0, 0, 0, None)
        time.sleep(0.06)
        user32.mouse_event(up, 0, 0, 0, None)
        time.sleep(0.08)
    return 'clicked %s at screen %d,%d' % (button, px, py)


def skip_intro(timeout=60):
    """Click through the start-up cinematics until the Server List opens.

    The list opening is detected from the wire log: the title scene sends a
    second eEGS_DB_LIST_GET_REQ (2402) when the dialog is shown.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if count_events(2402) >= 2:
            return 'server list open'
        if find_window():
            click(0.5, 0.5)
        time.sleep(1.5)
    raise GameError('Server list did not open within %ds' % timeout)


def count_events(opcode):
    return sum(1 for row in events(limit=100000) if ' C->S %d ' % opcode in row)


def wait_event(opcode, count=1, timeout=30):
    """Wait until the client has sent `opcode` at least `count` times."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if count_events(opcode) >= count:
            return True
        time.sleep(0.5)
    return False


def enter_lobby(timeout=90):
    """From launch to character select: skip intro, server, channel."""
    skip_intro(timeout)
    for opcode in (2001, 5028):  # knock (server list Ok), join square (channel Ok)
        for _ in range(6):
            time.sleep(1.5)
            keys('enter')
            if wait_event(opcode, timeout=4):
                break
        else:
            raise GameError('Client did not send %d' % opcode)
    if not wait_event(2008, timeout=20):  # sent automatically after join ack
        raise GameError('Character list was not requested')
    time.sleep(3)
    return 'character select reached'


def select_character():
    """From character select screen: press Enter to confirm and send opcode 2006."""
    focus()
    keys('enter')
    time.sleep(1)
    return 'character select confirmed'


# ---------------------------------------------------------------------- events
def _opcode_names():
    names = {}
    path = ROOT / 'server' / 'data' / 'opcodes.tsv'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line and not line.startswith('#'):
                key, name = line.split('\t', 1)
                names[int(key)] = name
    return names


def events(since_start=True, include_transport=False, limit=60):
    """Decoded wire log entries for the current session."""
    state = _load_state()
    offset = state.get('wire_offset', 0) if since_start else 0
    names = _opcode_names()
    rows = []
    if WIRE.exists():
        with WIRE.open('rb') as stream:
            stream.seek(offset)
            for line in stream:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                kind = entry.get('event')
                if kind in ('event', 'unhandled-event'):
                    opcode = entry.get('opcode')
                    rows.append('%s C->S %s %s body=%s' % (kind, opcode, names.get(opcode, '?'), entry['hex'][:120]))
                elif kind == 'send' and entry.get('note'):
                    rows.append('S->C %s' % entry['note'])
                elif include_transport or kind in ('connect', 'disconnect', 'session-key', 'unhandled', 'bad-event'):
                    rows.append('%s %s' % (kind, entry.get('hex', '')[:80]))
    rows = [row for row in rows if include_transport or 'C->S 0 ' not in row]
    return rows[-limit:]


def hook_log(lines=40):
    path = LAB / 'hook_log.txt'
    if not path.exists():
        return []
    return path.read_text(errors='replace').splitlines()[-lines:]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('start')
    sub.add_parser('stop')
    sub.add_parser('status')
    shot = sub.add_parser('screenshot')
    shot.add_argument('output')
    shot.add_argument('--width', type=int, default=1280)
    key = sub.add_parser('keys')
    key.add_argument('chord')
    text = sub.add_parser('type')
    text.add_argument('text')
    clk = sub.add_parser('click')
    clk.add_argument('x', type=float)
    clk.add_argument('y', type=float)
    clk.add_argument('--right', action='store_true')
    sub.add_parser('skip-intro')
    sub.add_parser('enter-lobby')
    ev = sub.add_parser('events')
    ev.add_argument('--all', action='store_true')
    sub.add_parser('hook-log')
    args = parser.parse_args(argv)
    try:
        if args.command == 'start':
            result = start()
        elif args.command == 'stop':
            result = stop()
        elif args.command == 'status':
            result = status()
        elif args.command == 'screenshot':
            screenshot(args.output, args.width)
            result = 'saved ' + args.output
        elif args.command == 'keys':
            result = keys(args.chord)
        elif args.command == 'type':
            result = type_text(args.text)
        elif args.command == 'click':
            result = click(args.x, args.y, 'right' if args.right else 'left')
        elif args.command == 'skip-intro':
            result = skip_intro()
        elif args.command == 'enter-lobby':
            result = enter_lobby()
        elif args.command == 'events':
            result = '\n'.join(events(include_transport=args.all))
        else:
            result = '\n'.join(hook_log())
    except GameError as exc:
        print('error:', exc, file=sys.stderr)
        return 1
    print(result if isinstance(result, str) else json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
