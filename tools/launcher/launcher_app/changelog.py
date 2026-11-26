"""Release changelog and commit-feed helpers for Dark Blood Launcher."""
import json
import re
import subprocess
import urllib.request

import updater

from launcher_app.theme import ROOT

# Map local git author emails/names to GitHub usernames so offline `git log`
# displays GitHub handles instead of local real names.
_GITHUB_USERNAMES = {
    'andrei.voicu133@gmail.com': 'saitatter',
    'voicu andrei-daniel': 'saitatter',
    'cri999sti@gmail.com': 'CristianVita',
}


def parse_commit_prefix(subject):
    """Extract conventional-commit type (feat/fix/docs/...) and clean title."""
    m = re.match(r'^([a-z]+)(?:\(([^)]+)\))?:\s*(.+)$', subject)
    if m:
        return m.group(1), m.group(2) or '', m.group(3)
    return 'chore', '', subject


def _resolve_github_username(name: str, email: str = '', login: str = '') -> str:
    if login:
        return login
    email_low = (email or '').strip().lower()
    if email_low in _GITHUB_USERNAMES:
        return _GITHUB_USERNAMES[email_low]
    if email_low.endswith('@users.noreply.github.com'):
        local_part = email_low.split('@', 1)[0]
        return local_part.split('+', 1)[-1]
    name_low = (name or '').strip().lower()
    if name_low in _GITHUB_USERNAMES:
        return _GITHUB_USERNAMES[name_low]
    return name or 'unknown'


def _current_release_tags(flags):
    """Return (current_tag, previous_tag) for the installed/latest release."""
    cur = ''
    ver_file = ROOT / updater.VERSION_FILE
    if ver_file.is_file():
        v = ver_file.read_text(encoding='utf-8', errors='replace').strip()
        if v.startswith('v'):
            cur = v
    try:
        proc = subprocess.run(
            ['git', 'tag', '--sort=-creatordate', '--list', 'v*'],
            cwd=str(ROOT), capture_output=True, text=True, timeout=5, creationflags=flags,
        )
        if proc.returncode == 0:
            tags = [t.strip() for t in proc.stdout.splitlines() if t.strip()]
            if cur:
                if cur in tags:
                    idx = tags.index(cur)
                    return cur, (tags[idx + 1] if idx + 1 < len(tags) else '')
                return cur, (tags[0] if tags else '')
            if tags:
                return tags[0], (tags[1] if len(tags) > 1 else '')
    except Exception:
        pass
    return cur, ''


def _resolve_github_release_range(cur_tag: str, prev_tag: str):
    """Resolve (cur_tag, prev_tag) from GitHub Releases API when prev_tag is unknown."""
    if cur_tag and prev_tag:
        return cur_tag, prev_tag
    try:
        api = f'https://api.github.com/repos/{updater.GITHUB_REPO}/releases?per_page=15'
        req = urllib.request.Request(api, headers={'User-Agent': 'DarkBlood-Launcher'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            releases = json.loads(resp.read().decode('utf-8'))
        tags = [
            (r.get('tag_name') or '').strip()
            for r in releases
            if not r.get('draft') and (r.get('tag_name') or '').strip()
        ]
        if not tags:
            return cur_tag, prev_tag
        if cur_tag and cur_tag in tags:
            idx = tags.index(cur_tag)
            return cur_tag, (tags[idx + 1] if idx + 1 < len(tags) else '')
        if not cur_tag:
            return tags[0], (tags[1] if len(tags) > 1 else '')
    except Exception:
        pass
    return cur_tag, prev_tag


def _parse_github_commit_items(items, limit=None):
    commits = []
    for item in items:
        sha = item.get('sha', '')
        c = item.get('commit', {})
        gh_author = item.get('author') or {}
        c_author = c.get('author') or {}
        subject = (c.get('message', '') or '').splitlines()[0]
        if '[skip ci]' in subject or 'github-actions[bot]' in (c_author.get('name', '') or '').lower():
            continue
        author = _resolve_github_username(
            c_author.get('name', ''),
            c_author.get('email', ''),
            gh_author.get('login', ''),
        )
        date = (c_author.get('date', '') or '')[:10]
        commits.append({
            'sha': sha, 'short': sha[:7],
            'date': date, 'author': author, 'subject': subject,
        })
        if limit is not None and len(commits) >= limit:
            break
    return commits


def fetch_recent_commits(limit=None):
    """Return list of dicts {sha, short, date, author, subject} for all commits in the current release."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    cur_tag, prev_tag = _current_release_tags(flags)
    rev_spec = f'{prev_tag}..{cur_tag}' if (cur_tag and prev_tag) else (cur_tag or 'HEAD')
    label = f'release {cur_tag}' if cur_tag else 'local git'
    try:
        git_args = ['git', 'log', rev_spec, '--no-merges',
                    '--pretty=format:%H\x1f%h\x1f%ad\x1f%an\x1f%ae\x1f%s', '--date=short']
        if limit is not None:
            git_args.insert(3, f'-n{limit * 3}')
        proc = subprocess.run(
            git_args,
            cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=8, creationflags=flags,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            commits = []
            for line in proc.stdout.splitlines():
                parts = line.split('\x1f')
                if len(parts) == 6:
                    if '[skip ci]' in parts[5] or 'github-actions[bot]' in parts[3].lower():
                        continue
                    commits.append({
                        'sha': parts[0], 'short': parts[1],
                        'date': parts[2],
                        'author': _resolve_github_username(parts[3], parts[4]),
                        'subject': parts[5],
                    })
                    if limit is not None and len(commits) >= limit:
                        break
            if commits:
                return commits, label
    except Exception:
        pass

    # Fallback: GitHub REST API — use /compare/{prev_tag}...{cur_tag} so ONLY commits
    # belonging to the current release are shown (never commits from older releases).
    try:
        cur_tag, prev_tag = _resolve_github_release_range(cur_tag, prev_tag)
        if cur_tag and prev_tag:
            api_url = f'https://api.github.com/repos/{updater.GITHUB_REPO}/compare/{prev_tag}...{cur_tag}'
            req = urllib.request.Request(api_url, headers={'User-Agent': 'DarkBlood-Launcher'})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            # GitHub /compare returns commits oldest-first; reverse for newest-first display.
            items = list(reversed(data.get('commits') or []))
            return _parse_github_commit_items(items, limit=limit), f'release {cur_tag}'

        base_api = f'https://api.github.com/repos/{updater.GITHUB_REPO}/commits?per_page=100'
        api_url = base_api + (f'&sha={cur_tag}' if cur_tag else '')
        req = urllib.request.Request(api_url, headers={'User-Agent': 'DarkBlood-Launcher'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return _parse_github_commit_items(data, limit=limit), (f'release {cur_tag}' if cur_tag else 'GitHub')
    except Exception as exc:
        # Offline portable fallback: parse all sections of bundled RELEASE_NOTES.md
        notes_file = ROOT / 'RELEASE_NOTES.md'
        if notes_file.is_file():
            commits = []
            section_kind = None
            pat = re.compile(r'^- (?:(?:\*\*([^*\n]+)\*\*:\s*)?)(.+?) \(`([0-9a-f]{7})`, @([^)]+)\)$')
            for raw_line in notes_file.read_text(encoding='utf-8', errors='replace').splitlines():
                s = raw_line.strip()
                if s.startswith('### '):
                    section_kind = None
                    continue
                if s.startswith('#### '):
                    low = s.lower()
                    if 'feature' in low:
                        section_kind = 'feat'
                    elif 'fix' in low:
                        section_kind = 'fix'
                    elif 'refactor' in low or 'perf' in low:
                        section_kind = 'refactor'
                    else:
                        section_kind = 'chore'
                    continue
                if not section_kind:
                    continue
                m = pat.match(s)
                if m:
                    scope, desc, sha, user = m.groups()
                    subj = f'{section_kind}({scope}): {desc}' if scope else f'{section_kind}: {desc}'
                    commits.append({'sha': sha, 'short': sha, 'date': cur_tag or 'release', 'author': user, 'subject': subj})
                    if limit is not None and len(commits) >= limit:
                        break
            if commits:
                return commits, (f'release {cur_tag} (offline)' if cur_tag else 'release notes')
        return [], f'unavailable ({exc.__class__.__name__})'
