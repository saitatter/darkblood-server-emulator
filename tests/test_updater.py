"""Unit tests for tools/updater.py (git clone mode and portable ZIP mode)."""
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from tests.common import ROOT  # noqa: F401 (adds tools/ to sys.path)
import updater


class ZipUpdaterTest(unittest.TestCase):
    def _make_zip(self, files: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            for name, content in files.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_zip_update_replaces_source_and_preserves_user_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Pre-existing user files that MUST NOT be overwritten
            (root / 'data').mkdir()
            (root / 'data' / 'darkblood.db').write_bytes(b'USER_DB_DATA')
            (root / 'research' / 'client').mkdir(parents=True)
            (root / 'research' / 'client' / 'darkblood_options.ini').write_text('host=192.168.1.5\n', encoding='utf-8')
            (root / 'logs').mkdir()
            (root / 'logs' / 'wire.jsonl').write_text('keep\n', encoding='utf-8')
            (root / 'src').mkdir()
            (root / 'src' / 'app.py').write_text('old = 1\n', encoding='utf-8')

            archive = self._make_zip({
                'darkblood-server-emulator-main/src/app.py': b'new = 2\n',
                'darkblood-server-emulator-main/client_hook/patches/network_redirect.c': b'/* hook */\n',
                'darkblood-server-emulator-main/tools/launcher.py': b'# updated launcher\n',
                'darkblood-server-emulator-main/data/darkblood.db': b'SHOULD_BE_SKIPPED',
                'darkblood-server-emulator-main/research/client/darkblood_options.ini': b'SHOULD_BE_SKIPPED',
                'darkblood-server-emulator-main/logs/wire.jsonl': b'SHOULD_BE_SKIPPED',
                'darkblood-server-emulator-main/../escape.txt': b'EVIL',
            })

            res = updater.apply_zip_archive(root, archive, new_sha='abcdef1234567890')
            self.assertTrue(res.ok)
            self.assertEqual(res.files_updated, 3)
            self.assertTrue(res.hook_changed)
            self.assertTrue(res.launcher_changed)
            self.assertEqual((root / 'src' / 'app.py').read_text(encoding='utf-8'), 'new = 2\n')
            self.assertEqual((root / '.version').read_text(encoding='utf-8').strip(), 'abcdef1234567890')
            # User files untouched
            self.assertEqual((root / 'data' / 'darkblood.db').read_bytes(), b'USER_DB_DATA')
            self.assertEqual((root / 'research' / 'client' / 'darkblood_options.ini').read_text(encoding='utf-8'),
                             'host=192.168.1.5\n')
            self.assertEqual((root / 'logs' / 'wire.jsonl').read_text(encoding='utf-8'), 'keep\n')
            self.assertFalse((root.parent / 'escape.txt').exists())

    def test_release_zip_deploys_prebuilt_steam_api_dll(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'research' / 'client').mkdir(parents=True)
            (root / 'research' / 'client' / 'steam_api.dll').write_bytes(b'OLD_DLL')

            archive = self._make_zip({
                'DarkBlood-Emulator-v0.1.0/client_hook/steam_api.dll': b'NEW_PREBUILT_DLL',
                'DarkBlood-Emulator-v0.1.0/src/darkblood/__init__.py': b'# v0.1.0\n',
            })
            res = updater.apply_zip_archive(root, archive, new_sha='v0.1.0')
            self.assertTrue(res.ok)
            self.assertEqual(res.mode, 'release')
            self.assertFalse(res.hook_changed)  # prebuilt DLL already deployed, no MSVC needed
            self.assertEqual((root / 'research' / 'client' / 'steam_api.dll').read_bytes(), b'NEW_PREBUILT_DLL')
            self.assertEqual((root / '.version').read_text(encoding='utf-8').strip(), 'v0.1.0')

    def test_release_zip_updates_locked_launcher_exe_via_rename(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            exe = root / updater.LAUNCHER_EXE_NAME
            exe.write_bytes(b'OLD_EXE')

            archive = self._make_zip({
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
                res = updater.apply_zip_archive(root, archive, new_sha='v0.2.0')

            self.assertTrue(res.ok)
            self.assertTrue(res.launcher_changed)
            self.assertEqual(exe.read_bytes(), b'NEW_EXE')
            self.assertEqual((root / f'{updater.LAUNCHER_EXE_NAME}.old').read_bytes(), b'OLD_EXE')
            self.assertEqual(updater.cleanup_old_binaries(root), 1)
            self.assertFalse((root / f'{updater.LAUNCHER_EXE_NAME}.old').exists())

    def test_build_release_zip_packages_clean_standalone_and_source_archives(self):
        import build_release
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            # Standalone EXE release archive
            fake_exe = out_dir / build_release.LAUNCHER_EXE_NAME
            fake_exe.write_bytes(b'MZ_FAKE_EXE')
            zip_path = build_release.create_release_zip(
                'v0.1.0-test', output_dir=out_dir, require_dll=False, exe_path=fake_exe,
            )
            self.assertTrue(zip_path.is_file())
            self.assertTrue((out_dir / f'{zip_path.name}.sha256').is_file())
            with zipfile.ZipFile(zip_path) as zf:
                names = set(zf.namelist())
                self.assertIn(f'DarkBlood-Emulator-v0.1.0-test/{build_release.LAUNCHER_EXE_NAME}', names)
                self.assertIn('DarkBlood-Emulator-v0.1.0-test/.version', names)
                self.assertTrue(any(n.startswith('DarkBlood-Emulator-v0.1.0-test/assets/') for n in names))
                self.assertFalse(any(n.endswith('.bat') for n in names))
                self.assertFalse(any('/data/' in n or '/research/' in n or '/logs/' in n for n in names))
                self.assertFalse(any(n.endswith(('.obj', '.db', '.log')) for n in names))


@unittest.skipUnless(shutil.which('git'), 'git CLI not available')
class GitUpdaterTest(unittest.TestCase):
    def _git(self, cwd: Path, *args):
        res = subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True)
        if res.returncode != 0:
            raise AssertionError(f'git {args} failed: {res.stderr}')
        return res.stdout.strip()

    def test_git_check_and_apply_fast_forward_detects_hook_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            origin = base / 'origin.git'
            upstream = base / 'upstream'
            clone = base / 'clone'
            origin.mkdir()
            self._git(origin, 'init', '--bare')

            # Seed upstream main branch
            self._git(base, 'clone', str(origin), str(upstream))
            self._git(upstream, 'config', 'user.email', 'test@example.com')
            self._git(upstream, 'config', 'user.name', 'Test')
            self._git(upstream, 'checkout', '-B', 'main')
            (upstream / 'hello.txt').write_text('v1\n', encoding='utf-8')
            self._git(upstream, 'add', 'hello.txt')
            self._git(upstream, 'commit', '-m', 'chore: init')
            self._git(upstream, 'push', '-u', 'origin', 'main')

            # Clone as local install
            self._git(base, 'clone', '-b', 'main', str(origin), str(clone))
            self._git(clone, 'config', 'user.email', 'test@example.com')
            self._git(clone, 'config', 'user.name', 'Test')

            st0 = updater.check_for_updates(clone, releases_only=False)
            self.assertEqual(st0.mode, 'git')
            self.assertTrue(st0.up_to_date)
            self.assertEqual(st0.behind, 0)

            # Push a new commit touching client_hook/
            (upstream / 'client_hook').mkdir()
            (upstream / 'client_hook' / 'common.c').write_text('// v2\n', encoding='utf-8')
            self._git(upstream, 'add', 'client_hook/common.c')
            self._git(upstream, 'commit', '-m', 'fix(hook): update common.c')
            self._git(upstream, 'push', 'origin', 'main')

            st1 = updater.check_for_updates(clone, releases_only=False)
            self.assertFalse(st1.up_to_date)
            self.assertEqual(st1.behind, 1)

            res = updater.apply_update(clone, releases_only=False)
            self.assertTrue(res.ok)
            self.assertTrue(res.hook_changed)
            self.assertFalse(res.launcher_changed)
            self.assertEqual((clone / 'client_hook' / 'common.c').read_text(encoding='utf-8'), '// v2\n')

    def test_releases_only_never_falls_back_to_random_commits(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.version').write_text('v0.1.0\n', encoding='utf-8')
            with patch.object(updater, '_fetch_latest_release_api', return_value=(None, None)), \
                 patch.object(updater, '_fetch_remote_sha_api', side_effect=AssertionError('must not query commits')):
                st = updater.check_for_updates(root, releases_only=True)
                self.assertEqual(st.mode, 'release')
                self.assertTrue(st.up_to_date)
                self.assertTrue(bool(st.error))
                res = updater.apply_update(root, releases_only=True)
                self.assertFalse(res.ok)

            with patch.object(updater, '_fetch_latest_release_api',
                              return_value=('v0.2.0', 'https://example.invalid/release.zip')):
                st2 = updater.check_for_updates(root, releases_only=True)
                self.assertEqual(st2.mode, 'release')
                self.assertFalse(st2.up_to_date)
                self.assertEqual(st2.remote_sha, 'v0.2.0')

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
