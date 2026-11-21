"""Architecture, layering, crypto KAT and storage index regression tests."""
import ast
import pathlib
import tempfile
import unittest

from tests.common import ROOT
from darkblood.core.network.crypto import AES, envelope_decrypt, envelope_encrypt
from darkblood.player_management.store import SqliteCharacterStore


class ArchitectureLayeringTest(unittest.TestCase):
    """Enforce downward-only package dependencies declared in docs/ARCHITECTURE.md."""

    def _imports_of(self, path: pathlib.Path):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((node.lineno, node.module))
        return found

    def test_core_imports_nothing_from_upper_layers(self):
        core_dir = ROOT / 'src' / 'darkblood' / 'core'
        bad = []
        for f in core_dir.rglob('*.py'):
            for lineno, mod in self._imports_of(f):
                if mod.startswith('darkblood.') and not mod.startswith('darkblood.core'):
                    bad.append(f'{f.relative_to(ROOT)}:{lineno} -> {mod}')
        self.assertEqual(bad, [])

    def test_games_never_imports_frontend(self):
        games_dir = ROOT / 'src' / 'darkblood' / 'games'
        bad = []
        for f in games_dir.rglob('*.py'):
            for lineno, mod in self._imports_of(f):
                if mod.startswith('darkblood.frontend'):
                    bad.append(f'{f.relative_to(ROOT)}:{lineno} -> {mod}')
        self.assertEqual(bad, [])

    def test_relay_never_imports_games(self):
        relay_file = ROOT / 'src' / 'darkblood' / 'frontend' / 'relay.py'
        bad = [
            f'relay.py:{lineno} -> {mod}'
            for lineno, mod in self._imports_of(relay_file)
            if mod.startswith('darkblood.games')
        ]
        self.assertEqual(bad, [])

    def test_store_never_imports_games(self):
        store_file = ROOT / 'src' / 'darkblood' / 'player_management' / 'store.py'
        bad = [
            f'store.py:{lineno} -> {mod}'
            for lineno, mod in self._imports_of(store_file)
            if mod.startswith('darkblood.games')
        ]
        self.assertEqual(bad, [])

    def test_aes_fips_197_kat_and_envelope_roundtrip(self):
        # FIPS-197 Appendix B AES-128 test vector
        key = bytes.fromhex('2b7e151628aed2a6abf7158809cf4f3c')
        pt = bytes.fromhex('3243f6a8885a308d313198a2e0370734')
        expected_ct = bytes.fromhex('3925841d02dc09fbdc118597196a0b32')
        aes = AES(key)
        self.assertEqual(aes.encrypt_block(pt), expected_ct)
        self.assertEqual(aes.decrypt_block(expected_ct), pt)

        for size in (0, 1, 15, 16, 17, 128, 513):
            msg = bytes((i * 37) & 0xFF for i in range(size))
            self.assertEqual(envelope_decrypt(aes, envelope_encrypt(aes, msg)), msg)

    def test_store_indexed_lookups_and_atomic_save_chars(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = pathlib.Path(tmp) / 'index.db'
            with SqliteCharacterStore(db_path=db) as store:
                c1 = store.create('Acc1', {'name': 'AlphaKnight', 'char_class': 2})
                c2 = store.create('Acc2', {'name': 'BetaMage', 'char_class': 3})
                c3 = store.create('Acc2', {'name': 'GammaThief', 'char_class': 4})
                c1['gold'] = 500
                c2['gold'] = 900
                c3['gold'] = 777  # intentionally not included in save_chars
                store.save_chars([('Acc1', c1['id']), ('Acc2', c2['id'])])

            with SqliteCharacterStore(db_path=db) as reloaded:
                acc, found = reloaded.get_by_id(c2['id'])
                self.assertEqual(acc, 'Acc2')
                self.assertEqual(found['gold'], 900)
                acc_n, found_n = reloaded.get_by_name('alphaknight')
                self.assertEqual(acc_n, 'Acc1')
                self.assertEqual(found_n['gold'], 500)
                self.assertEqual(reloaded.get('Acc2', c3['id']).get('gold', 0), 0)
                self.assertEqual(reloaded.get_by_id(99999), (None, None))
                self.assertEqual(reloaded.get_by_name('NoSuchHero'), (None, None))


if __name__ == '__main__':
    unittest.main()
