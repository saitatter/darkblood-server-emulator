"""GitHub self-updater for Dark Blood Server Emulator (git clone + portable ZIP modes).

Supports:
  1. Git repositories (.git present): `git fetch origin main` + `git pull --ff-only`
     (with optional autostash/rebase when local commits exist).
  2. Portable ZIP installs (no .git): checks the latest commit SHA on GitHub's
     `main` branch, downloads the archive, and extracts updated source files while
     preserving user data (`data/`, `research/`, `logs/`, `*.db`, `*.ini`, `*.log`).
"""
from dataclasses import dataclass
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
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
GITHUB_BRANCH = 'main'
GITHUB_COMMIT_API = f'https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}'
GITHUB_RELEASE_API = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
GITHUB_ZIP_URL = f'https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip'
VERSION_FILE = '.version'

# Top-level directories and file suffixes preserved during portable ZIP updates.
PROTECTED_DIRS = frozenset({'data', 'research', 'logs', '.git', '__pycache__'})
PROTECTED_SUFFIXES = frozenset({'.db', '.db-wal', '.db-shm', '.ini', '.log', '.key'})


@dataclass
class UpdateStatus:
    mode: str                 # 'git' | 'release' | 'zip'
    current_sha: str = ''
    remote_sha: str = ''
    behind: int = 0
    ahead: int = 0
    dirty: bool = False
    up_to_date: bool = True
    error: str = ''
    download_url: str = ''

    @property
    def short_current(self) -> str:
        if not self.current_sha:
            return 'unknown'
        return self.current_sha if self.current_sha.startswith('v') else self.current_sha[:7]

    @property
    def short_remote(self) -> str:
        if not self.remote_sha:
            return 'unknown'
        return self.remote_sha if self.remote_sha.startswith('v') else self.remote_sha[:7]


@dataclass
class UpdateResult:
    ok: bool
    mode: str
    old_sha: str = ''
    new_sha: str = ''
    message: str = ''
    hook_changed: bool = False
    launcher_changed: bool = False
    files_updated: int = 0


def _run_git(root: Path, *args, timeout: int = 15):
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.run(
        ['git', *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
        creationflags=flags,
    )


def _has_git_repo(root: Path) -> bool:
    return (root / '.git').exists() and shutil.which('git') is not None


def _fetch_remote_sha_api(timeout: int = 8) -> str:
    req = urllib.request.Request(
        GITHUB_COMMIT_API,
        headers={'User-Agent': 'DarkBlood-Launcher-Updater', 'Accept': 'application/vnd.github+json'},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return (data.get('sha') or '').strip()


def _fetch_latest_release_api(timeout: int = 8):
    """Return (tag_name, zip_download_url) from GitHub Releases API, or (None, None) if no release exists.

    Only returns published (non-draft, non-prerelease) releases that include a release `.zip` asset.
    """
    req = urllib.request.Request(
        GITHUB_RELEASE_API,
        headers={'User-Agent': 'DarkBlood-Launcher-Updater', 'Accept': 'application/vnd.github+json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    if data.get('draft'):
        return None, None
    tag = (data.get('tag_name') or '').strip()
    zip_url = ''
    for asset in data.get('assets') or []:
        name = (asset.get('name') or '').lower()
        if name.endswith('.zip'):
            zip_url = asset.get('browser_download_url') or ''
            break
    if not zip_url:
        return None, None
    return (tag or None), zip_url


def _current_installed_release(root: Path) -> str:
    """Return the currently installed release tag (from `.version` or git tag), or ''."""
    ver_file = root / VERSION_FILE
    if ver_file.is_file():
        v = ver_file.read_text(encoding='utf-8').strip()
        if v:
            return v
    if _has_git_repo(root):
        try:
            exact = _run_git(root, 'describe', '--tags', '--exact-match', 'HEAD')
            if exact.returncode == 0 and exact.stdout.strip():
                return exact.stdout.strip()
            tags = _run_git(root, 'tag', '--sort=-creatordate', '--list', 'v*')
            if tags.returncode == 0 and tags.stdout.strip():
                return tags.stdout.splitlines()[0].strip()
        except Exception:
            pass
    return ''


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


def check_for_updates(root: Path = ROOT, remote: str = 'origin', branch: str = GITHUB_BRANCH,
                      releases_only: bool = True) -> UpdateStatus:
    """Check whether a newer published GitHub Release is available for `root`.

    When `releases_only=True` (default), updates are strictly restricted to published
    GitHub Releases — arbitrary unreleased commits on `main` are never offered.
    """
    root = Path(root)
    if releases_only:
        current_ver = _current_installed_release(root)
        try:
            tag, zip_url = _fetch_latest_release_api()
        except Exception as exc:
            return UpdateStatus(mode='release', current_sha=current_ver, up_to_date=True, error=str(exc))
        if not tag or not zip_url:
            return UpdateStatus(
                mode='release',
                current_sha=current_ver,
                up_to_date=True,
                error='No published release found on GitHub.',
            )
        up_to_date = bool(current_ver and current_ver == tag)
        return UpdateStatus(
            mode='release',
            current_sha=current_ver,
            remote_sha=tag,
            behind=0 if up_to_date else 1,
            up_to_date=up_to_date,
            download_url=zip_url,
        )

    if _has_git_repo(root):
        try:
            cur = _run_git(root, 'rev-parse', 'HEAD')
            current_sha = cur.stdout.strip() if cur.returncode == 0 else ''
            dirty_proc = _run_git(root, 'status', '--porcelain')
            dirty = bool(dirty_proc.stdout.strip()) if dirty_proc.returncode == 0 else False

            fetch = _run_git(root, 'fetch', remote, branch, '--quiet', timeout=20)
            if fetch.returncode != 0:
                err = (fetch.stderr or fetch.stdout or 'git fetch failed').strip().splitlines()[-1]
                return UpdateStatus(mode='git', current_sha=current_sha, dirty=dirty, up_to_date=True, error=err)

            rem = _run_git(root, 'rev-parse', f'{remote}/{branch}')
            remote_sha = rem.stdout.strip() if rem.returncode == 0 else ''

            rev = _run_git(root, 'rev-list', '--left-right', '--count', f'HEAD...{remote}/{branch}')
            ahead, behind = 0, 0
            if rev.returncode == 0 and rev.stdout.strip():
                parts = rev.stdout.strip().split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

            return UpdateStatus(
                mode='git',
                current_sha=current_sha,
                remote_sha=remote_sha,
                behind=behind,
                ahead=ahead,
                dirty=dirty,
                up_to_date=(behind == 0),
            )
        except Exception as exc:
            return UpdateStatus(mode='git', error=str(exc))

    ver_file = root / VERSION_FILE
    current_sha = ver_file.read_text(encoding='utf-8').strip() if ver_file.is_file() else ''
    try:
        remote_sha = _fetch_remote_sha_api()
    except Exception as exc:
        return UpdateStatus(mode='zip', current_sha=current_sha, error=str(exc))
    up_to_date = bool(current_sha and remote_sha and current_sha == remote_sha)
    return UpdateStatus(
        mode='zip',
        current_sha=current_sha,
        remote_sha=remote_sha,
        behind=0 if up_to_date else 1,
        up_to_date=up_to_date,
        download_url=GITHUB_ZIP_URL,
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


def apply_zip_archive(root: Path, zip_bytes: bytes, new_sha: str = '') -> UpdateResult:
    """Safely extract a GitHub archive ZIP onto `root`, preserving local user data."""
    root = Path(root).resolve()
    ver_file = root / VERSION_FILE
    old_sha = ver_file.read_text(encoding='utf-8').strip() if ver_file.is_file() else ''
    updated = 0
    hook_changed = False
    launcher_changed = False

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = Path(info.filename).parts
            # GitHub archives wrap files in `<repo>-<branch>/...`
            rel_parts = parts[1:] if len(parts) > 1 else parts
            if not rel_parts:
                continue
            if any(p in ('', '.', '..') for p in rel_parts):
                continue
            if rel_parts[0] in PROTECTED_DIRS:
                continue
            rel_path = Path(*rel_parts)
            if rel_path.suffix.lower() in PROTECTED_SUFFIXES:
                continue
            dest = (root / rel_path).resolve()
            try:
                dest.relative_to(root)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(info)
            if not dest.exists() or dest.read_bytes() != data:
                _write_replacing_locked(dest, data)
                updated += 1
                rel_posix = rel_path.as_posix()
                if rel_posix.startswith('client_hook/'):
                    hook_changed = True
                if rel_posix in ('tools/launcher.py', 'tools/updater.py', LAUNCHER_EXE_NAME):
                    launcher_changed = True

    if new_sha:
        ver_file.write_text(new_sha + '\n', encoding='utf-8')
    dll_deployed = False
    if (root / 'client_hook' / 'steam_api.dll').is_file():
        dll_deployed = _deploy_prebuilt_dll(root)
    label = new_sha if new_sha.startswith('v') else (new_sha[:7] or 'latest')
    extra = ' (steam_api.dll deployed)' if dll_deployed else ''
    return UpdateResult(
        ok=True,
        mode='release' if new_sha.startswith('v') else 'zip',
        old_sha=old_sha,
        new_sha=new_sha,
        message=f'Updated {updated} file(s) to {label}.{extra}',
        hook_changed=hook_changed and not dll_deployed,
        launcher_changed=launcher_changed,
        files_updated=updated,
    )


def apply_update(root: Path = ROOT, remote: str = 'origin', branch: str = GITHUB_BRANCH,
                 releases_only: bool = True) -> UpdateResult:
    """Download and apply the latest published GitHub Release onto `root`.

    When `releases_only=True` (default), never updates to unreleased commits.
    """
    root = Path(root)
    if releases_only:
        try:
            tag, zip_url = _fetch_latest_release_api()
            if not tag or not zip_url:
                return UpdateResult(ok=False, mode='release',
                                    message='No published release found on GitHub.')
            current_ver = _current_installed_release(root)
            if current_ver and current_ver == tag:
                return UpdateResult(ok=True, mode='release', old_sha=current_ver, new_sha=tag,
                                    message=f'Already up to date ({tag}).')
            if _has_git_repo(root):
                fetch = _run_git(root, 'fetch', remote, '--tags', '--quiet', timeout=20)
                if fetch.returncode != 0:
                    err = (fetch.stderr or fetch.stdout or 'git fetch --tags failed').strip().splitlines()[-1]
                    return UpdateResult(ok=False, mode='release', old_sha=current_ver, message=err)
                merge = _run_git(root, 'merge', '--ff-only', tag, timeout=20)
                if merge.returncode != 0:
                    return UpdateResult(
                        ok=False, mode='release', old_sha=current_ver,
                        message=f'Cannot fast-forward local git branch to release {tag}. '
                                'Use git manually in a development checkout.',
                    )
                return UpdateResult(
                    ok=True, mode='release', old_sha=current_ver, new_sha=tag,
                    message=f'Updated to release {tag}.',
                )
            req = urllib.request.Request(zip_url, headers={'User-Agent': 'DarkBlood-Launcher-Updater'})
            with urllib.request.urlopen(req, timeout=60) as resp:
                zip_bytes = resp.read()
            return apply_zip_archive(root, zip_bytes, new_sha=tag)
        except Exception as exc:
            return UpdateResult(ok=False, mode='release', message=f'Release update failed: {exc}')

    if _has_git_repo(root):
        try:
            old_sha = _run_git(root, 'rev-parse', 'HEAD').stdout.strip()
            dirty = bool(_run_git(root, 'status', '--porcelain').stdout.strip())
            stashed = False
            if dirty:
                st = _run_git(root, 'stash', 'push', '-u', '-m', 'darkblood-launcher-auto-update')
                if st.returncode != 0:
                    return UpdateResult(ok=False, mode='git', old_sha=old_sha,
                                        message=f'Could not stash local changes: {st.stderr.strip()}')
                stashed = True

            pull = _run_git(root, 'pull', '--ff-only', remote, branch, timeout=30)
            if pull.returncode != 0:
                pull = _run_git(root, 'pull', '--rebase', remote, branch, timeout=30)
                if pull.returncode != 0:
                    _run_git(root, 'rebase', '--abort')
                    if stashed:
                        _run_git(root, 'stash', 'pop')
                    err = (pull.stderr or pull.stdout or 'git pull failed').strip().splitlines()[-1]
                    return UpdateResult(ok=False, mode='git', old_sha=old_sha, message=err)

            if stashed:
                pop = _run_git(root, 'stash', 'pop')
                if pop.returncode != 0:
                    return UpdateResult(
                        ok=True, mode='git', old_sha=old_sha,
                        new_sha=_run_git(root, 'rev-parse', 'HEAD').stdout.strip(),
                        message='Updated, but local stash could not be re-applied cleanly (saved in git stash).',
                    )

            new_sha = _run_git(root, 'rev-parse', 'HEAD').stdout.strip()
            changed = []
            if old_sha and new_sha and old_sha != new_sha:
                diff = _run_git(root, 'diff', '--name-only', f'{old_sha}..{new_sha}')
                if diff.returncode == 0:
                    changed = [l.strip() for l in diff.stdout.splitlines() if l.strip()]

            hook_changed = any(f.startswith('client_hook/') for f in changed)
            launcher_changed = any(f in ('tools/launcher.py', 'tools/updater.py') for f in changed)
            msg = (f'Updated {old_sha[:7]} -> {new_sha[:7]} ({len(changed)} files changed).'
                   if old_sha != new_sha else f'Already up to date ({new_sha[:7]}).')
            return UpdateResult(
                ok=True,
                mode='git',
                old_sha=old_sha,
                new_sha=new_sha,
                message=msg,
                hook_changed=hook_changed,
                launcher_changed=launcher_changed,
                files_updated=len(changed),
            )
        except Exception as exc:
            return UpdateResult(ok=False, mode='git', message=str(exc))

    # Portable Release / ZIP fallback
    try:
        tag, zip_url = None, None
        try:
            tag, zip_url = _fetch_latest_release_api()
        except Exception:
            pass
        if tag and zip_url:
            target_ver, url = tag, zip_url
        else:
            target_ver, url = _fetch_remote_sha_api(), GITHUB_ZIP_URL
        req = urllib.request.Request(url, headers={'User-Agent': 'DarkBlood-Launcher-Updater'})
        with urllib.request.urlopen(req, timeout=60) as resp:
            zip_bytes = resp.read()
        return apply_zip_archive(root, zip_bytes, new_sha=target_ver)
    except Exception as exc:
        return UpdateResult(ok=False, mode='zip', message=f'ZIP update failed: {exc}')


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if '--apply' in args:
        res = apply_update()
        print(res.message)
        return 0 if res.ok else 1
    st = check_for_updates()
    if st.error:
        print(f'Update check failed ({st.mode}): {st.error}', file=sys.stderr)
        return 1
    if st.up_to_date:
        print(f'Up to date ({st.mode}, {st.short_current}).')
        return 0
    print(f'Update available ({st.mode}): {st.short_current} -> {st.short_remote} ({st.behind} commit(s) behind).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
