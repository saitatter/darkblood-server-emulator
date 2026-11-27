"""Unit tests for tools/launcher/launcher_app/changelog.py."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.common import ROOT  # noqa: F401 (adds tools/ to sys.path)
from launcher_app import changelog


class LauncherChangelogTest(unittest.TestCase):
    def test_breaking_change_prefix_preserves_type_and_scope(self):
        self.assertEqual(changelog.parse_commit_prefix('feat(lobby)!: update selection'),
                         ('feat', 'lobby', 'update selection'))
        self.assertEqual(changelog.parse_commit_prefix('fix!: replace a setting'),
                         ('fix', '', 'replace a setting'))

    def test_github_commit_items_include_all_commit_types(self):
        items = [
            {
                'sha': '1111111aaaaaaa',
                'commit': {'message': 'feat(lobby): add preview', 'author': {'name': 'Dev', 'date': '2026-11-24T10:00:00Z'}},
                'author': {'login': 'saitatter'},
            },
            {
                'sha': '2222222bbbbbbb',
                'commit': {'message': 'fix(world): fix crash', 'author': {'name': 'Dev', 'date': '2026-11-24T10:01:00Z'}},
                'author': {'login': 'saitatter'},
            },
            {
                'sha': '3333333ccccccc',
                'commit': {'message': 'refactor(dungeon): split module', 'author': {'name': 'Dev', 'date': '2026-11-24T10:02:00Z'}},
                'author': {'login': 'saitatter'},
            },
            {
                'sha': '4444444ddddddd',
                'commit': {'message': 'docs: update handoff', 'author': {'name': 'Dev', 'date': '2026-11-24T10:03:00Z'}},
                'author': {'login': 'saitatter'},
            },
            {
                'sha': '5555555eeeeeee',
                'commit': {'message': 'test(pets): add coverage', 'author': {'name': 'Dev', 'date': '2026-11-24T10:04:00Z'}},
                'author': {'login': 'saitatter'},
            },
            {
                'sha': '6666666fffffff',
                'commit': {'message': 'chore: bump version [skip ci]', 'author': {'name': 'Dev', 'date': '2026-11-24T10:05:00Z'}},
                'author': {'login': 'saitatter'},
            },
            {
                'sha': '77777770000000',
                'commit': {'message': 'chore: automated update', 'author': {'name': 'github-actions[bot]', 'date': '2026-11-24T10:06:00Z'}},
                'author': {},
            },
        ]

        parsed = changelog._parse_github_commit_items(items)
        subjects = [c['subject'] for c in parsed]
        self.assertEqual(subjects, [
            'feat(lobby): add preview',
            'fix(world): fix crash',
            'refactor(dungeon): split module',
            'docs: update handoff',
            'test(pets): add coverage',
        ])

    def test_fetch_recent_commits_git_includes_all_types(self):
        fake_stdout = '\n'.join([
            '1111111aaaaaaa\x1f1111111\x1f2026-11-24\x1fDev\x1fandrei.voicu133@gmail.com\x1ffeat(ui): add tab',
            '2222222bbbbbbb\x1f2222222\x1f2026-11-24\x1fDev\x1fandrei.voicu133@gmail.com\x1frefactor: clean imports',
            '3333333ccccccc\x1f3333333\x1f2026-11-24\x1fDev\x1fandrei.voicu133@gmail.com\x1fdocs: update status',
            '4444444ddddddd\x1f4444444\x1f2026-11-24\x1fDev\x1fandrei.voicu133@gmail.com\x1fchore: release [skip ci]',
        ])
        fake_proc = subprocess.CompletedProcess(args=['git'], returncode=0, stdout=fake_stdout, stderr='')

        with patch.object(changelog, '_current_release_tags', return_value=('v0.2.0', 'v0.1.0')), \
             patch.object(changelog.subprocess, 'run', return_value=fake_proc):
            commits, label = changelog.fetch_recent_commits()

        self.assertEqual(label, 'release v0.2.0')
        self.assertEqual([c['subject'] for c in commits], [
            'feat(ui): add tab',
            'refactor: clean imports',
            'docs: update status',
        ])

    def test_fetch_recent_commits_offline_release_notes_includes_all_sections(self):
        notes = '\n'.join([
            '### Changes since `v0.1.0` (4 commits)',
            '',
            '#### Features (1)',
            '- **ui**: add tab (`1111111`, @saitatter)',
            '',
            '#### Bug Fixes (1)',
            '- **world**: fix crash (`2222222`, @saitatter)',
            '',
            '#### Refactoring & Performance (1)',
            '- **dungeon**: split module (`3333333`, @saitatter)',
            '',
            '#### Docs, Tests & Tooling (1)',
            '- update handoff (`4444444`, @saitatter)',
            '',
            '### Checksum',
            '- ignored bullet (`5555555`, @saitatter)',
        ])
        parent_git = [
            subprocess.CompletedProcess(['git', 'tag'], 0, stdout='v0.2.0\nv0.1.0\n'),
            subprocess.CompletedProcess(
                ['git', 'log'], 0,
                stdout='9999999aaaaaaa\x1f9999999\x1f2026-11-24\x1fDev\x1fdev@example.com\x1ffeat: unrelated commit',
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / '.git').mkdir()
            root = Path(tmp) / 'portable'
            root.mkdir()
            (root / '.version').write_text('v0.2.0\n', encoding='utf-8')
            (root / 'RELEASE_NOTES.md').write_text(notes, encoding='utf-8')
            with patch.object(changelog, 'ROOT', root), \
                 patch.object(changelog.subprocess, 'run', side_effect=parent_git) as git_run, \
                 patch.object(changelog.urllib.request, 'urlopen', side_effect=OSError('offline')):
                commits, label = changelog.fetch_recent_commits()

        self.assertEqual(label, 'release v0.2.0 (offline)')
        git_run.assert_not_called()
        self.assertEqual([c['subject'] for c in commits], [
            'feat(ui): add tab',
            'fix(world): fix crash',
            'refactor(dungeon): split module',
            'chore: update handoff',
        ])


if __name__ == '__main__':
    unittest.main()
