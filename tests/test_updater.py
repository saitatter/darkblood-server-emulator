"""Unit tests for tools/launcher/updater.py (GitHub Releases + manifest.json self-updater) and tools/build_release.py."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.common import ROOT  # noqa: F401 (adds tools/ to sys.path)
import updater


def _make_zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class SemverTest(unittest.TestCase):
    def test_version_ordering_and_no_downgrade(self):
        self.assertTrue(updater.is_newer_version('', 'v0.1.0-alpha'))
        self.assertTrue(updater.is_newer_version('v0.1.0-alpha', 'v0.1.0-beta'))
        self.assertTrue(updater.is_newer_version('v0.1.0-beta', 'v0.1.0'))
        self.assertTrue(updater.is_newer_version('v0.1.0', 'v0.2.0'))
        self.assertTrue(updater.is_newer_version('v0.2.0', 'v0.10.0'))
        # Same or older remote must never trigger an update
        self.assertFalse(updater.is_newer_version('v0.2.0', 'v0.2.0'))
        self.assertFalse(updater.is_newer_version('v0.2.0', 'v0.1.9'))
        self.assertFalse(updater.is_newer_version('v0.1.0', 'v0.1.0-alpha'))
        self.assertFalse(updater.is_newer_version('v0.1.0', ''))
        self.assertFalse(updater.is_newer_version('v0.2.0+build.5', 'v0.1.9'))
        self.assertFalse(updater.is_newer_version('v0.2.0+build.5', 'v0.2.0+build.6'))
        self.assertTrue(updater.is_newer_version('v0.2.0-rc.1+build.5', 'v0.2.0+build.6'))


class ReleaseUpdaterTest(unittest.TestCase):
    def test_zip_update_preserves_user_data_and_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'data' / 'darkblood.db').write_bytes(b'USER_DB_DATA')
            (root / 'research' / 'client').mkdir(parents=True)
            (root / 'research' / 'client' / 'darkblood_options.ini').write_text('host=192.168.1.5\n', encoding='utf-8')
            (root / 'logs').mkdir()
            (root / 'logs' / 'wire.jsonl').write_text('keep\n', encoding='utf-8')
            (root / 'assets').mkdir()
            (root / 'assets' / 'opcodes.tsv').write_text('old\n', encoding='utf-8')

            archive = _make_zip({
                'DarkBlood-Emulator-v0.2.0/assets/opcodes.tsv': b'new\n',
                'DarkBlood-Emulator-v0.2.0/client_hook/patches/network_redirect.c': b'/* hook */\n',
                'DarkBlood-Emulator-v0.2.0/tools/launcher/launcher.py': b'# updated launcher\n',
                'DarkBlood-Emulator-v0.2.0/data/darkblood.db': b'SHOULD_BE_SKIPPED',
                'DarkBlood-Emulator-v0.2.0/research/client/darkblood_options.ini': b'SHOULD_BE_SKIPPED',
                'DarkBlood-Emulator-v0.2.0/logs/wire.jsonl': b'SHOULD_BE_SKIPPED',
                'DarkBlood-Emulator-v0.2.0/../escape.txt': b'EVIL',
            })
            sha = hashlib.sha256(archive).hexdigest()

            res = updater.apply_zip_archive(root, archive, new_version='v0.2.0', expected_sha256=sha)
            self.assertTrue(res.ok)
            self.assertEqual(res.files_updated, 3)
            self.assertTrue(res.hook_changed)
            self.assertTrue(res.launcher_changed)
            self.assertEqual((root / 'assets' / 'opcodes.tsv').read_text(encoding='utf-8'), 'new\n')
            self.assertEqual((root / '.version').read_text(encoding='utf-8').strip(), 'v0.2.0')
            self.assertTrue((root / '.manifest.json').is_file())
            self.assertFalse((root / '.update_staging').exists())
            # User files untouched
            self.assertEqual((root / 'data' / 'darkblood.db').read_bytes(), b'USER_DB_DATA')
            self.assertEqual((root / 'research' / 'client' / 'darkblood_options.ini').read_text(encoding='utf-8'),
                             'host=192.168.1.5\n')
            self.assertEqual((root / 'logs' / 'wire.jsonl').read_text(encoding='utf-8'), 'keep\n')
            self.assertFalse((root.parent / 'escape.txt').exists())

    def test_invalid_release_zip_leaves_installation_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version_file = root / '.version'
            version_file.write_text('v0.1.0', encoding='utf-8')
            installed = root / 'README.md'
            installed.write_bytes(b'installed release')
            archive = b'incomplete ZIP download'
            zip_path = root / 'download.zip'
            zip_path.write_bytes(archive)
            checksum = hashlib.sha256(archive).hexdigest()

            for source in (archive, zip_path):
                with self.subTest(source=source):
                    result = updater.apply_zip_archive(
                        root, source, new_version='v0.2.0', expected_sha256=checksum,
                    )
                    self.assertFalse(result.ok)
                    self.assertIn('Invalid release ZIP', result.message)
                    self.assertEqual(result.old_version, 'v0.1.0')
                    self.assertEqual(version_file.read_text(encoding='utf-8'), 'v0.1.0')
                    self.assertEqual(installed.read_bytes(), b'installed release')
                    self.assertFalse((root / '.update_staging').exists())

    def test_sha256_mismatch_aborts_before_touching_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'assets').mkdir()
            (root / 'assets' / 'opcodes.tsv').write_text('original\n', encoding='utf-8')
            archive = _make_zip({'DarkBlood-Emulator-v0.2.0/assets/opcodes.tsv': b'corrupted\n'})

            res = updater.apply_zip_archive(
                root, archive, new_version='v0.2.0', expected_sha256='0' * 64,
            )
            self.assertFalse(res.ok)
            self.assertIn('SHA-256 mismatch', res.message)
            self.assertEqual((root / 'assets' / 'opcodes.tsv').read_text(encoding='utf-8'), 'original\n')
            self.assertFalse((root / '.version').exists())

    def test_orphan_files_removed_between_releases_while_user_files_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'user_notes.txt').write_text('keep me\n', encoding='utf-8')

            v1 = _make_zip({
                'DarkBlood-Emulator-v0.1.0/assets/keep.tsv': b'k1\n',
                'DarkBlood-Emulator-v0.1.0/assets/obsolete.tsv': b'old\n',
            })
            r1 = updater.apply_zip_archive(root, v1, new_version='v0.1.0')
            self.assertTrue(r1.ok)
            self.assertTrue((root / 'assets' / 'obsolete.tsv').is_file())

            v2 = _make_zip({
                'DarkBlood-Emulator-v0.2.0/assets/keep.tsv': b'k2\n',
            })
            r2 = updater.apply_zip_archive(root, v2, new_version='v0.2.0')
            self.assertTrue(r2.ok)
            self.assertEqual(r2.files_updated, 1)
            self.assertEqual(r2.files_removed, 1)
            self.assertFalse((root / 'assets' / 'obsolete.tsv').exists())
            self.assertEqual((root / 'assets' / 'keep.tsv').read_text(encoding='utf-8'), 'k2\n')
            self.assertEqual((root / 'user_notes.txt').read_text(encoding='utf-8'), 'keep me\n')

    def test_manifest_write_failure_leaves_previous_release_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_archive = _make_zip({'release/README.md': b'old', 'release/old.txt': b'restore me'})
            first = updater.apply_zip_archive(root, old_archive, new_version='v0.1.0')
            self.assertTrue(first.ok, first.message)
            manifest = root / updater.MANIFEST_FILE
            previous_manifest = manifest.read_bytes()
            new_archive = _make_zip({'release/README.md': b'new'})
            write_text = Path.write_text

            for marker in (updater.MANIFEST_FILE, updater.VERSION_FILE):
                with self.subTest(marker=marker):
                    def fail_marker(path, *args, **kwargs):
                        if path == root / marker:
                            raise OSError('release metadata write failed')
                        return write_text(path, *args, **kwargs)

                    with patch.object(Path, 'write_text', fail_marker):
                        result = updater.apply_zip_archive(root, new_archive, new_version='v0.2.0')

                    self.assertFalse(result.ok)
                    self.assertEqual(updater.current_installed_version(root), 'v0.1.0')
                    self.assertEqual(manifest.read_bytes(), previous_manifest)
                    self.assertEqual((root / 'README.md').read_bytes(), b'old')
                    self.assertEqual((root / 'old.txt').read_bytes(), b'restore me')

    def test_release_zip_deploys_prebuilt_steam_api_dll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'research' / 'client').mkdir(parents=True)
            (root / 'research' / 'client' / 'steam_api.dll').write_bytes(b'OLD_DLL')

            archive = _make_zip({
                'DarkBlood-Emulator-v0.1.0/client_hook/steam_api.dll': b'NEW_PREBUILT_DLL',
                'DarkBlood-Emulator-v0.1.0/README.md': b'# v0.1.0\n',
            })
            res = updater.apply_zip_archive(root, archive, new_version='v0.1.0')
            self.assertTrue(res.ok)
            self.assertEqual(res.mode, 'release')
            self.assertFalse(res.hook_changed)  # prebuilt DLL already deployed, no MSVC needed
            self.assertEqual((root / 'research' / 'client' / 'steam_api.dll').read_bytes(), b'NEW_PREBUILT_DLL')
            self.assertEqual((root / '.version').read_text(encoding='utf-8').strip(), 'v0.1.0')

    def test_release_zip_updates_locked_launcher_exe_via_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            exe = root / updater.LAUNCHER_EXE_NAME
            exe.write_bytes(b'OLD_EXE')

            archive = _make_zip({
                f'DarkBlood-Emulator-v0.2.0/{updater.LAUNCHER_EXE_NAME}': b'NEW_EXE',
            })

            orig_write_bytes = Path.write_bytes
            failed_once = {'done': False}

            def fake_write_bytes(self_path, data):
                if self_path == exe and not failed_once['done']:
                    failed_once['done'] = True
                    raise PermissionError('simulated Windows running exe lock')
                return orig_write_bytes(self_path, data)

            with patch.object(Path, 'write_bytes', fake_write_bytes):
                res = updater.apply_zip_archive(root, archive, new_version='v0.2.0')

            self.assertTrue(res.ok)
            self.assertTrue(res.launcher_changed)
            self.assertEqual(exe.read_bytes(), b'NEW_EXE')
            self.assertEqual((root / f'{updater.LAUNCHER_EXE_NAME}.old').read_bytes(), b'OLD_EXE')
            self.assertEqual(updater.cleanup_old_binaries(root), 1)
            self.assertFalse((root / f'{updater.LAUNCHER_EXE_NAME}.old').exists())

    def test_older_release_keeps_the_reported_installed_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version_file = root / '.version'
            version_file.write_text('v0.2.0', encoding='utf-8')
            info = updater.ReleaseInfo(version='v0.1.0', zip_url='https://example.invalid/release.zip')

            with patch.object(updater, 'fetch_latest_release', return_value=info), \
                 patch.object(updater, '_download_to_file') as download:
                result = updater.apply_update(root)

            download.assert_not_called()
            self.assertTrue(result.ok)
            self.assertEqual((result.old_version, result.new_version), ('v0.2.0', 'v0.2.0'))
            self.assertEqual(version_file.read_text(encoding='utf-8'), 'v0.2.0')

    def test_dev_checkout_disables_self_updater(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.git').mkdir()
            with patch.object(updater, 'fetch_latest_release', side_effect=AssertionError('must not hit network')):
                st = updater.check_for_updates(root)
                self.assertEqual(st.mode, 'dev')
                self.assertTrue(st.up_to_date)
                res = updater.apply_update(root)
                self.assertFalse(res.ok)
                self.assertEqual(res.mode, 'dev')

    def test_manifest_check_and_api_fallback_and_download_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.version').write_text('v0.1.0\n', encoding='utf-8')

            # No release published
            with patch.object(updater, '_fetch_latest_manifest', return_value=None), \
                 patch.object(updater, '_fetch_latest_release_api', return_value=None):
                st = updater.check_for_updates(root)
                self.assertEqual(st.mode, 'release')
                self.assertTrue(st.up_to_date)
                self.assertTrue(bool(st.error))

            # Manifest found -> does not call REST API
            archive = _make_zip({'DarkBlood-Emulator-v0.2.0/README.md': b'v0.2.0\n'})
            sha = hashlib.sha256(archive).hexdigest()
            info = updater.ReleaseInfo(
                version='v0.2.0',
                zip_url='https://example.invalid/DarkBlood-Emulator-v0.2.0-win32.zip',
                zip_sha256=sha,
                zip_size=len(archive),
            )
            with patch.object(updater, '_fetch_latest_manifest', return_value=info), \
                 patch.object(updater, '_fetch_latest_release_api', side_effect=AssertionError('should not call API')):
                st2 = updater.check_for_updates(root)
                self.assertEqual(st2.mode, 'release')
                self.assertFalse(st2.up_to_date)
                self.assertEqual(st2.remote_version, 'v0.2.0')
                self.assertEqual(st2.zip_sha256, sha)

            # Streaming apply with progress callback
            progress_events = []

            def fake_download(url, dest, expected_size=0, on_progress=None, timeout=60):
                dest.write_bytes(archive)
                if on_progress:
                    on_progress(len(archive) // 2, len(archive))
                    on_progress(len(archive), len(archive))
                return sha

            with patch.object(updater, 'fetch_latest_release', return_value=info), \
                 patch.object(updater, '_download_to_file', side_effect=fake_download):
                res = updater.apply_update(root, on_progress=lambda d, t: progress_events.append((d, t)))
                self.assertTrue(res.ok)
                self.assertEqual(res.new_version, 'v0.2.0')
                self.assertEqual(len(progress_events), 2)
                self.assertEqual(progress_events[-1], (len(archive), len(archive)))
                self.assertEqual((root / 'README.md').read_text(encoding='utf-8'), 'v0.2.0\n')

    def test_release_notes_use_the_previous_tag_on_build_history(self):
        import build_release

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args, day=1):
                subprocess.run(
                    ['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                     '-c', 'commit.gpgsign=false', *args],
                    cwd=root, check=True, capture_output=True,
                    env=dict(os.environ, GIT_COMMITTER_DATE=f'2020-01-{day:02}T12:00:00Z'),
                )

            git('init', '-q')
            git('commit', '--allow-empty', '-qm', 'feat: original feature')
            git('tag', 'v1.0.0')
            git('commit', '--allow-empty', '-qm', 'fix: correct release update', day=2)
            git('tag', 'v1.1.0')
            git('commit', '--allow-empty', '-qm', 'feat: later feature', day=3)
            git('tag', 'v1.2.0')

            git('checkout', '--detach', 'v1.1.0')
            notes = build_release.generate_release_notes('v1.1.0', 'release.zip', 'checksum', root=root)

            self.assertIn('### Changes since `v1.0.0`', notes)
            self.assertIn('- correct release update', notes)
            self.assertNotIn('original feature', notes)
            self.assertNotIn('later feature', notes)

    def test_build_release_zip_packages_clean_archive_and_manifest(self):
        import build_release
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fake_exe = out_dir / build_release.LAUNCHER_EXE_NAME
            fake_exe.write_bytes(b'MZ_FAKE_EXE')
            zip_path = build_release.create_release_zip(
                'v0.1.0-test', output_dir=out_dir, require_dll=False, exe_path=fake_exe,
            )
            self.assertTrue(zip_path.is_file())
            self.assertTrue((out_dir / f'{zip_path.name}.sha256').is_file())
            manifest_path = out_dir / 'manifest.json'
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['schema'], 1)
            self.assertEqual(manifest['version'], 'v0.1.0-test')
            self.assertEqual(manifest['zip_name'], zip_path.name)
            self.assertEqual(manifest['zip_sha256'], hashlib.sha256(zip_path.read_bytes()).hexdigest())
            self.assertEqual(manifest['zip_size'], zip_path.stat().st_size)
            self.assertIn(build_release.LAUNCHER_EXE_NAME, manifest['files'])
            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())
                self.assertIn(f'DarkBlood-Emulator-v0.1.0-test/{build_release.LAUNCHER_EXE_NAME}', names)
                self.assertIn('DarkBlood-Emulator-v0.1.0-test/.version', names)
                self.assertTrue(any(n.startswith('DarkBlood-Emulator-v0.1.0-test/assets/') for n in names))
                self.assertFalse(any(n.endswith('.bat') for n in names))
                self.assertFalse(any('/data/' in n or '/research/' in n or '/logs/' in n for n in names))
                self.assertFalse(any(n.endswith(('.obj', '.db', '.log')) for n in names))

    @unittest.skipUnless(sys.platform == 'win32', 'launcher/gamectl requires Windows')
    def test_launcher_ensure_hook_deployed_and_gm_doc_parser(self):
        import launcher
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            client_dir = base / 'client'
            client_dir.mkdir()
            (client_dir / 'steam_api.dll').write_bytes(b'ORIG_STEAM_API')
            hook_dll = base / 'hook_steam_api.dll'
            hook_dll.write_bytes(b'CUSTOM_HOOK_V2')

            self.assertTrue(launcher.ensure_hook_deployed(client_dir, hook_dll))
            self.assertEqual((client_dir / 'steam_api.dll.bak').read_bytes(), b'ORIG_STEAM_API')
            self.assertEqual((client_dir / 'steam_api.dll').read_bytes(), b'CUSTOM_HOOK_V2')
            # Second call is a no-op when already up to date
            self.assertFalse(launcher.ensure_hook_deployed(client_dir, hook_dll))

        cmds = launcher.parse_gm_commands_doc()
        names = {c['name'] for c in cmds}
        self.assertIn('lv', names)
        self.assertIn('itemcall', names)
        self.assertIn('dualskill', names)
        lv_cmd = next(c for c in cmds if c['name'] == 'lv')
        self.assertTrue(lv_cmd['live'])


if __name__ == '__main__':
    unittest.main()
