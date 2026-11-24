"""GitHub Releases self-updater for Dark Blood Server Emulator.

Pure release-based updater (no git dependency):
  1. Checks `releases/latest/download/manifest.json` (no GitHub REST API rate-limit),
     falling back to the GitHub Releases API if a legacy release lacks `manifest.json`.
  2. Compares semantic versions (`vMAJOR.MINOR.PATCH[-prerelease]`) so downgrades are
     never offered.
  3. Streams the release `.zip` to a temporary file with optional progress callbacks,
     verifies its SHA-256 digest before touching the installation, stages extraction,
     applies changes with rollback on failure, and removes orphaned managed files while
     preserving all user data (`data/`, `research/`, `logs/`, `*.db`, `*.ini`, `*.log`).
  4. Development git checkouts (`.git` present) are detected as `dev` mode and left
     untouched so contributors manage updates with git directly.
"""
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, 'frozen', False)
    else Path(__file__).resolve().parent.parent
)
LAUNCHER_EXE_NAME = 'DarkBloodLauncher.exe'
GITHUB_REPO = 'saitatter/darkblood-server-emulator'
GITHUB_MANIFEST_URL = f'https://github.com/{GITHUB_REPO}/releases/latest/download/manifest.json'
GITHUB_RELEASE_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
GITHUB_RELEASE_DOWNLOAD = f'https://github.com/{GITHUB_REPO}/releases/download'
VERSION_FILE = '.version'
MANIFEST_FILE = '.manifest.json'
USER_AGENT = 'DarkBlood-Launcher-Updater'

# Top-level directories and file suffixes never modified or deleted during updates.
PROTECTED_DIRS = frozenset({'data', 'research', 'logs', '.git', '__pycache__', '.update_staging'})
PROTECTED_SUFFIXES = frozenset({'.db', '.db-wal', '.db-shm', '.ini', '.log', '.key'})

_SEMVER_RE = re.compile(r'^v?(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$')


@dataclass
class ReleaseInfo:
    version: str
    zip_url: str
    zip_sha256: str = ''
    zip_size: int = 0
    files: tuple = ()


@dataclass
class UpdateStatus:
    mode: str                 # 'release' | 'dev'
    current_version: str = ''
    remote_version: str = ''
    up_to_date: bool = True
    error: str = ''
    download_url: str = ''
    zip_sha256: str = ''
    zip_size: int = 0

    @property
    def short_current(self) -> str:
        return self.current_version or 'unknown'

    @property
    def short_remote(self) -> str:
        return self.remote_version or 'unknown'


@dataclass
class UpdateResult:
    ok: bool
    mode: str
    old_version: str = ''
    new_version: str = ''
    message: str = ''
    hook_changed: bool = False
    launcher_changed: bool = False
    files_updated: int = 0
    files_removed: int = 0


def is_dev_checkout(root: Path = ROOT) -> bool:
    """Return True when `root` is a git development checkout."""
    return (Path(root) / '.git').exists()


def parse_version(tag: str):
    """Parse a release tag like `v0.2.1-alpha` into a comparable tuple.

    Stable releases sort higher than pre-releases of the same numeric version:
    `v0.1.0-alpha < v0.1.0-beta < v0.1.0 < v0.2.0`.
    Returns None if `tag` is not a recognized semantic version.
    """
    m = _SEMVER_RE.match((tag or '').strip())
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    pre = m.group(4)
    if not pre:
        return (major, minor, patch, 1, ())
    pre_parts = tuple(
        (0, int(p)) if p.isdigit() else (1, p.lower())
        for p in pre.split('.')
    )
    return (major, minor, patch, 0, pre_parts)


def is_newer_version(current: str, remote: str) -> bool:
    """Return True if `remote` is strictly newer than `current`."""
    remote = (remote or '').strip()
    current = (current or '').strip()
    if not remote:
        return False
    if not current:
        return True
    if current == remote:
        return False
    p_cur = parse_version(current)
    p_rem = parse_version(remote)
    if p_cur is not None and p_rem is not None:
        return p_rem > p_cur
    return current != remote


def current_installed_version(root: Path = ROOT) -> str:
    """Return the installed release version from `.version`, or '' if unknown."""
    ver_file = Path(root) / VERSION_FILE
    if ver_file.is_file():
        return ver_file.read_text(encoding='utf-8', errors='replace').strip()
    return ''


def _fetch_json(url: str, timeout: int = 10, accept: str = 'application/json') -> dict:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': USER_AGENT, 'Accept': accept},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _fetch_text(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def _fetch_latest_manifest(timeout: int = 10):
    """Fetch `manifest.json` from the latest GitHub Release (no REST API rate-limit).

    Returns ReleaseInfo or None if the latest release does not include `manifest.json`.
    """
    try:
        data = _fetch_json(GITHUB_MANIFEST_URL, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    version = (data.get('version') or '').strip()
    zip_name = (data.get('zip_name') or '').strip()
    zip_url = (data.get('zip_url') or '').strip()
    if not zip_url and version and zip_name:
        zip_url = f'{GITHUB_RELEASE_DOWNLOAD}/{version}/{zip_name}'
    if not version or not zip_url:
        return None
    return ReleaseInfo(
        version=version,
        zip_url=zip_url,
        zip_sha256=(data.get('zip_sha256') or '').strip().lower(),
        zip_size=int(data.get('zip_size') or 0),
        files=tuple(data.get('files') or ()),
    )


def _fetch_latest_release_api(timeout: int = 10):
    """Fallback to GitHub Releases REST API for releases published without `manifest.json`."""
    try:
        data = _fetch_json(GITHUB_RELEASE_API, timeout=timeout, accept='application/vnd.github+json')
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if data.get('draft'):
        return None
    version = (data.get('tag_name') or '').strip()
    zip_url = ''
    zip_size = 0
    sha_url = ''
    for asset in data.get('assets') or []:
        name = (asset.get('name') or '').lower()
        url = asset.get('browser_download_url') or ''
        if name.endswith('.zip') and not zip_url:
            zip_url = url
            zip_size = int(asset.get('size') or 0)
        elif name.endswith('.zip.sha256') and not sha_url:
            sha_url = url
    if not version or not zip_url:
        return None
    zip_sha256 = ''
    if sha_url:
        try:
            first_token = _fetch_text(sha_url, timeout=timeout).strip().split()[0].lower()
            if re.fullmatch(r'[0-9a-f]{64}', first_token):
                zip_sha256 = first_token
        except Exception:
            pass
    return ReleaseInfo(version=version, zip_url=zip_url, zip_sha256=zip_sha256, zip_size=zip_size)


def fetch_latest_release(timeout: int = 10):
    """Return ReleaseInfo for the latest published GitHub Release, or None."""
    info = _fetch_latest_manifest(timeout=timeout)
    if info is not None:
        return info
    return _fetch_latest_release_api(timeout=timeout)


def check_for_updates(root: Path = ROOT, timeout: int = 10) -> UpdateStatus:
    """Check whether a newer published GitHub Release is available for `root`."""
    root = Path(root)
    current_ver = current_installed_version(root)
    if is_dev_checkout(root):
        return UpdateStatus(
            mode='dev',
            current_version=current_ver or 'dev',
            up_to_date=True,
        )
    try:
        info = fetch_latest_release(timeout=timeout)
    except Exception as exc:
        return UpdateStatus(mode='release', current_version=current_ver, up_to_date=True, error=str(exc))
    if info is None:
        return UpdateStatus(
            mode='release',
            current_version=current_ver,
            up_to_date=True,
            error='No published release found on GitHub.',
        )
    newer = is_newer_version(current_ver, info.version)
    return UpdateStatus(
        mode='release',
        current_version=current_ver,
        remote_version=info.version,
        up_to_date=not newer,
        download_url=info.zip_url,
        zip_sha256=info.zip_sha256,
        zip_size=info.zip_size,
    )


def cleanup_old_binaries(root: Path = ROOT) -> int:
    """Remove leftover `.old` executables renamed during a Windows self-update."""
    root = Path(root)
    removed = 0
    for old in root.glob('*.old'):
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _is_protected(rel_path: Path) -> bool:
    if not rel_path.parts:
        return True
    if any(p in ('', '.', '..') for p in rel_path.parts):
        return True
    if rel_path.parts[0] in PROTECTED_DIRS:
        return True
    if rel_path.suffix.lower() in PROTECTED_SUFFIXES:
        return True
    return False


def _deploy_prebuilt_dll(root: Path) -> bool:
    """Copy prebuilt client_hook/steam_api.dll to research/client/steam_api.dll when client dir exists."""
    src_dll = root / 'client_hook' / 'steam_api.dll'
    dst_dir = root / 'research' / 'client'
    if src_dll.is_file() and dst_dir.is_dir():
        try:
            shutil.copy2(src_dll, dst_dir / 'steam_api.dll')
            return True
        except OSError:
            return False
    return False


def _write_replacing_locked(dest: Path, data: bytes) -> None:
    """Write `data` to `dest`, renaming aside a running Windows executable if locked."""
    try:
        dest.write_bytes(data)
    except PermissionError:
        backup = dest.with_name(dest.name + '.old')
        if backup.exists():
            try:
                backup.unlink()
            except OSError:
                pass
        dest.rename(backup)
        dest.write_bytes(data)


def _download_to_file(url: str, dest: Path, expected_size: int = 0,
                      on_progress=None, timeout: int = 60) -> str:
    """Stream `url` to `dest`, invoking `on_progress(downloaded, total)`, and return SHA-256 hex."""
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    hasher = hashlib.sha256()
    downloaded = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        header_len = resp.headers.get('Content-Length')
        total = int(header_len) if (header_len and header_len.isdigit()) else expected_size
        with dest.open('wb') as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)
    return hasher.hexdigest()


def _read_previous_manifest_files(root: Path) -> set:
    mf = root / MANIFEST_FILE
    if not mf.is_file():
        return set()
    try:
        data = json.loads(mf.read_text(encoding='utf-8', errors='replace'))
        return {str(p) for p in (data.get('files') or []) if isinstance(p, str)}
    except Exception:
        return set()


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    cur = path.parent
    while cur != stop_at and cur != cur.parent:
        try:
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def apply_zip_archive(root: Path, zip_source, new_version: str = '',
                      expected_sha256: str = '') -> UpdateResult:
    """Verify, stage, and apply a release ZIP onto `root`, preserving local user data.

    `zip_source` may be a `Path` to a ZIP file on disk or raw `bytes`.
    """
    root = Path(root).resolve()
    old_version = current_installed_version(root)

    if isinstance(zip_source, (str, Path)):
        zip_path = Path(zip_source)
        if expected_sha256:
            h = hashlib.sha256()
            with zip_path.open('rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
            actual = h.hexdigest().lower()
            if actual != expected_sha256.lower():
                return UpdateResult(
                    ok=False, mode='release', old_version=old_version,
                    message=f'SHA-256 mismatch (expected {expected_sha256[:12]}, got {actual[:12]}).',
                )
        zf_ctx = zipfile.ZipFile(zip_path, 'r')
    else:
        raw_bytes = bytes(zip_source)
        if expected_sha256:
            actual = hashlib.sha256(raw_bytes).hexdigest().lower()
            if actual != expected_sha256.lower():
                return UpdateResult(
                    ok=False, mode='release', old_version=old_version,
                    message=f'SHA-256 mismatch (expected {expected_sha256[:12]}, got {actual[:12]}).',
                )
        zf_ctx = zipfile.ZipFile(io.BytesIO(raw_bytes), 'r')

    staging = root / '.update_staging'
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    staged_files = []  # list of (rel_path: Path, staged_path: Path)
    managed_posix = set()
    backups = []       # list of (dest: Path, prev_bytes: bytes | None)
    updated = 0
    removed = 0
    hook_changed = False
    launcher_changed = False

    try:
        # Phase 1: extract all allowed files into staging directory
        with zf_ctx as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                parts = Path(info.filename).parts
                rel_parts = parts[1:] if len(parts) > 1 else parts
                if not rel_parts:
                    continue
                rel_path = Path(*rel_parts)
                if _is_protected(rel_path):
                    continue
                if rel_path.as_posix() in (VERSION_FILE, MANIFEST_FILE):
                    continue
                dest = (root / rel_path).resolve()
                try:
                    dest.relative_to(root)
                except ValueError:
                    continue
                staged_dest = staging / rel_path
                staged_dest.parent.mkdir(parents=True, exist_ok=True)
                staged_dest.write_bytes(zf.read(info))
                staged_files.append((rel_path, staged_dest))
                managed_posix.add(rel_path.as_posix())

        # Phase 2: apply staged files to root (recording backups for rollback)
        for rel_path, staged_dest in staged_files:
            dest = (root / rel_path).resolve()
            new_data = staged_dest.read_bytes()
            prev_data = dest.read_bytes() if dest.exists() else None
            if prev_data == new_data:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            backups.append((dest, prev_data))
            _write_replacing_locked(dest, new_data)
            updated += 1
            rel_posix = rel_path.as_posix()
            if rel_posix.startswith('client_hook/'):
                hook_changed = True
            if rel_posix in ('tools/launcher.py', 'tools/updater.py', LAUNCHER_EXE_NAME):
                launcher_changed = True

        # Phase 3: remove orphaned files that belonged to the previous release manifest
        prev_managed = _read_previous_manifest_files(root)
        for old_rel in sorted(prev_managed - managed_posix):
            rel_path = Path(old_rel)
            if _is_protected(rel_path):
                continue
            victim = (root / rel_path).resolve()
            try:
                victim.relative_to(root)
            except ValueError:
                continue
            if victim.is_file():
                try:
                    victim.unlink()
                    _prune_empty_parents(victim, root)
                    removed += 1
                except OSError:
                    pass

        # Phase 4: persist new version and manifest
        if new_version:
            (root / VERSION_FILE).write_text(new_version + '\n', encoding='utf-8')
        manifest_payload = {
            'schema': 1,
            'version': new_version,
            'files': sorted(managed_posix),
        }
        (root / MANIFEST_FILE).write_text(json.dumps(manifest_payload, indent=2) + '\n', encoding='utf-8')
    except Exception as exc:
        # Roll back any files modified before the failure
        for dest, prev_data in reversed(backups):
            try:
                if prev_data is None:
                    if dest.exists():
                        dest.unlink()
                else:
                    dest.write_bytes(prev_data)
            except OSError:
                pass
        return UpdateResult(
            ok=False, mode='release', old_version=old_version,
            message=f'Update failed and was rolled back: {exc}',
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    dll_deployed = False
    if (root / 'client_hook' / 'steam_api.dll').is_file():
        dll_deployed = _deploy_prebuilt_dll(root)

    label = new_version or 'latest'
    extras = []
    if removed:
        extras.append(f'{removed} removed')
    if dll_deployed:
        extras.append('steam_api.dll deployed')
    extra_txt = f' ({", ".join(extras)})' if extras else ''
    return UpdateResult(
        ok=True,
        mode='release',
        old_version=old_version,
        new_version=new_version,
        message=f'Updated {updated} file(s) to {label}.{extra_txt}',
        hook_changed=hook_changed and not dll_deployed,
        launcher_changed=launcher_changed,
        files_updated=updated,
        files_removed=removed,
    )


def apply_update(root: Path = ROOT, on_progress=None) -> UpdateResult:
    """Download, verify, and apply the latest published GitHub Release onto `root`."""
    root = Path(root)
    if is_dev_checkout(root):
        return UpdateResult(
            ok=False,
            mode='dev',
            old_version=current_installed_version(root) or 'dev',
            message='Development git checkout detected; update using git instead.',
        )
    try:
        info = fetch_latest_release()
        if info is None:
            return UpdateResult(ok=False, mode='release', message='No published release found on GitHub.')
        current_ver = current_installed_version(root)
        if not is_newer_version(current_ver, info.version):
            return UpdateResult(
                ok=True, mode='release', old_version=current_ver, new_version=info.version,
                message=f'Already up to date ({current_ver or info.version}).',
            )
        with tempfile.TemporaryDirectory(prefix='darkblood_update_') as tmp_dir:
            zip_file = Path(tmp_dir) / 'release.zip'
            actual_sha = _download_to_file(
                info.zip_url, zip_file, expected_size=info.zip_size, on_progress=on_progress,
            )
            if info.zip_sha256 and actual_sha.lower() != info.zip_sha256.lower():
                return UpdateResult(
                    ok=False, mode='release', old_version=current_ver,
                    message=f'Download corrupted: SHA-256 mismatch '
                            f'(expected {info.zip_sha256[:12]}, got {actual_sha[:12]}).',
                )
            return apply_zip_archive(root, zip_file, new_version=info.version)
    except Exception as exc:
        return UpdateResult(ok=False, mode='release', message=f'Release update failed: {exc}')


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if '--apply' in args:
        res = apply_update()
        print(res.message)
        return 0 if res.ok else 1
    st = check_for_updates()
    if st.mode == 'dev':
        print(f'Development git checkout ({st.short_current}); self-updater disabled.')
        return 0
    if st.error:
        print(f'Update check failed: {st.error}', file=sys.stderr)
        return 1
    if st.up_to_date:
        print(f'Up to date ({st.short_current}).')
        return 0
    print(f'Update available: {st.short_current} -> {st.short_remote}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
