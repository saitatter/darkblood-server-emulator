#!/usr/bin/env python3
"""Build a portable Windows release ZIP for Dark Blood Online Offline Server Emulator.

Produces `dist/DarkBlood-Emulator-<version>-win32.zip` (plus `.sha256`) containing:
  - Python server package (`src/darkblood/`)
  - Normalized game tables (`assets/`)
  - Launcher, updater and CLI tools (`tools/`)
  - Prebuilt `client_hook/steam_api.dll` (so players need no Visual Studio / MSVC)
  - Entry scripts (`run_server.py`, `Launch_DarkBlood.bat`, `Play_DarkBlood.bat`)
  - `.version` marker used by `tools/updater.py`

Strictly excludes user data (`data/`, `research/`, `logs/`, `.git/`, `*.db`, `*.ini`).
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
HOOK_BUILD_BAT = ROOT / 'client_hook' / 'build.bat'
HOOK_DLL = ROOT / 'client_hook' / 'steam_api.dll'

INCLUDE_ROOT_FILES = (
    'run_server.py',
    'Launch_DarkBlood.bat',
    'Play_DarkBlood.bat',
    'README.md',
    'LICENSE',
)

INCLUDE_DOC_FILES = (
    'docs/GM_COMMANDS.md',
)

INCLUDE_TOOLS = (
    'tools/launcher.py',
    'tools/updater.py',
    'tools/gamectl.py',
    'tools/multibox.py',
    'tools/dashboard.py',
    'tools/patcher.py',
    'tools/headless_client.py',
)

EXCLUDED_SUFFIXES = frozenset({'.pyc', '.pyo', '.obj', '.lib', '.exp', '.pdb', '.ilk', '.log', '.db'})


def detect_version() -> str:
    try:
        proc = subprocess.run(
            ['git', 'describe', '--tags', '--always'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return 'dev'


def build_hook_dll() -> Path:
    if not HOOK_BUILD_BAT.is_file():
        raise FileNotFoundError(f'Missing hook build script: {HOOK_BUILD_BAT}')
    proc = subprocess.run(
        ['cmd.exe', '/c', str(HOOK_BUILD_BAT)],
        cwd=str(HOOK_BUILD_BAT.parent),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'steam_api.dll build failed:\n{proc.stdout}\n{proc.stderr}')
    if not HOOK_DLL.is_file():
        raise FileNotFoundError(f'Expected built DLL at {HOOK_DLL}')
    return HOOK_DLL


def iter_release_files(root: Path = ROOT):
    """Yield (source_path, archive_rel_posix) pairs for the portable release archive."""
    for rel in INCLUDE_ROOT_FILES + INCLUDE_DOC_FILES + INCLUDE_TOOLS:
        p = root / rel
        if p.is_file():
            yield p, rel

    for subdir in ('src/darkblood', 'assets'):
        base = root / subdir
        if not base.is_dir():
            continue
        for p in sorted(base.rglob('*')):
            if not p.is_file():
                continue
            if '__pycache__' in p.parts or p.suffix.lower() in EXCLUDED_SUFFIXES:
                continue
            yield p, p.relative_to(root).as_posix()

    dll = root / 'client_hook' / 'steam_api.dll'
    if dll.is_file():
        yield dll, 'client_hook/steam_api.dll'


def create_release_zip(version: str, output_dir: Path = None, root: Path = ROOT,
                       require_dll: bool = True) -> Path:
    output_dir = Path(output_dir or (root / 'dist'))
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_ver = version.replace('/', '-').replace('\\', '-')
    top_dir = f'DarkBlood-Emulator-{safe_ver}'
    zip_path = output_dir / f'{top_dir}-win32.zip'

    if require_dll and not (root / 'client_hook' / 'steam_api.dll').is_file():
        raise FileNotFoundError('client_hook/steam_api.dll is missing; build it first or omit --skip-build')

    count = 0
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, rel in iter_release_files(root):
            zf.write(src, f'{top_dir}/{rel}')
            count += 1
        zf.writestr(f'{top_dir}/.version', version + '\n')
        count += 1

    sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (output_dir / f'{zip_path.name}.sha256').write_text(f'{sha256}  {zip_path.name}\n', encoding='utf-8')
    print(f'Built {zip_path} ({count} files, {zip_path.stat().st_size:,} bytes, sha256={sha256[:12]}...)')
    return zip_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default=None, help='Release version/tag (default: git describe)')
    parser.add_argument('--output', default=None, help='Output directory (default: dist/)')
    parser.add_argument('--skip-build', action='store_true', help='Skip running client_hook/build.bat')
    args = parser.parse_args(argv)

    version = args.version or detect_version()
    if not args.skip_build:
        build_hook_dll()
    create_release_zip(version, output_dir=Path(args.output) if args.output else None)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
