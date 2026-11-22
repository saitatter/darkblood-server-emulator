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
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
GITHUB_REPO = 'saitatter/darkblood-server-emulator'
GITHUB_BRANCH = 'main'
GITHUB_COMMIT_API = f'https://api.github.com/repos/{GITHUB_REPO}/commits/{GITHUB_BRANCH}'
GITHUB_ZIP_URL = f'https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip'
VERSION_FILE = '.version'

# Top-level directories and file suffixes preserved during portable ZIP updates.
PROTECTED_DIRS = frozenset({'data', 'research', 'logs', '.git', '__pycache__'})
PROTECTED_SUFFIXES = frozenset({'.db', '.db-wal', '.db-shm', '.ini', '.log', '.key'})


@dataclass
class UpdateStatus:
    mode: str                 # 'git' | 'zip'
    current_sha: str = ''
    remote_sha: str = ''
    behind: int = 0
    ahead: int = 0
    dirty: bool = False
    up_to_date: bool = True
    error: str = ''

    @property
    def short_current(self) -> str:
        return self.current_sha[:7] if self.current_sha else 'unknown'

    @property
    def short_remote(self) -> str:
        return self.remote_sha[:7] if self.remote_sha else 'unknown'


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


def check_for_updates(root: Path = ROOT, remote: str = 'origin', branch: str = GITHUB_BRANCH) -> UpdateStatus:
    """Check whether `root` is behind GitHub's latest `main` commit."""
    root = Path(root)
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

    # Portable ZIP fallback
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
    )


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
                dest.write_bytes(data)
                updated += 1
                rel_posix = rel_path.as_posix()
                if rel_posix.startswith('client_hook/'):
                    hook_changed = True
                if rel_posix in ('tools/launcher.py', 'tools/updater.py'):
                    launcher_changed = True

    if new_sha:
        ver_file.write_text(new_sha + '\n', encoding='utf-8')
    return UpdateResult(
        ok=True,
        mode='zip',
        old_sha=old_sha,
        new_sha=new_sha,
        message=f'Updated {updated} file(s) to {new_sha[:7] or "latest"}.',
        hook_changed=hook_changed,
        launcher_changed=launcher_changed,
        files_updated=updated,
    )


def apply_update(root: Path = ROOT, remote: str = 'origin', branch: str = GITHUB_BRANCH) -> UpdateResult:
    """Pull or download the latest version from GitHub onto `root`."""
    root = Path(root)
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

    # Portable ZIP fallback
    try:
        remote_sha = _fetch_remote_sha_api()
        req = urllib.request.Request(GITHUB_ZIP_URL, headers={'User-Agent': 'DarkBlood-Launcher-Updater'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            zip_bytes = resp.read()
        return apply_zip_archive(root, zip_bytes, new_sha=remote_sha)
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
