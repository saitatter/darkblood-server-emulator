"""Client staging, hook deployment, icon extraction, TCP probe, GM bridge and process launch."""
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path

from darkblood.games.gm_bridge import GM_BRIDGE_HOST, GM_BRIDGE_PORT, SERVER_LIVE_COMMANDS
import gamectl

from launcher_app.theme import CLIENT_DIR, CLIENT_DLL, CLIENT_EXE, HOOK_BUILT_DLL, ROOT


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
