"""Package emulator diagnostic bundle for GitHub issue submission and AI agent ingestion.

Usage:
    python tools/launcher/export_diagnostics.py [--output diagnostics.zip] [--lines 1000]

Collects:
    1. System & Python environment details.
    2. Git commit hash, branch, and status.
    3. Client executable SHA-256 (if found in research/client/).
    4. Recent wire traffic from wire.jsonl (last N lines).
    5. Character state snapshot (data/darkblood.db).
    6. Handler address map (research/client/handler_map.txt).
    7. Active server and client log snippets.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[2]


def get_git_info():
    info = {'commit': 'unknown', 'branch': 'unknown', 'dirty': False}
    try:
        out = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT, stderr=subprocess.DEVNULL)
        info['commit'] = out.decode().strip()
        out = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=REPO_ROOT, stderr=subprocess.DEVNULL)
        info['branch'] = out.decode().strip()
        out = subprocess.check_output(['git', 'status', '--porcelain'], cwd=REPO_ROOT, stderr=subprocess.DEVNULL)
        info['dirty'] = bool(out.strip())
    except Exception as e:
        info['error'] = str(e)
    return info


def hash_file(path: Path) -> str:
    if not path.is_file():
        return 'not_found'
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_tail_lines(path: Path, max_lines: int = 1000) -> str:
    if not path.is_file():
        return ''
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        return '\n'.join(lines[-max_lines:])
    except Exception as e:
        return f'error reading file: {e}'


def main():
    parser = argparse.ArgumentParser(description='Export Dark Blood emulator diagnostics bundle.')
    parser.add_argument('--output', '-o', type=str, default=None, help='Output ZIP archive path.')
    parser.add_argument('--lines', '-n', type=int, default=1000, help='Maximum wire lines to include.')
    args = parser.parse_args()

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    out_path = Path(args.output or (REPO_ROOT / f'darkblood_diagnostics_{timestamp}.zip'))

    git_info = get_git_info()
    sys_info = {
        'timestamp': timestamp,
        'os': platform.system(),
        'os_release': platform.release(),
        'os_version': platform.version(),
        'architecture': platform.machine(),
        'python_version': sys.version,
        'git': git_info,
    }

    # Locate client binary
    client_exe = REPO_ROOT / 'research' / 'client' / 'DarkBlood.exe'
    client_hash = hash_file(client_exe)
    sys_info['client_exe_sha256'] = client_hash

    # Find wire.jsonl
    wire_paths = [
        REPO_ROOT / 'wire.jsonl',
        REPO_ROOT / 'data' / 'wire.jsonl',
    ]
    # Check temp dirs
    wire_content = ''
    wire_source = None
    for p in wire_paths:
        if p.is_file():
            wire_content = get_tail_lines(p, args.lines)
            wire_source = str(p.relative_to(REPO_ROOT))
            break
    sys_info['wire_source'] = wire_source

    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. System info
        zf.writestr('system_info.json', json.dumps(sys_info, indent=2))

        # 2. Wire log snippet
        if wire_content:
            zf.writestr('wire_recent.jsonl', wire_content)

        # 3. Characters state
        char_path = REPO_ROOT / 'data' / 'darkblood.db'
        if char_path.is_file():
            zf.write(char_path, 'darkblood.db')

        # 4. Handler map
        hmap_path = REPO_ROOT / 'research' / 'client' / 'handler_map.txt'
        if hmap_path.is_file():
            zf.write(hmap_path, 'handler_map.txt')

        # 5. Opcodes TSV
        opcodes_tsv = REPO_ROOT / 'assets' / 'opcodes.tsv'
        if opcodes_tsv.is_file():
            zf.write(opcodes_tsv, 'opcodes.tsv')

    print(f'[+] Diagnostic bundle created: {out_path.resolve()}')
    print(f'    SHA-256 of bundle: {hash_file(out_path)}')
    print('\nPlease attach this ZIP file to your GitHub Issue.')


if __name__ == '__main__':
    main()
