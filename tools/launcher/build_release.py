#!/usr/bin/env python3
"""Build a portable Windows release ZIP for Dark Blood Online Offline Server Emulator.

Produces `dist/DarkBlood-Emulator-<version>-win32.zip` (plus `.sha256`) containing:
  - Standalone `DarkBloodLauncher.exe` (PyInstaller bundle with embedded GUI + server;
    no Python or Visual Studio required)
  - Normalized game tables (`assets/`)
  - Prebuilt `client_hook/steam_api.dll`
  - Documentation (`README.md`, `LICENSE`, `docs/GM_COMMANDS.md`, `RELEASE_NOTES.md`)
  - `.version` marker used by `tools/launcher/updater.py`

Strictly excludes user data (`data/`, `research/`, `logs/`, `.git/`, `*.db`, `*.ini`).
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'launcher'))
sys.path.insert(0, str(ROOT / 'tools' / 'automation'))
HOOK_BUILD_BAT = ROOT / 'client_hook' / 'build.bat'
HOOK_DLL = ROOT / 'client_hook' / 'steam_api.dll'
LAUNCHER_EXE_NAME = 'DarkBloodLauncher.exe'

INCLUDE_ROOT_FILES = (
    'README.md',
    'LICENSE',
)

INCLUDE_SOURCE_ROOT_FILES = (
    'run_server.py',
)

INCLUDE_DOC_FILES = (
    'docs/GM_COMMANDS.md',
)

INCLUDE_TOOLS = (
    'tools/launcher/launcher.py',
    'tools/launcher/updater.py',
    'tools/launcher/dashboard.py',
    'tools/launcher/patcher.py',
    'tools/automation/gamectl.py',
    'tools/automation/multibox.py',
    'tools/automation/headless_client.py',
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


def build_launcher_exe(output_dir: Path = None, root: Path = ROOT) -> Path:
    """Build standalone DarkBloodLauncher.exe using PyInstaller (embeds GUI + server)."""
    out_dir = Path(output_dir or (root / 'dist'))
    work_dir = out_dir / 'pyinstaller_build'
    out_dir.mkdir(parents=True, exist_ok=True)
    ico_path = root / 'assets' / 'darkblood.ico'
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--onefile',
        '--windowed',
        '--noconfirm',
        '--clean',
        '--name', 'DarkBloodLauncher',
        '--distpath', str(out_dir),
        '--workpath', str(work_dir),
        '--specpath', str(work_dir),
        '--paths', str(root / 'src'),
        '--paths', str(root / 'tools' / 'launcher'),
        '--paths', str(root / 'tools' / 'automation'),
        '--collect-submodules', 'darkblood',
        '--collect-submodules', 'launcher_app',
        '--hidden-import', 'gamectl',
        '--hidden-import', 'multibox',
        '--hidden-import', 'updater',
    ]
    if ico_path.is_file():
        cmd += ['--icon', str(ico_path)]
    cmd.append(str(root / 'tools' / 'launcher' / 'launcher.py'))
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f'PyInstaller build failed:\n{proc.stdout}\n{proc.stderr}')
    exe_path = out_dir / LAUNCHER_EXE_NAME
    if not exe_path.is_file():
        raise FileNotFoundError(f'Expected built launcher executable at {exe_path}')
    return exe_path


def iter_release_files(root: Path = ROOT, exe_path: Path = None):
    """Yield (source_path, archive_rel_posix) pairs for the portable release archive."""
    if exe_path is not None and Path(exe_path).is_file():
        yield Path(exe_path), LAUNCHER_EXE_NAME
        root_files = INCLUDE_ROOT_FILES + INCLUDE_DOC_FILES
        subdirs = ('assets',)
    else:
        root_files = INCLUDE_ROOT_FILES + INCLUDE_SOURCE_ROOT_FILES + INCLUDE_DOC_FILES + INCLUDE_TOOLS
        subdirs = ('src/darkblood', 'assets', 'tools/launcher/launcher_app')

    for rel in root_files:
        p = root / rel
        if p.is_file():
            yield p, rel

    for subdir in subdirs:
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
                       require_dll: bool = True, exe_path: Path = None) -> Path:
    output_dir = Path(output_dir or (root / 'dist'))
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_ver = version.replace('/', '-').replace('\\', '-')
    top_dir = f'DarkBlood-Emulator-{safe_ver}'
    zip_path = output_dir / f'{top_dir}-win32.zip'

    if require_dll and not (root / 'client_hook' / 'steam_api.dll').is_file():
        raise FileNotFoundError('client_hook/steam_api.dll is missing; build it first or omit --skip-build')

    count = 0
    managed_files = []
    notes_text = generate_release_notes(version, zip_path.name, '(see .sha256)', root=root)
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, rel in iter_release_files(root, exe_path=exe_path):
            zf.write(src, f'{top_dir}/{rel}')
            managed_files.append(rel)
            count += 1
        zf.writestr(f'{top_dir}/.version', version + '\n')
        zf.writestr(f'{top_dir}/RELEASE_NOTES.md', notes_text)
        managed_files.append('RELEASE_NOTES.md')
        count += 2

    zip_bytes = zip_path.read_bytes()
    sha256 = hashlib.sha256(zip_bytes).hexdigest()
    (output_dir / f'{zip_path.name}.sha256').write_text(f'{sha256}  {zip_path.name}\n', encoding='utf-8')
    manifest = {
        'schema': 1,
        'version': version,
        'zip_name': zip_path.name,
        'zip_sha256': sha256,
        'zip_size': len(zip_bytes),
        'files': sorted(set(managed_files)),
    }
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    notes_path = output_dir / 'RELEASE_NOTES.md'
    notes_path.write_text(generate_release_notes(version, zip_path.name, sha256, root=root), encoding='utf-8')
    print(f'Built {zip_path} ({count} files, {zip_path.stat().st_size:,} bytes, sha256={sha256[:12]}...)')
    return zip_path


_COMMIT_RE = re.compile(r'^(feat|fix|refactor|perf|docs|test|chore|ci|build)(?:\(([^)]+)\))?!?:\s*(.+)$', re.I)


def _prev_tag(version: str, root: Path) -> str:
    """Find the closest release tag in the history of the source being packaged."""
    try:
        proc = subprocess.run(
            ['git', 'describe', '--tags', '--abbrev=0', '--match=v*',
             f'--exclude={version}', 'HEAD'],
            cwd=str(root), capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ''


def generate_release_notes(version: str, zip_name: str, zip_sha256: str, root: Path = ROOT) -> str:
    """Build structured Markdown release notes from all commits since the previous tag."""
    prev = _prev_tag(version, root)
    rev_range = f'{prev}..HEAD' if prev else 'HEAD'
    commits = []
    try:
        proc = subprocess.run(
            ['git', 'log', rev_range, '--no-merges', '--pretty=format:%h\x1f%an\x1f%ae\x1f%s'],
            cwd=str(root), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
        )
        if proc.returncode == 0:
            try:
                from launcher import _resolve_github_username
            except Exception:
                _resolve_github_username = lambda n, e='', l='': n
            for line in proc.stdout.splitlines():
                parts = line.split('\x1f')
                if len(parts) != 4:
                    continue
                sha, name, email, subj = parts
                if '[skip ci]' in subj or 'github-actions[bot]' in name.lower():
                    continue
                user = _resolve_github_username(name, email)
                commits.append((sha, user, subj))
    except Exception:
        pass

    sections = {'feat': [], 'fix': [], 'refactor': [], 'other': []}
    for sha, user, subj in commits:
        m = _COMMIT_RE.match(subj)
        if m:
            kind, scope, desc = m.group(1).lower(), m.group(2), m.group(3)
            prefix = f'**{scope}**: ' if scope else ''
            bullet = f'- {prefix}{desc} (`{sha}`, @{user})'
            if kind == 'feat':
                sections['feat'].append(bullet)
            elif kind == 'fix':
                sections['fix'].append(bullet)
            elif kind in ('refactor', 'perf'):
                sections['refactor'].append(bullet)
            else:
                sections['other'].append(bullet)
        else:
            sections['other'].append(f'- {subj} (`{sha}`, @{user})')

    out = [
        '### Quick Start (Standalone Windows Release — no Python or Visual Studio required)',
        '1. Download and extract `' + zip_name + '`.',
        '2. Run `DarkBloodLauncher.exe`.',
        '3. Click **`Client Missing • Click to Setup`** in the top-right header and select your `DarkBlood.exe` (Steam build `1.6.5#0`, SHA-256 `a82ae3d71b596418c1f3593cb63d3f9746318d452143c2e88f6ebbaff339c931`). The launcher stages `research/client/`, links `Data/` via junction, and deploys the prebuilt `steam_api.dll` automatically.',
        '4. Click **`Start Local Server`** and **`▶ PLAY DARK BLOOD`**.',
        '',
        '### Highlights' if not prev else f'### Changes since `{prev}` ({len(commits)} commits)',
        '',
    ]
    if not prev:
        out += [
            '- **Connection & Transport**: Full ProudNet RSA-OAEP + AES handshake (optimized GF(2^8) tables), framing, TCP stream reassembly, and local square/room relay (`127.0.0.1:9400` / `9401`).',
            '- **Standalone Launcher & Auto-Updater**: Zero-install `DarkBloodLauncher.exe` (Bifrost dark UI + embedded server), live repository news feed, modular patch toggles, 1-click client staging, 1–4 client 2×2 grid multibox, and automatic GitHub Releases self-updater.',
            '- **Modular x86 Client Hook (`steam_api.dll` prebuilt)**: IPv4 `connect`/`WSAConnect` redirection, borderless fullscreen, lobby auto-reconnect on disconnect, 100 ms town peer sync, optional skip logos / skip tutorial.',
            '- **Lobby, World & Multiplayer**: Server/channel lists, character creation/deletion/undeletion, SQLite persistence (WAL mode), two-client town presence, chat/whispers, friends/blocklist/memos, character inspect, and party rooms with host promotion.',
            '- **Dungeons, Combat, Quests & Progression**: Tutorial & Act 1 dungeons, difficulty gate history, monster EXP/level-up, loot drops/pickup, stress (fatigue) & dungeon leave penalty timers, quest kill/item/dungeon-clear tracking (964/964 mission chains), end-of-dungeon rank & chest rewards, achievements, and native GM console (123 commands).',
            '- **Inventory, Skills & Economy**: Bags, equipment, dyeing, durability loss & repair, crafting/enchanting/avatar zam, storage/depot, skills & dual skill trees, NPC shops with full sell & repurchase, offline Steam Cash Shop, P2P trade, personal stalls, broker, mail, fishing, pets, guilds, and arena.',
            f'- **Protocol & Verification**: **801/1098 opcodes (73%)**, **88% named fields**, 17 schema-generated `WireMessage` domains, and **219 automated headless tests** (including fuzzing and 10-client concurrency).',
            '',
            f'<details><summary>Detailed changelog ({len(commits)} commits)</summary>',
            '',
        ]

    for title, key in (
        ('Features', 'feat'),
        ('Bug Fixes', 'fix'),
        ('Refactoring & Performance', 'refactor'),
        ('Docs, Tests & Tooling', 'other'),
    ):
        if sections[key]:
            out.append(f'#### {title} ({len(sections[key])})')
            out.extend(sections[key])
            out.append('')

    if not prev:
        out.append('</details>')
        out.append('')

    out += [
        '### Checksum',
        '```text',
        f'{zip_sha256}  {zip_name}',
        '```',
        '',
    ]
    if prev:
        out.append(f'**Full Changelog**: https://github.com/saitatter/darkblood-server-emulator/compare/{prev}...{version}')
    else:
        out.append(f'**Full Changelog**: https://github.com/saitatter/darkblood-server-emulator/commits/{version}')
    return '\n'.join(out) + '\n'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default=None, help='Release version/tag (default: git describe)')
    parser.add_argument('--output', default=None, help='Output directory (default: dist/)')
    parser.add_argument('--skip-build', action='store_true', help='Skip running client_hook/build.bat')
    parser.add_argument('--exe', default=None, help='Path to a prebuilt DarkBloodLauncher.exe to package')
    parser.add_argument('--skip-exe', action='store_true',
                        help='Skip building DarkBloodLauncher.exe with PyInstaller (package Python sources instead)')
    args = parser.parse_args(argv)

    version = args.version or detect_version()
    out_dir = Path(args.output) if args.output else None
    if not args.skip_build:
        build_hook_dll()
    exe_path = Path(args.exe) if args.exe else None
    if exe_path is None and not args.skip_exe:
        exe_path = build_launcher_exe(output_dir=out_dir)
    create_release_zip(version, output_dir=out_dir, exe_path=exe_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
