"""Run GM console commands in a running client through the hook's GM channel.

`client_hook/patches/gm_channel.c` creates a message-only window
"DarkBloodGmChannel" titled "DarkBloodGm:<pid>" in every client. Sending it
WM_COPYDATA (dwData = CHANNEL_MAGIC, UTF-16 text) runs the text on the game
thread exactly as if it had been typed in chat with the '%' prefix, so client
commands (camera, god mode, ...) and server-backed cheats behave the same.

The window is found by the client's process id. With several clients, the
process is the one owning the TCP connection whose local port the server
reports for the selected character (GM bridge status `client_port`).
"""
import ctypes
import ctypes.wintypes as wt
import sys

CHANNEL_CLASS = 'DarkBloodGmChannel'
CHANNEL_MAGIC = 0x444247
WM_COPYDATA = 0x004A
SMTO_ABORTIFHUNG = 0x0002
TIMEOUT_MS = 5000

# SendMessage results from gm_channel.c
RESULT_MESSAGES = {
    1: 'Executed in the client.',
    2: 'GM mode is off for this client (enable GM console in Patches, then relog).',
    3: 'The character is not in the game yet.',
    4: 'The client hook could not resolve its MSVCP functions (see hook_log.txt).',
    5: 'The command raised an exception in the client (see hook_log.txt).',
    0: 'The client rejected the message.',
}

_IS_WINDOWS = sys.platform == 'win32'
if _IS_WINDOWS:
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _iphlp = ctypes.WinDLL('iphlpapi')
    _HWND_MESSAGE = wt.HWND(-3)
    _user32.FindWindowExW.restype = wt.HWND
    _user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
    _user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _user32.SendMessageTimeoutW.restype = ctypes.c_size_t
    _user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                            ctypes.POINTER(ctypes.c_size_t)]


class _CopyData(ctypes.Structure):
    _fields_ = [('dwData', ctypes.c_size_t), ('cbData', wt.DWORD), ('lpData', ctypes.c_void_p)]


def list_channels() -> dict:
    """{client pid: channel hwnd} for every running client with the GM channel."""
    if not _IS_WINDOWS:
        return {}
    out = {}
    hwnd = None
    buf = ctypes.create_unicode_buffer(64)
    while True:
        hwnd = _user32.FindWindowExW(_HWND_MESSAGE, hwnd, CHANNEL_CLASS, None)
        if not hwnd:
            break
        _user32.GetWindowTextW(hwnd, buf, len(buf))
        title = buf.value
        if title.startswith('DarkBloodGm:'):
            try:
                out[int(title.split(':', 1)[1])] = hwnd
            except ValueError:
                pass
    return out


class _TcpRowOwnerPid(ctypes.Structure):
    _fields_ = [('state', wt.DWORD), ('local_addr', wt.DWORD), ('local_port', wt.DWORD),
                ('remote_addr', wt.DWORD), ('remote_port', wt.DWORD), ('pid', wt.DWORD)]


def pid_for_local_port(port: int):
    """Process id owning an IPv4 TCP connection with this local port, or None."""
    if not _IS_WINDOWS or not port:
        return None
    size = wt.DWORD(0)
    tcp_table_owner_pid_all = 5
    _iphlp.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, tcp_table_owner_pid_all, 0)
    buf = ctypes.create_string_buffer(size.value + 4096)
    size = wt.DWORD(len(buf))
    if _iphlp.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, tcp_table_owner_pid_all, 0) != 0:
        return None
    count = ctypes.c_uint32.from_buffer(buf).value
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(_TcpRowOwnerPid))
    for i in range(count):
        row = rows[i]
        local = ((row.local_port & 0xFF) << 8) | ((row.local_port >> 8) & 0xFF)
        if local == int(port):
            return int(row.pid)
    return None


def pick_channel(client_port: int = 0):
    """(pid, hwnd) of the client to command: the one behind `client_port`, or the only one."""
    channels = list_channels()
    if not channels:
        return None, None
    pid = pid_for_local_port(client_port) if client_port else None
    if pid in channels:
        return pid, channels[pid]
    if len(channels) == 1:
        return next(iter(channels.items()))
    return None, None


def send_command(command: str, client_port: int = 0) -> dict:
    """Run `command` ('%' optional) in the selected client. Returns {'ok', 'message', 'code'}."""
    text = (command or '').strip()
    if not text:
        return {'ok': False, 'message': 'Empty command.', 'code': 0}
    channels = list_channels()
    if not channels:
        return {'ok': False, 'no_channel': True, 'code': 0,
                'message': 'No running client with the GM channel (start the game; rebuild the hook if it is old).'}
    pid, hwnd = pick_channel(client_port)
    if hwnd is None:
        return {'ok': False, 'code': 0,
                'message': 'Several clients are running; select the character to command.'}
    data = ctypes.create_unicode_buffer(text)
    cds = _CopyData(CHANNEL_MAGIC, len(text) * ctypes.sizeof(ctypes.c_wchar), ctypes.cast(data, ctypes.c_void_p))
    result = ctypes.c_size_t(0)
    if not _user32.SendMessageTimeoutW(hwnd, WM_COPYDATA, 0, ctypes.addressof(cds), SMTO_ABORTIFHUNG,
                                       TIMEOUT_MS, ctypes.byref(result)):
        return {'ok': False, 'code': 0, 'message': f'The client (pid {pid}) did not answer in time.'}
    code = int(result.value)
    return {'ok': code == 1, 'code': code, 'pid': pid,
            'message': RESULT_MESSAGES.get(code, f'Unexpected reply {code}.')}
