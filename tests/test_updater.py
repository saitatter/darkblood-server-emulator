"""Unit tests for tools/updater.py (git clone mode and portable ZIP mode)."""
import io
from pathlib import Path
import shutil
import subprocess
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

            st0 = updater.check_for_updates(clone)
            self.assertEqual(st0.mode, 'git')
            self.assertTrue(st0.up_to_date)
            self.assertEqual(st0.behind, 0)

            # Push a new commit touching client_hook/
            (upstream / 'client_hook').mkdir()
            (upstream / 'client_hook' / 'common.c').write_text('// v2\n', encoding='utf-8')
            self._git(upstream, 'add', 'client_hook/common.c')
            self._git(upstream, 'commit', '-m', 'fix(hook): update common.c')
            self._git(upstream, 'push', 'origin', 'main')

            st1 = updater.check_for_updates(clone)
            self.assertFalse(st1.up_to_date)
            self.assertEqual(st1.behind, 1)

            res = updater.apply_update(clone)
            self.assertTrue(res.ok)
            self.assertTrue(res.hook_changed)
            self.assertFalse(res.launcher_changed)
            self.assertEqual((clone / 'client_hook' / 'common.c').read_text(encoding='utf-8'), '// v2\n')


if __name__ == '__main__':
    unittest.main()
